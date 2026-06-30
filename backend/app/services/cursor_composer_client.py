"""Cursor Composer 2.5 API client — OpenAI-compatible chat completions."""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class ComposerClientError(Exception):
    def __init__(self, message: str, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class CursorComposerClient:
    """Thin HTTP client for Composer 2.5 market briefs."""

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "",
        completions_path: str = "",
        model: str = "",
        auth_mode: str = "",
        timeout_seconds: float = 60.0,
    ) -> None:
        settings = get_settings()
        self.api_key = api_key or settings.cursor_api_key
        self.base_url = (base_url or settings.cursor_api_base_url).rstrip("/")
        self.completions_path = completions_path or settings.cursor_chat_completions_path
        self.model = model or settings.cursor_composer_model
        self.auth_mode = (auth_mode or settings.cursor_http_auth).lower()
        self.timeout_seconds = timeout_seconds

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> dict[str, str]:
        return {"Content-Type": "application/json"}

    def _auth(self) -> httpx.Auth | tuple[str, str] | None:
        if not self.api_key:
            return None
        if self.auth_mode == "basic":
            return (self.api_key, "")
        return None

    def _bearer_headers(self) -> dict[str, str]:
        headers = self._headers()
        if self.auth_mode != "basic":
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _model_payload(self) -> str | dict[str, Any]:
        settings = get_settings()
        if settings.cursor_composer_use_standard_tier:
            return {
                "id": self.model,
                "params": [{"id": "fast", "value": "false"}],
            }
        return self.model

    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1200,
    ) -> str:
        if not self.configured:
            raise ComposerClientError("CURSOR_API_KEY not configured")

        url = f"{self.base_url}{self.completions_path}"
        payload: dict[str, Any] = {
            "model": self._model_payload(),
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                resp = await client.post(
                    url,
                    json=payload,
                    headers=self._bearer_headers(),
                    auth=self._auth(),
                )
        except httpx.HTTPError as exc:
            raise ComposerClientError(f"Composer HTTP error: {exc}") from exc

        if resp.status_code >= 400:
            raise ComposerClientError(
                f"Composer API {resp.status_code}: {resp.text[:500]}",
                status_code=resp.status_code,
            )

        data = resp.json()
        try:
            return str(data["choices"][0]["message"]["content"]).strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise ComposerClientError(f"Unexpected Composer response: {data}") from exc

    async def ping(self) -> dict[str, Any]:
        """Verify API key via /v1/me or /v0/me."""
        if not self.configured:
            return {"ok": False, "reason": "missing_api_key"}

        for path in ("/v1/me", "/v0/me"):
            url = f"{self.base_url}{path}"
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.get(
                        url,
                        headers=self._bearer_headers(),
                        auth=self._auth(),
                    )
                if resp.status_code < 400:
                    return {"ok": True, "path": path, "body": resp.json()}
            except Exception as exc:
                logger.debug("Composer ping %s failed: %s", path, exc)
        return {"ok": False, "reason": "auth_check_failed"}


def get_composer_client() -> CursorComposerClient:
    return CursorComposerClient()
