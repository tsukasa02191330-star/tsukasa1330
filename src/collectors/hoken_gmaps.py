"""保険代理店タブ用の Google Maps (Playwright) Collector。

生命保険代理店 / 損害保険代理店の両方を取り扱う。
出典列にキーワードが残るので、後工程で生保/損保の別を判別できる。
"""

from __future__ import annotations

import logging
from typing import Iterator, Set

from .base import AREA_TO_PREF, Record
from ..gmaps_playwright import GoogleMapsScraper

logger = logging.getLogger(__name__)

QUERIES = ["保険代理店", "生命保険代理店", "損害保険代理店"]
SOURCE_PREFIX = "GoogleMaps"


def iter_records(
    scraper: GoogleMapsScraper,
    area: str,
    limit: int,
) -> Iterator[Record]:
    if area not in AREA_TO_PREF:
        raise ValueError(f"未対応 area: {area}")
    pref = AREA_TO_PREF[area]

    seen: Set[str] = set()
    emitted = 0
    for query in QUERIES:
        if limit and emitted >= limit:
            break
        remaining = (limit - emitted) if limit else 0
        per_query_cap = remaining if remaining else 20

        full_query = f"{query} {pref}"
        logger.info(
            "hoken_gmaps: 検索開始 q=%r cap=%d (累計 %d / limit %s)",
            full_query, per_query_cap, emitted, limit or "∞",
        )
        try:
            for place in scraper.search_places(full_query, max_results=per_query_cap):
                name = (place.name or "").strip()
                if not name or name in seen:
                    continue
                seen.add(name)
                yield Record(
                    prefecture=pref,
                    company=name,
                    website=place.website or "",
                    source=f"{SOURCE_PREFIX}:{query}",
                )
                emitted += 1
                if limit and emitted >= limit:
                    break
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "hoken_gmaps: 検索失敗 q=%r err=%s (次のクエリへ)",
                full_query, exc,
            )
            continue
