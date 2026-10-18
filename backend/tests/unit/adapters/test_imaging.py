"""An image on white: what PDFium's page images and OCRmyPDF's input share."""

import pytest
from PIL import Image

from papiq.adapters.outbound.imaging import flatten_on_white

RED = (200, 0, 0)
GREY = 90


def transparent(mode: str) -> Image.Image:
    """Two pixels of `mode`: a transparent one, then an opaque red (grey without colour)."""
    match mode:
        case "P":
            image = Image.new("P", (2, 1))
            image.putpalette([0, 0, 0, *RED])
            image.putpixel((1, 0), 1)
            image.info["transparency"] = 0
        case "PA":
            image = Image.new("PA", (2, 1))
            image.putpalette([0, 0, 0, *RED])
            image.putpixel((0, 0), (1, 0))
            image.putpixel((1, 0), (1, 255))
        case "RGBA" | "RGBa":
            image = Image.new("RGBA", (2, 1))
            image.putpixel((0, 0), (*RED, 0))
            image.putpixel((1, 0), (*RED, 255))
        case "LA" | "La":
            image = Image.new("LA", (2, 1))
            image.putpixel((0, 0), (0, 0))
            image.putpixel((1, 0), (GREY, 255))
    return image if image.mode == mode else image.convert(mode)


@pytest.mark.parametrize("mode", ["P", "PA", "RGBA", "RGBa", "LA", "La"])
def test_transparency_turns_white(mode: str) -> None:
    image = transparent(mode)
    assert image.mode == mode
    flat = flatten_on_white(image)
    assert flat.mode == "RGB"
    opaque = (GREY, GREY, GREY) if mode in ("LA", "La") else RED
    assert [flat.getpixel((0, 0)), flat.getpixel((1, 0))] == [(255, 255, 255), opaque]


@pytest.mark.parametrize("mode", ["1", "L", "P", "RGB", "CMYK", "I;16", "F"])
def test_an_image_without_transparency_stays_as_it_is(mode: str) -> None:
    image = Image.new(mode, (2, 1))
    assert flatten_on_white(image) is image
