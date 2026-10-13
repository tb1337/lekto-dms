"""A block of fixed-pitch text takes the place of what the layout analysis read there."""

from collections.abc import Callable

import pytest
from docling_core.types.doc.base import BoundingBox, CoordOrigin, Size
from docling_core.types.doc.common.reference import ProvenanceItem
from docling_core.types.doc.document import DoclingDocument
from docling_core.types.doc.items.node import DocItem
from docling_core.types.doc.items.table.table_data import TableData
from docling_core.types.doc.labels import DocItemLabel, GroupLabel

from papiq.adapters.outbound.docling.fixed_pitch import keep_fixed_pitch
from papiq.adapters.outbound.pdfium.fixed_pitch import FixedPitchBlock

TEXT = "Mitarbeiter : Erika Musterfrau\n-----------------\n|Tag |Kommen |\n|Mo  |07:31  |"
BLOCK = FixedPitchBlock(page=1, left=60, bottom=600, right=530, top=750, line=13.5, text=TEXT)


def place(left: float, top: float, right: float, bottom: float, page: int = 1) -> ProvenanceItem:
    box = BoundingBox(l=left, t=top, r=right, b=bottom, coord_origin=CoordOrigin.BOTTOMLEFT)
    return ProvenanceItem(page_no=page, bbox=box, charspan=(0, 0))


def printout() -> DoclingDocument:
    """Docling's reading of a printout: a title, a key-value group, a rule and a table where
    the block stands, a stamp on it, then a paragraph below and one on the next page."""
    document = DoclingDocument(name="printout")
    for number in (1, 2):
        document.add_page(page_no=number, size=Size(width=595, height=842))
    document.add_text(DocItemLabel.SECTION_HEADER, "Zeitnachweis", prov=place(60, 800, 160, 788))
    group = document.add_group(label=GroupLabel.KEY_VALUE_AREA)
    document.add_text(DocItemLabel.TEXT, "Mitarbeiter", prov=place(66, 744, 129, 737), parent=group)
    document.add_text(DocItemLabel.TEXT, ": Erika", prov=place(175, 744, 260, 737), parent=group)
    document.add_text(DocItemLabel.TEXT, "-----", prov=place(61, 730, 528, 723))
    document.add_table(data=TableData(num_rows=2, num_cols=2), prov=place(61, 720, 527, 605))
    document.add_picture(prov=place(400, 700, 500, 640))
    document.add_text(DocItemLabel.TEXT, "Ende", prov=place(60, 580, 120, 570))
    document.add_text(DocItemLabel.TEXT, "Seite zwei", prov=place(66, 744, 129, 737, page=2))
    return document


def reading(document: DoclingDocument) -> list[tuple[str, str]]:
    return [
        (item.label.value, getattr(item, "text", ""))
        for item, _ in document.iterate_items()
        if isinstance(item, DocItem)
    ]


def test_the_block_takes_the_place_of_what_it_covers() -> None:
    document = printout()
    assert keep_fixed_pitch(document, [BLOCK]) == 1
    assert reading(document) == [
        ("section_header", "Zeitnachweis"),
        ("code", TEXT),
        ("picture", ""),
        ("text", "Ende"),
        ("text", "Seite zwei"),
    ]
    assert document.groups == []
    assert document.tables == []
    (code,) = [item for item in document.texts if item.label == DocItemLabel.CODE]
    (prov,) = code.prov
    assert (prov.page_no, prov.bbox.l, prov.bbox.t, prov.charspan) == (1, 60, 750, (0, len(TEXT)))
    assert f"```\n{TEXT}\n```" in document.export_to_markdown(escape_html=False)
    DoclingDocument.model_validate(document.export_to_dict())


@pytest.mark.parametrize(
    "reaching",
    [
        # A paragraph that starts above the block and runs into it.
        lambda document: document.add_text(
            DocItemLabel.TEXT, "Kopf", prov=place(60, 765, 300, 745)
        ),
        # A table whose head stands below the block, set in another font.
        lambda document: document.add_table(
            data=TableData(num_rows=3, num_cols=2), prov=place(61, 640, 527, 560)
        ),
    ],
)
def test_an_item_reaching_into_the_block_keeps_doclings_reading(
    reaching: Callable[[DoclingDocument], object],
) -> None:
    document = printout()
    reaching(document)
    before = document.export_to_dict()
    assert keep_fixed_pitch(document, [BLOCK]) == 0
    assert document.export_to_dict() == before


def test_a_group_keeps_what_the_block_does_not_cover() -> None:
    document = printout()
    group = document.groups[0]
    document.add_text(DocItemLabel.TEXT, "Fusszeile", prov=place(60, 60, 120, 50), parent=group)
    keep_fixed_pitch(document, [BLOCK])
    assert ("text", "Fusszeile") in reading(document)
    assert ("text", "Mitarbeiter") not in reading(document)


def test_a_caption_stays_with_its_table() -> None:
    document = printout()
    table = document.add_table(
        data=TableData(num_rows=1, num_cols=1), prov=place(61, 400, 527, 300)
    )
    # Docling puts a caption below its table.
    caption = document.add_text(
        DocItemLabel.CAPTION, "Tabelle 1", prov=place(66, 700, 129, 690), parent=table
    )
    table.captions.append(caption.get_ref())
    keep_fixed_pitch(document, [BLOCK])
    (table,) = document.tables
    assert [ref.resolve(document).text for ref in table.captions] == ["Tabelle 1"]


def test_a_block_covering_nothing_stays_out() -> None:
    document = printout()
    before = document.export_to_dict()
    empty = FixedPitchBlock(page=2, left=60, bottom=100, right=530, top=300, line=13.5, text=TEXT)
    assert keep_fixed_pitch(document, [empty]) == 0
    assert document.export_to_dict() == before
