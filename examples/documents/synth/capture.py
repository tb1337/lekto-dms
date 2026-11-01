"""The quality stages: how a document reaches Lekto. Born digital (a PDF from a portal, or a
program's printout as PDF), or on paper and then scanned, faxed, photographed, or seen on a
screen. Each stage turns the laid-out pages into the bytes of one file."""

import io
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime

import numpy
from PIL import Image, ImageDraw, ImageFilter

from synth.fonts import MONO, SANS, truetype, width
from synth.layout import Page, Text
from synth.paper import NO_MARKS, Array, Marks, bleed_through, printed, smooth_noise
from synth.pdf import Info, ScannedPage, Word, scanned_pdf, vector_pdf
from synth.raster import render

STAGES = (
    "digital",
    "printout",
    "scan-clean",
    "scan-office",
    "scan-bw",
    "scanner-ocr",
    "fax",
    "scan-poor",
    "photo",
    "photo-poor",
    "screenshot",
)
"""The quality stages, from the best to the worst. `printout` is born digital, laid out as a
program prints (in Courier); the class lays it out, the stage writes it like `digital`."""

PAPER = {
    "scan-clean",
    "scan-office",
    "scan-bw",
    "scanner-ocr",
    "fax",
    "scan-poor",
    "photo",
    "photo-poor",
}


@dataclass(frozen=True)
class Capture:
    """How a document is captured, beyond its stage: when; what was done to its first page;
    `duplex`: scanned on both sides, the blank backs included; `turned`: pages (from 0)
    fed upside down; `tiff`: a bilevel scan saved as TIFF; `fax_from`: the sender's fax line."""

    when: datetime
    marks: Marks = NO_MARKS
    duplex: bool = False
    turned: frozenset[int] = frozenset()
    tiff: bool = False
    exif_turned: bool = False
    fax_from: str = ""
    label: str = ""  # the fax's sender name, the file name in a viewer, a page's address
    screen: bool = False  # a web page: a screenshot of the browser
    creator: str = "Lekto Beispiel"
    producer: str = "Lekto Beispiel"


@dataclass(frozen=True)
class File:
    data: bytes
    extension: str
    media_type: str
    pages: int


def capture(stage: str, pages: Sequence[Page], how: Capture, seed: int) -> File:
    return _STAGES[stage](pages, how, seed)


def _digital(pages: Sequence[Page], how: Capture, seed: int) -> File:
    info = Info(how.when, how.creator, how.producer)
    return File(vector_pdf(pages, info), "pdf", "application/pdf", len(pages))


def _sheets(
    pages: Sequence[Page], how: Capture, seed: int, dpi: float, *, glass: bool = True
) -> list[Array]:
    """The pages printed, the marks on the first, and with `duplex` each followed by its back.
    `glass`: a slip smaller than A4 (a receipt) lies on a scanner's glass, the lid around it."""
    sheets = []
    for number, page in enumerate(pages):
        marks = (
            how.marks
            if number == 0
            else replace(NO_MARKS, holes=how.marks.holes, folds=how.marks.folds)
        )
        small = page.width < 160 and page.height < 260
        thermal = page.width <= 80
        front = printed(
            page,
            dpi,
            seed + number,
            marks if not small else replace(marks, holes=False, folds=False),
            ink=70 if thermal else 28,
            tone=0.99 if thermal else 0.975,
        )
        if small and glass:
            front = _on_glass(front, dpi, seed + number)
        sheets.append(front)
        if how.duplex:
            sheets.append(bleed_through(front, seed + 100 + number))
    return sheets


def _on_glass(slip: Array, dpi: float, seed: int) -> Array:
    """A slip laid on the glass of a flatbed scanner, a little askew, the white lid around it."""
    rng = numpy.random.default_rng(seed)
    scale = dpi / 25.4
    h, w = round(297 * scale), round(210 * scale)
    lid = numpy.full((h, w, 3), 244, dtype=numpy.float32) + rng.normal(0, 1.5, (h, w, 1)).astype(
        numpy.float32
    )
    image = Image.fromarray(slip.astype(numpy.uint8)).rotate(
        float(rng.uniform(-4, 4)),
        expand=True,
        resample=Image.Resampling.BICUBIC,
        fillcolor=(244, 244, 244),
    )
    piece = numpy.asarray(image, dtype=numpy.float32)[: h - 20, : w - 20]
    x, y = int(rng.uniform(8, 25) * scale), int(rng.uniform(8, 20) * scale)
    ph, pw = min(piece.shape[0], h - y), min(piece.shape[1], w - x)
    region = lid[y : y + ph, x : x + pw]
    region[:] = numpy.minimum(region, piece[:ph, :pw])
    return lid


