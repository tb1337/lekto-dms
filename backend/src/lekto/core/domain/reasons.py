"""Why a check came out as it did, or a rule's action did not act: a code with parameters
(issue #83). Clients translate the code (the web UI with its messages); the English text stays
for the API, the processing log and the language model.

Every code has an English template (`TEMPLATES`) that names its parameters as `{name}`; a
parameter may name its kind after a colon (`KINDS`), which says how it is written: `{names:or}`
a list of names, quoted and joined by "or", `{date:date}` a day in ISO 8601, `{share:percent}`
a fraction as a percentage, `{value:value}` a field's value as a reason shows it (yes or no,
none, or the text). A parameter without a kind is text. `Reason.text` renders the template;
`catalog` lists the codes with their parameters and kinds for the clients (the OpenAPI
document).

A reason may be about a custom field (`subject`, its name: "'Amount': the amount does not
appear in the text"), come from a rule (`rule`, its name), or, among a node's reasons, be about
one of the built-in check fields (`field`: "contact: no contact recognised"). `TEXT` is a
reason as written: by a person (a review a rule forces, a migration plan's), or stored before
reasons had codes.
"""

import json
import string
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Self

from lekto.core.domain.errors import ValidationError
from lekto.core.domain.json_value import JsonObject, JsonValue, as_object, as_text


