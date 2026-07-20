"""Model settings store: lets a user pick a provider/model/key from the UI
instead of editing `backend/.env` (feature: in-app model picker).

Design intent (see docs/plans — model picker + open-source release):
  - `PROVIDER_REGISTRY` is the backend-owned typed list the UI renders from,
    the same pattern as `backend.agent.system_prompt.SKILLS` -> `/agent/skills`.
  - `SettingsStore` persists a *user override* to a small local JSON file so a
    pasted key survives a backend restart. An empty/missing store resolves to
    exactly today's env-only behavior — existing deployments are unaffected.
  - The raw API key NEVER appears in `public()` (the only thing routes may
    return) or in any `__repr__`/log line. `resolve()` returns it because the
    provider factory needs the real value to construct a client — that value
    must stay inside the process, never re-serialized to a client response.
"""

from __future__ import annotations

import json
import os
import stat
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

UNSET = object()  # sentinel: "argument not passed" (distinct from None/"")

DEFAULT_SETTINGS_PATH = (
    Path(__file__).resolve().parent.parent / ".data" / "settings.json"
)

# ---------------------------------------------------------------------------
# Provider registry — the UI's source of truth for what it can offer.
# ---------------------------------------------------------------------------

PROVIDER_REGISTRY: list[dict[str, Any]] = [
    {
        "id": "gemini",
        "label": "Google Gemini",
        "provider": "gemini",
        "default_model": "gemini-2.5-flash",
        "needs_key": True,
        "supports_base_url": False,
        "key_env_vars": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
        "key_help_url": "https://aistudio.google.com/apikey",
        "blurb": "Recommended. Free tier — paste a key from Google AI Studio, no card needed.",
    },
    {
        "id": "anthropic",
        "label": "Claude (Anthropic)",
        "provider": "anthropic",
        "default_model": "claude-sonnet-5",
        "needs_key": True,
        "supports_base_url": False,
        "key_env_vars": ["ANTHROPIC_API_KEY"],
        "key_help_url": "https://platform.claude.com/",
        "blurb": "Strong tool use and vision. Paid — usage-based billing on your Anthropic account.",
    },
    {
        "id": "openai",
        "label": "OpenAI",
        "provider": "openai",
        "default_model": "gpt-4o-mini",
        "needs_key": True,
        "supports_base_url": False,
        "key_env_vars": ["OPENAI_API_KEY"],
        "key_help_url": "https://platform.openai.com/api-keys",
        "blurb": "Paid — usage-based billing on your OpenAI account.",
    },
    {
        "id": "local",
        "label": "Local model (free)",
        "provider": "openai",
        "default_model": "qwen2.5-vl",
        "needs_key": False,
        "supports_base_url": True,
        "default_base_url": "http://localhost:11434/v1",
        "key_env_vars": [],
        "blurb": (
            "Ollama, LM Studio, or vLLM running on your machine. Must be a VISION "
            "model — the agent sees the scene through captured frames."
        ),
    },
]

_REGISTRY_BY_ID = {entry["id"]: entry for entry in PROVIDER_REGISTRY}


def _key_in_env(entry: dict[str, Any]) -> bool:
    return any(os.environ.get(name) for name in entry.get("key_env_vars", []))


def providers_public() -> list[dict[str, Any]]:
    """Registry entries plus a live `key_in_env` flag. Never includes a key value."""
    return [{**entry, "key_in_env": _key_in_env(entry)} for entry in PROVIDER_REGISTRY]


class UnknownPresetError(ValueError):
    """Raised when a preset id isn't in PROVIDER_REGISTRY."""


def registry_entry(preset: str) -> dict[str, Any] | None:
    """Public lookup — routes should use this instead of reaching into the
    module-private `_REGISTRY_BY_ID` dict."""
    return _REGISTRY_BY_ID.get(preset)


# ---------------------------------------------------------------------------
# Settings store
# ---------------------------------------------------------------------------

@dataclass
class ModelSettings:
    """What's persisted. All-None means 'use env, same as before this feature'."""

    preset: str | None = None
    model: str | None = None
    api_key: str | None = None
    base_url: str | None = None


@dataclass
class ResolvedConfig:
    """What the provider factory actually consumes for one agent run."""

    provider: str
    model: str | None
    api_key: str | None
    base_url: str | None
    key_set: bool
    key_source: str | None  # "ui" | "env" | None
    source: str  # "ui" | "env" | "default"
    preset: str = field(default="gemini")


