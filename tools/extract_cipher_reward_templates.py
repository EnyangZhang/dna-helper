"""Losslessly crop reward-choice assets from the user-supplied screenshot."""
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "reference-screenshots/cipher-endless-reward-selection-d2fd94bd.png"
MAGNET_SOURCE = ROOT / "reference-screenshots/cipher-endless-magnet-924c00fb.png"
# Crop only the stable item graphic; exclude the card frame and quantity below it.
MAGNET_BOX = (36, 40, 88, 89)
# The game draws its title bar inside the client: keep it, and do not rescale.
WINDOW_BOX = (10, 8, 1290, 728)
CROPS = {
    "reward_title.png": (600, 163, 681, 181),
    "reward_header1.png": (445, 278, 467, 303),
    "reward_header2.png": (629, 278, 651, 303),
    "reward_header3.png": (812, 278, 834, 303),
    "reward_red_cube.png": (613, 369, 666, 426),
    "reward_selected.png": (443, 505, 470, 533),
}


def main():
    with Image.open(SOURCE) as source, Image.open(MAGNET_SOURCE) as magnet:
        if source.size != (1294, 730):
            raise SystemExit("Unexpected reference dimensions; recheck the client offset")
        if magnet.size != (123, 122):
            raise SystemExit("Unexpected magnet reference dimensions; recheck the icon crop")
        window = source.convert("RGB").crop(WINDOW_BOX)
        output = ROOT / "assets/resource/base/image/RewardConfirm"
        for name, box in CROPS.items():
            window.crop(box).save(output / name)
            print(f"Extracted {name}: {box}")
        window.save(ROOT / "tests/fixtures/cipher_reward_choice.png")
        magnet.convert("RGB").crop(MAGNET_BOX).save(output / "reward_magnet.png")
        print(f"Extracted reward_magnet.png: {MAGNET_BOX}")


if __name__ == "__main__":
    main()
