"""robots.txt 許可チェックユーティリティ。

`RobotsChecker.allowed(url)` でアクセス可否を判定する。
- robots.txt を取得できない / 解釈不能な場合は「不明」として False 寄り(保守的)
- 同一ホストの robots.txt は 1 度だけ取得してメモ化
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, Optional
from urllib import robotparser
from urllib.parse import urlparse

from .http_client import DEFAULT_USER_AGENT, RateLimitedClient

logger = logging.getLogger(__name__)


@dataclass
class RobotsChecker:
    client: RateLimitedClient
    user_agent: str = DEFAULT_USER_AGENT
    _cache: Dict[str, Optional[robotparser.RobotFileParser]] = field(default_factory=dict)

    def _load(self, host_root: str) -> Optional[robotparser.RobotFileParser]:
        if host_root in self._cache:
            return self._cache[host_root]

        robots_url = f"{host_root}/robots.txt"
        rp: Optional[robotparser.RobotFileParser]
        try:
            resp = self.client.get(robots_url, allow_redirects=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning("robots.txt 取得に失敗: %s (%s)", robots_url, exc)
            self._cache[host_root] = None
            return None

        if resp.status_code == 404:
            # robots.txt が無い = すべて許可 (慣例)
            rp = robotparser.RobotFileParser()
            rp.parse([])
            self._cache[host_root] = rp
            return rp
        if resp.status_code >= 400:
            logger.warning(
                "robots.txt status=%s url=%s → 保守的に全不許可扱い",
                resp.status_code,
                robots_url,
            )
            self._cache[host_root] = None
            return None

        rp = robotparser.RobotFileParser()
        rp.parse(resp.text.splitlines())
        self._cache[host_root] = rp
        return rp

    def allowed(self, url: str) -> bool:
        """URL が自 User-Agent に対して許可されているか。取得不能は不許可扱い。"""
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return False
        host_root = f"{parsed.scheme}://{parsed.netloc}"
        rp = self._load(host_root)
        if rp is None:
            # 取得できない場合は保守的に不許可
            return False
        try:
            return rp.can_fetch(self.user_agent, url)
        except Exception as exc:  # noqa: BLE001
            logger.warning("robots.txt 判定エラー url=%s (%s) → 不許可", url, exc)
            return False
