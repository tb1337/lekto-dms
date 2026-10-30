"""The open identifiers (`/identifiers/open`)."""

from collections.abc import Mapping
from datetime import date
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from lekto.adapters.inbound.rest.schemas.inbox import LocationOut
from lekto.adapters.inbound.rest.schemas.refs import seal
from lekto.adapters.inbound.schemas import ReasonOut
from lekto.core.domain.document_facts import FactRole
from lekto.core.domain.identifiers import IdentifierKind
from lekto.core.domain.ids import ContactId, UserId
from lekto.core.domain.occurrences import Occurrence
from lekto.core.domain.open_identifiers import (
    OpenIdentifier,
    OpenSource,
    Recommendation,
    Recommended,
)
from lekto.core.ports.identity import RefCipher
from lekto.core.services.open_identifiers import (
    DecisionOutcome,
    OpenAction,
    OpenDecision,
    OpenDetail,
    OpenPage,
)
from lekto.core.services.places import Place

MAX_DECISIONS = 200


class OpenContactOut(BaseModel):
    id: UUID
    name: str


class OpenPersonOut(BaseModel):
    id: UUID = Field(description="The user.")
    name: str = Field(description="Their display name.")


class RecommendationOut(BaseModel):
    """What its confirmed documents recommend doing with an open identifier."""

    action: Recommendation = Field(
        description="`confirm`: it stands in two or more confirmed documents of its contact, at "
        "no other contact, and (of a kind with a holder) is its contact's in each; `reject` (a "
        "learned one): a document of its contact gives it someone else, or other contacts "
        "hold it as theirs."
    )
    reason: ReasonOut = Field(description="Why, with its code.")

    @classmethod
    def of(cls, recommended: Recommended) -> "RecommendationOut":
        return cls(action=recommended.action, reason=ReasonOut.of(recommended.reason))


class OpenIdentifierOut(BaseModel):
    """An identifier no person has confirmed."""

    kind: IdentifierKind
    value: str = Field(description="Normalised, as Lekto compares it.")
    ref: str = Field(
        description="The value's reference: for `GET /identifiers/open/{kind}/{ref}` and the "
        "`fact` filter of the documents."
    )
    written: str = Field(description="As the newest of its documents writes it.")
    source: OpenSource = Field(
        description="`learned`: training found it at `contacts[0]`; `unknown`: it stands in "
        "confirmed documents but at no contact, `contacts` are their contacts, the one with "
        "most documents first; `suggested`: a number with a holder (an IBAN, a creditor ID, "
        "a VAT ID, an e-mail domain) its documents name as another's, the contact's in "
        "`contacts[0]` or the person's in `person`."
    )
    contacts: list[OpenContactOut]
    person: OpenPersonOut | None = Field(
        default=None, description="A suggestion for this person's profile."
    )
    documents: int = Field(description="Confirmed documents that show it.")
    last: date | None = Field(description="The date of the newest of them.")
    recommendation: RecommendationOut | None = Field(
        default=None, description="What its documents recommend; none where they do not tell."
    )

    @classmethod
    def of(
        cls,
        item: OpenIdentifier,
        names: Mapping[ContactId, str],
        persons: Mapping[UserId, str],
        refs: RefCipher,
    ) -> "OpenIdentifierOut":
        return cls(
            kind=item.kind,
            value=item.value,
            ref=seal(refs, item.kind, item.value),
            written=item.written,
            source=item.source,
            contacts=[OpenContactOut(id=id, name=names.get(id, "")) for id in item.contacts],
            person=None
            if item.person is None
            else OpenPersonOut(id=item.person, name=persons.get(item.person, "")),
            documents=len(item.seen),
            last=item.last,
            recommendation=None
            if item.recommended is None
            else RecommendationOut.of(item.recommended),
        )


class OpenCountsOut(BaseModel):
    learned: int
    unknown: int
    suggested: int

    @classmethod
    def of(cls, counts: Mapping[OpenSource, int]) -> "OpenCountsOut":
        return cls(
            learned=counts.get(OpenSource.LEARNED, 0),
            unknown=counts.get(OpenSource.UNKNOWN, 0),
            suggested=counts.get(OpenSource.SUGGESTED, 0),
        )


