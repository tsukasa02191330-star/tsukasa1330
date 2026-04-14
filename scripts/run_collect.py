"""宅建業者リスト収集のメインスクリプト。

Usage:
    python scripts/run_collect.py --areas tokyo --source suumo --limit 5
    python scripts/run_collect.py --areas tokyo,kanagawa,saitama,chiba \
        --source suumo,athome,homes

出力先: data/brokers.csv (UPSERT)
ログ:   logs/run_YYYYMMDD_HHMMSS.log
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import sys
from typing import Dict, Iterable, List

# リポジトリ直下からの相対 import を通すためにパスを通す
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src import extract_contacts, portal_athome, portal_homes, portal_suumo, storage  # noqa: E402
from src.http_client import RateLimitedClient  # noqa: E402
from src.robots import RobotsChecker  # noqa: E402

SUPPORTED_AREAS = ("tokyo", "kanagawa", "saitama", "chiba")
SUPPORTED_SOURCES = ("suumo", "athome", "homes")

SOURCE_MODULES = {
    "suumo": portal_suumo,
    "athome": portal_athome,
    "homes": portal_homes,
}


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


def _parse_csv_arg(value: str, allowed: Iterable[str], name: str) -> List[str]:
    items = [v.strip() for v in value.split(",") if v.strip()]
    for item in items:
        if item not in allowed:
            raise SystemExit(
                f"--{name}: 未対応の値 '{item}'。利用可能: {', '.join(allowed)}"
            )
    return items


def main() -> int:
    parser = argparse.ArgumentParser(description="宅建業者リスト収集 (首都圏 / SUUMO・athome・HOME'S)")
    parser.add_argument(
        "--areas",
        default="tokyo",
        help=f"対象エリア(カンマ区切り)。例: tokyo,kanagawa。対応: {', '.join(SUPPORTED_AREAS)}",
    )
    parser.add_argument(
        "--source",
        default="suumo",
        help=f"データ源(カンマ区切り)。例: suumo,athome,homes。対応: {', '.join(SUPPORTED_SOURCES)}",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="各 (source, area) から取得する上限件数(初回は 5 〜 10 推奨)",
    )
    parser.add_argument(
        "--output",
        default="data/brokers.csv",
        help="出力 CSV (UPSERT)",
    )
    parser.add_argument(
        "--log-dir",
        default="logs",
        help="ログ出力先ディレクトリ",
    )
    parser.add_argument(
        "--skip-contacts",
        action="store_true",
        help="HP からの email / 問い合わせフォーム抽出をスキップ(疎通確認用)",
    )
    args = parser.parse_args()

    log_path = _setup_logging(args.log_dir)
    logger = logging.getLogger("run_collect")
    logger.info("ログ出力: %s", log_path)

    areas = _parse_csv_arg(args.areas, SUPPORTED_AREAS, "areas")
    sources = _parse_csv_arg(args.source, SUPPORTED_SOURCES, "source")
    logger.info("対象エリア=%s / ソース=%s / limit=%s", areas, sources, args.limit)

    client = RateLimitedClient()
    robots = RobotsChecker(client=client, user_agent=client.user_agent)

    all_rows: List[Dict[str, str]] = []
    total_collected = 0
    for src_name in sources:
        module = SOURCE_MODULES[src_name]
        logger.info("==== source=%s 開始 ====", src_name)
        try:
            for broker in module.iter_brokers(client, robots, areas, limit=args.limit):
                row = broker.as_row()
                if not args.skip_contacts:
                    try:
                        info = extract_contacts.extract(client, robots, row["HPリンク"])
                        row["メールアドレス"] = ";".join(info.emails)
                        row["問い合わせフォームリンク"] = info.contact_form_url or ""
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "連絡先抽出に失敗 company=%s url=%s (%s)",
                            row["会社名"], row["HPリンク"], exc,
                        )
                all_rows.append(row)
                total_collected += 1
                logger.info(
                    "[%d] %s | %s | email=%s | form=%s",
                    total_collected,
                    row["会社名"],
                    row["HPリンク"],
                    row["メールアドレス"] or "-",
                    row["問い合わせフォームリンク"] or "-",
                )
        except Exception as exc:  # noqa: BLE001
            logger.exception("source=%s の収集中にエラー (%s)", src_name, exc)
            continue

    if not all_rows:
        logger.warning(
            "収集件数ゼロ。各ソースの robots.txt / 利用規約 / HTML 構造変更を確認してください。"
        )
        return 1

    added, updated = storage.upsert(args.output, all_rows)
    logger.info(
        "CSV 書き出し完了: %s (追加=%d 件 / 更新=%d 件 / 取得=%d 件)",
        args.output, added, updated, total_collected,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
