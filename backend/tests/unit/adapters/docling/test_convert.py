"""The fallback of the conversion child process: the text layer when the layout analysis found
no text. Docling itself runs in the integration tests."""

from papiq.adapters.outbound.docling.convert import (
    TEXT_LAYER_NOTE,
    cells_unescaped,
    markdown_or_text_layer,
)
from tests.contracts.processing import SAMPLES


def test_docling_text_is_kept() -> None:
    markdown = "## Rechnung\n\nNummer 4711\n"
    assert markdown_or_text_layer(markdown, SAMPLES / "text.pdf") == (markdown, None)


def test_a_picture_only_result_falls_back_to_the_text_layer() -> None:
    text, note = markdown_or_text_layer("<!-- image -->\n", SAMPLES / "text.pdf")
    assert note == TEXT_LAYER_NOTE
    assert text == "Rechnung Nummer 4711 Papiq Testdokument Betrag 123,45 EUR\n"


def test_without_a_text_layer_the_result_stays_as_it_is() -> None:
    assert markdown_or_text_layer("<!-- image -->\n", SAMPLES / "scan.pdf") == (
        "<!-- image -->\n",
        None,
    )


def test_pipes_in_table_cells_are_escaped_as_markdown_does() -> None:
    markdown = (
        "Rechnung &#124; Nummer\n\n"
        "| Tag | Std.&#124;TAZPL |\n|---|---|\n| Mo | 7,48 &#124; 0,54 |\n"
    )
    assert cells_unescaped(markdown) == (
        "Rechnung &#124; Nummer\n\n| Tag | Std.\\|TAZPL |\n|---|---|\n| Mo | 7,48 \\| 0,54 |\n"
    )
