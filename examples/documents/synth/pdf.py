"""PDFs as programs and scanners write them: a page of text and vector graphics in the standard
fonts (born-digital), or a page holding one image (a scan), optionally with the scanner's own
invisible text over it. Written with pikepdf, without a time of their own: the same input gives
the same bytes."""

import io
import zlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime

import pikepdf
from PIL import Image

from synth.fonts import Font, width
from synth.layout import Ellipse, Line, Page, Picture, Polygon, Rect, Text

PT_PER_MM = 72 / 25.4
_KAPPA = 0.5523


@dataclass(frozen=True)
class Info:
    """The document information of a PDF: what wrote it and when."""

    created: datetime
    creator: str
    producer: str
    title: str | None = None
    author: str | None = None


@dataclass(frozen=True)
class Word:
    """A word of the invisible text over a scan, its box in millimetres (baseline `y`)."""

    x: float
    y: float
    w: float
    size: float
    text: str


@dataclass(frozen=True)
class ScannedPage:
    """A page of a scan: its image, encoded (`jpeg`, `g4` for bilevel or `flate`), at `dpi`
    across and `dpi_y` down; `words`: the scanner's own text, invisible."""

    image: Image.Image
    dpi: float
    encoding: str = "jpeg"
    quality: int = 60
    dpi_y: float | None = None
    words: Sequence[Word] = field(default_factory=tuple)


def _date(moment: datetime) -> str:
    return moment.strftime("D:%Y%m%d%H%M%S+01'00'")


def _new(info: Info) -> pikepdf.Pdf:
    pdf = pikepdf.new()
    with pdf.open_metadata(set_pikepdf_as_editor=False, update_docinfo=False):
        pass
    docinfo = {
        "/CreationDate": _date(info.created),
        "/ModDate": _date(info.created),
        "/Creator": info.creator,
        "/Producer": info.producer,
    }
    if info.title:
        docinfo["/Title"] = info.title
    if info.author:
        docinfo["/Author"] = info.author
    pdf.docinfo = pdf.make_indirect(pikepdf.Dictionary(docinfo))
    if "/Metadata" in pdf.Root:
        del pdf.Root.Metadata
    return pdf


def _saved(pdf: pikepdf.Pdf) -> bytes:
    out = io.BytesIO()
    pdf.save(out, deterministic_id=True, compress_streams=True, linearize=False)
    return out.getvalue()


def _escaped(text: str) -> bytes:
    data = text.encode("cp1252")
    return data.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _rgb(color: tuple[int, int, int]) -> str:
    return " ".join(f"{part / 255:.3f}" for part in color)


def _font_resource(pdf: pikepdf.Pdf, font: Font) -> pikepdf.Object:
    return pdf.make_indirect(
        pikepdf.Dictionary(
            Type=pikepdf.Name.Font,
            Subtype=pikepdf.Name.Type1,
            BaseFont=pikepdf.Name("/" + font.pdf_name),
            Encoding=pikepdf.Name.WinAnsiEncoding,
        )
    )


def _image_stream(pdf: pikepdf.Pdf, image: Image.Image) -> pikepdf.Stream:
    """A picture of a born-digital page, losslessly (Flate)."""
    if image.mode not in ("1", "L", "RGB"):
        image = image.convert("RGB")
    bits, space = {"1": (1, "/DeviceGray"), "L": (8, "/DeviceGray"), "RGB": (8, "/DeviceRGB")}[
        image.mode
    ]
    stream = pikepdf.Stream(pdf, b"")
    stream.write(zlib.compress(image.tobytes(), 9), filter=pikepdf.Name.FlateDecode)
    stream.Type = pikepdf.Name.XObject
    stream.Subtype = pikepdf.Name.Image
    stream.Width, stream.Height = image.size
    stream.BitsPerComponent = bits
    stream.ColorSpace = pikepdf.Name(space)
    return stream


def _path(points: Sequence[tuple[float, float]], height: float) -> str:
    first, *rest = points
    ops = [f"{first[0] * PT_PER_MM:.2f} {(height - first[1]) * PT_PER_MM:.2f} m"]
    ops += [f"{x * PT_PER_MM:.2f} {(height - y) * PT_PER_MM:.2f} l" for x, y in rest]
    return " ".join(ops)