def _scanned(
    sheet: Array,
    seed: int,
    *,
    skew: float,
    blur: float,
    noise: float,
    white: float,
    black: float = 0,
    gray: bool = True,
    shadow: float = 0,
    turned: bool = False,
) -> Image.Image:
    """A sheet through a scanner: tilted, a little soft, with sensor noise, its levels
    stretched so that the paper comes out white (`white`: the value that becomes white)."""
    rng = numpy.random.default_rng(seed)
    image = Image.fromarray(sheet.astype(numpy.uint8))
    if gray:
        image = image.convert("L")
    if skew:
        fill = 250 if gray else (250, 250, 250)
        image = image.rotate(skew, resample=Image.Resampling.BICUBIC, fillcolor=fill)
    if blur:
        image = image.filter(ImageFilter.GaussianBlur(blur))
    array = numpy.asarray(image, dtype=numpy.float32)
    if shadow:
        h, w = array.shape[:2]
        side = numpy.linspace(1, 0, w, dtype=numpy.float32) ** 3
        top = numpy.linspace(1, 0, h, dtype=numpy.float32)[:, None] ** 2
        factor = 1 - shadow * numpy.maximum(side[None, :] * 0.8, top * 0.6)
        array = array * (factor if array.ndim == 2 else factor[..., None])
    array = array + rng.normal(0, noise, array.shape).astype(numpy.float32)
    array = (array - black) * 255 / (white - black)
    image = Image.fromarray(numpy.clip(array, 0, 255).astype(numpy.uint8))
    if turned:
        image = image.rotate(180)
    return image


def _scan_info(how: Capture, producer: str) -> Info:
    return Info(how.when, producer, producer)


def _scan_clean(pages: Sequence[Page], how: Capture, seed: int) -> File:
    rng = random.Random(seed)
    sheets = _sheets(pages, how, seed, 200)
    scans = [
        ScannedPage(
            _scanned(
                sheet,
                seed + n,
                skew=rng.uniform(-0.25, 0.25),
                blur=0.45,
                noise=1.0,
                white=228,
                black=10,
                turned=n in how.turned,
            ),
            200,
            quality=45,
        )
        for n, sheet in enumerate(sheets)
    ]
    return File(
        scanned_pdf(scans, _scan_info(how, "ScanStation 7 (Flachbett)")),
        "pdf",
        "application/pdf",
        len(scans),
    )


def _scan_office(pages: Sequence[Page], how: Capture, seed: int) -> File:
    rng = random.Random(seed)
    sheets = _sheets(pages, how, seed, 150)
    scans = [
        ScannedPage(
            _scanned(
                sheet,
                seed + n,
                skew=rng.uniform(-1.3, 1.3),
                blur=0.6,
                noise=3,
                white=225,
                black=15,
                gray=False,
                turned=n in how.turned,
            ),
            150,
            quality=50,
        )
        for n, sheet in enumerate(sheets)
    ]
    return File(
        scanned_pdf(scans, _scan_info(how, "OfficeJet Pro ADF")),
        "pdf",
        "application/pdf",
        len(scans),
    )


def _bilevel(gray: Image.Image, seed: int, threshold: float, speckle: float) -> Image.Image:
    rng = numpy.random.default_rng(seed)
    array = numpy.asarray(gray, dtype=numpy.float32)
    array = array + rng.normal(0, 14, array.shape)
    dots = rng.random(array.shape) < speckle
    array[dots] = 0
    return Image.fromarray(((array > threshold) * 255).astype(numpy.uint8)).convert("1")


