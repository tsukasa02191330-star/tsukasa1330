"""宅建業者タブ用 — 国土交通省 「建設業者・宅建業者等企業情報検索」 etsuran2。

公式サイト: https://etsuran2.mlit.go.jp/TAKKEN/

【サイト変更時はここを書き換える】
本モジュールは公開情報を構造化 HTML として取得することを目的とする。
サイトが改修されてエンドポイント / フォームパラメータ / テーブル構造が変わった場合は
本ファイル先頭の定数 (BASE / INIT_PATH / SEARCH_PATH / TABLE_SELECTOR /
RESULT_ROW_NAME_INDEX 等) を調整すること。

実装ポリシー:
- robots.txt を尊重し、同一ホストへのアクセスは RateLimitedClient で 3s+ のインターバル
- POST 検索結果を BeautifulSoup でパース、複数のテーブル/カラム順に対応する
  フォールバックを持つ
- HP 列が無い (殆どの場合) ため、業者名 + 住所メモ程度で Record を作り、
  HP は extract_contacts 側で fallback URL 試行 + Google 検索代替 等に任せる
"""

from __future__ import annotations

import logging
import re
from typing import Iterator, List, Optional, Set
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import AREA_TO_JIS_CODE, AREA_TO_PREF, Record
from ..http_client import RateLimitedClient
from ..robots import RobotsChecker

logger = logging.getLogger(__name__)

# ---- サイト設定 (変更時はここを更新) ----
BASE = "https://etsuran2.mlit.go.jp"
INIT_PATH = "/TAKKEN/initialize.do"
SEARCH_PATH = "/TAKKEN/search.do"
NEXT_PAGE_PATH = "/TAKKEN/page.do"

# 検索結果テーブルのカラム順 (デフォルトの推測値)
# サイト変更時はここを書き換える。
DEFAULT_NAME_HEADERS = ("商号", "商号又は名称", "商号・名称", "業者名")
DEFAULT_HP_HEADERS = ("ホームページ", "ＨＰ", "HP", "URL")
DEFAULT_REP_HEADERS = ("代表者", "代表者氏名", "代表者名")

SOURCE_LABEL = "国交省:etsuran2/TAKKEN"

_PAGE_SIZE_GUESS = 50  # サイト側のデフォルト 1 ページ件数 (推測)


def _get_initial_session(client: RateLimitedClient, robots: RobotsChecker) -> bool:
    """検索画面 (initialize.do) を一度叩いてセッションを取得する。"""
    init_url = BASE + INIT_PATH
    if not robots.allowed(init_url):
        logger.warning("takken_mlit: robots により %s はスキップ", init_url)
        return False
    try:
        resp = client.get(init_url)
    except Exception as exc:  # noqa: BLE001
        logger.error("takken_mlit: initialize 取得失敗 %s: %s", init_url, exc)
        return False
    if resp.status_code != 200:
        logger.error("takken_mlit: initialize HTTP %d", resp.status_code)
        return False
    return True


def _post_search(
    client: RateLimitedClient,
    pref_code: str,
    page: int,
) -> Optional[BeautifulSoup]:
    """指定都道府県・指定ページで検索して soup を返す。"""
    url = BASE + SEARCH_PATH if page == 1 else BASE + NEXT_PAGE_PATH
    # 推測パラメータ — 実環境で 400 / 空が返る場合は要調整。
    params = {
        "todofukenCode": pref_code,
        "ninkaCode": "",            # 国土交通大臣 / 都道府県知事 両方
        "menkyoNo": "",
        "shogyoName": "",
        "currentPage": str(page),
        "pageSize": str(_PAGE_SIZE_GUESS),
    }
    try:
        resp = client.post(url, data=params)
    except Exception as exc:  # noqa: BLE001
        logger.warning("takken_mlit: 検索失敗 page=%d: %s", page, exc)
        return None
    if resp.status_code != 200:
        logger.warning("takken_mlit: 検索 HTTP %d page=%d", resp.status_code, page)
        return None
    return BeautifulSoup(resp.text, "lxml")