def _paint(fill: object, stroke: object) -> str:
    return "B" if fill and stroke else ("f" if fill else "S")


def _style(fill: tuple[int, int, int] | None, stroke: tuple[int, int, int] | None, w: float) -> str:
    parts = []
    if fill:
        parts.append(f"{_rgb(fill)} rg")
    if stroke:
        parts.append(f"{_rgb(stroke)} RG {w:.2f} w")
    return " ".join(parts)


def vector_pdf(pages: Sequence[Page], info: Info) -> bytes:
    """The pages as a born-digital PDF: text in the standard fonts, shapes as paths."""
    pdf = _new(info)
    fonts: dict[Font, tuple[str, pikepdf.Object]] = {}
    for page in pages:
        h = page.height
        ops: list[bytes] = []
        images: dict[str, pikepdf.Stream] = {}
        used: dict[str, pikepdf.Object] = {}
        for item in page.items:
            match item:
                case Text():
                    if item.font not in fonts:
                        fonts[item.font] = (f"F{len(fonts) + 1}", _font_resource(pdf, item.font))
                    name, resource = fonts[item.font]
                    used[name] = resource
                    x = item.x
                    if item.align != "left":
                        shift = width(item.text, item.font, item.size)
                        x -= shift if item.align == "right" else shift / 2
                    ops.append(
                        f"BT {_rgb(item.color)} rg /{name} {item.size:.2f} Tf "
                        f"1 0 0 1 {x * PT_PER_MM:.2f} {(h - item.y) * PT_PER_MM:.2f} Tm (".encode()
                        + _escaped(item.text)
                        + b") Tj ET"
                    )
                case Line():
                    ops.append(
                        f"{_rgb(item.color)} RG {item.width:.2f} w 1 J 1 j "
                        f"{_path(item.points, h)} S".encode()
                    )
                case Rect():
                    style = _style(item.fill, item.stroke, item.width)
                    box = (
                        f"{item.x * PT_PER_MM:.2f} {(h - item.y - item.h) * PT_PER_MM:.2f} "
                        f"{item.w * PT_PER_MM:.2f} {item.h * PT_PER_MM:.2f} re"
                    )
                    ops.append(f"{style} {box} {_paint(item.fill, item.stroke)}".encode())
                case Ellipse():
                    ops.append(
                        f"{_style(item.fill, item.stroke, item.width)} {_ellipse(item, h)} "
                        f"{_paint(item.fill, item.stroke)}".encode()
                    )
                case Polygon():
                    ops.append(
                        f"{_style(item.fill, item.stroke, item.width)} "
                        f"{_path(item.points, h)} h {_paint(item.fill, item.stroke)}".encode()
                    )
                case Picture():
                    name = f"Im{len(images) + 1}"
                    images[name] = _image_stream(pdf, item.image)
                    ops.append(
                        f"q {item.w * PT_PER_MM:.2f} 0 0 {item.h * PT_PER_MM:.2f} "
                        f"{item.x * PT_PER_MM:.2f} {(h - item.y - item.h) * PT_PER_MM:.2f} cm "
                        f"/{name} Do Q".encode()
                    )
        resources = pikepdf.Dictionary(
            Font=pikepdf.Dictionary({f"/{k}": v for k, v in used.items()})
        )
        if images:
            resources.XObject = pikepdf.Dictionary({f"/{k}": v for k, v in images.items()})
        _add_page(pdf, page.width, page.height, b"\n".join(ops), resources)
    return _saved(pdf)


def _ellipse(item: Ellipse, h: float) -> str:
    rx, ry = item.w / 2 * PT_PER_MM, item.h / 2 * PT_PER_MM
    cx, cy = (item.x + item.w / 2) * PT_PER_MM, (h - item.y - item.h / 2) * PT_PER_MM
    kx, ky = rx * _KAPPA, ry * _KAPPA
    return (
        f"{cx + rx:.2f} {cy:.2f} m "
        f"{cx + rx:.2f} {cy + ky:.2f} {cx + kx:.2f} {cy + ry:.2f} {cx:.2f} {cy + ry:.2f} c "
        f"{cx - kx:.2f} {cy + ry:.2f} {cx - rx:.2f} {cy + ky:.2f} {cx - rx:.2f} {cy:.2f} c "
        f"{cx - rx:.2f} {cy - ky:.2f} {cx - kx:.2f} {cy - ry:.2f} {cx:.2f} {cy - ry:.2f} c "
        f"{cx + kx:.2f} {cy - ry:.2f} {cx + rx:.2f} {cy - ky:.2f} {cx + rx:.2f} {cy:.2f} c h"
    )