class ReasonCode(StrEnum):
    TEXT = "text"
    ERROR = "error"
    # contact, document type, topic (the judge)
    SIGNALS_DISAGREE = "signals_disagree"
    ONLY_SUGGESTED = "only_suggested"
    ONE_SIGNAL_ONLY = "one_signal_only"
    ONLY_IDENTIFIER = "only_identifier"
    CONTACT_IS_RECIPIENT = "contact_is_recipient"
    CONTACT_IDENTIFIERS_SEVERAL = "contact_identifiers_several"
    CONTACT_NEW_PROPOSED = "contact_new_proposed"
    CONTACT_NONE = "contact_none"
    CONTACT_NONE_NO_MODEL = "contact_none_no_model"
    CONTACT_NOT_IN_TEXT = "contact_not_in_text"
    SENDER_NOT_A_CONTACT = "sender_not_a_contact"
    SENDER_MATCHES_SEVERAL = "sender_matches_several"
    SENDER_ONLY_SIMILAR = "sender_only_similar"
    TYPE_NEW_PROPOSED = "type_new_proposed"
    TYPE_NONE = "type_none"
    TOPIC_WITHOUT_CONTACT = "topic_without_contact"
    TOPIC_NONE = "topic_none"
    TOPIC_CONTACT_SUGGESTED = "topic_contact_suggested"
    # space (the judge)
    SPACE_CHOSEN_BY_PERSON = "space_chosen_by_person"
    SPACE_NAMED_UNSEEN = "space_named_unseen"
    SPACE_STAYS_FOR_NAMED = "space_stays_for_named"
    SPACE_SHOWS_MORE = "space_shows_more"
    SPACE_HAND_OVER = "space_hand_over"
    SPACE_UPLOADER_UNSEEN = "space_uploader_unseen"
    SPACE_OTHER = "space_other"
    SPACES_DISAGREE = "spaces_disagree"
    # dates, periods and field values (the judge and the fields node)
    DATE_NONE = "date_none"
    DATE_NONE_FROM_MODEL = "date_none_from_model"
    NOT_A_DATE = "not_a_date"
    DATE_IMPLAUSIBLE = "date_implausible"
    SAME_AS_DOCUMENT_DATE = "same_as_document_date"
    NOT_A_PERIOD = "not_a_period"
    PERIOD_IMPLAUSIBLE = "period_implausible"
    PERIOD_NO_YEAR = "period_no_year"
    SAME_DAY_AS_DOCUMENT_DATE = "same_day_as_document_date"
    FIELD_SET_BY_HAND = "field_set_by_hand"
    FIELD_BY_HAND_MISSING = "field_by_hand_missing"
    FIELD_NOT_FOUND = "field_not_found"
    FIELD_NOT_READ_NO_MODEL = "field_not_read_no_model"
    VALUE_INVALID = "value_invalid"
    QUOTE_NOT_IN_TEXT = "quote_not_in_text"
    QUOTE_MISSING = "quote_missing"
    QUOTE_WITHOUT_VALUE = "quote_without_value"
    QUOTE_TOO_SHORT = "quote_too_short"
    DATE_NOT_IN_TEXT = "date_not_in_text"
    PERIOD_NOT_IN_TEXT = "period_not_in_text"
    AMOUNT_NOT_IN_TEXT = "amount_not_in_text"
    CURRENCY_NOT_IN_TEXT = "currency_not_in_text"
    NUMBER_NOT_IN_TEXT = "number_not_in_text"
    LINK_NOT_IN_TEXT = "link_not_in_text"
    TEXT_NOT_IN_TEXT = "text_not_in_text"
    VALUE_READ_UNSURE = "value_read_unsure"
    PAGE_POORLY_READ = "page_poorly_read"
    PAGE_POORLY_READ_CONTENT = "page_poorly_read_content"
    SURROUNDINGS_POORLY_READ = "surroundings_poorly_read"
    # metadata taken over from another system
    SOURCE_LACKS_CONTACT = "source_lacks_contact"
    SOURCE_LACKS_DOCUMENT_TYPE = "source_lacks_document_type"
    SOURCE_LACKS_DOCUMENT_DATE = "source_lacks_document_date"
    # rules
    FIELD_DOES_NOT_APPLY = "field_does_not_apply"
    FIELD_GONE = "field_gone"
    CONTACT_GONE = "contact_gone"
    DOCUMENT_TYPE_GONE = "document_type_gone"
    TOPIC_GONE = "topic_gone"
    TAG_GONE = "tag_gone"
    SPACE_GONE = "space_gone"
    TAG_IS_GROUP = "tag_is_group"
    RULE_OTHER_SPACE = "rule_other_space"
    SPACE_NO_RIGHT_ANY_MORE = "space_no_right_any_more"
    SPACE_NO_RIGHT = "space_no_right"
    SPACE_WIDENS_UNCONFIRMED = "space_widens_unconfirmed"
    SPACE_WIDENS_NEEDS_CONFIRMED = "space_widens_needs_confirmed"
    REVIEW_ON_ARRIVAL_ONLY = "review_on_arrival_only"
    REVIEW_CONFIRMED = "review_confirmed"
    RULES_DISAGREE = "rules_disagree"
    VALUE_OTHER_NOT_ACCEPTED = "value_other_not_accepted"
    PERSON_DECIDED_FIELD = "person_decided_field"
    RULE_VALUE_ON_UNCONFIRMED = "rule_value_on_unconfirmed"
    MODEL_VALUE_OTHER = "model_value_other"
    RULES_VALUE_ON_UNCONFIRMED = "rules_value_on_unconfirmed"
    RULES_MODEL_VALUE_OTHER = "rules_model_value_other"
    TOPIC_PERSON_CHOSE = "topic_person_chose"
    TOPIC_NO_CONTACT = "topic_no_contact"
    TOPIC_NOT_ENABLED = "topic_not_enabled"
    TAG_ADDED_AND_REMOVED = "tag_added_and_removed"
    TAG_REMOVED_BY_PERSON = "tag_removed_by_person"
    TAG_SET_BY_PERSON = "tag_set_by_person"
    TAG_ABOVE_KEPT = "tag_above_kept"
    TITLE_EMPTY = "title_empty"
    TITLE_YIELDS = "title_yields"
    VALUE_EMPTY = "value_empty"
    TEMPLATE_MISSING_VALUE = "template_missing_value"
    # nodes: failures, notes, abstaining signals
    NODE_ATTEMPTS_EXHAUSTED = "node_attempts_exhausted"
    NODE_CRASHED = "node_crashed"
    FILE_NOT_PDF_OR_IMAGE = "file_not_pdf_or_image"
    FILE_DAMAGED = "file_damaged"
    FILE_NOT_PROCESSABLE = "file_not_processable"
    PDF_ENCRYPTED = "pdf_encrypted"
    PDF_UNREADABLE = "pdf_unreadable"
    PDF_UNREADABLE_DETAIL = "pdf_unreadable_detail"
    IMAGE_UNREADABLE = "image_unreadable"
    IMAGE_UNREADABLE_DETAIL = "image_unreadable_detail"
    DOCUMENT_NO_PAGES = "document_no_pages"
    OCR_FAILED = "ocr_failed"
    TEXT_UNREADABLE = "text_unreadable"
    SIGNATURE_DROPPED = "signature_dropped"
    COLOURS_CONVERTED = "colours_converted"
    NOT_PDFA = "not_pdfa"
    ARCHIVE_NOT_PDFA = "archive_not_pdfa"
    VISION_READ = "vision_read"
    VISION_NOT_CONFIGURED = "vision_not_configured"
    NO_TEXT = "no_text"
    ANSWER_UNFIT = "answer_unfit"
    NOTHING_RECOGNISED = "nothing_recognised"
    MASTER_DATA_CHANGED = "master_data_changed"
    METADATA_UNFIT = "metadata_unfit"
    TAKEN_OVER = "taken_over"
    SPACE_CHANGED_MEANWHILE = "space_changed_meanwhile"
    RULES_BACK_AND_FORTH = "rules_back_and_forth"
    RULES_CHANGE_UNFIT = "rules_change_unfit"
    SIGNAL_DID_NOT_RUN = "signal_did_not_run"
    NO_LANGUAGE_MODEL = "no_language_model"
    NO_DOCUMENT_TEXT = "no_document_text"
    NO_CLASSIFIER = "no_classifier"
    CLASSIFIER_UNUSABLE = "classifier_unusable"
    CLASSIFIER_UNTRAINED = "classifier_untrained"
    NEIGHBOURS_OFF = "neighbours_off"
    NO_EMBEDDING_INDEX = "no_embedding_index"
    TEXT_NOT_EMBEDDED = "text_not_embedded"
    VECTOR_MISFIT = "vector_misfit"
    NO_UPLOADER = "no_uploader"
    INDEX_UNAVAILABLE = "index_unavailable"
    NO_SIMILAR = "no_similar"


