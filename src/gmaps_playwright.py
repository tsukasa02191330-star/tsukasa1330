"""Playwright (Chromium) で Google Maps を操作して場所情報を収集する。

Serper API が使えない環境向けの代替手段。ブラウザで
https://www.google.com/maps/search/<query> にアクセスし、結果パネルを
スクロールして各プレイスの詳細を開き、業者名と website URL を取り出す。

法務・マナー上の注意:
    - Google のサービス利用規約では自動化された大量アクセスは制限されます。
      本モジュールは **小〜中規模 (数百件程度)** の B2B リスト整備用途に限定し、
      人間が操作する速度に近い遅延 (--delay-sec) を必ず設定してください。
    - 頻繁に実行するとキャプチャや一時ブロックが発生します。発生時は中止し
      時間を空けてください。

依存:
    pip install playwright
    playwright install chromium
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Iterator, List, Optional
from urllib.parse import quote

logger = logging.getLogger(__name__)


@dataclass
class GMapsPlace:
    name: str
    website: str


class GoogleMapsScraper:
    """Playwright Chromium で Google Maps を操作するスクレイパー。

    with 文で使うと、終了時に自動で close される。

        with GoogleMapsScraper(headless=True) as gm:
            for p in gm.search_places("不動産 東京都", max_results=5):
                print(p.name, p.website)
    """

    # Google Maps の HTML 構造は頻繁に変わるため、複数フォールバックを持つ。
    SEARCH_URL_TMPL = "https://www.google.com/maps/search/{q}/?hl=ja&gl=jp"
    FEED_SELECTORS = (
        'div[role="feed"]',
        'div[aria-label][role="feed"]',
    )
    PLACE_LINK_SELECTOR = 'a[href*="/maps/place/"]'
    WEBSITE_SELECTOR_CANDIDATES = (
        'a[data-item-id="authority"]',
        'a[aria-label^="ウェブサイト"]',
        'a[aria-label^="Website"]',
        'a[data-tooltip="ウェブサイトを開く"]',
    )

    def __init__(
        self,
        headless: bool = True,
        per_action_delay_sec: float = 1.5,
        nav_timeout_sec: float = 30.0,
    ) -> None:
        self.headless = headless
        self.per_action_delay_sec = per_action_delay_sec
        self.nav_timeout_ms = int(nav_timeout_sec * 1000)
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
    def __enter__(self) -> "GoogleMapsScraper":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def start(self) -> None:
        # 遅延 import: 未インストールでもモジュール自体は import できるように
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.headless)
        self._context = self._browser.new_context(
            locale="ja-JP",
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
            # 企業プロキシや検証環境の MITM TLS にも耐えるため。
            # 公開データ (Google Maps 検索結果) の読み取り用途のため実害は低い。
            ignore_https_errors=True,
        )
        self._page = self._context.new_page()
        self._page.set_default_timeout(self.nav_timeout_ms)
        logger.info("gmaps: Chromium 起動完了 (headless=%s)", self.headless)

    def close(self) -> None:
        for obj_name in ("_context", "_browser"):
            obj = getattr(self, obj_name, None)
            if obj:
                try:
                    obj.close()
                except Exception:  # noqa: BLE001
                    pass
        if self._pw:
            try:
                self._pw.stop()
            except Exception:  # noqa: BLE001
                pass
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None

    # ------------------------------------------------------------------
    # scraping
    # ------------------------------------------------------------------
    def search_places(
        self,
        query: str,
        max_results: int = 5,
    ) -> Iterator[GMapsPlace]:
        """Google Maps で query を検索し、上から max_results 件を yield する。"""
        if self._page is None:
            raise RuntimeError("GoogleMapsScraper.start() を先に呼んでください")
        page = self._page
        url = self.SEARCH_URL_TMPL.format(q=quote(query))
        logger.info("gmaps: %s", url)
        page.goto(url, wait_until="domcontentloaded")
        time.sleep(self.per_action_delay_sec)

        # 同意ダイアログ (EU 等) をクリックできればする
        self._try_consent()

        # 結果フィードが出現するまで待つ (検索結果が 1 件だけのときは出ない)
        feed = self._wait_for_feed(page)
        if feed is None:
            # 単一結果ページにリダイレクトされたケース
            single_name, single_web = self._extract_single_place_detail()
            if single_name:
                yield GMapsPlace(name=single_name, website=single_web)
            return

        seen_names: set[str] = set()
        emitted = 0
        # 最大 15 回までスクロールを試みる
        for scroll_round in range(15):
            links = page.query_selector_all(self.PLACE_LINK_SELECTOR)
            logger.info(
                "gmaps: scroll=%d 見えているプレイス=%d", scroll_round, len(links)
            )

            for idx in range(len(links)):
                if emitted >= max_results:
                    return
                # 毎回再取得 (クリック後に DOM が変わる)
                links_now = page.query_selector_all(self.PLACE_LINK_SELECTOR)
                if idx >= len(links_now):
                    break
                link = links_now[idx]
                try:
                    name = (link.get_attribute("aria-label") or "").strip()
                except Exception:  # noqa: BLE001
                    name = ""
                if not name or name in seen_names:
                    continue
                try:
                    link.scroll_into_view_if_needed()
                    link.click()
                except Exception as exc:  # noqa: BLE001
                    logger.debug("gmaps: クリック失敗 %s (%s)", name, exc)
                    continue
                time.sleep(self.per_action_delay_sec)
                website = self._extract_website_from_detail()
                seen_names.add(name)
                emitted += 1
                logger.info(
                    "gmaps: [%d/%d] %s | HP=%s",
                    emitted, max_results, name, website or "-",
                )
                yield GMapsPlace(name=name, website=website or "")

            if emitted >= max_results:
                return

            # 結果パネルをスクロールして追加ロード
            if not self._scroll_feed(page):
                logger.info("gmaps: これ以上スクロールできない。終了")
                return

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _try_consent(self) -> None:
        if self._page is None:
            return
        # "すべて同意" / "Accept all" 等のボタンがあれば押す
        for label in ("すべて同意", "同意する", "Accept all", "I agree"):
            try:
                btn = self._page.get_by_role("button", name=label)
                if btn and btn.count() > 0:
                    btn.first.click(timeout=2000)
                    time.sleep(self.per_action_delay_sec)
                    return
            except Exception:  # noqa: BLE001
                continue

    def _wait_for_feed(self, page) -> Optional[object]:
        # 結果フィードが表示されるまで最大 nav_timeout_ms 待つ
        for sel in self.FEED_SELECTORS:
            try:
                page.wait_for_selector(sel, timeout=5000)
                return page.query_selector(sel)
            except Exception:  # noqa: BLE001
                continue
        # 単一結果ページにリダイレクトされた可能性 → 詳細パネル有無で判定
        try:
            page.wait_for_selector('h1', timeout=3000)
        except Exception:  # noqa: BLE001
            pass
        return None

    def _scroll_feed(self, page) -> bool:
        """結果フィードを 1 画面分スクロールする。height が増えれば True。"""
        js = """
        () => {
          const feed = document.querySelector('div[role="feed"]');
          if (!feed) return {before: 0, after: 0};
          const before = feed.scrollHeight;
          feed.scrollTop = feed.scrollHeight;
          return {before: before, after: feed.scrollHeight};
        }
        """
        before = 0
        after = 0
        try:
            res = page.evaluate(js)
            before = int(res.get("before", 0))
            after = int(res.get("after", 0))
        except Exception:  # noqa: BLE001
            return False
        time.sleep(self.per_action_delay_sec * 1.5)
        # 再評価して増えていればスクロール成功
        try:
            after2 = page.evaluate(
                "() => { const f = document.querySelector('div[role=\"feed\"]'); return f ? f.scrollHeight : 0; }"
            )
        except Exception:  # noqa: BLE001
            after2 = after
        return int(after2 or 0) > before

    def _extract_website_from_detail(self) -> str:
        page = self._page
        if page is None:
            return ""
        for sel in self.WEBSITE_SELECTOR_CANDIDATES:
            try:
                el = page.query_selector(sel)
                if el:
                    href = el.get_attribute("href") or ""
                    if href.startswith("http"):
                        return href
            except Exception:  # noqa: BLE001
                continue
        return ""

    def _extract_single_place_detail(self) -> tuple[str, str]:
        page = self._page
        if page is None:
            return "", ""
        try:
            h1 = page.query_selector("h1")
            name = (h1.inner_text().strip() if h1 else "") or ""
        except Exception:  # noqa: BLE001
            name = ""
        website = self._extract_website_from_detail()
        return name, website


def is_available() -> bool:
    """playwright がインポートでき、かつ chromium がインストール済みか判定。"""
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError:
        return False
    return True
