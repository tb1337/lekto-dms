"""Generates the sample files in this directory: `uv run python tests/samples/make_samples.py`.

- scan.pdf        a scanned page: one image, no text layer
- text.pdf        a page with a text layer (born-digital)
- photo.jpg       a photo of a page, without DPI information
- lowres.jpg      a photo stating 72 dpi (OCRmyPDF refuses 96 dpi or less on its own)
- screenshot.png  text on a transparent background (RGBA)
- pages.tiff      two scanned pages in one TIFF
- blank.pdf       a scanned empty page: OCR finds no text
- signed.pdf      text.pdf with a signature flag (OCRmyPDF refuses it unless told to
                  invalidate the signature)
- printout.pdf    a time sheet printed in Courier, its table drawn with `|` and `-`, below a
                  title in Helvetica
- unmapped.pdf    scan.pdf's page with visible text over it in a Type3 font without a character
                  map (`/ToUnicode`), as some PDF printers write it: its codes come out as
                  control characters, and OCRmyPDF's `--skip-text` takes the page as read
- damaged.pdf     a PDF header followed by garbage
- unsupported.docx  an Office file (a ZIP archive), not supported
"""

import io
import random
import zipfile
import zlib
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).parent

LINES = ["Rechnung Nummer 4711", "Papiq Testdokument", "Betrag 123,45 EUR"]

PRINTOUT_TITLE = "Zeitnachweis"
PRINTOUT = [
    " Mitarbeiter        : Erika Musterfrau          Seite         : 1",
    " Personalnummer     : 00012345                  Druckdatum    : 15.07.2026",
    " Kostenstelle       : 4711",
    "",
    "-----------------------------------------------------------------",
    "|Tag Text           |Kommen Gehen Std.|TAZPL |Sollz.|Rahmz.|GLZ  |",
    "-----------------------------------------------------------------",
    "|01  Mo             |07:31 12:34 5.03 |      |      |      |     |",
    "|                   |13:18 15:53 2.35 |760   |  7.36| 7.38 | 0.02|",
    "|02  Di             |07:47 16:04 7.47 |760   |  7.36| 7.47 | 0.11|",
    "|Wochen-Summation   |                 |      | 14.72|14.85 | 0.13|",
    "-----------------------------------------------------------------",
]


def page(lines: list[str], size: tuple[int, int] = (1240, 1754)) -> Image.Image:
    """An A4 page at 150 dpi with large black text."""
    image = Image.new("L", size, 255)
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=56)
    for number, line in enumerate(lines):
        draw.text((120, 200 + number * 110), line, fill=0, font=font)
    return image


def text_pdf(lines: list[str], *, signed: bool = False) -> bytes:
    """A minimal PDF with Helvetica text, written by hand. `signed`: the catalog declares a
    signature (`/AcroForm /SigFlags 1`), which is what OCRmyPDF checks."""
    return pdf(text_lines("F1", 24, 36, 72, 760, lines), signed=signed)


def printout_pdf(title: str, lines: list[str]) -> bytes:
    """A page printed by a program: `title` in Helvetica, below it `lines` in Courier (an empty
    line stays empty)."""
    heading = text_lines("F1", 14, 0, 60, 790, [title])
    content = f"{heading} {text_lines('F2', 9.5, 13.5, 60, 750, lines)}"
    return pdf(content, fonts=("Helvetica", "Courier"))


