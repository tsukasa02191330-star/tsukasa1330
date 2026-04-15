"""サンプル Excel を生成するスクリプト (確認用)。

このリポジトリの実行環境ではネットワーク許可リストにより Google Maps や
国交省サイトにアクセスできないため、スプレッドシートの「完成形」を
可視化する目的で、東京都の実在する大手宅建業者 5 件のサンプルデータを
data/sales_list_sample.xlsx に書き出す。

本番のスクレイピングはユーザーのローカル環境で以下を実行:
    python scripts/run_collect.py --tab takken --areas tokyo --limit 5

このスクリプトは検証用途のみ。実運用では使用しない。
出典欄は "サンプル" と明示する。
"""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src import excel_io  # noqa: E402


# 実在する東京都の宅建業者。担当者名・メール等は公開されている情報に限定し、
# 不明確な情報は空のままとする。
SAMPLE_ROWS = [
    {
        "都道府県": "東京都",
        "業者名・事務所名": "三井不動産リアルティ株式会社",
        "担当者名": "",
        "メールアドレス": "",
        "問い合わせフォームURL": "https://www.mitsui-hanbai.co.jp/inquiry/",
        "HP": "https://www.mitsui-hanbai.co.jp/",
        "出典": "サンプル:東京都宅建業者名簿",
    },
    {
        "都道府県": "東京都",
        "業者名・事務所名": "住友不動産販売株式会社",
        "担当者名": "",
        "メールアドレス": "",
        "問い合わせフォームURL": "https://www.stepon.co.jp/contact/",
        "HP": "https://www.stepon.co.jp/",
        "出典": "サンプル:東京都宅建業者名簿",
    },
    {
        "都道府県": "東京都",
        "業者名・事務所名": "東急リバブル株式会社",
        "担当者名": "",
        "メールアドレス": "",
        "問い合わせフォームURL": "https://www.livable.co.jp/inquiry/",
        "HP": "https://www.livable.co.jp/",
        "出典": "サンプル:東京都宅建業者名簿",
    },
    {
        "都道府県": "東京都",
        "業者名・事務所名": "野村不動産ソリューションズ株式会社",
        "担当者名": "",
        "メールアドレス": "",
        "問い合わせフォームURL": "https://www.nomu.com/inquiry/",
        "HP": "https://www.nomu.com/",
        "出典": "サンプル:東京都宅建業者名簿",
    },
    {
        "都道府県": "東京都",
        "業者名・事務所名": "三菱UFJ不動産販売株式会社",
        "担当者名": "",
        "メールアドレス": "",
        "問い合わせフォームURL": "https://www.sumai1.com/inquiry/",
        "HP": "https://www.sumai1.com/",
        "出典": "サンプル:東京都宅建業者名簿",
    },
]


def main() -> int:
    out = os.path.join(_ROOT, "data", "sales_list_sample.xlsx")
    added, updated = excel_io.upsert_tab(out, "宅建業者", SAMPLE_ROWS)
    print(f"書き出し完了: {out} 追加={added} 更新={updated}")
    print("注意: これはサンプルです。本番は scripts/run_collect.py を使ってください。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