class OpenPageOut(BaseModel):
    items: list[OpenIdentifierOut]
    total: int = Field(description="How many match the filters.")
    counts: OpenCountsOut = Field(description="How many match under each source (not `source`).")
    kinds: dict[IdentifierKind, int] = Field(
        description="How many match of each kind (not `kind`)."
    )
    recommended: int = Field(
        description="How many have a recommendation, counted as `counts` (not `source`, not "
        "`recommended`)."
    )
    to_confirm: int = Field(
        description="How many of them have one to confirm: what `POST /recommended` confirms "
        "(of every source and kind, without the words)."
    )

    @classmethod
    def of(cls, page: OpenPage, refs: RefCipher) -> "OpenPageOut":
        return cls(
            items=[
                OpenIdentifierOut.of(item, page.names, page.persons, refs) for item in page.items
            ],
            total=page.total,
            counts=OpenCountsOut.of(page.counts),
            kinds=dict(page.kinds),
            recommended=page.recommended,
            to_confirm=page.to_confirm,
        )


class ExcerptOut(BaseModel):
    before: str
    match: str = Field(description="The identifier as it stands in the text.")
    after: str


class OccurrenceOut(BaseModel):
    """One place the pages show the value."""

    own: bool = Field(description="Where the fact was read (its first place in the text).")
    locations: list[LocationOut] = Field(description="By page, a box per line.")

    @classmethod
    def of(cls, occurrence: Occurrence) -> "OccurrenceOut":
        return cls(
            own=occurrence.own,
            locations=[LocationOut.of(location) for location in occurrence.locations],
        )


class PlaceOut(BaseModel):
    document_id: UUID
    title: str
    date: date
    role: FactRole
    excerpt: ExcerptOut | None = Field(
        description="The text around it, where the document has text and the fact a position."
    )
    occurrences: list[OccurrenceOut] = Field(
        description="Each place the document's pages show the value, in the order of its text; "
        "none for a document whose pages' words Lekto has not kept."
    )

    @classmethod
    def of(cls, place: Place) -> "PlaceOut":
        excerpt = place.excerpt
        return cls(
            document_id=place.document,
            title=place.title,
            date=place.dated,
            role=place.role,
            excerpt=None
            if excerpt is None
            else ExcerptOut(before=excerpt.before, match=excerpt.match, after=excerpt.after),
            occurrences=[OccurrenceOut.of(item) for item in place.occurrences],
        )


class PlacesOut(BaseModel):
    places: list[PlaceOut] = Field(description="The newest documents first, at most five.")


class OpenDetailOut(BaseModel):
    identifier: OpenIdentifierOut
    places: list[PlaceOut] = Field(description="Where it stands in its newest documents (5).")

    @classmethod
    def of(cls, detail: OpenDetail, refs: RefCipher) -> "OpenDetailOut":
        return cls(
            identifier=OpenIdentifierOut.of(detail.item, detail.names, detail.persons, refs),
            places=[PlaceOut.of(place) for place in detail.places],
        )


class OpenSearchIn(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [{"q": "2004 7718"}]})

    q: str = Field(
        min_length=1,
        max_length=200,
        description="Words in the value (with or without spaces), as written or in a contact's "
        "name.",
    )


class OpenDecisionIn(BaseModel):
    kind: IdentifierKind
    value: str = Field(description="Normalised, as the list gives it.")
    action: OpenAction = Field(
        description="`confirm`: enter it at the contact by hand, or a person's suggestion in "
        "their profile; `reject`: training does not learn it again, and a learned one no "
        "longer counts; a person's suggestion is noted as declined in their profile. A "
        "person's suggestion needs a session."
    )
    contact_id: UUID | None = Field(
        default=None,
        description="Where; without one, the learned one's contact or the one contact its "
        "documents name (to confirm one whose documents name several, give it).",
    )

    def decision(self) -> OpenDecision:
        return OpenDecision(
            kind=self.kind,
            value=self.value,
            action=self.action,
            contact=None if self.contact_id is None else ContactId(self.contact_id),
        )


class OpenDecisionsIn(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "decisions": [
                        {"kind": "customer_number", "value": "20047718", "action": "confirm"},
                        {"kind": "iban", "value": "DE02120300000000202051", "action": "reject"},
                    ]
                }
            ]
        }
    )

    decisions: Annotated[list[OpenDecisionIn], Field(min_length=1, max_length=MAX_DECISIONS)]


class OutcomeOut(BaseModel):
    kind: IdentifierKind
    value: str
    done: bool
    reason: ReasonOut | None = Field(description="Why it was not done.")

    @classmethod
    def of(cls, outcome: DecisionOutcome) -> "OutcomeOut":
        error = outcome.error
        return cls(
            kind=outcome.kind,
            value=outcome.value,
            done=error is None,
            reason=None if error is None else ReasonOut.of(error),
        )
