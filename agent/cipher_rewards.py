"""Read-only recognition of the endless cipher three-card reward page.

No input, counters, persisted selection or per-task state lives here. The
Pipeline performs all clicks and checks selection again on a fresh frame.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from maa.agent.agent_server import AgentServer
from maa.custom_recognition import CustomRecognition

ROOT = Path(__file__).resolve().parents[1]
SLOT_CENTERS = (456, 640, 823)
TEMPLATE_NAMES = (
    "reward_title.png", "reward_header1.png", "reward_header2.png",
    "reward_header3.png", "reward_red_cube.png", "reward_selected.png",
    "confirm_choice.png",
)


@lru_cache(maxsize=1)
def _templates():
    result = {}
    for name in TEMPLATE_NAMES:
        for root in (ROOT / "assets/resource/base/image", ROOT / "resource/base/image"):
            path = root / "RewardConfirm" / name
            if path.is_file():
                image = cv2.imread(str(path), cv2.IMREAD_COLOR)
                if image is not None:
                    result[name] = image
                    break
    return result


def _score(image, template, roi, *, gray=False):
    x, y, w, h = roi
    crop = image[y:y + h, x:x + w]
    if crop.shape[0] < template.shape[0] or crop.shape[1] < template.shape[1]:
        return -1.0
    if gray:
        crop = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        template = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
    scores = cv2.matchTemplate(crop, template, cv2.TM_CCOEFF_NORMED)
    scores = np.nan_to_num(scores, nan=-1.0, posinf=-1.0, neginf=-1.0)
    return float(cv2.minMaxLoc(scores)[1])


def inspect_reward_page(image):
    """Return page evidence, or None when this is not the complete card page."""
    if (not isinstance(image, np.ndarray) or image.dtype != np.uint8
            or image.shape != (720, 1280, 3)):
        return None
    templates = _templates()
    if any(name not in templates for name in TEMPLATE_NAMES):
        return None
    # Title + confirmation button + all three numbered card headers prevent
    # a red object elsewhere in combat, inventory, or a partial page selecting it.
    if _score(image, templates["reward_title.png"], (590, 155, 105, 35), gray=True) < 0.8:
        return None
    if _score(image, templates["confirm_choice.png"], (500, 520, 300, 130), gray=True) < 0.8:
        return None
    for slot, cx in enumerate(SLOT_CENTERS, 1):
        if _score(image, templates[f"reward_header{slot}.png"], (cx - 22, 270, 44, 42), gray=True) < 0.82:
            return None
    red_scores = [
        _score(image, templates["reward_red_cube.png"], (cx - 38, 352, 76, 78))
        for cx in SLOT_CENTERS
    ]
    red_slots = [i + 1 for i, score in enumerate(red_scores) if score >= 0.85]
    selected_slots = [
        i + 1 for i, cx in enumerate(SLOT_CENTERS)
        if _score(image, templates["reward_selected.png"], (cx - 22, 498, 44, 42), gray=True) >= 0.85
    ]
    return {"red_slots": red_slots, "selected_slots": selected_slots,
            "red_scores": [round(score, 4) for score in red_scores]}


def recognize_reward(image, mode, slot=None):
    page = inspect_reward_page(image)
    if page is None:
        return None, {"page": False}
    red_slots = page["red_slots"]
    selected_slots = page["selected_slots"]
    box = None
    if mode == "page":
        box = (375, 260, 530, 280)
    elif mode == "ready":
        # No target: retain the user's currently/default selected reward.
        # Multiple possible targets are ambiguous and must not be auto-confirmed.
        if len(selected_slots) == 1 and (not red_slots or red_slots == selected_slots):
            box = (610, 602, 20, 10)
    elif mode == "select" and type(slot) is int and slot in (1, 2, 3):
        if red_slots == [slot] and selected_slots != [slot]:
            box = (SLOT_CENTERS[slot - 1] - 5, 514, 10, 10)
    return box, {"page": True, **page}


@AgentServer.custom_recognition("cipher_reward")
class CipherRewardRecognition(CustomRecognition):
    def analyze(self, context, argv):
        params = argv.custom_recognition_param
        if isinstance(params, str):
            try:
                params = json.loads(params)
            except (ValueError, TypeError):
                params = {}
        if not isinstance(params, dict):
            params = {}
        box, detail = recognize_reward(argv.image, params.get("mode"), params.get("slot"))
        return CustomRecognition.AnalyzeResult(box=list(box) if box else None, detail=detail)
