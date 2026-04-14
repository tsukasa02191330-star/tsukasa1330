"""レート制御付き HTTP クライアント。

- 同一ホストへのアクセス間隔 3 秒以上 + ジッター
- User-Agent は自社識別用の文字列を明示
- 5xx / 接続エラーは指数バックオフで最大 3 回リトライ
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Dict, Optional
from urllib.parse import urlparse

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = (
    "TsukasaRealEstateBrokerCollector/0.1 "
    "(+contact: please-set-your-email@example.co.jp) "
    "Python-requests"
)

DEFAULT_MIN_INTERVAL_SEC = 3.0
DEFAULT_JITTER_SEC = 1.5
DEFAULT_TIMEOUT_SEC = 20.0


@dataclass
class RateLimitedClient:
    """同一ホスト単位でアクセス間隔を制御する HTTP クライアント。"""

    user_agent: str = DEFAULT_USER_AGENT
    min_interval_sec: float = DEFAULT_MIN_INTERVAL_SEC
    jitter_sec: float = DEFAULT_JITTER_SEC
    timeout_sec: float = DEFAULT_TIMEOUT_SEC
    _last_access: Dict[str, float] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)
    _session: requests.Session = field(default_factory=requests.Session)

    def __post_init__(self) -> None:
        self._session.headers.update({"User-Agent": self.user_agent})

    def _wait_for_host(self, host: str) -> None:
        with self._lock:
            now = time.monotonic()
            last = self._last_access.get(host)
            if last is not None:
                wait = self.min_interval_sec - (now - last)
                if wait > 0:
                    sleep = wait + random.uniform(0.0, self.jitter_sec)
                    logger.debug("rate-limit: sleep %.2fs for host=%s", sleep, host)
                    time.sleep(sleep)
            self._last_access[host] = time.monotonic()

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=16),
        retry=retry_if_exception_type((requests.ConnectionError, requests.Timeout)),
    )
    def get(
        self,
        url: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        allow_redirects: bool = True,
    ) -> requests.Response:
        """URL を GET する。同一ホストは 3 秒以上の間隔を空ける。"""
        host = urlparse(url).netloc
        self._wait_for_host(host)
        logger.info("GET %s", url)
        resp = self._session.get(
            url,
            headers=headers,
            timeout=self.timeout_sec,
            allow_redirects=allow_redirects,
        )
        if 500 <= resp.status_code < 600:
            # 5xx は ConnectionError 扱いでリトライ対象にする
            raise requests.ConnectionError(f"status={resp.status_code} url={url}")
        return resp
