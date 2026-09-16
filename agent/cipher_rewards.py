"""Read-only recognition of the endless cipher three-card reward page.

No input, counters or persisted selection lives here. Diagnostic log deduplication
never gates recognition. The Pipeline confirms directly after selection clicks.
"""
from __future__ import annotations

import json
import time
from functools import lru_cache
from pathlib import Path
from threading import Lock

import cv2
import numpy as np
from maa.agent.agent_server import AgentServer
from maa.custom_recognition import CustomRecognition

ROOT = Path(__file__).resolve().parents[1]
SLOT_CENTERS = (456, 640, 823)
TEMPLATE_NAMES = (
    "reward_red_cube.png", "confirm_choice.png",
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


def inspect_reward_page(image, *, diagnostics=None):
    """Inspect fixed slots without depending on rarity-sensitive card decorations."""
    if diagnostics is None:
        diagnostics = {}
    if (not isinstance(image, np.ndarray) or image.dtype != np.uint8
            or image.shape != (720, 1280, 3)):
        diagnostics.update(reason="invalid_frame", shape=str(getattr(image, "shape", None)),
                           dtype=str(getattr(image, "dtype", None)))
        return None
    templates = _templates()
    missing = [name for name in TEMPLATE_NAMES if name not in templates]
    if missing:
        diagnostics.update(reason="missing_templates", missing_templates=missing)
        return None
    # Only the original first-page confirm button gates the reward page.
    confirm_score = _score(image, templates["confirm_choice.png"], (500, 520, 300, 130))
    diagnostics["confirm_score"] = round(confirm_score, 4)
    if confirm_score < 0.8:
        diagnostics["reason"] = "confirm_not_matched"
        return None
    red_scores = [
        _score(image, templates["reward_red_cube.png"], (cx - 38, 352, 76, 78))
        for cx in SLOT_CENTERS
    ]
    red_slots = [i + 1 for i, score in enumerate(red_scores) if score >= 0.85]
    return {"confirm_score": round(confirm_score, 4),
            "target_slot": red_slots[0] if red_slots else None,
            "red_slots": red_slots,
            "red_scores": [round(score, 4) for score in red_scores]}


def recognize_reward(image, mode, slot=None):
    diagnostics = {}
    page = inspect_reward_page(image, diagnostics=diagnostics)
    if page is None:
        return None, {"page": False, **diagnostics}
    target_slot = page["target_slot"]
    box = None
    if mode == "page":
        box = (375, 260, 530, 280)
    elif mode == "ready":
        # Slots 2/3 must pass through the native selection chain first.
        if target_slot in (None, 1):
            box = (610, 602, 20, 10)
    elif mode == "select" and type(slot) is int and slot in (2, 3):
        if target_slot == slot:
            box = (SLOT_CENTERS[slot - 1] - 5, 514, 10, 10)
    return box, {"page": True, **page}


class RewardRecognitionLog:
    """UI diagnostics only: one task, semantic deduplication, no decision cache."""

    def __init__(self):
        self._lock = Lock()
        self._task_id = None
        self._signature = None
        self._last_time = 0.0

    def emit(self, task_id, mode, box, detail):
        # Page success precedes the loading wait; do not print its stale red result.
        # Select candidates repeat ready's inspection, so only log the fresh decision.
        if mode not in ("page", "ready") or (mode == "page" and detail["page"]):
            return
        if not detail["page"]:
            reason = detail["reason"]
            if reason == "invalid_frame":
                message = f"画面尺寸/类型无效：{detail['shape']} / {detail['dtype']}，要求 720×1280×3 / uint8"
            elif reason == "missing_templates":
                message = "模板缺失：" + ", ".join(detail["missing_templates"])
            else:
                message = f"确认按钮未命中：{detail['confirm_score']:.3f} < 0.80；当前不选卡、不确认"
            signature = (False, reason)
        else:
            red = detail["red_slots"]
            target = detail["target_slot"]
            if target is None:
                decision = "未发现红色目标，允许确认默认奖励"
            elif target == 1:
                decision = "最左红色在第 1 张，直接确认"
            else:
                decision = f"点击第 {target} 张后直接确认，不检查勾选"
            signature = (True, tuple(red), target, decision)
            scores = lambda key: "/".join(f"{value:.3f}" for value in detail[key])
            slots = lambda values: "/".join(map(str, values)) or "无"
            message = (
                f"红色={slots(red)}，分数={scores('red_scores')}（阈值0.85）；"
                f"确认按钮={detail['confirm_score']:.3f}/0.80；判断={decision}"
            )
        now = time.monotonic()
        with self._lock:
            changed = task_id != self._task_id or signature != self._signature
            if not changed and (not detail["page"] or now - self._last_time < 10.0):
                return
            self._task_id, self._signature, self._last_time = task_id, signature, now
            try:
                print(f"[密函选卡] {message}", flush=True)
            except OSError:
                # A closed UI log pipe must not change recognition or stop the task.
                pass


_recognition_log = RewardRecognitionLog()


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
        task_id = getattr(getattr(argv, "task_detail", None), "task_id", 0)
        _recognition_log.emit(task_id, params.get("mode"), box, detail)
        return CustomRecognition.AnalyzeResult(box=list(box) if box else None, detail=detail)
