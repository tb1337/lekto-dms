"""Generates the example documents in `files/`, `manifest.json` and the statistics in
`README.md`. Run it in the devcontainer from `backend/` (it needs the backend's dependencies and
the URW fonts of Ghostscript):

    uv run python ../examples/documents/generate.py            # everything
    uv run python ../examples/documents/generate.py --check    # only check the layouts

The output is deterministic: the same code gives the same bytes. `--check` lays every document
out and checks that each identifier of the manifest is found in its text by Lekto's own
patterns (where it has any) and that no text runs off its page.
"""

import argparse
import json
import multiprocessing
import random
import re
import shutil
import sys
import zlib
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from synth.capture import STAGES, Capture, File, capture  # noqa: E402
from synth.corpus import TODAY, Entry, entries  # noqa: E402
from synth.document import Doc  # noqa: E402
from synth.fonts import width  # noqa: E402
from synth.layout import Text  # noqa: E402

FILES = HERE / "files"
MANIFEST = HERE / "manifest.json"
README = HERE / "README.md"
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

_ENTRIES: list[Entry] = []


def seed_of(key: str) -> int:
    return zlib.crc32(key.encode())


def captured_at(entry: Entry, document: Doc) -> datetime:
    """When the document was scanned, photographed or downloaded: after its date, not after
    the end of the corpus."""
    rng = random.Random(seed_of(entry.key) + 1)
    day = document.date or entry.day or TODAY
    if entry.delay is not None:
        delay = entry.delay
    elif entry.stage in ("digital", "printout", "screenshot"):
        delay = rng.randint(0, 2)
    else:
        delay = rng.randint(1, 21)
    moment = datetime(day.year, day.month, day.day) + timedelta(
        days=delay, hours=rng.randint(7, 22), minutes=rng.randint(0, 59), seconds=rng.randint(0, 59)
    )
    latest = datetime(TODAY.year, TODAY.month, TODAY.day, 21, 0, 0)
    return min(moment, latest)


def file_name(entry: Entry, document: Doc, when: datetime, pages: int, taken: set[str]) -> str:
    """The name the file got where it came from: the portal's, the scanner's, the phone's."""
    rng = random.Random(seed_of(entry.key) + 2)
    stage = entry.stage
    multi = pages > 1
    if stage in ("digital", "printout"):
        name = document.download
    elif stage == "scan-clean":
        name = f"Scan_{when:%Y-%m-%d_%H%M%S}.pdf"
    elif stage == "scan-office":
        name = rng.choice([f"SCN_{when:%Y%m%d_%H%M%S}.pdf", f"{when:%Y%m%d%H%M%S}.pdf"])
    elif stage == "scan-bw":
        name = (
            f"scan{when:%y%m%d}{when.hour * 60 + when.minute:04d}.{'tif' if entry.tiff else 'pdf'}"
        )
    elif stage == "scanner-ocr":
        name = f"OCR_{when:%Y%m%d_%H%M%S}.pdf"
    elif stage == "fax":
        name = f"Fax_{entry.fax_from.replace(' ', '')}_{when:%Y%m%d-%H%M}.pdf"
    elif stage == "scan-poor":
        name = f"Dokument {when:%Y-%m-%d %H%M%S}.pdf"
    elif stage == "photo":
        name = f"Scan {when:%Y-%m-%d %H.%M.%S}.pdf" if multi else f"IMG_{when:%Y%m%d_%H%M%S}.jpg"
    elif stage == "photo-poor":
        name = (
            f"Scan {when:%Y-%m-%d %H.%M.%S}.pdf"
            if multi
            else f"IMG-{when:%Y%m%d}-WA{rng.randint(1, 60):04d}.jpg"
        )
    else:
        name = rng.choice(
            [
                f"Bildschirmfoto {when:%Y-%m-%d} um {when:%H.%M.%S}.png",
                f"Screenshot_{when:%Y%m%d-%H%M%S}.png",
            ]
        )
    stem, _, extension = name.rpartition(".")
    number = 0
    while name.lower() in taken:
        number += 1
        name = f"{stem} ({number}).{extension}"
    taken.add(name.lower())
    return name