def text_lines(font: str, size: float, leading: float, x: float, y: float, lines: list[str]) -> str:
    """Text lines in a content stream, from (x, y) down."""
    escaped = (line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") for line in lines)
    shown = " ".join(f"({line}) Tj 0 -{leading} Td" for line in escaped)
    return f"BT /{font} {size} Tf {x} {y} Td {shown} ET"


def unmapped_pdf(lines: list[str]) -> bytes:
    """The page of `lines` as an image, and over it text in a Type3 font whose 30 glyphs draw
    nothing, named only by codes 1 to 30, without a character map."""
    image = page(lines)
    data = zlib.compress(image.tobytes()).decode("latin-1")
    width, height = image.size
    codes = "".join(f"{code:02x}" for code in range(1, 31)) * 3
    content = f"q 595 0 0 842 0 0 cm /Im1 Do Q BT /F1 10 Tf 60 80 Td <{codes}> Tj ET"
    glyph = "500 0 d0"
    names = " ".join(f"/g{code}" for code in range(1, 31))
    procs = " ".join(f"/g{code} 6 0 R" for code in range(1, 31))
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        "/Resources << /Font << /F1 4 0 R >> /XObject << /Im1 7 0 R >> >> /Contents 5 0 R >>",
        "<< /Type /Font /Subtype /Type3 /FontBBox [0 0 500 700] "
        f"/FontMatrix [0.001 0 0 0.001 0 0] /CharProcs << {procs} >> "
        f"/Encoding << /Type /Encoding /Differences [1 {names}] >> "
        f"/FirstChar 1 /LastChar 30 /Widths [{' '.join(['500'] * 30)}] /Resources << >> >>",
        f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
        f"<< /Length {len(glyph)} >>\nstream\n{glyph}\nendstream",
        f"<< /Type /XObject /Subtype /Image /Width {width} /Height {height} "
        "/ColorSpace /DeviceGray /BitsPerComponent 8 /Filter /FlateDecode "
        f"/Length {len(data)} >>\nstream\n{data}\nendstream",
    ]
    return serialized(objects)


def pdf(content: str, *, fonts: tuple[str, ...] = ("Helvetica",), signed: bool = False) -> bytes:
    """A one-page A4 PDF with the content stream `content`, written by hand; `fonts` (standard
    ones) are `F1`, `F2` and so on."""
    acroform = " /AcroForm << /Fields [] /SigFlags 1 >>" if signed else ""
    numbers = [4, *range(6, 5 + len(fonts))]  # the content stream is object 5
    names = " ".join(f"/F{index} {number} 0 R" for index, number in enumerate(numbers, start=1))
    font_objects = [f"<< /Type /Font /Subtype /Type1 /BaseFont /{font} >>" for font in fonts]
    objects = [
        f"<< /Type /Catalog /Pages 2 0 R{acroform} >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        f"/Resources << /Font << {names} >> >> /Contents 5 0 R >>",
        font_objects[0],
        f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
        *font_objects[1:],
    ]
    return serialized(objects)


def serialized(objects: list[str]) -> bytes:
    """A PDF of `objects`, numbered from 1 (the catalog), with its cross-reference table."""
    out = io.BytesIO()
    out.write(b"%PDF-1.7\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{number} 0 obj\n{body}\nendobj\n".encode("latin-1"))
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode())
    out.write(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return out.getvalue()


def main() -> None:
    page(LINES).save(HERE / "scan.pdf", resolution=150)
    (HERE / "text.pdf").write_bytes(text_pdf(LINES))
    (HERE / "signed.pdf").write_bytes(text_pdf(LINES, signed=True))
    (HERE / "printout.pdf").write_bytes(printout_pdf(PRINTOUT_TITLE, PRINTOUT))
    (HERE / "unmapped.pdf").write_bytes(unmapped_pdf(LINES))
    page(LINES, (1000, 1300)).convert("RGB").save(HERE / "photo.jpg", quality=80)
    page(LINES, (900, 1200)).convert("RGB").save(HERE / "lowres.jpg", quality=80, dpi=(72, 72))
    transparent = Image.new("RGBA", (1000, 600), (255, 255, 255, 0))
    ImageDraw.Draw(transparent).multiline_text(
        (60, 100),
        "\n".join(LINES),
        fill=(0, 0, 0, 255),
        font=ImageFont.load_default(size=56),
        spacing=40,
    )
    transparent.save(HERE / "screenshot.png", dpi=(150, 150))
    first = page(LINES).convert("1")
    second = page(["Seite zwei", "Papiq Testdokument"]).convert("1")
    first.save(
        HERE / "pages.tiff",
        save_all=True,
        append_images=[second],
        dpi=(150, 150),
        compression="group4",
    )
    page([]).save(HERE / "blank.pdf", resolution=150)
    (HERE / "damaged.pdf").write_bytes(b"%PDF-1.7\n" + random.Random(4711).randbytes(2000))
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as docx:
        docx.writestr("[Content_Types].xml", "<Types/>")
        docx.writestr("word/document.xml", "<document/>")
    (HERE / "unsupported.docx").write_bytes(archive.getvalue())


if __name__ == "__main__":
    main()
