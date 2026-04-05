from __future__ import annotations

import logging
from typing import Any

import httpx

log = logging.getLogger("metrics_margin.telegram")

_MAX_MESSAGE_LEN = 4096


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str, timeout: float = 15.0) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id
        self._client = httpx.Client(timeout=timeout)

    @property
    def enabled(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def send(self, html: str) -> None:
        if not self.enabled:
            log.debug("telegram_disabled (no token/chat_id)")
            return
        chunks = _split_message(html)
        for chunk in chunks:
            self._post(chunk)

    def _post(self, text: str) -> None:
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload: dict[str, Any] = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        try:
            resp = self._client.post(url, json=payload)
            if resp.status_code != 200:
                log.warning("telegram_send_failed status=%s body=%s", resp.status_code, resp.text[:200])
            else:
                log.info("telegram_sent len=%d", len(text))
        except Exception as exc:
            log.warning("telegram_send_error error=%s", exc)

    def close(self) -> None:
        self._client.close()


def _split_message(html: str) -> list[str]:
    if len(html) <= _MAX_MESSAGE_LEN:
        return [html]
    lines = html.split("\n")
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in lines:
        line_len = len(line) + 1  # +1 for newline
        if current_len + line_len > _MAX_MESSAGE_LEN and current:
            chunks.append("\n".join(current))
            current = []
            current_len = 0
        current.append(line)
        current_len += line_len
    if current:
        chunks.append("\n".join(current))
    return chunks