def _scan_bw(pages: Sequence[Page], how: Capture, seed: int) -> File:
    rng = random.Random(seed)
    sheets = _sheets(pages, how, seed, 300)
    images = [
        _bilevel(
            _scanned(
                sheet,
                seed + n,
                skew=rng.uniform(-0.6, 0.6),
                blur=0.7,
                noise=2,
                white=235,
                black=10,
                turned=n in how.turned,
            ),
            seed + n,
            150,
            0.00004,
        )
        for n, sheet in enumerate(sheets)
    ]
    if how.tiff:
        out = io.BytesIO()
        images[0].save(
            out,
            "TIFF",
            save_all=True,
            append_images=images[1:],
            compression="group4",
            dpi=(300, 300),
            tiffinfo={305: "ScanStation 7"},
        )
        return File(out.getvalue(), "tiff", "image/tiff", len(images))
    scans = [ScannedPage(image, 300, encoding="g4") for image in images]
    return File(
        scanned_pdf(scans, _scan_info(how, "ScanStation 7 (ADF, s/w)")),
        "pdf",
        "application/pdf",
        len(scans),
    )


# The confusions of a scanner's own text recognition.
_CONFUSIONS = (
    ("ü", "u"),
    ("ä", "a"),
    ("ö", "o"),
    ("ß", "B"),
    ("€", "C"),
    ("l", "1"),
    ("I", "l"),
    ("O", "0"),
    ("rn", "m"),
    ("e", "c"),
    ("1", "l"),
    (",", "."),
    ("8", "B"),
    ("5", "S"),
)


def _misread(word: str, rng: random.Random) -> str:
    for wrong, right_now in rng.sample(_CONFUSIONS, len(_CONFUSIONS)):
        if wrong in word:
            return word.replace(wrong, right_now, 1)
    return word


def ocr_words(page: Page, rng: random.Random, error_rate: float) -> list[Word]:
    """The words of `page` as a scanner reads them: in place, some misread."""
    words = []
    for item in page.items:
        if not isinstance(item, Text):
            continue
        full = width(item.text, item.font, item.size)
        x0 = item.x - (full if item.align == "right" else full / 2 if item.align == "center" else 0)
        offset = 0
        for word in item.text.split(" "):
            start = item.text.index(word, offset)
            offset = start + len(word)
            if not word:
                continue
            x = x0 + width(item.text[:start], item.font, item.size)
            w = width(word, item.font, item.size)
            text = _misread(word, rng) if rng.random() < error_rate else word
            try:
                text.encode("cp1252")
            except UnicodeEncodeError:
                continue
            words.append(Word(x, item.y, w, item.size, text))
    return words


def _scanner_ocr(pages: Sequence[Page], how: Capture, seed: int) -> File:
    rng = random.Random(seed)
    sheets = _sheets(pages, replace(how, duplex=False), seed, 200)
    scans = []
    for n, (page, sheet) in enumerate(zip(pages, sheets, strict=True)):
        image = _scanned(sheet, seed + n, skew=0, blur=0.5, noise=1.5, white=228, black=12)
        scans.append(ScannedPage(image, 200, quality=40, words=ocr_words(page, rng, 0.12)))
    return File(
        scanned_pdf(scans, _scan_info(how, "ScanStation 7 OCR 2.1")),
        "pdf",
        "application/pdf",
        len(scans),
    )


def _fax(pages: Sequence[Page], how: Capture, seed: int) -> File:
    rng = numpy.random.default_rng(seed)
    images = []
    total = len(pages)
    for n, page in enumerate(pages):
        header = Page(page.width, page.height, list(page.items))
        line = f"{how.when:%d.%m.%Y %H:%M}   {how.fax_from:<18} {how.label[:24]:<24}   S. {n + 1:02d}/{total:02d}"
        header.text(8, 5.5, line, MONO.bolder(), 9)
        sheet = printed(header, 204, seed + n, how.marks if n == 0 else NO_MARKS, ink=10)
        gray = _scanned(
            sheet,
            seed + n,
            skew=float(rng.uniform(-0.8, 0.8)),
            blur=0.8,
            noise=4,
            white=225,
            black=20,
        )
        gray = gray.resize((gray.width, round(gray.height * 98 / 204)), Image.Resampling.BOX)
        array = numpy.asarray(gray, dtype=numpy.float32).copy()
        for _ in range(int(rng.integers(2, 7))):
            y = int(rng.integers(0, array.shape[0]))
            array[y : y + int(rng.integers(1, 3))] *= float(rng.choice([0.2, 1.4]))
        images.append(
            _bilevel(
                Image.fromarray(numpy.clip(array, 0, 255).astype(numpy.uint8)),
                seed + n,
                185,
                0.0002,
            )
        )
    scans = [ScannedPage(image, 204, encoding="g4", dpi_y=98) for image in images]
    return File(
        scanned_pdf(scans, _scan_info(how, "FaxServer 3.4")), "pdf", "application/pdf", len(scans)
    )


