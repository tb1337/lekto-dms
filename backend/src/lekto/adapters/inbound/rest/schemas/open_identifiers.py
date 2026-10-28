"""The open identifiers (`/identifiers/open`)."""

from collections.abc import Mapping
from datetime import date
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from lekto.adapters.inbound.schemas import ReasonOut
from lekto.core.domain.document_facts import FactRole
from lekto.core.domain.identifiers import IdentifierKind
from lekto.core.domain.ids import ContactId, UserId
from lekto.core.domain.open_identifiers import (
    OpenIdentifier,
    OpenSource,
    Recommendation,
    Recommended,
)
from lekto.core.services.open_identifiers import (
    DecisionOutcome,
    OpenAction,
    OpenDecision,
    OpenDetail,
    OpenPage,
    Place,
)

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
    ) -> "OpenIdentifierOut":
        return cls(
            kind=item.kind,
            value=item.value,
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
        "(of every source and kind, without `q`)."
    )

    @classmethod
    def of(cls, page: OpenPage) -> "OpenPageOut":
        return cls(
            items=[OpenIdentifierOut.of(item, page.names, page.persons) for item in page.items],
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


class PlaceOut(BaseModel):
    document_id: UUID
    title: str
    date: date
    role: FactRole
    excerpt: ExcerptOut | None = Field(
        description="The text around it, where the document has text and the fact a position."
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
        )


class OpenDetailOut(BaseModel):
    identifier: OpenIdentifierOut
    places: list[PlaceOut] = Field(description="Where it stands in its newest documents (5).")

    @classmethod
    def of(cls, detail: OpenDetail) -> "OpenDetailOut":
        return cls(
            identifier=OpenIdentifierOut.of(detail.item, detail.names, detail.persons),
            places=[PlaceOut.of(place) for place in detail.places],
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
