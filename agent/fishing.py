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
from maa.custom_action import CustomAction
from maa.custom_recognition import CustomRecognition

import progress_state


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_TEMPLATE_FILENAMES = {
    "space": "fishing_prompt.png",
    "e": "fishing_e_prompt.png",
    "escape": "fishing_close_prompt.png",
    "empty": "fishing_pool_empty.png",
}
_POOL_EMPTY_ROI = (320, 180, 640, 140)
_POOL_EMPTY_SCALES = (1.0, 0.95, 0.975, 1.025, 1.05)
_POOL_EMPTY_SEGMENT_THRESHOLD = 0.80
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


def _pool_empty_text_mask(image: np.ndarray) -> np.ndarray:
    """Subtract local scenery/notice-bar brightness, retaining bright text strokes.

    Canny also keeps the translucent bar and scenery edges. A small white top-hat
    instead retains the thin glyphs with their antialiasing and local contrast.
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, np.ones((5, 5), np.uint8))


def _prompt_mask(image: np.ndarray, prompt: str) -> np.ndarray:
    if prompt == "empty":
        return _pool_empty_text_mask(image)
    if prompt == "escape":
        return _text_edge_mask(image)
    return _white_icon_mask(image)


_template_images = {
    name: _load_template(filename) for name, filename in _TEMPLATE_FILENAMES.items()
}
_template_masks = {
    name: _prompt_mask(image, name)
    for name, image in _template_images.items()
}
for name, mask in _template_masks.items():
    if int(cv2.countNonZero(mask)) < 100:
        raise RuntimeError(f"Fishing {name} template has too few stable pixels")

# Backwards-compatible names used by focused recognition tests.
_template_image = _template_images["space"]
_template_mask = _template_masks["space"]
_template_height, _template_width = _template_mask.shape


_pool_empty_variants = tuple(
    _pool_empty_text_mask(
        cv2.resize(_template_images["empty"], None, fx=scale, fy=scale)
    )
    for scale in _POOL_EMPTY_SCALES
)


def _match_pool_empty(
    image: np.ndarray,
) -> tuple[float, tuple[int, int, int, int], float]:
    """Match only the central notice band, then verify all three glyph groups.

    The segment check prevents a partial phrase (including a missing 'no fish'
    suffix) from passing just because the other characters match well.
    """
    empty_result = (0.0, (0, 0, 0, 0), 0.0)
    if image.ndim != 3 or image.shape[2] != 3:
        return empty_result
    rx, ry, rw, rh = _POOL_EMPTY_ROI
    region = image[ry : ry + rh, rx : rx + rw]
    if not region.size:
        return empty_result
    screen_mask = _pool_empty_text_mask(region)
    best = empty_result
    best_valid = empty_result
    for template_mask in _pool_empty_variants:
        height, width = template_mask.shape
        if screen_mask.shape[0] < height or screen_mask.shape[1] < width:
            continue
        result = cv2.matchTemplate(screen_mask, template_mask, cv2.TM_CCOEFF_NORMED)
        _, score, _, (x, y) = cv2.minMaxLoc(result)
        candidate = screen_mask[y : y + height, x : x + width]
        segment_score = min(
            float(cv2.matchTemplate(
                candidate[:, index * width // 3 : (index + 1) * width // 3],
                template_mask[:, index * width // 3 : (index + 1) * width // 3],
                cv2.TM_CCOEFF_NORMED,
            )[0, 0])
            for index in range(3)
        )
        match = (float(score), (rx + x, ry + y, width, height), segment_score)
        if score > best[0]:
            best = match
        if segment_score >= _POOL_EMPTY_SEGMENT_THRESHOLD and score > best_valid[0]:
            best_valid = match
    return best_valid if best_valid[0] > 0.0 else best


def _match_prompt(
    image: np.ndarray, prompt: str = "space"
) -> tuple[float, tuple[int, int]]:
    if prompt == "empty":
        score, box, segment_score = _match_pool_empty(image)
        return (
            score if segment_score >= _POOL_EMPTY_SEGMENT_THRESHOLD else 0.0,
            (box[0], box[1]),
        )
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
    screen_mask = _prompt_mask(image, prompt)
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
        default_threshold = 0.85 if prompt == "empty" else 0.72
        threshold = min(1.0, max(0.0, float(params.get("threshold", default_threshold))))
        cooldown_ms = min(60_000, max(0, int(params.get("cooldown_ms", 3000))))
        detail = {}
        if prompt == "empty":
            score, candidate_box, segment_score = _match_pool_empty(argv.image)
            matched = score >= threshold and segment_score >= _POOL_EMPTY_SEGMENT_THRESHOLD
            detail = {"segment_score": round(segment_score, 4), "roi": list(_POOL_EMPTY_ROI)}
        else:
            score, (x, y) = _match_prompt(argv.image, prompt)
            height, width = _template_masks[prompt].shape
            candidate_box = (x, y, width, height)
            matched = score >= threshold
        task_id = int(getattr(argv.task_detail, "task_id", 0))
        accepted = _accept_after_cooldown(
            task_id, matched, cooldown_ms, prompt
        )
        box = list(candidate_box) if accepted else None
        return CustomRecognition.AnalyzeResult(
            box=box,
            detail={
                "prompt": prompt,
                "score": round(score, 4),
                "accepted": accepted,
                **detail,
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


@AgentServer.custom_action("fishing_pool_empty")
class FishingPoolEmptyAction(CustomAction):
    """Record a natural fishing stop when the current pool has no fish."""

    def run(
        self, context: Context, argv: CustomAction.RunArg
    ) -> CustomAction.RunResult:
        success = progress_state.mark_fishing_pool_empty()
        if success:
            print("[挂机钓鱼] 鱼池已空，任务结束", flush=True)
        return CustomAction.RunResult(success=success)