def _add_page(
    pdf: pikepdf.Pdf, w: float, h: float, content: bytes, resources: pikepdf.Dictionary
) -> None:
    page = pikepdf.Dictionary(
        Type=pikepdf.Name.Page,
        MediaBox=[0, 0, round(w * PT_PER_MM, 2), round(h * PT_PER_MM, 2)],
        Resources=resources,
        Contents=pikepdf.Stream(pdf, content),
    )
    pdf.pages.append(pikepdf.Page(page))


def _g4(image: Image.Image) -> bytes:
    """The CCITT Group 4 data of a bilevel image: the one strip of its TIFF."""
    out = io.BytesIO()
    image.save(out, "TIFF", compression="group4", strip_size=(image.width + 7) // 8 * image.height)
    tiff = Image.open(io.BytesIO(out.getvalue()))
    offset, count = tiff.tag_v2[273], tiff.tag_v2[279]
    offset = offset[0] if isinstance(offset, tuple) else offset
    count = count[0] if isinstance(count, tuple) else count
    return out.getvalue()[offset : offset + count]


def _scan_stream(pdf: pikepdf.Pdf, page: ScannedPage) -> pikepdf.Stream:
    image = page.image
    stream = pikepdf.Stream(pdf, b"")
    if page.encoding == "g4":
        image = image.convert("1")
        stream.write(
            _g4(image),
            filter=pikepdf.Name.CCITTFaxDecode,
            decode_parms=pikepdf.Dictionary(
                K=-1, Columns=image.width, Rows=image.height, BlackIs1=True
            ),
        )
        bits, space = 1, "/DeviceGray"
    elif page.encoding == "jpeg":
        if image.mode not in ("L", "RGB"):
            image = image.convert("RGB")
        out = io.BytesIO()
        image.save(out, "JPEG", quality=page.quality, optimize=True)
        stream.write(out.getvalue(), filter=pikepdf.Name.DCTDecode)
        bits, space = 8, "/DeviceGray" if image.mode == "L" else "/DeviceRGB"
    else:
        return _image_stream(pdf, image)
    stream.Type = pikepdf.Name.XObject
    stream.Subtype = pikepdf.Name.Image
    stream.Width, stream.Height = image.size
    stream.BitsPerComponent = bits
    stream.ColorSpace = pikepdf.Name(space)
    return stream


def scanned_pdf(pages: Sequence[ScannedPage], info: Info) -> bytes:
    """The pages of a scan, one image each, sized by their resolution; a page's `words` as
    invisible text (render mode 3) over it, as a scanner's own text recognition writes it."""
    pdf = _new(info)
    font = None
    for page in pages:
        dpi_y = page.dpi_y or page.dpi
        w = page.image.width / page.dpi * 25.4
        h = page.image.height / dpi_y * 25.4
        ops = [
            f"q {w * PT_PER_MM:.2f} 0 0 {h * PT_PER_MM:.2f} 0 0 cm /Im1 Do Q".encode(),
        ]
        resources = pikepdf.Dictionary(
            XObject=pikepdf.Dictionary(Im1=_scan_stream(pdf, page)),
        )
        if page.words:
            if font is None:
                font = _font_resource(pdf, Font("sans"))
            resources.Font = pikepdf.Dictionary(F1=font)
            for word in page.words:
                natural = width(word.text, Font("sans"), word.size)
                scale = 100 * word.w / natural if natural else 100
                ops.append(
                    f"BT 3 Tr /F1 {word.size:.2f} Tf {scale:.1f} Tz "
                    f"1 0 0 1 {word.x * PT_PER_MM:.2f} {(h - word.y) * PT_PER_MM:.2f} Tm (".encode()
                    + _escaped(word.text)
                    + b") Tj ET"
                )
        _add_page(pdf, w, h, b"\n".join(ops), resources)
    return _saved(pdf)