def how(entry: Entry, document: Doc, when: datetime) -> Capture:
    label = document.url or document.download
    if entry.stage == "fax":
        label = document.contact
    return Capture(
        when,
        marks=entry.marks,
        duplex=entry.duplex,
        turned=entry.turned,
        tiff=entry.tiff,
        exif_turned=entry.exif_turned,
        fax_from=entry.fax_from,
        label=label,
        screen=document.layout == "screen",
        creator=f"{document.contact or 'Scanner'}",
        producer="Lekto example documents",
    )


def _capture(index: int) -> tuple[int, File]:
    entry = _ENTRIES[index]
    document = entry.make()
    when = captured_at(entry, document)
    return index, capture(
        entry.stage, document.pages, how(entry, document, when), seed_of(entry.key)
    )


def text_of(document: Doc) -> str:
    """The document's text, a line per baseline, its pieces apart as columns."""
    lines = []
    for page in document.pages:
        rows: dict[float, list[Text]] = {}
        for item in page.items:
            if isinstance(item, Text):
                rows.setdefault(round(item.y * 2) / 2, []).append(item)
        for y in sorted(rows):
            pieces = sorted(rows[y], key=lambda item: _left(item))
            lines.append("    ".join(piece.text for piece in pieces))
    return "\n".join(lines)


def _left(item: Text) -> float:
    full = width(item.text, item.font, item.size)
    return item.x - (full if item.align == "right" else full / 2 if item.align == "center" else 0)


def check(documents: list[tuple[Entry, Doc]]) -> int:
    """Each identifier found by Lekto's patterns, no text off its page; the number of findings.
    A value the patterns read on into the next line ("R-2024-0277" and the "12347" of the
    line below) is Lekto's to fix, not the corpus's: reported, not counted."""
    from lekto.core.domain.identifiers import IdentifierKind, identifiers_in, normalise_identifier

    model_only = {"credit_note_number", "letter_date"}
    findings = 0
    for entry, document in documents:
        found = identifiers_in(text_of(document))
        for fact in document.facts:
            kind = IdentifierKind(fact.kind)
            try:
                value = normalise_identifier(kind, fact.value)
            except Exception as error:
                print(f"{entry.key}: {fact.kind} {fact.value!r} is none of its kind: {error}")
                findings += 1
                continue
            if (kind, value) in found or fact.kind in model_only or not fact.pattern:
                continue
            longer = [
                other
                for other_kind, other in found
                if other_kind == kind and other.startswith(value)
            ]
            if longer:
                print(f"{entry.key}: Lekto reads {fact.kind} {fact.value!r} on as {longer[0]!r}")
                continue
            print(f"{entry.key}: {fact.kind} {fact.value!r} not found by the patterns")
            findings += 1
        for number, page in enumerate(document.pages, start=1):
            for item in page.items:
                if isinstance(item, Text):
                    left = _left(item)
                    right = left + width(item.text, item.font, item.size)
                    if left < 2 or right > page.width - 2 or item.y > page.height - 1:
                        print(f"{entry.key} p. {number}: off the page: {item.text[:50]!r}")
                        findings += 1
    return findings


def manifest_entry(
    entry: Entry, document: Doc, name: str, file: File, names: dict[str, str]
) -> dict[str, object]:
    from lekto.core.domain.document_facts import role_of
    from lekto.core.domain.identifiers import IdentifierKind

    capture_details: dict[str, object] = {}
    if entry.duplex:
        capture_details["duplex"] = True
    if entry.turned:
        capture_details["turned_pages"] = sorted(page + 1 for page in entry.turned)
    if entry.exif_turned:
        capture_details["exif_orientation"] = 6
    return {
        "file": name,
        "key": entry.key,
        "class": document.cls,
        "quality": entry.stage,
        "layout": document.layout,
        "media_type": file.media_type,
        "pages": file.pages,
        "language": document.language,
        "contact": document.contact or None,
        "document_type": document.document_type or None,
        "document_date": document.date.isoformat() if document.date else None,
        "title": document.title,
        "recipient": document.recipient,
        "fields": document.fields,
        "facts": [
            {
                "kind": fact.kind,
                "value": fact.value,
                "role": fact.role or role_of(IdentifierKind(fact.kind)).value,
            }
            | ({} if fact.pattern else {"pattern": False})
            for fact in document.facts
        ],
        "codes": document.codes,
        "relations": [names[key] for key in entry.refers],
        "series": entry.series,
        "duplicate_of": names[entry.duplicate_of] if entry.duplicate_of else None,
        "marks": entry.marks.names(),
        "capture": capture_details,
    }


