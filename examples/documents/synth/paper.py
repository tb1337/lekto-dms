"""A page on paper: printed with toner on a sheet that is not quite white, and what happens to
it in a household: a stamp, a highlighter, a note by hand, punched holes, folds, a coffee ring,
a staple. Images are numpy arrays of floats (0 to 255), RGB."""

import math
import random
from dataclasses import dataclass

import numpy
from PIL import Image, ImageDraw, ImageFilter

from synth.fonts import HAND, MM_PER_PT, SANS_BOLD, truetype, width
from synth.layout import Page, Text
from synth.raster import render

type Array = numpy.ndarray


@dataclass(frozen=True)
class Marks:
    """What a person did to the first page: `stamp` (its text, e.g. "BEZAHLT"), `highlight`
    (the text marked), `note` (written by hand), `holes`, `folds`, `stain`, `staple`."""

    stamp: str | None = None
    stamp_date: str | None = None
    highlight: str | None = None
    note: str | None = None
    holes: bool = False
    folds: bool = False
    stain: bool = False
    staple: bool = False

    def names(self) -> list[str]:
        """The marks in the manifest."""
        found = []
        for name in ("stamp", "highlight", "note", "holes", "folds", "stain", "staple"):
            if getattr(self, name):
                found.append(name)
        return found


NO_MARKS = Marks()


