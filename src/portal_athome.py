"""athome の不動産会社検索ページから業者情報を収集するアダプタ。

SUUMO アダプタと同じインタフェース(`iter_brokers`)を提供します。
HTML 構造は変わりやすいので、壊れた時は `_SELECTORS` を更新してください。
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

BASE = "https://www.athome.co.jp"

# 都道府県 → athome の会社検索パス (首都圏 4 都県)
AREA_PATHS: Dict[str, str] = {
    "tokyo": "/realestate-companies/tokyo/",
    "kanagawa": "/realestate-companies/kanagawa/",
    "saitama": "/realestate-companies/saitama/",
    "chiba": "/realestate-companies/chiba/",
}

_SELECTORS = {
    "detail_link": "a[href*='/realestate-companies/'][href*='/detail']",
    "company_name": "h1, h2.companyName, .company-detail__name",
    "detail_official_url": "a[href^='http']:not([href*='athome.co.jp']):not([href*='recruit'])",
    "detail_manager": ".representative, .ceo, .manager",
}


@dataclass
class AthomeBroker:
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
    soup = BeautifulSoup(html, "lxml")
    urls: List[str] = []
    for a in soup.select(_SELECTORS["detail_link"]):
        href = a.get("href")
        if href:
            urls.append(urljoin(base_url, href))
    seen = set()
    unique: List[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            unique.append(u)
    return unique


def _parse_detail_page(html: str) -> Optional[AthomeBroker]:
    soup = BeautifulSoup(html, "lxml")
    name_el = soup.select_one(_SELECTORS["company_name"])
    name = name_el.get_text(strip=True) if name_el else ""

    mgr_el = soup.select_one(_SELECTORS["detail_manager"])
    manager = mgr_el.get_text(strip=True) if mgr_el else ""

    official = ""
    for a in soup.select(_SELECTORS["detail_official_url"]):
        href = a.get("href", "")
        if href.startswith("http"):
            official = href
            break
    if not name or not official:
        return None
    return AthomeBroker(会社名=name, 担当者名=manager, HPリンク=official)


def iter_brokers(
    client: RateLimitedClient,
    robots: RobotsChecker,
    areas: Iterable[str],
    limit: Optional[int] = None,
) -> Iterable[AthomeBroker]:
    for area in areas:
        path = AREA_PATHS.get(area)
        if not path:
            logger.warning("athome: 未対応エリア %s をスキップ", area)
            continue
        list_url = urljoin(BASE, path)
        if not robots.allowed(list_url):
            logger.warning("athome: robots.txt により %s は不許可。スキップします", list_url)
            continue
        try:
            resp = client.get(list_url)
        except Exception as exc:  # noqa: BLE001
            logger.error("athome: 一覧取得失敗 %s (%s)", list_url, exc)
            continue
        if resp.status_code != 200:
            logger.warning("athome: 一覧 status=%s %s", resp.status_code, list_url)
            continue
        detail_urls = _parse_list_page(resp.text, list_url)
        logger.info("athome: %s から詳細 %d 件を検出", area, len(detail_urls))

        count = 0
        for detail_url in detail_urls:
            if limit is not None and count >= limit:
                break
            if not robots.allowed(detail_url):
                continue
            try:
                dresp = client.get(detail_url)
            except Exception as exc:  # noqa: BLE001
                logger.warning("athome: 詳細取得失敗 %s (%s)", detail_url, exc)
                continue
            if dresp.status_code != 200:
                continue
            broker = _parse_detail_page(dresp.text)
            if broker is None:
                continue
            count += 1
            yield broker
