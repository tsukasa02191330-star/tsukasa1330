"""Serper API (https://serper.dev) の Places 検索ラッパー。

Google Maps のローカル検索結果を返す。営業リストの一次ソースとして使用する。

環境変数:
    SERPER_API_KEY -- 必須。.env または export で設定する。

使い方:
    from src.serper import SerperClient
    client = SerperClient()
    places = client.search_places(
        query="不動産",
        location="Tokyo, Japan",
        gl="jp", hl="ja",
        max_results=100,
    )
    # places は {title, website, address, phoneNumber, category, ...} の dict list
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

SERPER_ENDPOINT = "https://google.serper.dev/places"
DEFAULT_PAGE_SIZE = 20  # Serper Places は 1 ページ 20 件前後が通例
DEFAULT_RATE_LIMIT_SEC = 1.1  # 1 req/sec 程度。無料プランでも安全に収まる値


class SerperConfigError(RuntimeError):
    """API キー未設定など、実行前に解消すべき設定エラー。"""


class SerperAPIError(RuntimeError):
    """Serper API からエラーレスポンスが返された場合。"""


def _load_api_key() -> str:
    """環境変数 (または python-dotenv) から API キーを読む。未設定なら例外。"""
    # 遅延 import で python-dotenv が未インストールでも他機能は動かす
    try:
        from dotenv import load_dotenv  # type: ignore

        load_dotenv()
    except ImportError:
        pass

    key = os.environ.get("SERPER_API_KEY", "").strip()
    if not key:
        raise SerperConfigError(
            "SERPER_API_KEY が .env に未設定です。"
            "https://serper.dev でキーを発行し、.env に SERPER_API_KEY=... を追記してください。"
        )
    return key


class SerperClient:
    """Serper Places API の最小ラッパー。"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        rate_limit_sec: float = DEFAULT_RATE_LIMIT_SEC,
        timeout: float = 20.0,
    ) -> None:
        self.api_key = api_key or _load_api_key()
        self.rate_limit_sec = rate_limit_sec
        self.timeout = timeout
        self._last_call_ts: float = 0.0

    # ------------------------------------------------------------------
    # internal
    # ------------------------------------------------------------------
    def _throttle(self) -> None:
        elapsed = time.time() - self._last_call_ts
        wait = self.rate_limit_sec - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_call_ts = time.time()

    def _post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self._throttle()
        headers = {
            "X-API-KEY": self.api_key,
            "Content-Type": "application/json",
        }
        try:
            resp = requests.post(
                SERPER_ENDPOINT, headers=headers, json=payload, timeout=self.timeout
            )
        except requests.RequestException as exc:
            raise SerperAPIError(f"Serper API への通信に失敗: {exc}") from exc

        if resp.status_code >= 400:
            raise SerperAPIError(
                f"Serper API エラー status={resp.status_code} body={resp.text[:500]}"
            )
        try:
            return resp.json()
        except ValueError as exc:
            raise SerperAPIError(f"Serper API から JSON 以外が返却: {exc}") from exc

    # ------------------------------------------------------------------
    # public
    # ------------------------------------------------------------------
    def search_places(
        self,
        query: str,
        location: str,
        max_results: int = 20,
        gl: str = "jp",
        hl: str = "ja",
    ) -> List[Dict[str, Any]]:
        """Places 検索。

        Args:
            query: 検索キーワード (例: "不動産")
            location: 地名 (例: "Tokyo, Japan")
            max_results: 取得上限。0 なら 1 ページだけ取得 (≒ DEFAULT_PAGE_SIZE 件)。
                Serper Places はページング(page=1,2,3,...)に対応。
            gl: 国コード (default: jp)
            hl: 言語 (default: ja)

        Returns:
            places 配列を dict のリストで返す。website が無いレコードも含む。
        """
        results: List[Dict[str, Any]] = []
        page = 1
        # max_results=0 は 1 ページで打ち切り、それ以外は max_results を超えるまで
        hard_cap = max_results if max_results > 0 else DEFAULT_PAGE_SIZE

        seen_titles = set()
        while len(results) < hard_cap and page <= 20:  # 念のため 20 ページで打ち切り
            payload = {
                "q": query,
                "location": location,
                "gl": gl,
                "hl": hl,
                "page": page,
            }
            logger.info(
                "serper: POST q=%r location=%r page=%d", query, location, page
            )
            data = self._post(payload)
            places = data.get("places") or []
            if not places:
                logger.info("serper: page=%d で places 空。終了", page)
                break

            added = 0
            for p in places:
                title = (p.get("title") or "").strip()
                if not title or title in seen_titles:
                    continue
                seen_titles.add(title)
                results.append(p)
                added += 1
                if len(results) >= hard_cap:
                    break
            logger.info(
                "serper: page=%d で %d 件取得 (累計 %d / cap %d)",
                page, added, len(results), hard_cap,
            )
            if added == 0:
                # これ以上新しい結果が無い
                break
            page += 1

        return results
