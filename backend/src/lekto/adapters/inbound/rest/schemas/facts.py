"""What a document shows of its contact: names, identifiers and codes."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from lekto.adapters.inbound.rest.schemas.inbox import BoxOut, LocationOut
from lekto.adapters.inbound.schemas import MoneyValue
from lekto.core.domain.document_facts import FactOrigin, FactRole, FactState, role_of
from lekto.core.domain.facts import FoundIdentifier, Span, Strength
from lekto.core.domain.identifiers import IdentifierKind
from lekto.core.services.documents import CodeFacts, DocumentFacts, DocumentNumber
from lekto.core.services.fact_decisions import FactAction, FactDecision


class SpanOut(BaseModel):
    start: int = Field(description="First character, from 0.")
    end: int = Field(description="After the last character.")
    locations: list[LocationOut] = Field(
        description=(
            "Where it stands on the archive's pages, a box per line; empty where the words of "
            "the text have no boxes (a text parsed before 0.2)."
        ),
    )

    @classmethod
    def of(cls, span: Span) -> "SpanOut":
        return cls(
            start=span.start,
            end=span.end,
            locations=[LocationOut.of(location) for location in span.locations],
        )


class NamedContactOut(BaseModel):
    contact_id: UUID
    name: str = Field(description="The contact's name or alias that stands there.")
    alias: bool
    in_text: bool
    in_code: bool = Field(description="The payee of a GiroCode on the pages.")
    spans: list[SpanOut] = Field(description="Where it stands in the text.")


class FoundIdentifierOut(BaseModel):
    kind: IdentifierKind
    value: str = Field(description="Normalised, as a contact keeps it.")
    contact_id: UUID | None = Field(
        description="The contact it is an identifier of (entered or learned); null if none."
    )
    topic_id: UUID | None = Field(
        default=None, description="The topic of the contact it points to, if any."
    )
    in_text: bool
    in_code: bool = Field(description="A code on the pages holds it.")
    spans: list[SpanOut] = Field(description="Where it stands in the text.")
    role: FactRole = Field(
        description=(
            "What it is to the document (`contact`: points to the contact, `target`: to what a "
            "series refers to, `own`: marks the document, `thread`: joins a strand, `refers`: "
            "refers to another document, `person`: points to a person). As kept for the "
            "document; until the facts signal ran again after 0.7, the role of its kind."
        )
    )
    origins: list[FactOrigin] = Field(
        description="Where it comes from: `pattern` (the text), `code`, `model`, `person`."
    )
    state: FactState = Field(
        default=FactState.FOUND,
        description=(
            "`found` as the sources found it, or a person's decision: `added`, `corrected`, "
            "`rejected` (it is no fact of the document)."
        ),
    )
    other_contacts: int | None = Field(
        description=(
            "For admins: on the confirmed documents of how many contacts other than the "
            "document's it stands (the IBAN of one's own account stands on many); null for "
            "others."
        )
    )
    other_contact_ids: list[UUID] | None = Field(
        default=None,
        description=(
            "For admins: those contacts (`other_contacts` of them), to name and open them; "
            "null for others."
        ),
    )


class DocumentNumberOut(BaseModel):
    """A fact kept for the document: a number that is no contact's or person's identifier, its
    own (invoice, credit note, order number), a strand's (file reference, "Unser Zeichen",
    claim, ticket) or another document's it refers to ("Ihre Rechnung Nr.", "Ihr Zeichen"); or
    one of another kind a person decided."""

    kind: IdentifierKind
    value: str = Field(description="Normalised, as Lekto compares it.")
    written: str | None = Field(description="As the text writes it where it stands first.")
    role: FactRole
    origins: list[FactOrigin]
    state: FactState = Field(default=FactState.FOUND, description="As `FoundIdentifierOut.state`.")
    spans: list[SpanOut] = Field(description="Where it stands in the text.")

    @classmethod
    def of(cls, item: DocumentNumber) -> "DocumentNumberOut":
        return cls(
            kind=item.fact.kind,
            value=item.fact.value,
            written=item.fact.written,
            role=item.fact.role,
            origins=sorted(item.fact.origins),
            state=item.fact.state,
            spans=[SpanOut.of(span) for span in item.spans],
        )


class FoundPersonOut(BaseModel):
    """A user the document names, with the kinds of evidence (never the values)."""

    user_id: UUID
    name: str = Field(description="Their display name, else the username.")
    strength: Strength = Field(
        description=(
            "`hard`: one of their identifiers (or a contact's number that names them); "
            "`medium`: their birth date; `weak`: their display name or an alias."
        )
    )
    evidence: list[str] = Field(
        description="`name`, `alias`, `birth_date` and the kinds of identifiers found."
    )
    spans: list[SpanOut] = Field(description="Where their names and identifiers stand.")


class IdentifierFoundOut(BaseModel):
    kind: IdentifierKind
    value: str


class GiroCodeOut(BaseModel):
    """The credit transfer of a GiroCode (EPC QR code)."""

    name: str = Field(description="The payee.")
    iban: str
    bic: str | None
    amount: MoneyValue | None
    purpose: str | None


class CodePlaceOut(BaseModel):
    """Where a code stands on a page of the archive."""

    page: int = Field(description="From 1.")
    boxes: list[BoxOut] = Field(description="One per copy of the code on the page.")


class CodeOut(BaseModel):
    """A code once for its format and text, however often the pages show it."""

    format: str = Field(examples=["QR Code", "Code 128", "Data Matrix"])
    text: str = Field(description="What it holds, as it holds it; someone else's text.")
    places: list[CodePlaceOut] = Field(description="The pages it stands on, in order.")
    giro: GiroCodeOut | None = Field(description="A GiroCode, read as its credit transfer.")
    identifiers: list[IdentifierFoundOut]
    fields: list[UUID] = Field(
        description="Amount fields of the document with the GiroCode's amount as their value."
    )

    @classmethod
    def of(cls, item: CodeFacts) -> "CodeOut":
        giro = None
        if item.giro is not None:
            amount = item.giro.amount
            giro = GiroCodeOut(
                name=item.giro.name,
                iban=item.giro.iban,
                bic=item.giro.bic,
                amount=None
                if amount is None
                else MoneyValue(amount=str(amount.amount), currency=amount.currency),
                purpose=item.giro.purpose,
            )
        return cls(
            format=item.format,
            text=item.text,
            places=[
                CodePlaceOut(page=place.page, boxes=[BoxOut.of(box) for box in place.boxes])
                for place in item.places
            ],
            giro=giro,
            identifiers=[
                IdentifierFoundOut(kind=kind, value=value) for kind, value in item.identifiers
            ],
            fields=list(item.fields),
        )


class FactsOut(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "contact_id": "01999d5e-3333-7c1e-b6a3-2f4d5e6f7a8b",
                    "named": [],
                    "identifiers": [
                        {
                            "kind": "customer_number",
                            "value": "20047718",
                            "contact_id": None,
                            "in_text": True,
                            "in_code": False,
                            "spans": [
                                {
                                    "start": 412,
                                    "end": 421,
                                    "locations": [
                                        {
                                            "page": 1,
                                            "boxes": [
                                                {
                                                    "x": 0.62,
                                                    "y": 0.18,
                                                    "width": 0.11,
                                                    "height": 0.012,
                                                }
                                            ],
                                        }
                                    ],
                                }
                            ],
                            "role": "contact",
                            "origins": ["pattern"],
                            "other_contacts": 0,
                            "other_contact_ids": [],
                        }
                    ],
                    "codes": [],
                }
            ]
        }
    )

    contact_id: UUID | None = Field(description="The document's contact.")
    named: list[NamedContactOut]
    identifiers: list[FoundIdentifierOut] = Field(
        description="Those of contacts first, then those of none."
    )
    codes: list[CodeOut] | None = Field(
        description="The codes on the pages; null while they are not read (`read-codes`)."
    )
    numbers: list[DocumentNumberOut] = Field(
        default_factory=list,
        description=(
            "The document's numbers that are no contact's or person's identifier, as the text "
            "reads: as the facts signal kept them (empty until it ran again after 0.7), with "
            "a person's decisions, those rejected too."
        ),
    )
    decided: list[DocumentNumberOut] = Field(
        default_factory=list,
        description=(
            "The facts of the other kinds a person decided that `identifiers` does not show: "
            "one added, a corrected value, one rejected the text does not show; a person's "
            "kinds only for admins."
        ),
    )
    editable: bool = Field(
        default=False,
        description="Whether the caller decides about the facts: an editor of the space or an "
        "admin (`POST /documents/{id}/facts/decisions`).",
    )
    persons: list[FoundPersonOut] | None = Field(
        default=None,
        description=(
            "The users the document names, the surest first: for the editors of its space and "
            "admins; null for readers. What is private about a person (aliases, birth date, "
            "identifiers, a contact's number that names them) finds them only for admins and "
            "that person: anyone else sees another user only where the text has their display "
            "name (that a number is Anna's tax ID is Anna's)."
        ),
    )

    @classmethod
    def of(cls, report: DocumentFacts) -> "FactsOut":
        others = report.other_contacts
        return cls(
            contact_id=report.contact_id,
            named=[
                NamedContactOut(
                    contact_id=item.contact_id,
                    name=item.name,
                    alias=item.alias,
                    in_text=item.in_text,
                    in_code=item.in_code,
                    spans=[SpanOut.of(span) for span in item.spans],
                )
                for item in report.facts.named
            ],
            identifiers=[
                FoundIdentifierOut(
                    kind=item.kind,
                    value=item.value,
                    contact_id=item.contact_id,
                    topic_id=item.topic_id,
                    in_text=item.in_text,
                    in_code=item.in_code,
                    spans=[SpanOut.of(span) for span in item.spans],
                    role=_role(report, item),
                    origins=_origins(report, item),
                    state=_state(report, item),
                    other_contacts=None if others is None else len(others.get(item.key, ())),
                    other_contact_ids=(
                        None if others is None else sorted(others.get(item.key, frozenset()))
                    ),
                )
                for item in report.facts.identifiers
            ],
            codes=None if report.codes is None else [CodeOut.of(item) for item in report.codes],
            numbers=[DocumentNumberOut.of(item) for item in report.numbers],
            decided=[DocumentNumberOut.of(item) for item in report.decided],
            editable=report.editable,
            persons=(
                None
                if report.person_names is None
                else [
                    FoundPersonOut(
                        user_id=item.user_id,
                        name=report.person_names.get(item.user_id, str(item.user_id)),
                        strength=item.strength,
                        evidence=list(item.evidence),
                        spans=[SpanOut.of(span) for span in item.spans],
                    )
                    for item in report.facts.persons
                ]
            ),
        )


def _role(report: DocumentFacts, item: FoundIdentifier) -> FactRole:
    kept = report.stored.get(item.key)
    return role_of(item.kind) if kept is None else kept.role


def _state(report: DocumentFacts, item: FoundIdentifier) -> FactState:
    kept = report.stored.get(item.key)
    return FactState.FOUND if kept is None else kept.state


def _origins(report: DocumentFacts, item: FoundIdentifier) -> list[FactOrigin]:
    """The text's patterns and a code as the facts are found now (a row taken over by revision
    0047 does not know whether a code held it), other sources as kept."""
    kept = report.stored.get(item.key)
    found = {
        *([FactOrigin.PATTERN] if item.in_text else []),
        *([FactOrigin.CODE] if item.in_code else []),
    }
    if kept is not None:
        found |= kept.origins - {FactOrigin.PATTERN, FactOrigin.CODE}
    return sorted(found)


class FactDecisionIn(BaseModel):
    """A person's decision about a fact of the document."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "action": "correct",
                    "kind": "invoice_number",
                    "value": "4711",
                    "role": "refers",
                },
                {
                    "action": "correct",
                    "kind": "customer_number",
                    "value": "20047718",
                    "new_value": "2004 7719",
                    "at_contact": True,
                },
                {"action": "add", "kind": "contract_number", "value": "V-123", "role": "target"},
            ]
        }
    )

    action: FactAction = Field(
        description=(
            "`add` a fact the sources did not find (`value` as written, `role` required); "
            "`correct` the fact of `kind` and `value` (its role, and with `new_value` its "
            "value: the old one is then rejected); `reject` it (it is no fact of the "
            "document); `withdraw` a decision (a fact a source found is as found again, one "
            "only a person gave goes)."
        )
    )
    kind: IdentifierKind
    value: str = Field(
        min_length=1,
        max_length=200,
        description="`add`: as written; otherwise the fact's value, normalised.",
    )
    role: FactRole | None = Field(
        default=None, description="`add`: its role; `correct`: the role it has instead."
    )
    new_value: str | None = Field(
        default=None, min_length=1, max_length=200, description="`correct`: the value, as written."
    )
    at_contact: bool = Field(
        default=False,
        description=(
            "`correct`, for admins: correct the value at the document's contact too (the old "
            "one goes from its identifiers, the new one is entered by hand); only for the kinds "
            "a contact keeps."
        ),
    )

    def decision(self) -> FactDecision:
        return FactDecision(
            action=self.action,
            kind=self.kind,
            value=self.value,
            role=self.role,
            new_value=self.new_value,
            at_contact=self.at_contact,
        )