TEMPLATES: Mapping[ReasonCode, str] = {
    ReasonCode.TEXT: "{text}",
    ReasonCode.ERROR: "{detail}",
    ReasonCode.SIGNALS_DISAGREE: "the signals disagree: {names:or}",
    ReasonCode.ONLY_SUGGESTED: "'{name}' is only suggested: no signal is sure of it",
    ReasonCode.ONE_SIGNAL_ONLY: "only one signal names '{name}'",
    ReasonCode.ONLY_IDENTIFIER: "only an identifier points to '{name}'",
    ReasonCode.CONTACT_IS_RECIPIENT: "'{contact}' is the recipient, not the sender",
    ReasonCode.CONTACT_IDENTIFIERS_SEVERAL: "identifiers of several contacts stand in the text",
    ReasonCode.CONTACT_NEW_PROPOSED: "no contact matches '{sender}'; a new contact is proposed",
    ReasonCode.CONTACT_NONE: "no contact recognised",
    ReasonCode.CONTACT_NONE_NO_MODEL: "no contact recognised (the language model did not answer)",
    ReasonCode.CONTACT_NOT_IN_TEXT: "the contact '{contact}' does not appear in the text",
    ReasonCode.SENDER_NOT_A_CONTACT: (
        "'{sender}' is no contact, and only other signals point to '{contact}'"
    ),
    ReasonCode.SENDER_MATCHES_SEVERAL: "'{sender}' matches several contacts",
    ReasonCode.SENDER_ONLY_SIMILAR: "'{sender}' is only similar to the contact '{contact}'",
    ReasonCode.TYPE_NEW_PROPOSED: "no document type fits; a new type '{type}' is proposed",
    ReasonCode.TYPE_NONE: "no document type recognised",
    ReasonCode.TOPIC_WITHOUT_CONTACT: "no contact: a topic is one of a contact's",
    ReasonCode.TOPIC_NONE: "no topic of '{contact}' recognised",
    ReasonCode.TOPIC_CONTACT_SUGGESTED: "the contact '{contact}' is only suggested",
    ReasonCode.SPACE_CHOSEN_BY_PERSON: "a person chose the space",
    ReasonCode.SPACE_NAMED_UNSEEN: "names someone who would not see it there",
    ReasonCode.SPACE_STAYS_FOR_NAMED: (
        "stays: the space the signals name leaves out someone it names"
    ),
    ReasonCode.SPACE_SHOWS_MORE: "suggests another space, which shows it to more people",
    ReasonCode.SPACE_HAND_OVER: "suggests handing it over into another user's personal space",
    ReasonCode.SPACE_UPLOADER_UNSEEN: "suggests a space its uploader does not see",
    ReasonCode.SPACE_OTHER: "suggests another space",
    ReasonCode.SPACES_DISAGREE: "the signals name different spaces",
    ReasonCode.DATE_NONE: "no date recognised",
    ReasonCode.DATE_NONE_FROM_MODEL: (
        "no date recognised: the language model gave none ({why:reason})"
    ),
    ReasonCode.NOT_A_DATE: "'{value}' is not a date",
    ReasonCode.DATE_IMPLAUSIBLE: "{date:date} is not plausible",
    ReasonCode.SAME_AS_DOCUMENT_DATE: "the same date as the document date",
    ReasonCode.NOT_A_PERIOD: "'{value}' is not a period",
    ReasonCode.PERIOD_IMPLAUSIBLE: "{period} is not plausible",
    ReasonCode.PERIOD_NO_YEAR: "no year given; the year of the document date is assumed",
    ReasonCode.SAME_DAY_AS_DOCUMENT_DATE: "the same day as the document date",
    ReasonCode.FIELD_SET_BY_HAND: "'{field}' is set by hand",
    ReasonCode.FIELD_BY_HAND_MISSING: "'{field}' is set by hand and has no value yet",
    ReasonCode.FIELD_NOT_FOUND: "'{field}' was not found",
    ReasonCode.FIELD_NOT_READ_NO_MODEL: "'{field}' was not read: no language model is configured",
    ReasonCode.VALUE_INVALID: "'{value}' is not a valid value of '{field}' ({type})",
    ReasonCode.QUOTE_NOT_IN_TEXT: "the quoted passage does not appear in the text",
    ReasonCode.QUOTE_MISSING: "no quoted passage",
    ReasonCode.QUOTE_WITHOUT_VALUE: "the quoted passage does not show the value",
    ReasonCode.QUOTE_TOO_SHORT: "the quoted passage is too short to show the value",
    ReasonCode.DATE_NOT_IN_TEXT: "the date does not appear in the text",
    ReasonCode.PERIOD_NOT_IN_TEXT: "the period does not appear in the text",
    ReasonCode.AMOUNT_NOT_IN_TEXT: "the amount does not appear in the text",
    ReasonCode.CURRENCY_NOT_IN_TEXT: "the currency {currency} does not appear in the text",
    ReasonCode.NUMBER_NOT_IN_TEXT: "the number does not appear in the text",
    ReasonCode.LINK_NOT_IN_TEXT: "the link does not appear in the text",
    ReasonCode.TEXT_NOT_IN_TEXT: "the text does not appear in the text",
    ReasonCode.VALUE_READ_UNSURE: "the value was read unsure ({unsure:number}%)",
    ReasonCode.PAGE_POORLY_READ: (
        "page {page:number} was poorly read ({share:percent} of its words unsure)"
    ),
    ReasonCode.PAGE_POORLY_READ_CONTENT: (
        "page {page:number} was poorly read ({share:percent} of its content words unsure)"
    ),
    ReasonCode.SURROUNDINGS_POORLY_READ: (
        "the text around the value was poorly read ({unsure:number} of {words:number} content "
        "words unsure)"
    ),
    ReasonCode.SOURCE_LACKS_CONTACT: "no contact in the source system",
    ReasonCode.SOURCE_LACKS_DOCUMENT_TYPE: "no document type in the source system",
    ReasonCode.SOURCE_LACKS_DOCUMENT_DATE: "no document date in the source system",
    ReasonCode.FIELD_DOES_NOT_APPLY: "'{field}' does not apply",
    ReasonCode.FIELD_GONE: "the field no longer exists",
    ReasonCode.CONTACT_GONE: "contact {id} no longer exists",
    ReasonCode.DOCUMENT_TYPE_GONE: "document_type {id} no longer exists",
    ReasonCode.TOPIC_GONE: "topic {id} no longer exists",
    ReasonCode.TAG_GONE: "tag {id} no longer exists",
    ReasonCode.SPACE_GONE: "space {id} no longer exists",
    ReasonCode.TAG_IS_GROUP: "tag '{tag}' is a group, not a document tag",
    ReasonCode.RULE_OTHER_SPACE: "the rule belongs to another space",
    ReasonCode.SPACE_NO_RIGHT_ANY_MORE: "no right to file into space '{space}' (any more)",
    ReasonCode.SPACE_NO_RIGHT: "you have no right to file into space '{space}'",
    ReasonCode.SPACE_WIDENS_UNCONFIRMED: (
        "files into the space '{space}', which more people see, with an unconfirmed "
        "{fields:fields}; not accepted"
    ),
    ReasonCode.SPACE_WIDENS_NEEDS_CONFIRMED: (
        "files into the space '{space}', which more people see, only with a confirmed "
        "{fields:fields}"
    ),
    ReasonCode.REVIEW_ON_ARRIVAL_ONLY: "reviews are forced on arrival only",
    ReasonCode.REVIEW_CONFIRMED: "a person confirmed the review",
    ReasonCode.RULES_DISAGREE: "rules set different values ({values:rule_values})",
    ReasonCode.VALUE_OTHER_NOT_ACCEPTED: (
        "the document has another value ({value:value}); not accepted"
    ),
    ReasonCode.PERSON_DECIDED_FIELD: "a person decided this field",
    ReasonCode.RULE_VALUE_ON_UNCONFIRMED: (
        "a rule set another value on unconfirmed values ({value:value})"
    ),
    ReasonCode.MODEL_VALUE_OTHER: "the model set another value ({value:value})",
    ReasonCode.RULES_VALUE_ON_UNCONFIRMED: (
        "rules: a rule set another value on unconfirmed values ({value:value})"
    ),
    ReasonCode.RULES_MODEL_VALUE_OTHER: "rules: the model set another value ({value:value})",
    ReasonCode.TOPIC_PERSON_CHOSE: "a person chose the topic '{topic}', which it does not enable",
    ReasonCode.TOPIC_NO_CONTACT: "the document has no contact",
    ReasonCode.TOPIC_NOT_ENABLED: "its contact does not enable the topic '{topic}'",
    ReasonCode.TAG_ADDED_AND_REMOVED: "tag '{tag}' is added and removed by rules",
    ReasonCode.TAG_REMOVED_BY_PERSON: "a person removed tag '{tag}'",
    ReasonCode.TAG_SET_BY_PERSON: "a person set tag '{tag}'",
    ReasonCode.TAG_ABOVE_KEPT: "tag '{tag}' is above a tag the document has",
    ReasonCode.TITLE_EMPTY: "the title would be empty",
    ReasonCode.TITLE_YIELDS: "another rule sets the title",
    ReasonCode.VALUE_EMPTY: "the value would be empty",
    ReasonCode.TEMPLATE_MISSING_VALUE: "{path} has no value",
    ReasonCode.NODE_ATTEMPTS_EXHAUSTED: (
        "node did not finish in {attempts:number} attempts (the worker died or ran out of time "
        "each time)"
    ),
    ReasonCode.NODE_CRASHED: "{error}: {detail}",
    ReasonCode.FILE_NOT_PDF_OR_IMAGE: "the file is no PDF and no image",
    ReasonCode.FILE_DAMAGED: "the file is damaged or not a valid document",
    ReasonCode.FILE_NOT_PROCESSABLE: "the file cannot be processed",
    ReasonCode.PDF_ENCRYPTED: "the PDF is encrypted",
    ReasonCode.PDF_UNREADABLE: "the PDF cannot be read",
    ReasonCode.PDF_UNREADABLE_DETAIL: "the PDF cannot be read: {detail}",
    ReasonCode.IMAGE_UNREADABLE: "the image cannot be read",
    ReasonCode.IMAGE_UNREADABLE_DETAIL: "the image cannot be read: {detail}",
    ReasonCode.DOCUMENT_NO_PAGES: "the document has no pages",
    ReasonCode.OCR_FAILED: "{problem:reason}: {detail}",
    ReasonCode.TEXT_UNREADABLE: (
        "the text in the PDF cannot be read (a font without a character map); every page was "
        "recognised from its image"
    ),
    ReasonCode.SIGNATURE_DROPPED: (
        "the original is digitally signed; the archive does not carry the signature (the "
        "original is unchanged)"
    ),
    ReasonCode.COLOURS_CONVERTED: (
        "the colours were converted to RGB to make the archive PDF/A (the original is unchanged)"
    ),
    ReasonCode.NOT_PDFA: "not PDF/A: {detail}",
    ReasonCode.ARCHIVE_NOT_PDFA: "the archive could not be made PDF/A",
    ReasonCode.VISION_READ: (
        "every page was read by the vision language model {model} ({endpoint})"
    ),
    ReasonCode.VISION_NOT_CONFIGURED: (
        "a person asked for the vision language model, but none is configured"
    ),
    ReasonCode.NO_TEXT: "no text recognised: the pages are blank or hold only pictures",
    ReasonCode.ANSWER_UNFIT: "the model's answer does not fit the schema: {detail}",
    ReasonCode.NOTHING_RECOGNISED: "nothing recognised: no contact, document type or date",
    ReasonCode.MASTER_DATA_CHANGED: (
        "the master data changed during the node; nothing was applied ({detail})"
    ),
    ReasonCode.METADATA_UNFIT: "the metadata of the source system no longer fits: {detail}",
    ReasonCode.TAKEN_OVER: "taken over from the source system",
    ReasonCode.SPACE_CHANGED_MEANWHILE: ("the space the signals chose changed meanwhile; it stays"),
    ReasonCode.RULES_BACK_AND_FORTH: "rules move it back and forth: {spaces:path}",
    ReasonCode.RULES_CHANGE_UNFIT: "the rules' change does not fit: {detail}",
    ReasonCode.SIGNAL_DID_NOT_RUN: "it did not run",
    ReasonCode.NO_LANGUAGE_MODEL: "no language model is configured",
    ReasonCode.NO_DOCUMENT_TEXT: "the document has no text",
    ReasonCode.NO_CLASSIFIER: "no classifier is configured",
    ReasonCode.CLASSIFIER_UNUSABLE: "the classifier cannot be used: {detail}",
    ReasonCode.CLASSIFIER_UNTRAINED: "no model is trained yet",
    ReasonCode.NEIGHBOURS_OFF: "neighbours are turned off",
    ReasonCode.NO_EMBEDDING_INDEX: "there is no search index with embeddings",
    ReasonCode.TEXT_NOT_EMBEDDED: "the text could not be embedded: {detail}",
    ReasonCode.VECTOR_MISFIT: "the text's vector does not fit the index",
    ReasonCode.NO_UPLOADER: "the document has no active uploader to look from",
    ReasonCode.INDEX_UNAVAILABLE: "the search index cannot be asked: {detail}",
    ReasonCode.NO_SIMILAR: "no similar confirmed document",
}

