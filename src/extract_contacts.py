"""業者の公式 HP から、メールアドレスと問い合わせフォーム URL を抽出する。

- トップページ + 「お問い合わせ / contact」系リンクの先(深さ 2 まで)を走査
- メール: ページ内の `mailto:` と、本文テキスト中の正規表現マッチ
- 問い合わせフォーム: リンクテキストが「お問い合わせ / お問合せ / contact / inquiry」を含み、
  かつ遷移先に `<form>` + (`textarea` or `input[type=email]`) があるものを採用
- 外部ドメインは辿らない
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Iterable, List, Optional, Set
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .http_client import RateLimitedClient
from .robots import RobotsChecker

logger = logging.getLogger(__name__)

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
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
)

# 除外するメールドメイン(CMS / サンプル / noreply 系)
_EXCLUDE_EMAIL_DOMAINS = {
    "example.com",
    "example.co.jp",
    "sample.com",
    "sentry.io",
    "wixpress.com",
}


@dataclass
class ContactInfo:
    emails: List[str]
    contact_form_url: Optional[str]


def _same_host(a: str, b: str) -> bool:
    return urlparse(a).netloc.split(":")[0].lower() == urlparse(b).netloc.split(":")[0].lower()


def _collect_emails(text: str, mailto_hrefs: Iterable[str]) -> List[str]:
    found: List[str] = []
    seen: Set[str] = set()
    for href in mailto_hrefs:
        if not href.lower().startswith("mailto:"):
            continue
        addr = href[7:].split("?", 1)[0].strip()
        if addr and addr not in seen:
            seen.add(addr)
            found.append(addr)
    for m in EMAIL_RE.findall(text or ""):
        if m in seen:
            continue
        domain = m.split("@", 1)[-1].lower()
        if domain in _EXCLUDE_EMAIL_DOMAINS:
            continue
        seen.add(m)
        found.append(m)
    return found


def _page_has_contact_form(html: str) -> bool:
    soup = BeautifulSoup(html, "lxml")
    for form in soup.find_all("form"):
        has_textarea = form.find("textarea") is not None
        has_email = form.find("input", attrs={"type": "email"}) is not None
        if has_textarea or has_email:
            return True
    return False


def _find_contact_candidates(soup: BeautifulSoup, base_url: str) -> List[str]:
    urls: List[str] = []
    seen: Set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = (a.get_text() or "") + " " + (a.get("title") or "")
        if not any(kw in text.lower() or kw in text for kw in CONTACT_KEYWORDS):
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

    # Step 1: トップページ
    if not robots.allowed(site_url):
        logger.info("extract_contacts: robots により %s はスキップ", site_url)
        return ContactInfo(emails=[], contact_form_url=None)
    try:
        resp = client.get(site_url)
    except Exception as exc:  # noqa: BLE001
        logger.warning("extract_contacts: 取得失敗 %s (%s)", site_url, exc)
        return ContactInfo(emails=[], contact_form_url=None)
    if resp.status_code != 200:
        return ContactInfo(emails=[], contact_form_url=None)

    soup = BeautifulSoup(resp.text, "lxml")
    mailto_hrefs = [a.get("href", "") for a in soup.find_all("a", href=True)]
    emails.extend(_collect_emails(resp.text, mailto_hrefs))

    if _page_has_contact_form(resp.text):
        form_url = site_url

    # Step 2: 問い合わせ系リンクを辿る (深さ 1)
    candidates = _find_contact_candidates(soup, site_url)
    for cand in candidates[:5]:  # 候補は 5 件まで
        if not robots.allowed(cand):
            continue
        try:
            cresp = client.get(cand)
        except Exception as exc:  # noqa: BLE001
            logger.debug("extract_contacts: 子ページ取得失敗 %s (%s)", cand, exc)
            continue
        if cresp.status_code != 200:
            continue
        csoup = BeautifulSoup(cresp.text, "lxml")
        emails.extend(
            _collect_emails(
                cresp.text, [a.get("href", "") for a in csoup.find_all("a", href=True)]
            )
        )
        if form_url is None and _page_has_contact_form(cresp.text):
            form_url = cand
        # 問い合わせページとメール両方揃ったら早期終了
        if form_url is not None and emails:
            break

    # 重複排除(順序保持)
    dedup: List[str] = []
    seen: Set[str] = set()
    for e in emails:
        if e in seen:
            continue
        seen.add(e)
        dedup.append(e)
    return ContactInfo(emails=dedup, contact_form_url=form_url)
