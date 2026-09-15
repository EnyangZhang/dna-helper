"""Extract Theatre scene transition templates and client-region fixtures 1:1."""
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
TEMP = Path(r"C:\Users\GGPC\AppData\Local\Temp")
OUT = ROOT / "assets" / "resource" / "base" / "image" / "TheatreAFK"
FIXTURES = ROOT / "tests" / "fixtures"

SOURCES = {
    2: ("codex-clipboard-c088926b-86fa-4d00-b666-9e09a8917186.png", (4, 0), (601, 259)),
    3: ("codex-clipboard-7d1ab309-eb9a-45fa-8ae8-0fcc4a32b90d.png", (3, 6), (600, 265)),
    4: ("codex-clipboard-ed29ed50-0333-4926-91e6-9ab29bbfcac6.png", (21, 17), (620, 278)),
}
SCENE5_SOURCE = "codex-clipboard-89a38ab5-2958-42f5-8787-1be2dfed80c5.png"
TEMPLATE_SIZE = (86, 18)
FIXTURE_SIZE = (330, 100)


def crop_absolute(image: Image.Image, origin: tuple[int, int], xy: tuple[int, int], size: tuple[int, int]) -> Image.Image:
    x, y = origin[0] + xy[0], origin[1] + xy[1]
    return image.crop((x, y, x + size[0], y + size[1]))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    FIXTURES.mkdir(parents=True, exist_ok=True)
    for scene, (filename, origin, text_xy) in SOURCES.items():
        source = TEMP / filename
        with Image.open(source) as image:
            assert image.size[0] > origin[0] + 830 and image.size[1] > origin[1] + 320
            template = image.crop((text_xy[0], text_xy[1], text_xy[0] + TEMPLATE_SIZE[0], text_xy[1] + TEMPLATE_SIZE[1]))
            fixture = crop_absolute(image, origin, (500, 220), FIXTURE_SIZE)
            template.save(OUT / f"scene{scene}.png")
            fixture.save(FIXTURES / f"theatre_scene{scene}.png")
            print(f"scene{scene}: source={image.size} origin={origin} template={template.size} fixture={fixture.size}")
    with Image.open(TEMP / SCENE5_SOURCE) as image:
        fixture = image.crop((307, 35, 1007, 125))
        boss = image.crop((410, 72, 885, 88))
        fixture.save(FIXTURES / "theatre_scene5.png")
        boss.save(OUT / "scene5.png")
        print(f"scene5: source={image.size} fixture={fixture.size} boss={boss.size}")


if __name__ == "__main__":
    main()
