"""営業リスト収集オーケストレーター (段階実装版)。

Usage (STEP 1):
    python scripts/run_collect.py --tab takken --areas tokyo

Optional:
    --limit N             YAML の limits を上書きし、各 area で N 件だけ取得
    --skip-contacts       HP からの email/form/担当者名 抽出をスキップ (Serper のみ)
    --output PATH         出力 xlsx (default: data/sales_list.xlsx)
    --log-dir DIR         ログ出力先 (default: logs)

入力:
    .env                  SERPER_API_KEY を定義
    config/limits.yaml    タブ × 都県 ごとの件数上限

出力:
    data/sales_list.xlsx の対応タブに UPSERT
    logs/run_YYYYMMDD_HHMMSS.log
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import sys
from typing import Dict, List

# リポジトリ直下を import path に追加
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import yaml  # noqa: E402

from src import excel_io, extract_contacts  # noqa: E402
from src.collectors import takken_serper  # noqa: E402
from src.collectors.base import AREA_TO_PREF, Record  # noqa: E402
from src.http_client import RateLimitedClient  # noqa: E402
from src.robots import RobotsChecker  # noqa: E402
from src.serper import SerperClient, SerperConfigError  # noqa: E402


SUPPORTED_AREAS = tuple(AREA_TO_PREF.keys())

# タブキー -> (Excel タブ名, collector モジュール list)
# STEP 1 では takken のみ。以降の STEP で拡張する。
TAB_CONFIG: Dict[str, Dict] = {
    "takken": {
        "sheet": "宅建業者",
        "collectors": [takken_serper],
    },
}

DEFAULT_OUTPUT = "data/sales_list.xlsx"
LIMITS_YAML = "config/limits.yaml"


def _setup_logging(log_dir: str) -> str:
    os.makedirs(log_dir, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(log_dir, f"run_{stamp}.log")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return log_path


def _load_limits(tab: str) -> Dict[str, int]:
    limits_path = os.path.join(_ROOT, LIMITS_YAML)
    if not os.path.exists(limits_path):
        return {a: 0 for a in SUPPORTED_AREAS}
    with open(limits_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    tab_limits = data.get(tab) or {}
    return {a: int(tab_limits.get(a, 0) or 0) for a in SUPPORTED_AREAS}


def _parse_csv(value: str, allowed, name: str) -> List[str]:
    items = [v.strip() for v in value.split(",") if v.strip()]
    for item in items:
        if item not in allowed:
            raise SystemExit(
                f"--{name}: 未対応の値 '{item}'。利用可能: {', '.join(allowed)}"
            )
    return items


def main() -> int:
    parser = argparse.ArgumentParser(description="営業リスト収集 (段階実装)")
    parser.add_argument(
        "--tab",
        required=True,
        choices=list(TAB_CONFIG.keys()),
        help=f"対象タブ。STEP 1 は {list(TAB_CONFIG.keys())} のみ",
    )
    parser.add_argument(
        "--areas",
        default="tokyo",
        help=f"対象エリア (カンマ区切り). 対応: {','.join(SUPPORTED_AREAS)}",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="各 area の件数上限を YAML より優先して上書き (0 で無制限)",
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        help=f"出力 xlsx パス (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--log-dir",
        default="logs",
        help="ログ出力ディレクトリ",
    )
    parser.add_argument(
        "--skip-contacts",
        action="store_true",
        help="HP からの email/form/担当者名 抽出をスキップ",
    )
    args = parser.parse_args()

    log_path = _setup_logging(args.log_dir)
    logger = logging.getLogger("run_collect")
    logger.info("ログ出力: %s", log_path)

    areas = _parse_csv(args.areas, SUPPORTED_AREAS, "areas")
    tab_config = TAB_CONFIG[args.tab]
    sheet_name = tab_config["sheet"]
    collectors = tab_config["collectors"]

    yaml_limits = _load_limits(args.tab)
    if args.limit is not None:
        area_limits = {a: args.limit for a in areas}
    else:
        area_limits = {a: yaml_limits.get(a, 0) for a in areas}
    logger.info(
        "tab=%s sheet=%s areas=%s limits=%s skip_contacts=%s",
        args.tab, sheet_name, areas, area_limits, args.skip_contacts,
    )

    # Serper API キーチェック (未設定なら早期エラー)
    try:
        serper = SerperClient()
    except SerperConfigError as exc:
        logger.error("Serper 設定エラー: %s", exc)
        logger.error(
            "解消手順: (1) https://serper.dev でキー発行 "
            "(2) リポジトリ直下に .env を作成し SERPER_API_KEY=xxxxx を追記 "
            "(3) 再実行"
        )
        return 2

    http_client = RateLimitedClient()
    robots = RobotsChecker(client=http_client, user_agent=http_client.user_agent)

    all_rows: List[Dict[str, str]] = []
    total = 0
    for area in areas:
        limit = area_limits.get(area, 0)
        if limit == 0 and args.limit is None:
            logger.info("area=%s は limits.yaml で 0 のためスキップ (STEP 未有効化)", area)
            continue

        logger.info("==== area=%s (limit=%s) 開始 ====", area, limit or "∞")
        for collector in collectors:
            for rec in collector.iter_records(serper, area, limit):
                assert isinstance(rec, Record)
                row = rec.as_row()
                if not args.skip_contacts and rec.website:
                    try:
                        info = extract_contacts.extract(http_client, robots, rec.website)
                        row["メールアドレス"] = ";".join(info.emails)
                        row["問い合わせフォームURL"] = info.contact_form_url or ""
                        row["担当者名"] = info.representative or ""
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "連絡先抽出に失敗 company=%s url=%s (%s)",
                            rec.company, rec.website, exc,
                        )
                all_rows.append(row)
                total += 1
                logger.info(
                    "[%d] %s | %s | 担当=%s | email=%s | form=%s",
                    total, rec.company, rec.website or "-",
                    row["担当者名"] or "-",
                    row["メールアドレス"] or "-",
                    row["問い合わせフォームURL"] or "-",
                )

    if not all_rows:
        logger.warning(
            "取得件数 0。Serper のレスポンスや limits.yaml の設定を確認してください。"
        )
        return 1

    added, updated = excel_io.upsert_tab(args.output, sheet_name, all_rows)
    logger.info(
        "Excel 書き出し完了: %s [%s] 追加=%d 更新=%d 取得=%d",
        args.output, sheet_name, added, updated, total,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
