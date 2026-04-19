"""サンプル Excel を生成するスクリプト (確認用)。

このリポジトリの実行環境ではネットワーク許可リストにより Google Maps や
国交省サイトにアクセスできないため、スプレッドシートの「完成形」を
可視化する目的で、東京都の実在する業者・事務所 (各タブ 5 件ずつ) の
サンプルデータを data/sales_list_sample.xlsx に書き出す。

本番のスクレイピングはユーザーのローカル環境で以下を実行:
    python scripts/run_collect.py --tab takken   --areas tokyo --limit 100
    python scripts/run_collect.py --tab shigyo   --areas tokyo --limit 100
    python scripts/run_collect.py --tab souzoku  --areas tokyo --limit 100
    python scripts/run_collect.py --tab chintai  --areas tokyo --limit 100
    python scripts/run_collect.py --tab hoken    --areas tokyo --limit 100

このスクリプトは検証用途のみ。実運用では使用しない。
出典欄は "サンプル:..." と明示する。
"""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src import excel_io  # noqa: E402


def _row(pref: str, company: str, hp: str, form: str, source: str) -> dict:
    return {
        "都道府県": pref,
        "業者名・事務所名": company,
        "担当者名": "",
        "メールアドレス": "",
        "問い合わせフォームURL": form,
        "HP": hp,
        "出典": source,
    }


# ====== 宅建業者 (大手不動産販売会社) ======
TAKKEN_ROWS = [
    _row("東京都", "三井不動産リアルティ株式会社",
         "https://www.mitsui-hanbai.co.jp/",
         "https://www.mitsui-hanbai.co.jp/inquiry/",
         "サンプル:宅建業者"),
    _row("東京都", "住友不動産販売株式会社",
         "https://www.stepon.co.jp/",
         "https://www.stepon.co.jp/contact/",
         "サンプル:宅建業者"),
    _row("東京都", "東急リバブル株式会社",
         "https://www.livable.co.jp/",
         "https://www.livable.co.jp/inquiry/",
         "サンプル:宅建業者"),
    _row("東京都", "野村不動産ソリューションズ株式会社",
         "https://www.nomu.com/",
         "https://www.nomu.com/inquiry/",
         "サンプル:宅建業者"),
    _row("東京都", "三菱UFJ不動産販売株式会社",
         "https://www.sumai1.com/",
         "https://www.sumai1.com/inquiry/",
         "サンプル:宅建業者"),
]

# ====== 士業 (司法書士/税理士/弁護士/行政書士 を 1 件以上ずつ) ======
SHIGYO_ROWS = [
    _row("東京都", "日本司法書士会連合会",
         "https://www.shiho-shoshi.or.jp/", "",
         "サンプル:司法書士"),
    _row("東京都", "東京司法書士会",
         "https://www.tokyokai.jp/", "",
         "サンプル:司法書士"),
    _row("東京都", "日本税理士会連合会",
         "https://www.nichizeiren.or.jp/", "",
         "サンプル:税理士"),
    _row("東京都", "東京弁護士会",
         "https://www.toben.or.jp/", "",
         "サンプル:弁護士"),
    _row("東京都", "東京都行政書士会",
         "https://www.tokyo-gyosei.or.jp/", "",
         "サンプル:行政書士"),
]

# ====== 相続専門業者 ======
SOUZOKU_ROWS = [
    _row("東京都", "遺品整理士認定協会",
         "https://ihinseiri.or.jp/", "",
         "サンプル:遺品整理"),
    _row("東京都", "株式会社あんしんネット",
         "https://www.anshin-net.com/", "",
         "サンプル:遺品整理"),
    _row("東京都", "株式会社メモリーズ",
         "https://www.ihin-memories.jp/", "",
         "サンプル:遺品整理"),
    _row("東京都", "一般社団法人日本相続知財センター",
         "https://chizai-souzoku.jp/", "",
         "サンプル:相続コンサル"),
    _row("東京都", "税理士法人チェスター",
         "https://chester-tax.com/", "",
         "サンプル:相続専門"),
]

# ====== 賃貸管理会社 ======
CHINTAI_ROWS = [
    _row("東京都", "大東建託パートナーズ株式会社",
         "https://www.kentaku-partners.com/", "",
         "サンプル:賃貸管理"),
    _row("東京都", "スターツピタットハウス株式会社",
         "https://www.pitathouse.com/", "",
         "サンプル:賃貸管理"),
    _row("東京都", "レオパレス21",
         "https://www.leopalace21.com/", "",
         "サンプル:賃貸管理"),
    _row("東京都", "三井不動産レジデンシャルリース株式会社",
         "https://www.mfr.co.jp/", "",
         "サンプル:プロパティマネジメント"),
    _row("東京都", "東急住宅リース株式会社",
         "https://www.tokyu-housing-lease.co.jp/", "",
         "サンプル:プロパティマネジメント"),
]

# ====== 保険代理店 ======
HOKEN_ROWS = [
    _row("東京都", "株式会社保険見直し本舗",
         "https://www.hokepon.com/", "",
         "サンプル:保険代理店"),
    _row("東京都", "株式会社ほけんの窓口グループ",
         "https://www.hokennomadoguchi.com/", "",
         "サンプル:保険代理店"),
    _row("東京都", "ライフプラザパートナーズ株式会社",
         "https://www.lifeplaza.co.jp/", "",
         "サンプル:生命保険代理店"),
    _row("東京都", "株式会社FPパートナー",
         "https://fp-partner.com/", "",
         "サンプル:生命保険代理店"),
    _row("東京都", "丸紅セーフネット株式会社",
         "https://www.marubeni-safenet.com/", "",
         "サンプル:損害保険代理店"),
]


TABS_AND_ROWS = [
    ("宅建業者", TAKKEN_ROWS),
    ("士業", SHIGYO_ROWS),
    ("相続専門業者", SOUZOKU_ROWS),
    ("賃貸管理会社", CHINTAI_ROWS),
    ("保険代理店", HOKEN_ROWS),
]


def main() -> int:
    out = os.path.join(_ROOT, "data", "sales_list_sample.xlsx")
    # 既存ファイルがあると古い行が残るので削除して新規生成する
    if os.path.exists(out):
        os.remove(out)
    total_added = 0
    for sheet, rows in TABS_AND_ROWS:
        added, updated = excel_io.upsert_tab(out, sheet, rows)
        total_added += added
        print(f"  [{sheet}] 追加={added} 更新={updated}")
    print(f"書き出し完了: {out} (合計 {total_added} 行)")
    print("注意: これはサンプルです。本番は scripts/run_collect.py を使ってください。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
