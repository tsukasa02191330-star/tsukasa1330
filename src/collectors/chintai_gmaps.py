"""賃貸管理会社タブ用の Google Maps (Playwright) Collector。"""

from __future__ import annotations

import logging
from typing import Iterator, Set

from .base import AREA_TO_PREF, Record
from ..gmaps_playwright import GoogleMapsScraper

logger = logging.getLogger(__name__)

QUERIES = ["賃貸管理会社", "賃貸管理", "プロパティマネジメント"]
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
            "chintai_gmaps: 検索開始 q=%r cap=%d (累計 %d / limit %s)",
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
                "chintai_gmaps: 検索失敗 q=%r err=%s (次のクエリへ)",
                full_query, exc,
            )
            continue
