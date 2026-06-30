"""Cursor Composer 2.5 client — official cursor-sdk (no chat/completions route)."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Optional

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class ComposerClientError(Exception):
    def __init__(self, message: str, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _model_selection():
    from cursor_sdk import ModelParameterValue, ModelSelection

    settings = get_settings()
    if settings.cursor_composer_use_standard_tier:
        return ModelSelection(
            id=settings.cursor_composer_model,
            params=(ModelParameterValue(id="fast", value="false"),),
        )
    return ModelSelection(id=settings.cursor_composer_model)


def _prompt_from_messages(messages: list[dict[str, str]]) -> str:
    parts: list[str] = []
    for msg in messages:
        role = str(msg.get("role", "user")).upper()
        content = str(msg.get("content", "")).strip()
        if content:
            parts.append(f"{role}:\n{content}")
    return "\n\n".join(parts)


def _send_sync(prompt: str) -> str:
    """Blocking Composer call via cursor-sdk."""
    from cursor_sdk import Agent, CloudAgentOptions, LocalAgentOptions

    settings = get_settings()
    api_key = settings.cursor_api_key
    if not api_key:
        raise ComposerClientError("CURSOR_API_KEY not configured")

    model = _model_selection()
    runtime = (settings.cursor_composer_runtime or "cloud").lower()
    opts: dict[str, Any] = {"model": model, "api_key": api_key}

    if runtime == "local":
        cwd = settings.cursor_composer_workspace or os.getcwd()
        opts["local"] = LocalAgentOptions(cwd=cwd)
    else:
        opts["cloud"] = CloudAgentOptions()

    with Agent.create(**opts) as agent:
        run = agent.send(prompt)
        text = run.text()
        if not text or not str(text).strip():
            raise ComposerClientError("Composer returned empty response")
        return str(text).strip()


class CursorComposerClient:
    """Composer 2.5 via cursor-sdk — cloud default for Docker/EC2."""

    def __init__(self, api_key: str = "", timeout_seconds: float = 90.0) -> None:
        settings = get_settings()
        self.api_key = api_key or settings.cursor_api_key
        self.base_url = settings.cursor_api_base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1200,
    ) -> str:
        del temperature, max_tokens  # SDK controls generation; prompt carries instructions
        if not self.configured:
            raise ComposerClientError("CURSOR_API_KEY not configured")
        prompt = _prompt_from_messages(messages)
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(_send_sync, prompt),
                timeout=self.timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            raise ComposerClientError(f"Composer timed out after {self.timeout_seconds}s") from exc
        except ComposerClientError:
            raise
        except Exception as exc:
            raise ComposerClientError(f"Composer SDK error: {exc}") from exc

    async def ping(self) -> dict[str, Any]:
        if not self.configured:
            return {"ok": False, "reason": "missing_api_key"}

        settings = get_settings()
        auth = (self.api_key, "") if settings.cursor_http_auth == "basic" else None
        headers = {}
        if settings.cursor_http_auth != "basic":
            headers["Authorization"] = f"Bearer {self.api_key}"

        for path in ("/v1/me", "/v0/me"):
            url = f"{self.base_url}{path}"
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.get(url, headers=headers, auth=auth)
                if resp.status_code < 400:
                    body = resp.json()
                    return {
                        "ok": True,
                        "path": path,
                        "apiKeyName": body.get("apiKeyName"),
                        "userEmail": body.get("userEmail"),
                    }
            except Exception as exc:
                logger.debug("Composer ping %s failed: %s", path, exc)
        return {"ok": False, "reason": "auth_check_failed"}


def get_composer_client() -> CursorComposerClient:
    return CursorComposerClient()
