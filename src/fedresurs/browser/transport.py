from __future__ import annotations

from typing import Any

from fedresurs.browser.errors import SessionExpiredError

_FETCH_JS = """
async ({path, timeoutMs}) => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
        const response = await fetch(path, {
            credentials: 'include',
            headers: {Accept: 'application/json'},
            signal: controller.signal,
        });
        const body = await response.text();
        return {status: response.status, body};
    } finally {
        clearTimeout(timer);
    }
}
"""


class PageTransport:
    """Runs same-origin fetch inside the browser page (keeps Qrator cookies)."""

    def __init__(self, page: Any, timeout_ms: int = 60_000) -> None:
        self.page = page
        self.timeout_ms = timeout_ms

    async def get_text(self, path: str) -> tuple[int, str]:
        if self.page.is_closed():
            raise SessionExpiredError("browser page is closed")
        result = await self.page.evaluate(_FETCH_JS, {"path": path, "timeoutMs": self.timeout_ms})
        return int(result["status"]), str(result["body"])