def _scan_poor(pages: Sequence[Page], how: Capture, seed: int) -> File:
    rng = random.Random(seed)
    sheets = _sheets(pages, how, seed, 100)
    scans = [
        ScannedPage(
            _scanned(
                sheet,
                seed + n,
                skew=rng.uniform(1.2, 3.2) * rng.choice((-1, 1)),
                blur=0.9,
                noise=11,
                white=215,
                black=40,
                shadow=0.45,
                turned=n in how.turned,
            ),
            100,
            quality=18,
        )
        for n, sheet in enumerate(sheets)
    ]
    return File(
        scanned_pdf(scans, _scan_info(how, "MiniScan 100")), "pdf", "application/pdf", len(scans)
    )


# Photos.


def _surface(rng: numpy.random.Generator, size: tuple[int, int], kind: str) -> Array:
    """What the paper lies on: a wooden table, a grey desk, a dark textile or a stone top."""
    w, h = size
    if kind == "wood":
        xx = numpy.linspace(0, 1, w, dtype=numpy.float32)[None, :]
        warp = smooth_noise(rng, (h, w), 180) * 0.08
        grain = numpy.sin((xx + warp) * 90 + smooth_noise(rng, (h, w), 40) * 0.6) * 0.5 + 0.5
        base = numpy.array([120, 84, 52], dtype=numpy.float32)
        array = base * (0.82 + 0.25 * grain[..., None])
    elif kind == "desk":
        base = numpy.array([150, 152, 150], dtype=numpy.float32)
        array = base * (1 + 0.04 * smooth_noise(rng, (h, w), 60)[..., None])
    elif kind == "textile":
        yy, xx = numpy.mgrid[:h, :w]
        weave = (numpy.sin(xx * 0.9) * numpy.sin(yy * 0.9)).astype(numpy.float32)
        base = numpy.array([45, 55, 75], dtype=numpy.float32)
        array = base * (1 + 0.12 * weave[..., None])
    else:
        base = numpy.array([170, 165, 158], dtype=numpy.float32)
        speckle = rng.normal(0, 18, (h, w)).astype(numpy.float32)
        array = base + speckle[..., None] * numpy.array([1, 0.95, 0.9], dtype=numpy.float32)
    return array + rng.normal(0, 3, array.shape).astype(numpy.float32)


def _homography(
    src: Sequence[tuple[float, float]], dst: Sequence[tuple[float, float]]
) -> list[float]:
    """The coefficients of Pillow's perspective transform: from the output's `dst` corners back
    to the input's `src`."""
    rows, values = [], []
    for (x, y), (u, v) in zip(dst, src, strict=True):
        rows.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        rows.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        values += [u, v]
    return list(
        numpy.linalg.solve(numpy.array(rows, dtype=float), numpy.array(values, dtype=float))
    )


