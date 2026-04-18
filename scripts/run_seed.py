"""シードリスト (data/seeds/*.yaml) から連絡先を抽出して Excel に書き込む。

Usage:
    python scripts/run_seed.py                   # 全タブ処理
    python scripts/run_seed.py --tab shigyo      # 士業のみ
    python scripts/run_seed.py --tab takken --limit 10  # 10 件でテスト

YAML フォーマット (data/seeds/<tab>.yaml):
    - name: 〇〇事務所
      url: https://example.jp/
      pref: 東京都
      category: 税理士   # 出典列に使われる (省略可)
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import sys
from typing import Dict, List

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import yaml  # noqa: E402

from src import excel_io, extract_contacts  # noqa: E402
from src.http_client import RateLimitedClient  # noqa: E402
from src.robots import RobotsChecker  # noqa: E402

SEEDS_DIR = os.path.join(_ROOT, "data", "seeds")
DEFAULT_OUTPUT = os.path.join(
    r"C:\Users\User\Desktop\claude\リスト作成\スプレットシート",
    "sales_list.xlsx",
) if os.name == "nt" else os.path.join(_ROOT, "data", "sales_list.xlsx")

TAB_CONFIG = {
    "shigyo":  {"sheet": "士業",       "seed": "shigyo.yaml"},
    "takken":  {"sheet": "宅建業者",   "seed": "takken.yaml"},
    "souzoku": {"sheet": "相続専門業者", "seed": "souzoku.yaml"},
    "chintai": {"sheet": "賃貸管理会社", "seed": "chintai.yaml"},
}


def _setup_logging(log_dir: str) -> None:
    os.makedirs(log_dir, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(log_dir, f"seed_{stamp}.log")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def _load_seeds(seed_file: str, limit: int) -> List[Dict]:
    path = os.path.join(SEEDS_DIR, seed_file)
    if not os.path.exists(path):
        logging.warning("シードファイルが見つかりません: %s", path)
        return []
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or []
    return data[:limit] if limit else data


def _process_tab(
    tab_key: str,
    client: RateLimitedClient,
    robots: RobotsChecker,
    output: str,
    limit: int,
    skip_contacts: bool,
) -> None:
    cfg = TAB_CONFIG[tab_key]
    sheet = cfg["sheet"]
    seeds = _load_seeds(cfg["seed"], limit)
    if not seeds:
        logging.warning("[%s] シードが空です。data/seeds/%s を確認してください。", sheet, cfg["seed"])
        return

    logging.info("==== [%s] %d 件処理開始 ====", sheet, len(seeds))
    rows: List[Dict] = []

    for i, entry in enumerate(seeds, 1):
        name = (entry.get("name") or "").strip()
        url = (entry.get("url") or "").strip()
        pref = (entry.get("pref") or "東京都").strip()
        category = (entry.get("category") or "").strip()
        source = f"seed:{category}" if category else "seed"

        if not name or not url:
            logging.warning("[%d] name/url 空のためスキップ", i)
            continue

        row: Dict = {
            "都道府県": pref,
            "業者名・事務所名": name,
            "担当者名": "",
            "メールアドレス": "",
            "問い合わせフォームURL": "",
            "HP": url,
            "出典": source,
            "ステータス": "",
            "送信日時": "",
            "送信方式": "",
            "エラー": "",
        }

        if not skip_contacts:
            try:
                info = extract_contacts.extract(client, robots, url)
                row["メールアドレス"] = ";".join(info.emails)
                row["問い合わせフォームURL"] = info.contact_form_url or ""
                row["担当者名"] = info.representative or ""
                logging.info(
                    "[%d/%d] %s | email=%s | form=%s | 担当=%s",
                    i, len(seeds), name,
                    row["メールアドレス"] or "-",
                    row["問い合わせフォームURL"] or "-",
                    row["担当者名"] or "-",
                )
            except Exception as exc:  # noqa: BLE001
                logging.warning("[%d/%d] %s 抽出失敗: %s", i, len(seeds), name, exc)
        else:
            logging.info("[%d/%d] %s (skip-contacts)", i, len(seeds), name)

        rows.append(row)

    if not rows:
        logging.warning("[%s] 出力行なし", sheet)
        return

    added, updated = excel_io.upsert_tab(output, sheet, rows)
    logging.info("[%s] 完了: 追加=%d 更新=%d", sheet, added, updated)


def main() -> int:
    parser = argparse.ArgumentParser(description="シードベース 連絡先収集")
    parser.add_argument(
        "--tab",
        choices=list(TAB_CONFIG.keys()),
        default=None,
        help="対象タブ (省略時は全タブ). shigyo / takken / souzoku / chintai",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="各タブ上限件数 (0=全件)",
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        help=f"出力 xlsx (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--log-dir",
        default=os.path.join(_ROOT, "logs"),
        help="ログ出力ディレクトリ",
    )
    parser.add_argument(
        "--skip-contacts",
        action="store_true",
        help="HP からのメール/フォーム/担当者 抽出をスキップ (URL 確認のみ)",
    )
    args = parser.parse_args()

    _setup_logging(args.log_dir)
    logger = logging.getLogger(__name__)

    tabs = [args.tab] if args.tab else list(TAB_CONFIG.keys())
    logger.info("対象タブ: %s  出力: %s  上限: %s",
                tabs, args.output, args.limit or "全件")

    client = RateLimitedClient()
    robots = RobotsChecker(client=client, user_agent=client.user_agent)

    for tab in tabs:
        _process_tab(tab, client, robots, args.output, args.limit, args.skip_contacts)

    logger.info("=== 全タブ完了。%s を開いてください。===", args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
