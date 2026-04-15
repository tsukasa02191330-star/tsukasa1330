"""宅建業者タブ用の Serper (Google Maps) Collector。

Serper の Places API に対して複数キーワードで検索し、業者名でユニーク化した
Record を yield する。
"""

from __future__ import annotations

import logging
from typing import Iterator, Optional, Set

from .base import AREA_TO_PREF, AREA_TO_SERPER_LOCATION, Record
from ..serper import SerperClient

logger = logging.getLogger(__name__)

# STEP 1 で使用する検索キーワード
QUERIES = ["不動産", "不動産買取", "不動産仲介"]

SOURCE_PREFIX = "Serper/GoogleMaps"


def iter_records(
    serper: SerperClient,
    area: str,
    limit: int,
) -> Iterator[Record]:
    """area (tokyo / kanagawa / ...) から Record を yield する。

    Args:
        serper: SerperClient インスタンス
        area: 'tokyo' 等
        limit: 上限件数。0 なら無制限 (ただし 20 ページで打ち切り)。
    """
    if area not in AREA_TO_PREF:
        raise ValueError(f"未対応 area: {area}")
    pref = AREA_TO_PREF[area]
    location = AREA_TO_SERPER_LOCATION[area]

    seen_companies: Set[str] = set()
    emitted = 0
    for query in QUERIES:
        if limit and emitted >= limit:
            break
        remaining = (limit - emitted) if limit else 0
        # 1 クエリあたりの取得上限 (limit を超えないよう調整)。
        # limit=0 (無制限) のときは 40 件ずつ取得する。
        per_query_cap = remaining if remaining else 40
        logger.info(
            "takken_serper: query=%r location=%r cap=%d (累計 %d / limit %s)",
            query, location, per_query_cap, emitted, limit or "∞",
        )
        try:
            places = serper.search_places(
                query=f"{query} {pref}",
                location=location,
                max_results=per_query_cap,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "takken_serper: Serper 失敗 query=%r pref=%s err=%s",
                query, pref, exc,
            )
            continue

        for p in places:
            title = (p.get("title") or "").strip()
            website = (p.get("website") or "").strip()
            if not title:
                continue
            if title in seen_companies:
                continue
            seen_companies.add(title)
            yield Record(
                prefecture=pref,
                company=title,
                website=website,
                source=f"{SOURCE_PREFIX}:{query}",
            )
            emitted += 1
            if limit and emitted >= limit:
                break
