"""Machine-readable codes on the pages: GiroCodes (EPC069-12), QR codes, bar codes."""

import numpy
import zxingcpp
from PIL import Image

FORMATS = {
    "QR Code": zxingcpp.BarcodeFormat.QRCode,
    "Code 128": zxingcpp.BarcodeFormat.Code128,
    "Code 39": zxingcpp.BarcodeFormat.Code39,
    "EAN-13": zxingcpp.BarcodeFormat.EAN13,
    "ITF": zxingcpp.BarcodeFormat.ITF,
    "Data Matrix": zxingcpp.BarcodeFormat.DataMatrix,
    "PDF417": zxingcpp.BarcodeFormat.PDF417,
    "Aztec": zxingcpp.BarcodeFormat.Aztec,
}


def code(content: str, format: str = "QR Code") -> Image.Image:
    """The symbol of `content` in `format`, one pixel a module, with its quiet zone (mode 1)."""
    barcode = zxingcpp.create_barcode(content, FORMATS[format])
    symbol = numpy.asarray(zxingcpp.write_barcode_to_image(barcode, scale=1))
    return Image.fromarray(symbol).convert("1")


def girocode(name: str, iban: str, amount: str, purpose: str, bic: str = "") -> str:
    """The content of a GiroCode: a SEPA credit transfer of `amount` (`12.34`) in euro."""
    return "\n".join(
        [
            "BCD",
            "002",
            "1",
            "SCT",
            bic,
            name[:70],
            iban.replace(" ", ""),
            f"EUR{amount}",
            "",
            "",
            purpose[:140],
        ]
    )
