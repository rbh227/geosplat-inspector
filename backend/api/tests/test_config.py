"""Model-settings store + /config/* endpoints (in-app model picker).

Every test isolates the store to a tmp file via `SPLATAGENT_SETTINGS_PATH` +
`reset_store()`, so tests never touch the real dev machine's saved config.
"""

from __future__ import annotations

import json
import os
import stat

import pytest
from fastapi.testclient import TestClient

from backend.api.settings import (
    ResolvedConfig,
    SettingsStore,
    UnknownPresetError,
    get_store,
    reset_store,
)
from backend.contracts import ModelResponse
from backend.providers.errors import ProviderConfigError
from backend.server import create_app


@pytest.fixture
def store(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    monkeypatch.setenv("SPLATAGENT_SETTINGS_PATH", str(path))
    reset_store()
    yield get_store()
    reset_store()


@pytest.fixture
def client(store):  # noqa: ARG001 - fixture order matters: env must be set before create_app()
    return TestClient(create_app())


# ---------------------------------------------------------------------------
# GET /config/providers
# ---------------------------------------------------------------------------

def test_providers_endpoint_lists_four_with_no_key_material(client):
    resp = client.get("/config/providers")
    assert resp.status_code == 200
    providers = resp.json()["providers"]
    assert len(providers) == 4
    ids = {p["id"] for p in providers}
    assert ids == {"gemini", "anthropic", "openai", "local"}
    for p in providers:
        assert "api_key" not in p
        # only env VAR NAMES are listed, never a value
        for var_name in p.get("key_env_vars", []):
            assert var_name.isupper() and "_" in var_name  # e.g. "GEMINI_API_KEY"


def test_local_preset_needs_no_key_and_supports_base_url(client):
    providers = client.get("/config/providers").json()["providers"]
    local = next(p for p in providers if p["id"] == "local")
    assert local["needs_key"] is False
    assert local["supports_base_url"] is True
    assert local["default_base_url"] == "http://localhost:11434/v1"


# ---------------------------------------------------------------------------
# GET /config/model
# ---------------------------------------------------------------------------

def test_model_config_defaults_when_env_clean(client, monkeypatch):
    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    reset_store()
    body = client.get("/config/model").json()
    assert body["source"] == "default"
    assert body["key_set"] is False
    assert body["provider"] == "gemini"
    assert "api_key" not in body


def test_model_config_reflects_env_key(client, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaSyFAKE_TEST_KEY_ONLY")
    body = client.get("/config/model").json()
    assert body["key_set"] is True
    assert body["key_source"] == "env"


# ---------------------------------------------------------------------------
# POST /config/model
# ---------------------------------------------------------------------------

def test_save_roundtrip_never_echoes_key_and_persists(client, store):
    secret = "sk-test-super-secret-value-12345"
    resp = client.post("/config/model", json={"preset": "openai", "model": "gpt-4o-mini", "api_key": secret})
    assert resp.status_code == 200
    body = resp.json()
    assert secret not in json.dumps(body)
    assert body["key_set"] is True
    assert body["key_source"] == "ui"
    assert body["source"] == "ui"

    # not in a fresh GET either
    body2 = client.get("/config/model").json()
    assert secret not in json.dumps(body2)
    assert body2["key_set"] is True

    # a brand-new SettingsStore pointed at the same file reloads the value
    reloaded = SettingsStore(store._path)  # noqa: SLF001 - test-only introspection
    cfg = reloaded.resolve()
    assert cfg.api_key == secret

    # file exists and is owner-only
    assert store._path.exists()  # noqa: SLF001
    mode = stat.S_IMODE(os.stat(store._path).st_mode)  # noqa: SLF001
    assert mode == 0o600


def test_key_semantics_omit_keeps_empty_clears(client):
    secret = "sk-original-key-value"
    client.post("/config/model", json={"preset": "openai", "api_key": secret})

    # omitted api_key (None) keeps the existing one
    r1 = client.post("/config/model", json={"preset": "openai", "model": "gpt-4o"})
    assert r1.json()["key_set"] is True

    store = get_store()
    assert store.resolve().api_key == secret

    # "" clears it
    r2 = client.post("/config/model", json={"preset": "openai", "api_key": ""})
    assert r2.json()["key_set"] is False
    assert store.resolve().api_key is None


def test_unknown_preset_is_400(client):
    resp = client.post("/config/model", json={"preset": "not-a-real-provider"})
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# POST /config/test
# ---------------------------------------------------------------------------

class _StubOkProvider:
    def __init__(self, *args, **kwargs):
        pass

    def generate(self, messages, tools, images=None):
        return ModelResponse(text="OK", tool_calls=[], raw=None)


def _make_stub_bad_key(secret: str):
    class _StubBadKey:
        def __init__(self, *args, api_key=None, **kwargs):
            self._key = api_key

        def generate(self, messages, tools, images=None):
            raise RuntimeError(f"401 unauthorized: bad key {self._key}")

    return _StubBadKey


def test_test_connection_ok(client, monkeypatch):
    monkeypatch.setitem(
        __import__("backend.providers.factory", fromlist=["PROVIDERS"]).PROVIDERS,
        "gemini",
        _StubOkProvider,
    )
    resp = client.post("/config/test", json={"preset": "gemini", "api_key": "fake-key"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True


def test_test_connection_error_redacts_key(client, monkeypatch):
    secret = "sk-should-not-leak-1234567890"
    monkeypatch.setitem(
        __import__("backend.providers.factory", fromlist=["PROVIDERS"]).PROVIDERS,
        "openai",
        _make_stub_bad_key(secret),
    )
    resp = client.post("/config/test", json={"preset": "openai", "api_key": secret})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert secret not in body["error"]
    assert "•••" in body["error"]


def test_test_connection_config_error_is_friendly(client, monkeypatch):
    class _StubNoKey:
        def __init__(self, *args, **kwargs):
            raise ProviderConfigError("No Gemini API key.")

    monkeypatch.setitem(
        __import__("backend.providers.factory", fromlist=["PROVIDERS"]).PROVIDERS,
        "gemini",
        _StubNoKey,
    )
    resp = client.post("/config/test", json={"preset": "gemini"})
    body = resp.json()
    assert body["ok"] is False
    assert "No Gemini API key" in body["error"]


# ---------------------------------------------------------------------------
# Resolution precedence (unit-level, no HTTP)
# ---------------------------------------------------------------------------

def test_resolution_precedence_ui_beats_env_beats_default(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key-value")
    s = SettingsStore(tmp_path / "s.json")

    cfg = s.resolve()
    assert isinstance(cfg, ResolvedConfig)
    assert cfg.key_source == "env"

    s.update(preset="gemini", api_key="ui-key-value")
    cfg2 = s.resolve()
    assert cfg2.key_source == "ui"
    assert cfg2.api_key == "ui-key-value"


def test_update_unknown_preset_raises():
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as d:
        s = SettingsStore(Path(d) / "s.json")
        with pytest.raises(UnknownPresetError):
            s.update(preset="nope")
