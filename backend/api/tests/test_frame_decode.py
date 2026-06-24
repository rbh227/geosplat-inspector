"""Regression guard for the vision frame contract (C1).

The frontend (`/frontend/src/agent`) sends captured frames as BARE base64 under
explicit keys: single capture -> {"png_base64": <str>}, orbit ->
{"frames_base64": [<str>, ...]}. `ws.ConnectionManager._decode_frames`
normalizes both into `frames: list[bytes]`, and `dispatch._extract_frames`
pulls those bytes for the model. Before the fix these three sites disagreed
(png / png_base64 / frame) so the real loop received ZERO frames while the mock
hid it. These tests pin the wire shape end to end.
"""

from __future__ import annotations

import base64

from backend.agent.dispatch import _extract_frames
from backend.api.ws import ConnectionManager

RAW_A = b"\x89PNG\r\n\x1a\nfake-frame-A"
RAW_B = b"\x89PNG\r\n\x1a\nfake-frame-B"


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def test_single_capture_decodes_to_bytes():
    reply = {"png_base64": _b64(RAW_A)}
    decoded = ConnectionManager._decode_frames(reply)
    assert decoded["frames"] == [RAW_A]
    assert decoded["png"] == RAW_A
    # and the dispatcher pulls those bytes for the model
    assert _extract_frames(decoded) == [RAW_A]


def test_orbit_capture_decodes_to_bytes_list():
    reply = {"frames_base64": [_b64(RAW_A), _b64(RAW_B)]}
    decoded = ConnectionManager._decode_frames(reply)
    assert decoded["frames"] == [RAW_A, RAW_B]
    assert _extract_frames(decoded) == [RAW_A, RAW_B]


def test_non_capture_ack_is_untouched():
    reply = {"ok": True}
    decoded = ConnectionManager._decode_frames(reply)
    assert decoded == {"ok": True}
    assert _extract_frames(decoded) == []


def test_malformed_base64_is_dropped_not_raised():
    reply = {"png_base64": "!!!not base64!!!", "frames_base64": ["%%%"]}
    decoded = ConnectionManager._decode_frames(reply)
    # nothing decoded -> no frames key added, no exception
    assert "frames" not in decoded
    assert _extract_frames(decoded) == []