def _extract_table(soup: BeautifulSoup):
    """結果テーブルを抽出する。複数のヒューリスティクスでフォールバック。"""
    # 1) 結果らしき table を id / class で探す
    candidates = soup.find_all("table")
    best = None
    best_rows = 0
    for t in candidates:
        rows = t.find_all("tr")
        if len(rows) > best_rows:
            best = t
            best_rows = len(rows)
    return best


def _column_index(header_cells: List[str], candidates: tuple) -> Optional[int]:
    for i, h in enumerate(header_cells):
        ht = (h or "").strip()
        if any(c in ht for c in candidates):
            return i
    return None


def _parse_rows(table, pref: str) -> List[Record]:
    """テーブルから (業者名, HP, 代表者) を抽出して Record リストを返す。"""
    if table is None:
        return []
    rows = table.find_all("tr")
    if not rows:
        return []

    # 1 行目をヘッダーとみなす (th または td)
    header_cells = [c.get_text(" ", strip=True) for c in rows[0].find_all(["th", "td"])]
    name_idx = _column_index(header_cells, DEFAULT_NAME_HEADERS)
    hp_idx = _column_index(header_cells, DEFAULT_HP_HEADERS)
    rep_idx = _column_index(header_cells, DEFAULT_REP_HEADERS)

    # ヘッダーから取れない場合は推測 (1 列目を name とする)
    if name_idx is None:
        name_idx = 1 if len(header_cells) > 2 else 0

    out: List[Record] = []
    for tr in rows[1:]:
        cells = tr.find_all(["td", "th"])
        if len(cells) <= name_idx:
            continue
        name = cells[name_idx].get_text(" ", strip=True)
        if not name or len(name) > 200:
            continue
        # ヘッダー行や合計行を除外
        if any(kw in name for kw in ("商号", "件中", "ページ", "戻る")):
            continue
        website = ""
        if hp_idx is not None and hp_idx < len(cells):
            a = cells[hp_idx].find("a")
            href = a.get("href", "") if a else cells[hp_idx].get_text(" ", strip=True)
            href = (href or "").strip()
            if href.startswith("http"):
                website = href
        out.append(Record(
            prefecture=pref,
            company=name,
            website=website,
            source=SOURCE_LABEL,
        ))
    return out


def _has_more_pages(soup: BeautifulSoup) -> bool:
    """次ページリンクがあるか (緩い判定)。"""
    text = soup.get_text(" ", strip=True)
    if "次へ" in text or "次のページ" in text or "Next" in text:
        # 「次へ」が無効化されているかは見た目だけでは判断しにくいので、
        # 結果が空 or 見出しに「該当なし」がある場合のみ False とする
        if "該当する業者がありません" in text or "該当データがありません" in text:
            return False
        return True
    return False


def iter_records(
    client: RateLimitedClient,
    robots: RobotsChecker,
    area: str,
    limit: int,
) -> Iterator[Record]:
    """国交省 etsuran2 から area の宅建業者を yield する。

    Args:
        client:  RateLimitedClient
        robots:  RobotsChecker
        area:    'tokyo' / 'kanagawa' / 'saitama' / 'chiba'
        limit:   最大件数。0 なら無制限。
    """
    if area not in AREA_TO_PREF:
        raise ValueError(f"未対応 area: {area}")
    pref = AREA_TO_PREF[area]
    pref_code = AREA_TO_JIS_CODE.get(area)
    if not pref_code:
        logger.warning("takken_mlit: pref_code 未設定 area=%s", area)
        return

    if not _get_initial_session(client, robots):
        return

    seen: Set[str] = set()
    emitted = 0
    max_pages = 50  # 暴走防止
    for page in range(1, max_pages + 1):
        if limit and emitted >= limit:
            break
        soup = _post_search(client, pref_code, page)
        if soup is None:
            break
        table = _extract_table(soup)
        records = _parse_rows(table, pref)
        if not records:
            logger.info("takken_mlit: page=%d 結果0 終了", page)
            break
        logger.info("takken_mlit: page=%d 取得=%d (累計=%d)", page, len(records), emitted)
        for rec in records:
            if not rec.company or rec.company in seen:
                continue
            seen.add(rec.company)
            yield rec
            emitted += 1
            if limit and emitted >= limit:
                return
        if not _has_more_pages(soup):
            logger.info("takken_mlit: 次ページ無し 終了")
            break
