"""Settings REST endpoints."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Optional

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

log = logging.getLogger("api.settings")

router = APIRouter(prefix="/api/settings", tags=["settings"])

_CONFIG_PATH = Path("config.yaml")


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class SettingsUpdateRequest(BaseModel):
    """Partial settings update."""
    llm: Optional[dict] = None
    imagegen: Optional[dict] = None
    tts: Optional[dict] = None
    subtitle: Optional[dict] = None
    video: Optional[dict] = None
    videogen: Optional[dict] = None
    novel: Optional[dict] = None


class TestKeyRequest(BaseModel):
    """Test an API key."""
    provider: str  # "openai" | "deepseek" | "gemini" | "siliconflow" | etc.
    api_key: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_KEY_ENV_NAMES = {
    "OPENAI_API_KEY",
    "DEEPSEEK_API_KEY",
    "GEMINI_API_KEY",
    "SILICONFLOW_API_KEY",
    "DASHSCOPE_API_KEY",
    "TOGETHER_API_KEY",
    "KLING_API_KEY",
    "SEEDANCE_API_KEY",
    "MINIMAX_API_KEY",
}


def _mask_value(key: str, value: Any) -> Any:
    """Mask sensitive values (API keys)."""
    if isinstance(value, str) and any(kw in key.upper() for kw in ("KEY", "SECRET", "TOKEN", "PASSWORD")):
        if len(value) > 8:
            return value[:4] + "****" + value[-4:]
        elif value:
            return "****"
    return value


def _sanitize_config(config: dict) -> dict:
    """Recursively mask sensitive values in config."""
    sanitized = {}
    for k, v in config.items():
        if isinstance(v, dict):
            sanitized[k] = _sanitize_config(v)
        else:
            sanitized[k] = _mask_value(k, v)
    return sanitized


def _load_config() -> dict:
    """Load config.yaml."""
    if not _CONFIG_PATH.exists():
        return {}
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _save_config(config: dict) -> None:
    """Save config.yaml."""
    with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("")
def get_settings():
    """Return current config (sanitized, no full API keys)."""
    config = _load_config()
    sanitized = _sanitize_config(config)

    # Add detected environment keys
    env_keys = {}
    for name in _KEY_ENV_NAMES:
        val = os.environ.get(name, "")
        if val:
            env_keys[name] = _mask_value(name, val)
        else:
            env_keys[name] = None

    return {
        "config": sanitized,
        "env_keys": env_keys,
    }


@router.put("")
def update_settings(req: SettingsUpdateRequest):
    """Update settings. Merges into existing config."""
    config = _load_config()

    updates = req.model_dump(exclude_none=True)
    for section, values in updates.items():
        if isinstance(values, dict):
            if section not in config:
                config[section] = {}
            config[section].update(values)
        else:
            config[section] = values

    _save_config(config)
    return {"status": "ok", "config": _sanitize_config(config)}


@router.post("/test-key")
def test_key(req: TestKeyRequest):
    """Test an API key connectivity."""
    provider = req.provider.lower()
    api_key = req.api_key.strip()

    if not api_key:
        raise HTTPException(400, "api_key is required")

    try:
        if provider in ("openai", "deepseek"):
            import httpx
            base_url = "https://api.openai.com/v1" if provider == "openai" else "https://api.deepseek.com/v1"
            r = httpx.get(
                f"{base_url}/models",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=10.0,
            )
            if r.status_code == 200:
                return {"status": "ok", "message": f"{provider} key is valid"}
            elif r.status_code == 401:
                return {"status": "error", "message": "Invalid API key (401 Unauthorized)"}
            else:
                return {"status": "error", "message": f"Unexpected status: {r.status_code}"}

        elif provider == "gemini":
            import httpx
            r = httpx.get(
                f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}",
                timeout=10.0,
            )
            if r.status_code == 200:
                return {"status": "ok", "message": "Gemini key is valid"}
            else:
                return {"status": "error", "message": f"Gemini API returned status {r.status_code}"}

        elif provider == "siliconflow":
            import httpx
            r = httpx.get(
                "https://api.siliconflow.cn/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=10.0,
            )
            if r.status_code == 200:
                return {"status": "ok", "message": "SiliconFlow key is valid"}
            else:
                return {"status": "error", "message": f"SiliconFlow returned status {r.status_code}"}

        else:
            return {"status": "unknown", "message": f"No test implemented for provider: {provider}"}

    except Exception as exc:
        return {"status": "error", "message": f"Connection failed: {exc}"}
