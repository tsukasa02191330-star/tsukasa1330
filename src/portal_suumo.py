"""SUUMO の不動産会社(業者)一覧ページから、会社名・担当者名・HP URL を収集するアダプタ。

注意:
    SUUMO の HTML 構造は予告なく変更されます。CSS セレクタは `_SELECTORS` に集約しているので、
    動かなくなった場合はブラウザの開発者ツールで実際のマークアップを確認して調整してください。

参考: SUUMO の不動産会社検索は都道府県別のページが用意されています。
    例: https://suumo.jp/kaisha/tokyo/
本実装は 「都道府県トップ → 会社詳細ページ → 公式HP リンク抽出」 の流れで取得します。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .http_client import RateLimitedClient
from .robots import RobotsChecker

logger = logging.getLogger(__name__)

BASE = "https://suumo.jp"

# 都道府県 → SUUMO パスの対応 (首都圏 4 都県のみ)
AREA_PATHS: Dict[str, str] = {
    "tokyo": "/kaisha/tokyo/",
    "kanagawa": "/kaisha/kanagawa/",
    "saitama": "/kaisha/saitama/",
    "chiba": "/kaisha/chiba/",
}

# 実サイトの HTML 変更で壊れた時は以下を更新する (代表的な候補を複数用意)
_SELECTORS = {
    # 会社一覧内の各社ブロック(候補をスペース区切りで複数持つ)
    "company_card": "div.ui-media, li.companyListItem, article.company",
    "company_name": "h3, h2, a.companyListItem__name, .company__name",
    "company_link_on_list": "a[href*='/kaisha/']",
    # 次ページリンク
    "next_page": "a.pagination-parts__link--next, a[rel='next']",
    # 詳細ページでの公式HP
    "detail_official_url": "a[href*='http']:not([href*='suumo.jp']):not([href*='recruit'])",
    # 担当者名(店舗責任者など、取れれば)
    "detail_manager": ".representativePerson, .staff-name, .manager-name",
}


@dataclass
class SuumoBroker:
    会社名: str
    担当者名: str
    HPリンク: str

    def as_row(self) -> Dict[str, str]:
        return {
            "会社名": self.会社名,
            "担当者名": self.担当者名,
            "HPリンク": self.HPリンク,
            "メールアドレス": "",
            "問い合わせフォームリンク": "",
        }


def _parse_list_page(html: str, base_url: str) -> List[str]:
    """会社一覧ページから、各社の詳細ページ URL を抽出する。"""
    soup = BeautifulSoup(html, "lxml")
    detail_urls: List[str] = []
    for a in soup.select(_SELECTORS["company_link_on_list"]):
        href = a.get("href")
        if not href:
            continue
        # 会社詳細は /kaisha/{area}/sc_/ha_*/ のような形
        if "/kaisha/" in href:
            detail_urls.append(urljoin(base_url, href))
    # 重複除去(順序維持)
    seen = set()
    unique: List[str] = []
    for u in detail_urls:
        if u not in seen:
            seen.add(u)
            unique.append(u)
    return unique


def _parse_detail_page(html: str) -> Optional[SuumoBroker]:
    """会社詳細ページから SuumoBroker を作る。公式 HP が無ければ None。"""
    soup = BeautifulSoup(html, "lxml")

    name_el = soup.select_one(_SELECTORS["company_name"])
    company_name = name_el.get_text(strip=True) if name_el else ""

    mgr_el = soup.select_one(_SELECTORS["detail_manager"])
    manager = mgr_el.get_text(strip=True) if mgr_el else ""

    official_url = ""
    for a in soup.select(_SELECTORS["detail_official_url"]):
        href = a.get("href", "")
        if href.startswith("http"):
            # suumo.jp や recruit.co.jp のような内部ドメインは除外済み
            official_url = href
            break

    if not company_name or not official_url:
        return None
    return SuumoBroker(会社名=company_name, 担当者名=manager, HPリンク=official_url)


def iter_brokers(
    client: RateLimitedClient,
    robots: RobotsChecker,
    areas: Iterable[str],
    limit: Optional[int] = None,
) -> Iterable[SuumoBroker]:
    """SUUMO からエリア別に業者を収集するジェネレータ。limit で各エリア上限。"""
    for area in areas:
        path = AREA_PATHS.get(area)
        if not path:
            logger.warning("SUUMO: 未対応エリア %s をスキップ", area)
            continue

        list_url = urljoin(BASE, path)
        if not robots.allowed(list_url):
            logger.warning("SUUMO: robots.txt により %s は不許可。スキップします", list_url)
            continue

        try:
            resp = client.get(list_url)
        except Exception as exc:  # noqa: BLE001
            logger.error("SUUMO: 一覧取得失敗 %s (%s)", list_url, exc)
            continue
        if resp.status_code != 200:
            logger.warning("SUUMO: 一覧 status=%s %s", resp.status_code, list_url)
            continue

        detail_urls = _parse_list_page(resp.text, list_url)
        logger.info("SUUMO: %s から詳細 %d 件を検出", area, len(detail_urls))

        count = 0
        for detail_url in detail_urls:
            if limit is not None and count >= limit:
                break
            if not robots.allowed(detail_url):
                logger.debug("SUUMO: robots により %s スキップ", detail_url)
                continue
            try:
                dresp = client.get(detail_url)
            except Exception as exc:  # noqa: BLE001
                logger.warning("SUUMO: 詳細取得失敗 %s (%s)", detail_url, exc)
                continue
            if dresp.status_code != 200:
                continue
            broker = _parse_detail_page(dresp.text)
            if broker is None:
                continue
            count += 1
            yield broker