KINDS: Mapping[str, str] = {
    "": "text",
    "number": "number",
    "percent": "percent",
    "date": "date",
    "value": "value",
    "or": "names",
    "fields": "fields",
    "rule_values": "rule_values",
    "path": "path",
    "reason": "reason",
}
"""The kinds a template may give a parameter (after its colon; none: text), by the name the
catalog gives them: `number` a number, `percent` a fraction from 0 to 1, `date` a day in ISO
8601, `value` a field's value as a reason shows it (a string, true or false for yes or no, null
for none), `names` a list of names, `fields` a list of check fields (`contact`, `field:<id>`,
...), `rule_values` a list of `{"rule": name, "value": value}` (what each rule sets), `path`
a list of names one after the other (spaces a document went through), `reason` another reason
(`Reason.to_json`)."""


class _Formatter(string.Formatter):
    def format_field(self, value: object, format_spec: str) -> str:
        match format_spec:
            case "percent":
                return format(value, ".0%")
            case "value":
                return _value(value)
            case "or":
                return " or ".join(f"'{item}'" for item in _items(value))
            case "fields":
                return ", ".join(str(item) for item in _items(value))
            case "rule_values":
                return ", ".join(
                    f"'{item.get('rule')}': {_value(item.get('value'))}"
                    for item in _items(value)
                    if isinstance(item, dict)
                )
            case "path":
                return " → ".join(str(item) for item in _items(value))
            case "reason":
                try:
                    return Reason.from_json(value).text  # type: ignore[arg-type]
                except ValidationError:
                    return str(value)
        return str(value)


