"""A page drawn as an image, as a printer puts it on paper: at `dpi`, black on white."""

from PIL import Image, ImageDraw

from synth.fonts import MM_PER_PT, truetype
from synth.layout import WHITE, Ellipse, Line, Page, Picture, Polygon, Rect, Text

_ANCHORS = {"left": "ls", "right": "rs", "center": "ms"}


def render(page: Page, dpi: float, dpi_y: float | None = None) -> Image.Image:
    """`page` as an RGB image at `dpi` (across) and `dpi_y` (down, default the same)."""
    dpi_y = dpi_y or dpi
    if dpi_y != dpi:
        # Non-square pixels (a fax): drawn square, then squeezed.
        image = render(page, dpi)
        return image.resize(
            (image.width, round(page.height / 25.4 * dpi_y)), Image.Resampling.LANCZOS
        )
    scale = dpi / 25.4
    image = Image.new("RGB", (round(page.width * scale), round(page.height * scale)), WHITE)
    draw = ImageDraw.Draw(image)

    def px(x: float, y: float) -> tuple[float, float]:
        return (x * scale, y * scale)

    def stroke(width: float) -> int:
        return max(1, round(width * MM_PER_PT * scale))

    for item in page.items:
        match item:
            case Text():
                font = truetype(item.font, item.size / 72 * dpi)
                draw.text(
                    px(item.x, item.y),
                    item.text,
                    fill=item.color,
                    font=font,
                    anchor=_ANCHORS[item.align],
                )
            case Line():
                draw.line(
                    [px(x, y) for x, y in item.points],
                    fill=item.color,
                    width=stroke(item.width),
                    joint="curve",
                )
            case Rect():
                box = [px(item.x, item.y), px(item.x + item.w, item.y + item.h)]
                draw.rectangle(
                    box,
                    fill=item.fill,
                    outline=item.stroke,
                    width=stroke(item.width) if item.stroke else 0,
                )
            case Ellipse():
                box = [px(item.x, item.y), px(item.x + item.w, item.y + item.h)]
                draw.ellipse(
                    box,
                    fill=item.fill,
                    outline=item.stroke,
                    width=stroke(item.width) if item.stroke else 0,
                )
            case Polygon():
                points = [px(x, y) for x, y in item.points]
                draw.polygon(
                    points,
                    fill=item.fill,
                    outline=item.stroke,
                    width=stroke(item.width) if item.stroke else 0,
                )
            case Picture():
                size = (max(1, round(item.w * scale)), max(1, round(item.h * scale)))
                picture = item.image.convert("RGB").resize(size, Image.Resampling.NEAREST)
                image.paste(picture, (round(item.x * scale), round(item.y * scale)))
    return image
