"""Extract lossless Theatre button assets from the supplied 1327x756 screenshot.

The Unreal-drawn title bar belongs to the 1280x720 client in this capture.
Do not remove its 30 pixels a second time or rescale the screenshot.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
WINDOW_BOX = (29, 16, 1309, 736)
TEXT_BOX = (1150, 662, 1196, 687)
PANEL_BOX = (800, 600, 1280, 720)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("screenshot", type=Path)
    args = parser.parse_args()
    with Image.open(args.screenshot) as source:
        if source.size != (1327, 756):
            raise SystemExit("Expected the supplied 1327x756 screenshot; recheck crop coordinates.")
        window = source.convert("RGB").crop(WINDOW_BOX)
        outputs = (
            ("assets/resource/base/image/TheatreAFK/go.png", TEXT_BOX),
            ("tests/fixtures/theatre_go_panel.png", PANEL_BOX),
        )
        for relative, box in outputs:
            output = ROOT / relative
            output.parent.mkdir(parents=True, exist_ok=True)
            window.crop(box).save(output)
            print(f"Extracted {relative}: {box}")


if __name__ == "__main__":
    main()
