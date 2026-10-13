"""Text set in a fixed-pitch font, in Docling's document as it is set: one code item per block
(see `papiq.adapters.outbound.pdfium.fixed_pitch`) in place of the paragraphs and tables the
layout analysis read there. The Markdown has it as a fenced code block then."""

from collections.abc import Sequence

from docling_core.types.doc.base import BoundingBox, CoordOrigin
from docling_core.types.doc.common.reference import ProvenanceItem
from docling_core.types.doc.document import DoclingDocument
from docling_core.types.doc.items.group import GroupItem
from docling_core.types.doc.items.node import DocItem, NodeItem
from docling_core.types.doc.items.picture.picture import PictureItem

from papiq.adapters.outbound.pdfium.fixed_pitch import FixedPitchBlock

OVERLAP = 0.1
"""Share of an item's box inside a block from which the item reads part of the block."""


def keep_fixed_pitch(document: DoclingDocument, blocks: Sequence[FixedPitchBlock]) -> int:
    """Puts each block into `document` as a code item where the first item it covers stands,
    and removes the items it covers (a group, too, once nothing else is left in it; a caption
    goes with its table). An item is covered when it lies inside the block, give or take half
    a line. Pictures stay. A block covering no item, or with an item reaching into it from
    outside (a table whose head is set in another font, say), stays out: Docling's reading of
    that place is kept whole. Returns the number of blocks put in."""
    return sum(_replace(document, block) for block in blocks)


def _replace(document: DoclingDocument, block: FixedPitchBlock) -> bool:
    page = document.pages.get(block.page)
    if page is None:
        return False
    items = [item for item, _ in document.iterate_items(with_groups=True)]
    covered: set[str] = set()
    for item in items:
        if not isinstance(item, DocItem) or isinstance(item, PictureItem):
            continue
        if not _in_group(document, item):
            continue
        boxes = [
            (prov.page_no, prov.bbox.to_bottom_left_origin(page.size.height)) for prov in item.prov
        ]
        if boxes and all(number == block.page and _inside(box, block) for number, box in boxes):
            covered.add(item.self_ref)
        elif any(number == block.page and _overlaps(box, block) for number, box in boxes):
            return False
    if not covered:
        return False
    tops: list[NodeItem] = []
    for item in items:
        if item.self_ref in covered:
            top = _top(document, item, covered)
            if all(top.self_ref != other.self_ref for other in tops):
                tops.append(top)
    tops = [top for top in tops if not _within(document, top, tops)]
    document.insert_code(
        sibling=tops[0],
        text=block.text,
        prov=ProvenanceItem(
            page_no=block.page,
            bbox=BoundingBox(
                l=block.left,
                t=block.top,
                r=block.right,
                b=block.bottom,
                coord_origin=CoordOrigin.BOTTOMLEFT,
            ),
            charspan=(0, len(block.text)),
        ),
        after=False,
    )
    document.delete_items(node_items=tops)
    return True


def _inside(box: BoundingBox, block: FixedPitchBlock) -> bool:
    margin = block.line / 2
    return (
        box.l >= block.left - margin
        and box.r <= block.right + margin
        and box.b >= block.bottom - margin
        and box.t <= block.top + margin
    )


def _overlaps(box: BoundingBox, block: FixedPitchBlock) -> bool:
    width = min(box.r, block.right) - max(box.l, block.left)
    height = min(box.t, block.top) - max(box.b, block.bottom)
    if width <= 0 or height <= 0:
        return False
    return width * height > OVERLAP * (box.r - box.l) * (box.t - box.b)


def _in_group(document: DoclingDocument, item: NodeItem) -> bool:
    """Whether `item` stands in a group (the body is one); a caption of a table goes with it."""
    return item.parent is not None and isinstance(item.parent.resolve(document), GroupItem)


def _top(document: DoclingDocument, item: NodeItem, covered: set[str]) -> NodeItem:
    """The outermost group around `item` with nothing but covered items in it, else `item`."""
    top = item
    while top.parent is not None:
        parent = top.parent.resolve(document)
        if not isinstance(parent, GroupItem) or parent.self_ref == document.body.self_ref:
            break
        inside = [node.self_ref for node, _ in document.iterate_items(root=parent)]
        if not inside or any(ref not in covered for ref in inside):
            break
        top = parent
    return top


def _within(document: DoclingDocument, item: NodeItem, others: list[NodeItem]) -> bool:
    """Whether `item` lies inside one of `others` (and goes when that one goes)."""
    refs = {other.self_ref for other in others}
    parent = item.parent
    while parent is not None:
        if parent.cref in refs:
            return True
        parent = parent.resolve(document).parent
    return False
