"""The installer's pictures, drawn from the app's own icon (build.bat runs it):

    python installer/wizard_images.py OUT_DIR

wizard.bmp is the tall panel on the first and last pages, wizard_small.bmp the corner of the
others; each comes at every size Windows' display scaling asks for (100 % to 250 %)."""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from customclassic_chat import icon_image  # noqa: E402

TALL = [(164, 314), (192, 386), (246, 459), (273, 556), (328, 604), (410, 797)]
SMALL = [(55, 55), (64, 68), (83, 80), (92, 97), (110, 106), (138, 140)]
TOP, BOTTOM = (23, 42, 77), (47, 85, 151)  # the bubble's blue, darker at the top


def font(size):
    for name in ("segoeuib.ttf", "arialbd.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def tall(w, h):
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / (h - 1)
        d.line([(0, y), (w, y)], fill=tuple(round(a + (b - a) * t) for a, b in zip(TOP, BOTTOM)))
    n = round(w * 0.7)
    icon = icon_image(n)
    img.paste(icon, ((w - n) // 2, round(h * 0.22)), icon)
    for text, size, y, colour in (("CustomClassic", 0.13, 0.22 + 0.7 * w / h + 0.06, "#ffffff"),
                                  ("Chat", 0.13, 0.22 + 0.7 * w / h + 0.13, "#f28c28")):
        f = font(round(w * size))
        d.text(((w - d.textlength(text, font=f)) / 2, h * y), text, font=f, fill=colour)
    return img


def small(w, h):
    img = Image.new("RGB", (w, h), "white")
    n = min(w, h)
    icon = icon_image(n)
    img.paste(icon, ((w - n) // 2, (h - n) // 2), icon)
    return img


def main(out):
    out.mkdir(parents=True, exist_ok=True)
    for name, draw, sizes in (("wizard", tall, TALL), ("wizard_small", small, SMALL)):
        for i, (w, h) in enumerate(sizes):
            draw(w, h).save(out / (f"{name}.bmp" if i == 0 else f"{name}_{i}.bmp"))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