def statistics(records: list[dict[str, object]], sizes: int) -> str:
    stages = Counter(str(record["quality"]) for record in records)
    classes = Counter(str(record["class"]) for record in records)
    types = Counter(str(record["document_type"]) for record in records if record["document_type"])
    media = Counter(str(record["media_type"]) for record in records)
    pages = sum(int(record["pages"]) for record in records)  # type: ignore[call-overload]
    lines = [
        f"{len(records)} documents, {pages} pages, {sizes / 1_000_000:.1f} MB.",
        "",
        "| Quality stage | Documents |",
        "| --- | ---: |",
        *(f"| `{stage}` | {stages[stage]} |" for stage in STAGES),
        "",
        "| Document type | Documents |",
        "| --- | ---: |",
        *(
            f"| {name} | {count} |"
            for name, count in sorted(types.items(), key=lambda item: (-item[1], item[0]))
        ),
        "",
        "| Class | Documents | Class | Documents |",
        "| --- | ---: | --- | ---: |",
    ]
    ordered = sorted(classes.items())
    half = (len(ordered) + 1) // 2
    right_column = [*ordered[half:], ("", "")][: len(ordered[:half])]
    for left, right in zip(ordered[:half], right_column, strict=True):
        lines.append(
            f"| `{left[0]}` | {left[1]} | {f'`{right[0]}`' if right[0] else ''} | {right[1]} |"
        )
    lines += [
        "",
        "| File type | Documents |",
        "| --- | ---: |",
        *(f"| {kind} | {count} |" for kind, count in sorted(media.items())),
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--check", action="store_true", help="only lay out and check")
    arguments = parser.parse_args()
    _ENTRIES.extend(entries())
    documents = [(entry, entry.make()) for entry in _ENTRIES]
    keys = Counter(entry.key for entry in _ENTRIES)
    duplicated = [key for key, count in keys.items() if count > 1]
    if duplicated:
        raise SystemExit(f"keys twice: {duplicated}")
    findings = check(documents)
    print(f"{len(documents)} documents laid out, {findings} findings")
    if arguments.check or findings:
        raise SystemExit(1 if findings else 0)
    with multiprocessing.get_context("fork").Pool() as pool:
        files = dict(pool.imap_unordered(_capture, range(len(documents)), chunksize=2))
    if FILES.exists():
        shutil.rmtree(FILES)
    FILES.mkdir()
    taken: set[str] = set()
    names = {
        entry.key: file_name(entry, document, captured_at(entry, document), files[n].pages, taken)
        for n, (entry, document) in enumerate(documents)
    }
    records = []
    sizes = 0
    for n, (entry, document) in enumerate(documents):
        name = names[entry.key]
        (FILES / name).write_bytes(files[n].data)
        sizes += len(files[n].data)
        records.append(manifest_entry(entry, document, name, files[n], names))
    MANIFEST.write_text(
        json.dumps({"documents": records}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    text = (
        README.read_text(encoding="utf-8")
        if README.exists()
        else "<!-- statistics -->\n<!-- /statistics -->\n"
    )
    text = re.sub(
        r"<!-- statistics -->.*<!-- /statistics -->",
        lambda _: f"<!-- statistics -->\n{statistics(records, sizes)}\n<!-- /statistics -->",
        text,
        flags=re.DOTALL,
    )
    README.write_text(text, encoding="utf-8")
    print(f"{len(records)} files, {sizes / 1_000_000:.1f} MB")


if __name__ == "__main__":
    main()