def _photographed(sheet: Array, seed: int, *, poor: bool) -> Image.Image:
    """A sheet photographed with a phone on a table: at an angle, with the light falling from
    one side, a shadow at the edges; `poor`: dark, out of focus, a glare and one corner cut off."""
    rng = numpy.random.default_rng(seed)
    pyrng = random.Random(seed)
    sh, sw = sheet.shape[:2]
    landscape = sw > sh * 1.1
    size = (1600, 1200) if landscape else (1200, 1600)
    w, h = size
    surface = _surface(rng, size, pyrng.choice(("wood", "desk", "textile", "stone")))
    # Where the corners of the sheet land.
    fill = 0.84 if not poor else 0.95
    pw = min(w * fill, h * fill * sw / sh)
    ph = pw * sh / sw
    cx, cy = w / 2 + rng.uniform(-0.04, 0.04) * w, h / 2 + rng.uniform(-0.03, 0.03) * h
    jitter = 0.035 if not poor else 0.07
    corners = [
        (cx - pw / 2, cy - ph / 2),
        (cx + pw / 2, cy - ph / 2),
        (cx + pw / 2, cy + ph / 2),
        (cx - pw / 2, cy + ph / 2),
    ]
    top_squeeze = rng.uniform(0.0, 0.06 if not poor else 0.12) * pw
    corners[0] = (corners[0][0] + top_squeeze, corners[0][1])
    corners[1] = (corners[1][0] - top_squeeze, corners[1][1])
    corners = [
        (x + rng.uniform(-jitter, jitter) * w, y + rng.uniform(-jitter, jitter) * h)
        for x, y in corners
    ]
    if poor:
        corner = pyrng.randrange(4)
        x, y = corners[corner]
        corners[corner] = (
            x + (-1 if x < cx else 1) * 0.08 * w,
            y + (-1 if y < cy else 1) * 0.06 * h,
        )
    coefficients = _homography([(0, 0), (sw, 0), (sw, sh), (0, sh)], corners)
    paper = Image.fromarray(sheet.astype(numpy.uint8)).convert("RGB")
    warped = numpy.asarray(
        paper.transform(size, Image.Transform.PERSPECTIVE, coefficients, Image.Resampling.BICUBIC),
        dtype=numpy.float32,
    )
    mask_image = Image.new("L", (sw, sh), 255).transform(
        size, Image.Transform.PERSPECTIVE, coefficients, Image.Resampling.BICUBIC
    )
    mask = numpy.asarray(mask_image, dtype=numpy.float32)[..., None] / 255
    shadow = (
        numpy.asarray(mask_image.filter(ImageFilter.GaussianBlur(14)), dtype=numpy.float32)[
            ..., None
        ]
        / 255
    )
    shifted = numpy.roll(numpy.roll(shadow, 8, axis=0), 6, axis=1)
    surface = surface * (1 - 0.45 * shifted)
    array = surface * (1 - mask) + warped * mask
    # The light: brighter on one side, a warm or cold cast.
    yy, xx = numpy.mgrid[:h, :w].astype(numpy.float32)
    angle = rng.uniform(0, 2 * numpy.pi)
    ramp = numpy.cos(angle) * (xx / w - 0.5) + numpy.sin(angle) * (yy / h - 0.5)
    light = 1 + (0.18 if not poor else 0.3) * ramp
    vignette = 1 - 0.25 * (((xx / w - 0.5) ** 2 + (yy / h - 0.5) ** 2) * 2)
    cast = numpy.array(
        [1.02, 1.0, 0.93] if pyrng.random() < 0.6 else [0.95, 0.99, 1.04], dtype=numpy.float32
    )
    array = array * (light * vignette)[..., None] * cast
    if poor:
        array *= 0.62
        gx, gy = rng.uniform(0.3, 0.7) * w, rng.uniform(0.25, 0.6) * h
        glare = numpy.exp(-(((xx - gx) / (0.16 * w)) ** 2 + ((yy - gy) / (0.09 * h)) ** 2))
        array = array + 150 * glare[..., None]
    array = array + rng.normal(0, 2.5 if not poor else 9, array.shape).astype(numpy.float32)
    image = Image.fromarray(numpy.clip(array, 0, 255).astype(numpy.uint8))
    image = image.filter(ImageFilter.GaussianBlur(0.7 if not poor else 1.1))
    if poor:
        # Shaken: the picture smeared along one direction.
        steps = 5
        dx, dy = rng.uniform(-1, 1, 2)
        smear = numpy.zeros_like(numpy.asarray(image, dtype=numpy.float32))
        for step in range(steps):
            shift = step - steps // 2
            smear += numpy.roll(
                numpy.roll(numpy.asarray(image, dtype=numpy.float32), int(shift * dy), axis=0),
                int(shift * dx),
                axis=1,
            )
        image = Image.fromarray(numpy.clip(smear / steps, 0, 255).astype(numpy.uint8))
    return image


def _jpeg(image: Image.Image, quality: int, when: datetime, *, turned: bool = False) -> bytes:
    exif = Image.Exif()
    exif[0x0132] = when.strftime("%Y:%m:%d %H:%M:%S")  # DateTime
    if turned:
        exif[0x0112] = 6  # Orientation: turn 90 degrees clockwise to show
    out = io.BytesIO()
    image.save(out, "JPEG", quality=quality, optimize=True, exif=exif)
    return out.getvalue()


