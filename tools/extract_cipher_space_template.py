"""Losslessly tighten the original shared Cipher Space-confirm template."""

from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "reference-screenshots/cipher-space-confirm-template-original.png"
OUTPUT = ROOT / "assets/resource/base/image/RewardConfirm/space_confirm_choice.png"
# Keep the complete keycap and glyphs, excluding right countdown/bottom bar.
# Pillow right and bottom coordinates are exclusive.
TEXT_BOX = (5, 6, 127, 25)


def main() -> None:
    with Image.open(SOURCE) as image:
        if image.size != (134, 33):
            raise SystemExit("Original template changed; recheck the lossless crop coordinates.")
        image.crop(TEXT_BOX).save(OUTPUT)
    print(f"Cropped existing template: {TEXT_BOX} -> {OUTPUT.name} (122x19)")


if __name__ == "__main__":
    main()
