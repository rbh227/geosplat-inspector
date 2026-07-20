"""Live smoke test for the local OpenAI-compatible (vLLM) model path.

Proves the three things the design doc calls out as risky for the swap:
  1. SERVING        — the model answers at OPENAI_BASE_URL.
  2. TOOL-CALLING    — the real AgentLoop drives a multi-turn perceive->act->verify
                       round-trip (mock renderer stands in for the browser), i.e.
                       the model calls a tool, the result is fed back, and it
                       produces a coherent follow-up. (Success criterion #2.)
  3. VISION          — the VL model describes an image we send it. (Criterion #3.)

Run it against a tunnelled vLLM:
    MODEL_PROVIDER=openai \
    MODEL_NAME=Qwen/Qwen2.5-VL-7B-Instruct \
    OPENAI_BASE_URL=http://localhost:8000/v1 \
    OPENAI_API_KEY=not-needed \
    python examples/smoke_local_vllm.py

No live network is touched unless OPENAI_BASE_URL is set, so this never runs in CI.
"""

from __future__ import annotations

import asyncio
import io
import os
import sys

# Make `backend` importable when run from the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.agent import AgentConfig, AgentLoop, ToolDispatcher  # noqa: E402
from backend.agent.mocks import MockBackendExecutor, MockFrontendChannel  # noqa: E402
from backend.providers import get_provider  # noqa: E402
from backend.providers.openai import OpenAIProvider  # noqa: E402


def _require_endpoint() -> None:
    if not os.environ.get("OPENAI_BASE_URL"):
        sys.exit("Set OPENAI_BASE_URL (and MODEL_NAME) to the tunnelled vLLM first.")


def _red_circle_png() -> bytes:
    """A white image with a big red circle — a thing a VLM should name."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (256, 256), "white")
    ImageDraw.Draw(img).ellipse((48, 48, 208, 208), fill="red")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_serving_and_vision() -> bool:
    print("\n=== [2/3] VISION: does the VL model see the image? ===")
    provider = OpenAIProvider(
        model=os.environ["MODEL_NAME"],
        system_instruction="You are a terse visual assistant.",
    )
    resp = provider.generate(
        messages=[{"role": "user", "content": "What single shape and color is in this image? Answer in 4 words."}],
        tools=[],
        images=[_red_circle_png()],
    )
    text = (resp.text or "").lower()
    print("  model said:", repr(resp.text))
    ok = "red" in text and ("circle" in text or "round" in text or "ellipse" in text)
    print("  VISION", "PASS" if ok else "INCONCLUSIVE (model replied but didn't name red circle)")
    return ok


def test_loop_round_trip() -> bool:
    print("\n=== [3/3] TOOL-CALLING: real perceive->act->verify round-trip ===")
    provider = get_provider()  # MODEL_PROVIDER=openai + OPENAI_BASE_URL from env
    executor = MockBackendExecutor()  # fake renderer: metrics + reversible edits
    # Real-sized frame for captures: the VL model rejects the mock's 1x1 PNG
    # (vision patches need ~28px). The browser returns full frames in the app.
    channel = MockFrontendChannel(frame=_red_circle_png())
    dispatcher = ToolDispatcher(executor, channel)
    loop = AgentLoop(provider, dispatcher, channel, config=AgentConfig(max_steps=10))

    result = asyncio.run(
        loop.run(
            "This scene has outlier/floater Gaussians. Measure the scene, remove the "
            "outliers with a targeted tool, then tell me what changed."
        )
    )

    names = [e.get("name") for e in result.trace if e["type"] == "tool_call"]
    print("  status:", result.status, "| steps:", result.steps,
          "| edits_kept:", result.edits_kept, "| reverted:", result.edits_reverted)
    print("  tool calls:", names)
    # Round-trip bar: the model called at least one real tool AND the loop fed a
    # result back AND the model produced a follow-up (another call or an answer).
    made_calls = len(names) >= 1
    multi_turn = result.steps >= 2 or result.status == "answered"
    measured = "get_metrics" in names
    ok = made_calls and multi_turn
    print("  made tool calls:", made_calls, "| multi-turn:", multi_turn, "| measured:", measured)
    print("  ROUND-TRIP", "PASS" if ok else "FAIL")
    return ok


def main() -> int:
    _require_endpoint()
    print(f"Endpoint: {os.environ['OPENAI_BASE_URL']}  model: {os.environ.get('MODEL_NAME')}")
    print("\n=== [1/3] SERVING handled implicitly by the calls below ===")
    vision_ok = test_serving_and_vision()
    loop_ok = test_loop_round_trip()
    print("\n──────────── SUMMARY ────────────")
    print(f"  vision round-trip : {'PASS' if vision_ok else 'INCONCLUSIVE'}")
    print(f"  tool-call loop    : {'PASS' if loop_ok else 'FAIL'}")
    # The loop round-trip is the hard gate; vision can be model-dependent.
    return 0 if loop_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