def _photo_stage(poor: bool) -> Callable[[Sequence[Page], Capture, int], File]:
    def stage(pages: Sequence[Page], how: Capture, seed: int) -> File:
        dpi = 150
        sheets = _sheets(pages, replace(how, duplex=False), seed, dpi, glass=False)
        photos = [_photographed(sheet, seed + n, poor=poor) for n, sheet in enumerate(sheets)]
        if how.exif_turned:
            # Held sideways: the pixels lie on their side, the camera's tag says how to turn them.
            photos = [photo.rotate(90, expand=True) for photo in photos]
        quality = 75 if not poor else 55
        if len(photos) == 1:
            return File(
                _jpeg(photos[0], quality, how.when, turned=how.exif_turned), "jpg", "image/jpeg", 1
            )
        # Several pages photographed into one PDF, as a phone's scan function keeps them.
        scans = [ScannedPage(photo, 144, quality=quality) for photo in photos]
        return File(
            scanned_pdf(scans, _scan_info(how, "Kamera-Scan")), "pdf", "application/pdf", len(scans)
        )

    return stage


def _screenshot(pages: Sequence[Page], how: Capture, seed: int) -> File:
    """A web page in a browser window, or the first page as a PDF viewer shows it: a title bar,
    a toolbar, the page on grey, cut off at the bottom of the screen."""
    w, h = 1440, 900
    if how.screen:
        page = render(pages[0], 96)
        screen = Image.new("RGB", (w, h + 76), (222, 225, 230))
        draw = ImageDraw.Draw(screen)
        draw.rounded_rectangle((90, 6, 400, 38), radius=8, fill=(255, 255, 255))
        draw.text(
            (110, 28),
            how.label.split("/")[2] if "//" in how.label else "Seite",
            fill=(40, 40, 40),
            font=truetype(SANS, 14),
            anchor="ls",
        )
        for number, color in enumerate(((237, 106, 94), (245, 191, 79), (98, 197, 84))):
            draw.ellipse((14 + number * 22, 14, 28 + number * 22, 28), fill=color)
        draw.rounded_rectangle((120, 44, w - 120, 70), radius=13, fill=(255, 255, 255))
        draw.text((140, 62), how.label, fill=(60, 60, 60), font=truetype(SANS, 14), anchor="ls")
        screen.paste(page.crop((0, 0, w, h)), (0, 76))
    else:
        screen = Image.new("RGB", (w, h), (82, 86, 89))
        draw = ImageDraw.Draw(screen)
        draw.rectangle((0, 0, w, 36), fill=(50, 54, 57))
        draw.text(
            (16, 24),
            how.label or "Dokument.pdf",
            fill=(235, 235, 235),
            font=truetype(SANS, 15),
            anchor="ls",
        )
        draw.text(
            (w / 2, 24),
            f"1 / {len(pages)}",
            fill=(235, 235, 235),
            font=truetype(SANS, 14),
            anchor="ms",
        )
        for number in range(4):
            x = w - 40 - number * 36
            draw.rounded_rectangle((x - 12, 10, x + 12, 28), radius=4, fill=(80, 84, 88))
        draw.text(
            (w / 2 + 80, 24), "125 %", fill=(235, 235, 235), font=truetype(SANS, 14), anchor="ls"
        )
        page = render(pages[0], 112)
        left = (w - page.width) // 2
        shadow = Image.new("RGB", (page.width + 8, h), (60, 63, 66))
        screen.paste(shadow, (left - 4, 52))
        screen.paste(page.crop((0, 0, page.width, h - 56)), (left, 56))
    out = io.BytesIO()
    screen.quantize(colors=96, dither=Image.Dither.NONE).save(out, "PNG", optimize=True)
    return File(out.getvalue(), "png", "image/png", 1)


_STAGES: dict[str, Callable[[Sequence[Page], Capture, int], File]] = {
    "digital": _digital,
    "printout": _digital,
    "scan-clean": _scan_clean,
    "scan-office": _scan_office,
    "scan-bw": _scan_bw,
    "scanner-ocr": _scanner_ocr,
    "fax": _fax,
    "scan-poor": _scan_poor,
    "photo": _photo_stage(poor=False),
    "photo-poor": _photo_stage(poor=True),
    "screenshot": _screenshot,
}
