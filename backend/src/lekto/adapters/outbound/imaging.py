"""What the adapters that read images with Pillow share: an image as it looks on white paper
(PDFium's page images, OCRmyPDF's input)."""

from PIL import Image

# Modes with an alpha channel, straight or premultiplied (`RGBa`, `La`).
_ALPHA = ("RGBA", "LA", "PA", "RGBa", "La")


def flatten_on_white(image: Image.Image) -> Image.Image:
    """`image` on white: one with transparency (an alpha channel, or a palette with a
    transparent colour) becomes an RGB copy on white; any other is returned as it is."""
    if image.mode == "P" and "transparency" in image.info:
        image = image.convert("RGBA")
    if image.mode not in _ALPHA:
        return image
    if image.mode == "La":
        image = image.convert("LA")  # Pillow converts premultiplied grey to nothing else
    rgba = image.convert("RGBA")
    white = Image.new("RGB", rgba.size, "white")
    white.paste(rgba, mask=rgba.getchannel("A"))
    return white