class SettingsStore:
    """Reads/writes a single user-chosen model override, best-effort persisted.

    Not for secrets-at-rest hardening — this is a local single-user dev tool.
    The bar is "don't commit it, don't world-read it, never echo it back."
    """

    def __init__(self, path: Path | None = None):
        self._path = path or DEFAULT_SETTINGS_PATH
        self._lock = threading.Lock()
        self._settings = ModelSettings()
        self._load()

    # -- persistence --------------------------------------------------------
    def _load(self) -> None:
        try:
            raw = json.loads(self._path.read_text())
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return
        self._settings = ModelSettings(
            preset=raw.get("preset"),
            model=raw.get("model"),
            api_key=raw.get("api_key"),
            base_url=raw.get("base_url"),
        )

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "preset": self._settings.preset,
            "model": self._settings.model,
            "api_key": self._settings.api_key,
            "base_url": self._settings.base_url,
        }
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2))
        os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)  # 0o600, owner read/write only
        tmp.replace(self._path)

    # -- mutation -------------------------------------------------------------
    def update(
        self,
        *,
        preset: str,
        model: str | None = None,
        api_key: str | None = UNSET,  # type: ignore[assignment]
        base_url: str | None = None,
    ) -> None:
        if preset not in _REGISTRY_BY_ID:
            raise UnknownPresetError(preset)
        with self._lock:
            self._settings.preset = preset
            self._settings.model = model
            self._settings.base_url = base_url
            if api_key is not UNSET:
                # "" clears the stored key; a string replaces it; omitted keeps it.
                self._settings.api_key = api_key or None
            self._save()

    # -- reads ----------------------------------------------------------------
    def public(self) -> dict[str, Any]:
        """Safe-to-return view: never includes the raw key."""
        cfg = self.resolve()
        return {
            "preset": cfg.preset,
            "provider": cfg.provider,
            "model": cfg.model,
            "base_url": cfg.base_url,
            "key_set": cfg.key_set,
            "key_source": cfg.key_source,
            "source": cfg.source,
        }

    def resolve(self) -> ResolvedConfig:
        """Precedence: saved UI override -> MODEL_PROVIDER/MODEL_NAME/OPENAI_BASE_URL
        env (today's pre-picker behavior) -> hard default (gemini).

        A UI-saved preset wins outright once one exists. Until then, this must
        reproduce exactly what `get_provider()` used to do when called bare —
        including a non-default `MODEL_PROVIDER` (e.g. "openai" pointed at a
        local vLLM via `OPENAI_BASE_URL`) — so setting env vars keeps working
        for anyone who hasn't touched the in-app settings panel.
        """
        s = self._settings

        if s.preset:
            entry = _REGISTRY_BY_ID.get(s.preset, _REGISTRY_BY_ID["gemini"])
            preset = s.preset
            provider = entry["provider"]
            model = s.model or entry["default_model"]
            base_url = s.base_url or entry.get("default_base_url")
            is_ui = True
            env_active = False  # unused on this branch; source is always "ui" below
        else:
            raw_provider = os.environ.get("MODEL_PROVIDER")
            env_provider = (raw_provider or "gemini").lower()
            env_model_name = os.environ.get("MODEL_NAME")
            env_base_url = os.environ.get("OPENAI_BASE_URL") if env_provider == "openai" else None
            # Map back to a registry entry for default_model/key_env_vars/UI display.
            # "openai provider + a base_url" reads as the "local" preset card;
            # otherwise match by provider name (gemini/anthropic/openai all have
            # a same-named registry id).
            if env_provider == "openai" and env_base_url:
                entry = _REGISTRY_BY_ID["local"]
            else:
                entry = next(
                    (e for e in PROVIDER_REGISTRY if e["provider"] == env_provider),
                    _REGISTRY_BY_ID["gemini"],
                )
            preset = entry["id"]
            provider = env_provider
            model = env_model_name or entry["default_model"]
            base_url = env_base_url or entry.get("default_base_url")
            is_ui = False
            # Did MODEL_PROVIDER/MODEL_NAME/OPENAI_BASE_URL actually say anything,
            # or are we just falling all the way through to the hard default?
            env_active = bool(raw_provider or env_model_name or env_base_url)

        if s.api_key:
            return ResolvedConfig(
                provider=provider, model=model, api_key=s.api_key, base_url=base_url,
                key_set=True, key_source="ui", source="ui", preset=preset,
            )
        if _key_in_env(entry):
            return ResolvedConfig(
                provider=provider, model=model, api_key=None, base_url=base_url,
                key_set=True, key_source="env",
                source="ui" if is_ui else "env", preset=preset,
            )
        return ResolvedConfig(
            provider=provider, model=model, api_key=None, base_url=base_url,
            key_set=not entry["needs_key"], key_source=None,
            source="ui" if is_ui else ("env" if env_active else "default"),
            preset=preset,
        )


# ---------------------------------------------------------------------------
# Process-wide singleton (mirrors the rest of the API layer's module-level
# state, e.g. ConnectionManager) — honors SPLATAGENT_SETTINGS_PATH for tests.
# ---------------------------------------------------------------------------

_store: SettingsStore | None = None
_store_lock = threading.Lock()


def get_store() -> SettingsStore:
    global _store
    with _store_lock:
        if _store is None:
            path_env = os.environ.get("SPLATAGENT_SETTINGS_PATH")
            _store = SettingsStore(Path(path_env) if path_env else None)
        return _store


def reset_store() -> None:
    """Test helper: forces the next get_store() to build a fresh instance."""
    global _store
    with _store_lock:
        _store = None


__all__ = [
    "PROVIDER_REGISTRY",
    "providers_public",
    "registry_entry",
    "UnknownPresetError",
    "UNSET",
    "ModelSettings",
    "ResolvedConfig",
    "SettingsStore",
    "get_store",
    "reset_store",
]
