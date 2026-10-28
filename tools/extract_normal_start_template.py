"""Losslessly crop the existing ordinary start template, not a new screenshot."""

from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "reference-screenshots/normal-start-challenge-template-original.png"
OUTPUT = ROOT / "assets/resource/base/image/NormalEndlessBoost/start_challenge.png"
# Pillow box: left, top, right-exclusive, bottom-exclusive. Keep the full
# Space keycap and Chinese glyphs; omit countdown text and the lower bar.
TEXT_BOX = (4, 7, 125, 26)


def main() -> None:
    with Image.open(SOURCE) as image:
        if image.size != (135, 33):
            raise SystemExit("Original template changed; recheck the lossless crop coordinates.")
        image.crop(TEXT_BOX).save(OUTPUT)
    print(f"Cropped existing template: {TEXT_BOX} -> {OUTPUT.name} (121x19)")


if __name__ == "__main__":
    main()
