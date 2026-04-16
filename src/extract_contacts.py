"""業者の公式 HP から、メールアドレスと問い合わせフォーム URL を抽出する。

取得率を上げるため、以下の順で走査する:
  1. トップページ
  2. トップから辿れる `お問い合わせ / contact / 会社概要 / 企業情報` 系リンク (深さ 1、最大 8)
  3. 1〜2 で何も取れなかった場合のフォールバック URL
     (`/contact`, `/inquiry`, `/company`, `/about` などの慣例的パス)

メール抽出:
  - `mailto:` リンク (クエリパラメータは剥がす、全角 `ｍａｉｌｔｏ：` も許容)
  - `og:email` meta と `<address>` タグ
  - 本文中の通常メール (`user@example.com`)
  - 難読化メール (`info[at]example[dot]com`, `info (at) example (dot) com`,
    `info＠example.com` など) を復元して採用

問い合わせフォーム:
  - リンクテキストが「お問い合わせ / 問合せ / contact / inquiry / フォーム」等を含み、
    遷移先に `<form>` + (`textarea` or `input[type=email]`) があるものを採用
  - 外部ドメインは辿らない
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Iterable, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .http_client import RateLimitedClient
from .robots import RobotsChecker

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------------
# 正規表現
# ----------------------------------------------------------------------------

# 通常形式: user@example.com
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

# 難読化トークンを `@` / `.` に正規化してから EMAIL_RE を走らせる方式。
# これで `info[at]example.co.jp` や `info[at]textmail[dot]co[dot]jp` のような
# ホスト部に `.` が複数含まれるケースも拾える。
_BRACKETED_AT_RE = re.compile(
    r"\s*[\[\(\{（]\s*(?:at|アット)\s*[\]\)\}）]\s*", re.IGNORECASE
)
_BRACKETED_DOT_RE = re.compile(
    r"\s*[\[\(\{（]\s*(?:dot|ドット)\s*[\]\)\}）]\s*", re.IGNORECASE
)
# ブラケット無しの "user at host dot tld" — 誤爆防止のため厳しめに単語境界を見る
_BARE_AT_DOT_RE = re.compile(
    r"\b([A-Za-z0-9._%+\-]+)\s+at\s+([A-Za-z0-9.\-]+)\s+dot\s+([A-Za-z]{2,})\b",
    re.IGNORECASE,
)

CONTACT_KEYWORDS = (
    "お問い合わせ",
    "お問合せ",
    "お問合わせ",
    "問合せ",
    "問い合わせ",
    "contact",
    "inquiry",
    "ご相談",
    "フォーム",
    # 会社情報系 (代表メールが載っていることが多い)
    "会社概要",
    "企業情報",
    "会社案内",
    "アクセス",
    "メール",
    "mail",
    "e-mail",
)

# メール候補が無かった場合に試すフォールバックパス
_FALLBACK_PATHS = (
    "/contact",
    "/contact/",
    "/contact.html",
    "/contact.php",
    "/inquiry",
    "/inquiry/",
    "/inquiry.html",
    "/company",
    "/company/",
    "/company/info",
    "/company-profile",
    "/about",
    "/about/",
    "/about/company",
    "/info",
    "/info/",
    "/corporate",
    "/corporate/",
)

# 除外するメールドメイン (CMS / サンプル / noreply 系)
_EXCLUDE_EMAIL_DOMAINS = {
    "example.com",
    "example.co.jp",
    "example.org",
    "sample.com",
    "sentry.io",
    "wixpress.com",
    "domain.com",
    "your-domain.com",
    "yourdomain.com",
}

# アセット拡張子で終わるメールは誤検出 (画像パス etc.)
_EMAIL_FALSE_POSITIVE_SUFFIXES = (
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp",
    ".css", ".js", ".ico", ".woff", ".woff2", ".ttf",
)


@dataclass
class ContactInfo:
    emails: List[str]
    contact_form_url: Optional[str]
    representative: Optional[str] = None


# ----------------------------------------------------------------------------
# 代表者 / 担当者抽出 (既存ロジック踏襲)
# ----------------------------------------------------------------------------

_REP_KEYWORDS = ("代表取締役", "代表者", "代表 ", "店長", "所長", "担当者", "担当 ")
_REP_NAME_RE = re.compile(
    r"[一-龥々ぁ-んァ-ヴー]{1,6}[\s　]{0,2}[一-龥々ぁ-んァ-ヴー]{1,6}"
)


def _extract_representative(text: str) -> Optional[str]:
    if not text:
        return None
    for kw in _REP_KEYWORDS:
        idx = text.find(kw)
        if idx < 0:
            continue
        window = text[idx : idx + 80]
        tail = window[len(kw):]
        m = _REP_NAME_RE.search(tail)
        if m:
            name = m.group(0).strip()
            if 2 <= len(name.replace(" ", "").replace("　", "")) <= 12:
                return f"{kw.strip()} {name}".strip()
    return None


# ----------------------------------------------------------------------------
# URL / ホスト判定
# ----------------------------------------------------------------------------

def _same_host(a: str, b: str) -> bool:
    return urlparse(a).netloc.split(":")[0].lower() == urlparse(b).netloc.split(":")[0].lower()


def _site_root(site_url: str) -> str:
    parsed = urlparse(site_url)
    return f"{parsed.scheme}://{parsed.netloc}"


# ----------------------------------------------------------------------------
# メール抽出
# ----------------------------------------------------------------------------

def _strip_mailto(href: str) -> Optional[str]:
    """`mailto:info@example.com?subject=...` -> `info@example.com`。全角 `ｍａｉｌｔｏ：` も許容。"""
    if not href:
        return None
    h = href.strip()
    # 全角 "ｍａｉｌｔｏ：" → 半角 "mailto:"
    h = h.replace("ｍａｉｌｔｏ", "mailto").replace("：", ":")
    low = h.lower()
    if not low.startswith("mailto:"):
        return None
    addr = h[7:].split("?", 1)[0].strip()
    return addr or None


def _is_valid_email(addr: str) -> bool:
    if not addr:
        return False
    a = addr.lower()
    if "@" not in a:
        return False
    for suf in _EMAIL_FALSE_POSITIVE_SUFFIXES:
        if a.endswith(suf):
            return False
    domain = a.split("@", 1)[-1]
    if domain in _EXCLUDE_EMAIL_DOMAINS:
        return False
    # `user@x` のようなドットなしドメインは除外
    if "." not in domain:
        return False
    return True


def _deobfuscate_emails(text: str) -> List[str]:
    """本文中の難読化メールを `user@example.com` の形に復元して返す。"""
    if not text:
        return []
    found: List[str] = []

    # 1) 置換方式: [at] / (at) / [dot] / (dot) / 全角 ＠ / 全角 ．を通常記号に変換
    normalized = _BRACKETED_AT_RE.sub("@", text)
    normalized = _BRACKETED_DOT_RE.sub(".", normalized)
    normalized = normalized.replace("＠", "@").replace("．", ".")
    for m in EMAIL_RE.findall(normalized):
        if _is_valid_email(m):
            found.append(m)

    # 2) ブラケット無しの bare "user at host dot tld" (低頻度、誤爆しやすいので別扱い)
    for m in _BARE_AT_DOT_RE.finditer(text):
        cand = f"{m.group(1)}@{m.group(2)}.{m.group(3)}"
        if _is_valid_email(cand):
            found.append(cand)

    return found


def _extract_emails_from_soup(soup: BeautifulSoup, raw_text: str) -> List[str]:
    """1 ページ分の soup + 生 HTML から、ベストエフォートでメールを拾う。"""
    found: List[str] = []

    # mailto: リンク (最優先)
    for a in soup.find_all("a", href=True):
        addr = _strip_mailto(a["href"])
        if addr and _is_valid_email(addr):
            found.append(addr)

    # og:email
    og = soup.find("meta", attrs={"property": "og:email"})
    if og and og.get("content"):
        c = og["content"].strip()
        if _is_valid_email(c):
            found.append(c)

    # <address> タグ内のメール
    for addr_tag in soup.find_all("address"):
        for m in EMAIL_RE.findall(addr_tag.get_text(" ")):
            if _is_valid_email(m):
                found.append(m)

    # 本文テキストの通常メール
    body_text = soup.get_text(" ")
    for m in EMAIL_RE.findall(body_text):
        if _is_valid_email(m):
            found.append(m)

    # 生 HTML から難読化メール (テキスト抽出で壊れるケースに備えて raw_text も併用)
    for src in (body_text, raw_text or ""):
        for m in _deobfuscate_emails(src):
            found.append(m)

    return found


def _dedup_keep_order(items: Iterable[str]) -> List[str]:
    seen: Set[str] = set()
    out: List[str] = []
    for x in items:
        k = x.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(x)
    return out


# ----------------------------------------------------------------------------
# 問い合わせフォーム判定 / リンク候補抽出
# ----------------------------------------------------------------------------

def _page_has_contact_form(html: str) -> bool:
    soup = BeautifulSoup(html, "lxml")
    for form in soup.find_all("form"):
        has_textarea = form.find("textarea") is not None
        has_email = form.find("input", attrs={"type": "email"}) is not None
        if has_textarea or has_email:
            return True
    return False


def _find_contact_candidates(soup: BeautifulSoup, base_url: str) -> List[str]:
    """aria-label / title / href も含めて contact キーワードを広めに拾う。"""
    urls: List[str] = []
    seen: Set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text_parts = [
            a.get_text() or "",
            a.get("title") or "",
            a.get("aria-label") or "",
            href,
        ]
        text = " ".join(text_parts)
        text_low = text.lower()
        if not any((kw in text) or (kw.lower() in text_low) for kw in CONTACT_KEYWORDS):
            continue
        full = urljoin(base_url, href)
        if not full.startswith("http"):
            continue
        if not _same_host(full, base_url):
            continue
        if full in seen:
            continue
        seen.add(full)
        urls.append(full)
    return urls


# ----------------------------------------------------------------------------
# ページ取得ユーティリティ
# ----------------------------------------------------------------------------

def _fetch(
    client: RateLimitedClient,
    robots: RobotsChecker,
    url: str,
) -> Optional[Tuple[BeautifulSoup, str]]:
    """URL を取得し、(soup, html) を返す。失敗時 None。"""
    if not robots.allowed(url):
        logger.debug("extract_contacts: robots により %s はスキップ", url)
        return None
    try:
        resp = client.get(url)
    except Exception as exc:  # noqa: BLE001
        logger.debug("extract_contacts: 取得失敗 %s (%s)", url, exc)
        return None
    if resp.status_code != 200:
        return None
    # HTML 以外 (PDF 等) は除外
    ctype = (resp.headers.get("Content-Type") or "").lower()
    if ctype and "html" not in ctype:
        return None
    try:
        soup = BeautifulSoup(resp.text, "lxml")
    except Exception as exc:  # noqa: BLE001
        logger.debug("extract_contacts: parse 失敗 %s (%s)", url, exc)
        return None
    return soup, resp.text


# ----------------------------------------------------------------------------
# 本体
# ----------------------------------------------------------------------------

# Step 2 (contact 候補リンク追跡) の上限
_MAX_CANDIDATE_PAGES = 8
# Step 3 (慣例パス) の上限
_MAX_FALLBACK_PAGES = 6


def extract(
    client: RateLimitedClient,
    robots: RobotsChecker,
    site_url: str,
) -> ContactInfo:
    """公式 HP URL から連絡先情報を取得する。失敗時は空の ContactInfo。"""
    if not site_url or not site_url.startswith("http"):
        return ContactInfo(emails=[], contact_form_url=None)

    emails: List[str] = []
    form_url: Optional[str] = None
    rep_name: Optional[str] = None

    visited: Set[str] = set()

    # -- Step 1: トップページ --
    top = _fetch(client, robots, site_url)
    if top is None:
        return ContactInfo(emails=[], contact_form_url=None)
    top_soup, top_html = top
    visited.add(site_url)

    emails.extend(_extract_emails_from_soup(top_soup, top_html))
    if _page_has_contact_form(top_html):
        form_url = site_url
    if rep_name is None:
        rep_name = _extract_representative(top_soup.get_text("\n"))

    # -- Step 2: contact 系リンクを辿る (深さ 1) --
    candidates = _find_contact_candidates(top_soup, site_url)
    for cand in candidates[:_MAX_CANDIDATE_PAGES]:
        if cand in visited:
            continue
        visited.add(cand)
        result = _fetch(client, robots, cand)
        if result is None:
            continue
        csoup, chtml = result
        emails.extend(_extract_emails_from_soup(csoup, chtml))
        if form_url is None and _page_has_contact_form(chtml):
            form_url = cand
        if rep_name is None:
            rep_name = _extract_representative(csoup.get_text("\n"))
        # メールもフォームも揃ったら早期終了
        if emails and form_url is not None:
            break

    # -- Step 3: フォールバック URL (メールもフォームも見つからなかったときのみ) --
    need_fallback = (not emails) or (form_url is None)
    if need_fallback:
        root = _site_root(site_url)
        attempted = 0
        for path in _FALLBACK_PATHS:
            if attempted >= _MAX_FALLBACK_PAGES:
                break
            fb_url = root + path
            if fb_url in visited:
                continue
            visited.add(fb_url)
            result = _fetch(client, robots, fb_url)
            if result is None:
                continue
            attempted += 1
            fsoup, fhtml = result
            emails.extend(_extract_emails_from_soup(fsoup, fhtml))
            if form_url is None and _page_has_contact_form(fhtml):
                form_url = fb_url
            if rep_name is None:
                rep_name = _extract_representative(fsoup.get_text("\n"))
            if emails and form_url is not None:
                break

    return ContactInfo(
        emails=_dedup_keep_order(emails),
        contact_form_url=form_url,
        representative=rep_name,
    )