def smooth_noise(rng: numpy.random.Generator, shape: tuple[int, int], cell: int) -> Array:
    """Noise that varies over about `cell` pixels, between -1 and 1."""
    h, w = shape
    small = rng.uniform(-1, 1, (max(2, h // cell + 2), max(2, w // cell + 2))).astype(numpy.float32)
    image = Image.fromarray(small, mode="F").resize((w, h), Image.Resampling.BICUBIC)
    return numpy.asarray(image, dtype=numpy.float32)


def printed(
    page: Page,
    dpi: float,
    seed: int,
    marks: Marks = NO_MARKS,
    *,
    tone: float = 0.975,
    ink: float = 28,
) -> Array:
    """`page` printed at `dpi`: toner of darkness `ink` (0 is black) on paper of `tone`, with
    `marks`."""
    rng = numpy.random.default_rng(seed)
    pyrng = random.Random(seed)
    image = render(page, dpi)
    if marks.highlight:
        _highlight(image, page, marks.highlight, dpi)
    array = numpy.asarray(image, dtype=numpy.float32)
    # Toner is not quite black, nor even.
    array = ink + array * (255 - ink) / 255
    h, w = array.shape[:2]
    sheet = 255 * tone * (1 + 0.012 * smooth_noise(rng, (h, w), max(8, int(dpi))))
    sheet += rng.normal(0, 1.4, (h, w)).astype(numpy.float32)
    array = array * (sheet / 255)[..., None]
    scale = dpi / 25.4
    if marks.folds:
        for y in (105, 210):
            _fold(array, y * scale, rng)
    if marks.stain:
        _stain(array, rng, scale)
    if marks.stamp:
        _stamp(array, marks.stamp, marks.stamp_date, dpi, pyrng)
    if marks.note:
        _note(array, marks.note, page, dpi, pyrng)
    if marks.holes:
        for y in (148.5 - 40, 148.5 + 40):
            _hole(array, 12 * scale, y * scale, 2.75 * scale)
    if marks.staple:
        _staple(array, scale)
    return numpy.clip(array, 0, 255)


def _highlight(image: Image.Image, page: Page, text: str, dpi: float) -> None:
    """A yellow marker over the first line containing `text`, as multiplied ink."""
    scale = dpi / 25.4
    for item in page.items:
        if isinstance(item, Text) and text in item.text:
            start = item.text.index(text)
            x = item.x + width(item.text[:start], item.font, item.size)
            full = width(item.text, item.font, item.size)
            if item.align == "right":
                x -= full
            elif item.align == "center":
                x -= full / 2
            w = width(text, item.font, item.size)
            size = item.size * MM_PER_PT
            box = (
                (x - 1) * scale,
                (item.y - size * 0.85) * scale,
                (x + w + 1) * scale,
                (item.y + size * 0.3) * scale,
            )
            overlay = Image.new("RGB", image.size, (255, 255, 255))
            ImageDraw.Draw(overlay).rounded_rectangle(box, radius=scale * 0.8, fill=(255, 238, 70))
            overlay = overlay.filter(ImageFilter.GaussianBlur(scale * 0.15))
            multiplied = (
                numpy.asarray(image, dtype=numpy.float32)
                * numpy.asarray(overlay, dtype=numpy.float32)
                / 255
            )
            image.paste(Image.fromarray(multiplied.astype(numpy.uint8)))
            return


def _fold(array: Array, y: float, rng: numpy.random.Generator) -> None:
    """A fold across the sheet: a soft shadow with a bright edge."""
    h, w = array.shape[:2]
    rows = numpy.arange(h, dtype=numpy.float32)[:, None]
    tilt = numpy.linspace(-1, 1, w, dtype=numpy.float32)[None, :] * rng.uniform(-3, 3)
    d = rows - (y + tilt)
    shade = 1 - 0.07 * numpy.exp(-((d - 2) ** 2) / 8) + 0.03 * numpy.exp(-((d + 2) ** 2) / 4)
    array *= shade[..., None]


def _stain(array: Array, rng: numpy.random.Generator, scale: float) -> None:
    """The ring a cup leaves, coffee brown, somewhere on the lower half."""
    h, w = array.shape[:2]
    cx, cy = rng.uniform(0.3, 0.8) * w, rng.uniform(0.45, 0.8) * h
    r = rng.uniform(30, 38) * scale
    yy, xx = numpy.ogrid[:h, :w]
    d = numpy.sqrt((xx - cx) ** 2 + ((yy - cy) * 1.05) ** 2) / r
    wobble = 1 + 0.03 * smooth_noise(rng, (h, w), int(8 * scale))
    d = d * wobble
    ring = numpy.exp(-((d - 1) ** 2) / 0.0012) * 0.35 + (d < 1) * 0.07
    brown = numpy.array([150, 105, 55], dtype=numpy.float32) / 255
    array *= 1 - ring[..., None] * (1 - brown)


def _stamp(array: Array, text: str, day: str | None, dpi: float, rng: random.Random) -> None:
    """A rubber stamp in red, rotated a little, its ink uneven, on the upper right."""
    scale = dpi / 25.4
    size = 16 / 72 * dpi
    font = truetype(SANS_BOLD, size)
    small = truetype(SANS_BOLD, size * 0.55)
    tw = font.getlength(text)
    bw, bh = int(tw + 8 * scale), int(size * (2.1 if day else 1.5))
    stamp = Image.new("L", (bw, bh), 0)
    draw = ImageDraw.Draw(stamp)
    border = max(2, int(0.7 * scale))
    draw.rounded_rectangle((0, 0, bw - 1, bh - 1), radius=int(2 * scale), outline=255, width=border)
    draw.text((bw / 2, size * 1.05), text, fill=255, font=font, anchor="ms")
    if day:
        draw.text((bw / 2, size * 1.75), day, fill=255, font=small, anchor="ms")
    stamp = stamp.rotate(rng.uniform(-12, 12), expand=True, resample=Image.Resampling.BICUBIC)
    mask = numpy.asarray(stamp, dtype=numpy.float32) / 255
    noise = numpy.random.default_rng(rng.randrange(1 << 30))
    mask = mask * (noise.uniform(0.55, 1.0, mask.shape) > 0.25) * noise.uniform(0.7, 1, mask.shape)
    x, y = _emptiest(array, mask.shape[:2], dpi / 25.4, _STAMP_PLACES, rng)
    region = array[y : y + mask.shape[0], x : x + mask.shape[1]]
    mask = mask[: region.shape[0], : region.shape[1], None] * 0.85
    red = numpy.array([200, 35, 45], dtype=numpy.float32)
    region[:] = region * (1 - mask) + red * mask * (region / 255)


def _note(array: Array, text: str, page: Page, dpi: float, rng: random.Random) -> None:
    """Words written by hand in blue, where the page is emptiest: in the margins or the gap
    between head and window."""
    scale = dpi / 25.4
    font = truetype(HAND, 17 / 72 * dpi)
    w = int(font.getlength(text) + 4 * scale)
    h = int(12 * scale)
    note = Image.new("L", (w, h), 0)
    ImageDraw.Draw(note).text((2 * scale, h * 0.75), text, fill=255, font=font, anchor="ls")
    note = note.rotate(rng.uniform(-6, 3), expand=True, resample=Image.Resampling.BICUBIC)
    mask = numpy.asarray(note, dtype=numpy.float32)[..., None] / 255 * 0.9
    x, y = _emptiest(array, mask.shape[:2], scale, _NOTE_PLACES, rng)
    region = array[y : y + mask.shape[0], x : x + mask.shape[1]]
    blue = numpy.array([25, 45, 140], dtype=numpy.float32)
    region[:] = region * (1 - mask) + blue * mask * (region / 255)


# Where a stamp or a note may go (millimetres from the top left): the gap between head and
# window, beside the window, the lower margin, and the body's right side.
_STAMP_PLACES = ((110, 30), (118, 92), (125, 170), (120, 232), (30, 238), (70, 30))
_NOTE_PLACES = ((105, 36), (110, 92), (120, 240), (28, 250), (130, 120), (60, 36))


def _emptiest(
    array: Array,
    shape: tuple[int, int],
    scale: float,
    places: tuple[tuple[float, float], ...],
    rng: random.Random,
) -> tuple[int, int]:
    """Of `places`, the one where a box of `shape` covers the least ink; of equal ones, any."""
    gray = array.mean(axis=2)
    best, found = -1.0, (0, 0)
    for mx, my in rng.sample(places, len(places)):
        x, y = int(mx * scale), int(my * scale)
        window = gray[y : y + shape[0], x : x + shape[1]]
        if window.shape[:2] != shape:
            continue
        light = float(numpy.percentile(window, 2))
        if light > best + 1:
            best, found = light, (x, y)
    return found


def _hole(array: Array, cx: float, cy: float, r: float) -> None:
    """A punched hole: the dark backing of the scanner shows through."""
    h, w = array.shape[:2]
    yy, xx = numpy.ogrid[:h, :w]
    d = numpy.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    inside = numpy.clip(r - d, 0, 1)
    array *= 1 - inside[..., None] * 0.72


def _staple(array: Array, scale: float) -> None:
    """A staple in the top left corner, at an angle, and the two holes of an earlier one."""
    image = Image.fromarray(numpy.clip(array, 0, 255).astype(numpy.uint8))
    draw = ImageDraw.Draw(image)
    x, y = 8 * scale, 10 * scale
    length = 11 * scale
    angle = math.radians(-38)
    end = (x + length * math.cos(angle), y - length * math.sin(angle) * -1)
    draw.line([(x, y), end], fill=(95, 95, 100), width=max(2, int(0.7 * scale)))
    draw.line(
        [(x + 1, y + 1), (end[0] + 1, end[1] + 1)],
        fill=(200, 200, 200),
        width=max(1, int(0.25 * scale)),
    )
    for hx, hy in ((14 * scale, 5 * scale), (21 * scale, 5.4 * scale)):
        draw.ellipse(
            (hx - 0.4 * scale, hy - 0.4 * scale, hx + 0.4 * scale, hy + 0.4 * scale), fill=(80,) * 3
        )
    array[:] = numpy.asarray(image, dtype=numpy.float32)


def bleed_through(front: Array, seed: int, strength: float = 0.05) -> Array:
    """The back of a sheet printed on one side: blank, the front showing through, mirrored."""
    rng = numpy.random.default_rng(seed)
    mirrored = front[:, ::-1]
    blurred = numpy.asarray(
        Image.fromarray(mirrored.astype(numpy.uint8)).filter(ImageFilter.GaussianBlur(3)),
        dtype=numpy.float32,
    )
    h, w = front.shape[:2]
    sheet = 255 * 0.975 * (1 + 0.012 * smooth_noise(rng, (h, w), 150))
    back = sheet[..., None] - (255 - blurred) * strength
    return numpy.clip(back + rng.normal(0, 1.2, (h, w, 1)), 0, 255)
