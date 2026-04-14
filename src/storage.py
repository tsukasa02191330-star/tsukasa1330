"""CSV 読み書きユーティリティ。UTF-8 BOM 付き / CRLF。

- ヘッダー: 会社名, 担当者名, HPリンク, メールアドレス, 問い合わせフォームリンク
- UPSERT キー: (会社名, HPリンク)
"""

from __future__ import annotations

import csv
import io
import logging
import os
from typing import Dict, Iterable, List, Tuple

logger = logging.getLogger(__name__)

FIELDS: List[str] = [
    "会社名",
    "担当者名",
    "HPリンク",
    "メールアドレス",
    "問い合わせフォームリンク",
]

UTF8_BOM = "\ufeff"


def _key(row: Dict[str, str]) -> Tuple[str, str]:
    return (row.get("会社名", "").strip(), row.get("HPリンク", "").strip())


def load(path: str) -> List[Dict[str, str]]:
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows: List[Dict[str, str]] = []
        for r in reader:
            rows.append({k: (r.get(k) or "") for k in FIELDS})
        return rows


def save(path: str, rows: Iterable[Dict[str, str]]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    buf = io.StringIO()
    buf.write(UTF8_BOM)
    writer = csv.DictWriter(
        buf,
        fieldnames=FIELDS,
        lineterminator="\r\n",
        quoting=csv.QUOTE_MINIMAL,
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({k: (row.get(k) or "") for k in FIELDS})
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(buf.getvalue())


def upsert(path: str, new_rows: Iterable[Dict[str, str]]) -> Tuple[int, int]:
    """(会社名, HPリンク) キーで UPSERT する。戻り値は (追加件数, 更新件数)。"""
    existing = load(path)
    index: Dict[Tuple[str, str], int] = {_key(r): i for i, r in enumerate(existing)}
    added = 0
    updated = 0
    for new in new_rows:
        k = _key(new)
        if not k[0] and not k[1]:
            # 空キーは保存しない
            continue
        if k in index:
            idx = index[k]
            prev = existing[idx]
            # 非空の値で上書き (既存に情報がある場合は残す)
            merged = {
                field: (new.get(field) or prev.get(field) or "") for field in FIELDS
            }
            if merged != prev:
                existing[idx] = merged
                updated += 1
        else:
            existing.append({field: (new.get(field) or "") for field in FIELDS})
            index[k] = len(existing) - 1
            added += 1
    save(path, existing)
    return added, updated