def _items(value: object) -> list[object]:
    return list(value) if isinstance(value, list | tuple) else [value]


def _value(value: object) -> str:
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


_FORMATTER = _Formatter()


def _parameters(template: str) -> dict[str, str]:
    """The parameters of `template` with their kinds."""
    found: dict[str, str] = {}
    for _, name, spec, _ in _FORMATTER.parse(template):
        if name is not None:
            found[name] = KINDS[spec or ""]
    return found


PARAMETERS: Mapping[ReasonCode, Mapping[str, str]] = {
    code: _parameters(template) for code, template in TEMPLATES.items()
}


def catalog() -> dict[str, dict[str, str]]:
    """The codes with their parameters and kinds, as the OpenAPI document lists them."""
    return {code.value: dict(PARAMETERS[code]) for code in ReasonCode}


@dataclass(frozen=True)
class Reason:
    """A reason with its code: `params` are exactly the template's parameters; `subject` the
    name of the custom field it is about, `rule` the name of the rule it comes from, `field`
    the built-in check field (`contact`, ...) a node's reason is about."""

    code: ReasonCode
    params: Mapping[str, JsonValue] = field(default_factory=dict)
    subject: str | None = None
    rule: str | None = None
    field: str | None = None

    def __post_init__(self) -> None:
        expected = PARAMETERS[self.code].keys()
        if set(self.params) != set(expected):
            raise ValidationError(
                f"reason {self.code}: parameters {sorted(self.params)}, expected {sorted(expected)}"
            )

    def __hash__(self) -> int:
        params = json.dumps(self.params, sort_keys=True, ensure_ascii=False, default=str)
        return hash((self.code, params, self.subject, self.rule, self.field))

    @property
    def text(self) -> str:
        """In English, as the API and the log give it."""
        text = _FORMATTER.vformat(TEMPLATES[self.code], (), dict(self.params))
        if self.subject is not None:
            text = f"'{self.subject}': {text}"
        if self.rule is not None:
            text = f"rule '{self.rule}': {text}"
        if self.field is not None:
            text = f"{self.field}: {text}"
        return text

    def about(self, subject: str) -> Self:
        return replace(self, subject=subject)

    def by_rule(self, rule: str) -> Self:
        return replace(self, rule=rule)

    def for_field(self, field: str) -> Self:
        return replace(self, field=field)

    def to_json(self) -> JsonObject:
        data: JsonObject = {"code": self.code.value, "params": dict(self.params)}
        if self.subject is not None:
            data["subject"] = self.subject
        if self.rule is not None:
            data["rule"] = self.rule
        if self.field is not None:
            data["field"] = self.field
        return data

    @classmethod
    def from_json(cls, data: JsonValue) -> Self:
        """ValidationError for an unknown code (written by a newer version) or parameters that
        do not fit."""
        found = as_object(data)
        if found is None:
            raise ValidationError(f"invalid reason {data!r}")
        try:
            code = ReasonCode(str(found.get("code")))
        except ValueError:
            raise ValidationError(f"unknown reason code {found.get('code')!r}") from None
        return cls(
            code,
            dict(as_object(found.get("params")) or {}),
            subject=as_text(found.get("subject")),
            rule=as_text(found.get("rule")),
            field=as_text(found.get("field")),
        )


def because(code: ReasonCode, /, **params: JsonValue) -> Reason:
    """The reason `code` with `params`."""
    return Reason(code, params)


def written(text: str) -> Reason:
    """A reason as written (`TEXT`)."""
    return Reason(ReasonCode.TEXT, {"text": text})


def text_of(reasons: Iterable[Reason]) -> str | None:
    """The reasons in English, joined by "; "; None without any."""
    return "; ".join(reason.text for reason in reasons) or None


def reasons_to_json(reasons: Iterable[Reason]) -> list[JsonValue]:
    return [reason.to_json() for reason in reasons]


def reasons_from_json(data: JsonValue, text: str | None) -> tuple[Reason, ...]:
    """The reasons stored next to their English `text`: as written where there are none (stored
    before reasons had codes) or they cannot be read (a code of a newer version)."""
    if isinstance(data, list):
        try:
            return tuple(Reason.from_json(item) for item in data)
        except ValidationError:
            pass
    return () if not text else (written(text),)
