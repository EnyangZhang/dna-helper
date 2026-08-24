"""Background-resistant fishing prompt recognition with per-prompt cooldowns."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_recognition import CustomRecognition

import progress_state


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_TEMPLATE_FILENAMES = {
    "space": "fishing_prompt.png",
    "e": "fishing_e_prompt.png",
    "escape": "fishing_close_prompt.png",
}
_state_lock = threading.Lock()


@dataclass
class _PromptState:
    locked_until: float = 0.0


_prompt_states: dict[tuple[int, str], _PromptState] = {}


def _load_template(filename: str) -> np.ndarray:
    candidates = (
        _PROJECT_ROOT / "resource" / "base" / "image" / "Fishing" / filename,
        _PROJECT_ROOT
        / "assets"
        / "resource"
        / "base"
        / "image"
        / "Fishing"
        / filename,
    )
    for path in candidates:
        if not path.is_file():
            continue
        template = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if template is not None:
            return template
    raise RuntimeError(f"Fishing prompt template is missing: {filename}")


def _white_icon_mask(image: np.ndarray) -> np.ndarray:
    """Discard changing scenery and retain the bright low-saturation HUD icon."""
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    return cv2.inRange(hsv, (0, 0, 175), (179, 115, 255))


def _text_edge_mask(image: np.ndarray) -> np.ndarray:
    """Retain the stable glyph edges while discarding the translucent background."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return cv2.Canny(gray, 25, 80)


_template_images = {
    name: _load_template(filename) for name, filename in _TEMPLATE_FILENAMES.items()
}
_template_masks = {
    name: (_text_edge_mask(image) if name == "escape" else _white_icon_mask(image))
    for name, image in _template_images.items()
}
for name, mask in _template_masks.items():
    if int(cv2.countNonZero(mask)) < 100:
        raise RuntimeError(f"Fishing {name} template has too few stable pixels")

# Backwards-compatible names used by focused recognition tests.
_template_image = _template_images["space"]
_template_mask = _template_masks["space"]
_template_height, _template_width = _template_mask.shape


def _match_prompt(
    image: np.ndarray, prompt: str = "space"
) -> tuple[float, tuple[int, int]]:
    template_mask = _template_masks.get(prompt)
    if template_mask is None:
        return 0.0, (0, 0)
    template_height, template_width = template_mask.shape
    if (
        image.ndim != 3
        or image.shape[0] < template_height
        or image.shape[1] < template_width
    ):
        return 0.0, (0, 0)
    screen_mask = _text_edge_mask(image) if prompt == "escape" else _white_icon_mask(image)
    result = cv2.matchTemplate(screen_mask, template_mask, cv2.TM_CCOEFF_NORMED)
    _, score, _, location = cv2.minMaxLoc(result)
    return float(score), (int(location[0]), int(location[1]))


def _parse_params(raw: object) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw:
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}
    return {}


def _accept_after_cooldown(
    task_id: int,
    matched: bool,
    cooldown_ms: int,
    prompt: str = "space",
    *,
    now: float | None = None,
) -> bool:
    """Accept a matching prompt at most once per independent cooldown window."""
    with _state_lock:
        key = (task_id, prompt)
        if key not in _prompt_states and len(_prompt_states) >= 384:
            _prompt_states.pop(next(iter(_prompt_states)))
        state = _prompt_states.setdefault(key, _PromptState())
        if not matched:
            return False
        current = time.monotonic() if now is None else now
        if current < state.locked_until:
            return False
        state.locked_until = current + (cooldown_ms / 1000.0)
        return True


@AgentServer.custom_recognition("fishing_prompt")
class FishingPromptRecognition(CustomRecognition):
    """Recognize fishing prompts with independent time-based cooldowns."""

    def analyze(
        self, context: Context, argv: CustomRecognition.AnalyzeArg
    ) -> CustomRecognition.AnalyzeResult:
        params = _parse_params(argv.custom_recognition_param)
        prompt = str(params.get("prompt", "space"))
        if prompt not in _template_masks:
            return CustomRecognition.AnalyzeResult(
                box=None, detail={"error": "unknown fishing prompt"}
            )
        threshold = min(1.0, max(0.0, float(params.get("threshold", 0.72))))
        cooldown_ms = min(60_000, max(0, int(params.get("cooldown_ms", 3000))))
        score, (x, y) = _match_prompt(argv.image, prompt)
        task_id = int(getattr(argv.task_detail, "task_id", 0))
        accepted = _accept_after_cooldown(
            task_id, score >= threshold, cooldown_ms, prompt
        )
        height, width = _template_masks[prompt].shape
        box = [x, y, width, height] if accepted else None
        return CustomRecognition.AnalyzeResult(
            box=box,
            detail={
                "prompt": prompt,
                "score": round(score, 4),
                "accepted": accepted,
            },
        )


@AgentServer.custom_recognition("fishing_target_reached")
class FishingTargetReachedRecognition(CustomRecognition):
    """Finish the task immediately after the configured catch target is reached."""

    def analyze(
        self, context: Context, argv: CustomRecognition.AnalyzeArg
    ) -> CustomRecognition.AnalyzeResult:
        state = progress_state.snapshot()
        reached = state.get("mode") == "挂机钓鱼" and state.get("status") == "completed"
        return CustomRecognition.AnalyzeResult(
            box=[0, 0, 1, 1] if reached else None,
            detail={"target_reached": reached},
        )
