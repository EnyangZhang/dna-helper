"""Stateless recognition for Theatre AFK Yiwei stage banners and boss bar."""
from __future__ import annotations

import json
from pathlib import Path
import cv2
import numpy as np
from maa.agent.agent_server import AgentServer
from maa.custom_recognition import CustomRecognition

ROOT = Path(__file__).resolve().parent.parent
_ASSET = ROOT / "assets" / "resource" / "base" / "image" / "TheatreAFK"
_STAGE_ROI = (500, 220, 330, 100)
_BOSS_ROI = (390, 60, 520, 50)
_BOSS_MAX_SQDIFF = 0.05
_templates: dict[int, np.ndarray] = {}
_boss_template: np.ndarray | None = None

def _load(name: str) -> np.ndarray | None:
    for base in (_ASSET, ROOT / "resource" / "base" / "image" / "TheatreAFK"):
        p = base / name
        if p.is_file():
            image = cv2.imread(str(p), cv2.IMREAD_COLOR)
            if image is not None:
                return image
    return None

def _white_text(image: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    top = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, np.ones((5, 5), np.uint8))
    return cv2.threshold(top, 28, 255, cv2.THRESH_BINARY)[1]

for _scene in (2, 3, 4):
    _image = _load(f"scene{_scene}.png")
    if _image is not None:
        _templates[_scene] = _white_text(_image)
_boss_template = _load("scene5.png")

def detect_scene(image: np.ndarray, scene: int) -> tuple[int, int, int, int] | None:
    """Find a requested stage banner (2-4) or the long top boss bar (5)."""
    if not isinstance(image, np.ndarray) or image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:
        return None
    if scene in (2, 3, 4):
        template = _templates.get(scene)
        if template is None or cv2.countNonZero(template) < 12:
            return None
        x0, y0, w, h = _STAGE_ROI
        if image.shape[0] <= y0 or image.shape[1] <= x0:
            return None
        roi = image[y0:min(y0+h, image.shape[0]), x0:min(x0+w, image.shape[1])]
        mask = _white_text(roi)
        if mask.shape[0] < template.shape[0] or mask.shape[1] < template.shape[1]:
            return None
        matches = {
            key: cv2.minMaxLoc(cv2.matchTemplate(mask, candidate, cv2.TM_CCOEFF_NORMED))
            for key, candidate in _templates.items()
            if mask.shape[0] >= candidate.shape[0] and mask.shape[1] >= candidate.shape[1]
        }
        scores = {key: result[1] for key, result in matches.items()}
        score = scores.get(scene, -1.0)
        # Require the requested banner to win decisively; shared Chinese glyphs
        # alone must not classify a different stage.
        loc = matches[scene][3]
        numeral_width = min(28, template.shape[1])
        numeral = template[:, :numeral_width]
        numeral_score = cv2.matchTemplate(
            mask[loc[1]:loc[1] + template.shape[0], loc[0]:loc[0] + template.shape[1]],
            numeral, cv2.TM_CCOEFF_NORMED
        )[0, 0]
        scene_threshold = {2: 0.80, 3: 0.78, 4: 0.90}[scene]
        if score < scene_threshold or numeral_score < 0.60:
            return None
        return (x0 + int(loc[0]), y0 + int(loc[1]), template.shape[1], template.shape[0])
    if scene == 5:
        template = _boss_template
        if template is None:
            return None
        x0, y0, w, h = _BOSS_ROI
        if image.shape[0] <= y0 or image.shape[1] <= x0:
            return None
        roi = image[y0:min(y0+h, image.shape[0]), x0:min(x0+w, image.shape[1])]
        if roi.shape[0] < template.shape[0] or roi.shape[1] < template.shape[1]:
            return None
        # Match the supplied full-health screenshot directly, including its
        # original colors and complete fill. No generic red/edge or damaged-HP fallback.
        differences = cv2.matchTemplate(roi, template, cv2.TM_SQDIFF_NORMED)
        differences = np.nan_to_num(differences, nan=1.0, posinf=1.0, neginf=1.0)
        difference, _, location, _ = cv2.minMaxLoc(differences)
        if difference > _BOSS_MAX_SQDIFF:
            return None
        return (x0 + location[0], y0 + location[1], template.shape[1], template.shape[0])
    return None

def _params(raw: object) -> dict:
    if isinstance(raw, dict): return raw
    if isinstance(raw, str):
        try:
            value = json.loads(raw)
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError: return {}
    return {}

@AgentServer.custom_recognition("theatre_scene")
class TheatreSceneRecognition(CustomRecognition):
    def analyze(self, context, argv):
        scene = _params(argv.custom_recognition_param).get("scene")
        try: scene = int(scene)
        except (TypeError, ValueError): scene = 0
        box = detect_scene(argv.image, scene) if scene in (2, 3, 4, 5) else None
        return CustomRecognition.AnalyzeResult(box=list(box) if box else None,
            detail={"scene": scene, "matched": box is not None})
