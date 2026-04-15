"""Collector 共通型。

各 Collector は iter_records(area, limit) -> Iterable[Record] を公開する。
Record は Excel 書き込み前の最小情報 (業者名・HP・出典) を持ち、
extract_contacts による連絡先抽出はオーケストレーター側で行う。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# area キー -> 都道府県 (日本語) マップ。Serper Places の location にも使う。
AREA_TO_PREF = {
    "tokyo": "東京都",
    "kanagawa": "神奈川県",
    "saitama": "埼玉県",
    "chiba": "千葉県",
}

AREA_TO_SERPER_LOCATION = {
    "tokyo": "Tokyo, Japan",
    "kanagawa": "Kanagawa, Japan",
    "saitama": "Saitama, Japan",
    "chiba": "Chiba, Japan",
}


@dataclass
class Record:
    prefecture: str
    company: str
    website: str
    source: str

    def as_row(self) -> dict:
        return {
            "都道府県": self.prefecture,
            "業者名・事務所名": self.company,
            "担当者名": "",
            "メールアドレス": "",
            "問い合わせフォームURL": "",
            "HP": self.website,
            "出典": self.source,
            "ステータス": "",
            "送信日時": "",
            "送信方式": "",
            "エラー": "",
        }
