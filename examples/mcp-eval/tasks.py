"""Write `tasks.json`: questions about the example documents, each with the answers it accepts,
reckoned from `examples/documents/manifest.json` (the truth `seed.py` puts into Lekto).

    python tasks.py

Each task names what an answer has to contain (one of `expect`, case and spaces aside); amounts
in the forms a German or an English answer writes them. Standard library only.
"""

import argparse
import json
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any

from manifest import documents

HERE = Path(__file__).resolve().parent


def amounts(value: Decimal) -> list[str]:
    """`value` as answers write it: 5259.80, 5259,80, 5.259,80, 5,259.80."""
    fixed = f"{value:.2f}"
    whole, cents = fixed.split(".")
    grouped = f"{int(whole):,}"
    return [fixed, f"{whole},{cents}", f"{grouped.replace(',', '.')},{cents}", f"{grouped}.{cents}"]


def build(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    docs = [doc for doc in documents if not doc.get("duplicate_of")]
    tasks: list[dict[str, Any]] = []

    def task(question: str, expect: list[str], kind: str) -> None:
        tasks.append(
            {"id": f"t{len(tasks) + 1:02d}", "kind": kind, "question": question, "expect": expect}
        )

    def paid(contact: str, year: str) -> Decimal:
        return sum(
            (
                Decimal(doc["fields"]["Betrag"]["amount"])
                for doc in docs
                if doc.get("contact") == contact
                and (doc.get("document_date") or "").startswith(year)
                and "Betrag" in (doc.get("fields") or {})
            ),
            Decimal(0),
        )

    for contact in ("Umzüge Express Nord GmbH", "FernNetz Telekommunikation GmbH"):
        total = paid(contact, "2025")
        if total:
            task(
                f"Wie viel habe ich 2025 laut Feld Betrag an {contact} gezahlt? Nenne die Summe.",
                amounts(total),
                "sum",
            )
    for kind, year in (("Rechnung", "2025"), ("Kassenbon", "2026")):
        count = sum(
            1
            for doc in docs
            if doc.get("document_type") == kind
            and (doc.get("document_date") or "").startswith(year)
        )
        task(
            f"Wie viele Dokumente vom Typ {kind} sind von {year}? Nur die Zahl.",
            [str(count)],
            "count",
        )
    by_contact = Counter(doc.get("contact") for doc in docs if doc.get("contact"))
    top = alone(by_contact)
    if top is not None:
        task("Von welchem Kontakt habe ich die meisten Dokumente?", [top], "group")
    for contact, count in by_contact.most_common(1):
        task(f"Wie viele Dokumente habe ich von {contact}? Nur die Zahl.", [str(count)], "count")
    numbered = next(
        (doc for doc in docs if (doc.get("fields") or {}).get("Rechnungsnummer") == "R-2024-0277"),
        None,
    )
    if numbered is not None:
        task(
            "Welches Dokument hat die Rechnungsnummer R-2024-0277? Nenne seinen Titel.",
            [numbered["title"]],
            "find",
        )
    payslips = sorted(
        (doc for doc in docs if doc.get("document_type") == "Lohnabrechnung"),
        key=lambda doc: doc.get("document_date") or "",
    )
    if payslips:
        task(
            "Wie heißt meine neueste Lohnabrechnung? Nenne ihren Titel.",
            [payslips[-1]["title"]],
            "latest",
        )
    statements = sorted(
        (
            doc
            for doc in docs
            if doc.get("contact") == "Sparkasse Musterstadt"
            and "Kontostand" in (doc.get("fields") or {})
        ),
        key=lambda doc: doc.get("document_date") or "",
    )
    if statements:
        balance = statements[-1]["fields"]["Kontostand"]
        task(
            "Wie war der letzte Kontostand auf den Kontoauszügen der Sparkasse Musterstadt?",
            amounts(Decimal(balance["amount"])) if isinstance(balance, dict) else [str(balance)],
            "latest",
        )
    customer = next(
        (
            doc["fields"]["Kundennummer"]
            for doc in docs
            if doc.get("contact") == "Stadtwerke Musterstadt GmbH"
            and "Kundennummer" in (doc.get("fields") or {})
        ),
        None,
    )
    if customer is not None:
        task("Welche Kundennummer habe ich bei den Stadtwerken Musterstadt?", [customer], "field")
    per_year: dict[str, int] = defaultdict(int)
    for doc in docs:
        if doc.get("document_type") == "Kontoauszug":
            per_year[(doc.get("document_date") or "")[:4]] += 1
    busiest = alone(Counter(per_year))
    if busiest is not None:
        task("In welchem Jahr habe ich die meisten Kontoauszüge? Nur das Jahr.", [busiest], "group")
    commonest = alone(Counter(doc.get("document_type") for doc in docs if doc.get("document_type")))
    if commonest is not None:
        task("Welcher Dokumenttyp kommt am häufigsten vor?", [commonest], "group")
    return tasks


def alone(counts: Counter[Any]) -> Any:
    """The value counted most often; None when another is counted as often (no one answer)."""
    top = counts.most_common(2)
    if not top or (len(top) == 2 and top[0][1] == top[1][1]):
        return None
    return top[0][0]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--documents", type=int, help="the sample seed.py loaded (default: all)")
    parser.add_argument("--out", type=Path, default=HERE / "tasks.json")
    arguments = parser.parse_args()
    tasks = build(documents(arguments.documents))
    arguments.out.write_text(json.dumps(tasks, ensure_ascii=False, indent=2) + "\n")
    print(f"{len(tasks)} tasks")


if __name__ == "__main__":
    main()
