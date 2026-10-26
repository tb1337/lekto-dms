"""The values a template sees: plain data, nested in mappings and lists. A value a document
does not have is left out, not given as None: the template tests it with `{% if %}` or
`| default`, and writing it is a missing value (`MissingValueError`)."""

import dataclasses
import re
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from datetime import date
from decimal import Decimal

from lekto.core.domain.codes import Code, giro_code
from lekto.core.domain.document_facts import (
    DocumentFact,
    FactOrigin,
    FactRole,
    FactState,
    person_only,
    reading_order,
)
from lekto.core.domain.documents import Document
from lekto.core.domain.fields import FieldDefinition, FieldValue, Money, Url
from lekto.core.domain.json_value import JsonValue
from lekto.core.domain.periods import Period
from lekto.core.domain.sorting import sort_key

type TemplateValue = (
    str
    | int
    | bool
    | Decimal
    | date
    | Money
    | Period
    | Sequence[TemplateValue]
    | Mapping[str, TemplateValue]
)

type Render = Callable[[str, Mapping[str, TemplateValue]], str]
"""A template renderer's `render` (the port `TemplateRenderer`), as the rule planner takes it."""


@dataclasses.dataclass(frozen=True, kw_only=True)
class _Given:
    """What a template can use, one attribute per name; `field.<key>` names a field
    (`FieldDefinition.key`). None: the document does not have it."""

    title: TemplateValue | None
    filename: TemplateValue | None
    original_filename: TemplateValue | None
    contact: TemplateValue | None
    document_type: TemplateValue | None
    document_date: TemplateValue | None
    added: TemplateValue | None
    tags: TemplateValue | None
    topic: TemplateValue | None
    contact_groups: TemplateValue | None
    document_type_groups: TemplateValue | None
    space: TemplateValue | None
    uploaded_by: TemplateValue | None
    channel: TemplateValue | None
    pages: TemplateValue | None
    field: TemplateValue | None
    facts: TemplateValue | None
    fact_list: TemplateValue | None


NAMES = tuple(item.name for item in dataclasses.fields(_Given))
FIELD = "field"
FACTS = "facts"
FACT_LIST = "fact_list"
EVENT = "event"
RULE = "rule"
TASK = "task"
STEPS = "steps"
WEBHOOK_NAMES = (*NAMES, EVENT, "document_id", "lane", "link", RULE, TASK, STEPS)
"""What the template of a webhook's body sees besides a rule's values: the event (`event.type`,
`event.id`, `event.occurred_at`), the document's id, lane and link into the web UI, the rule
that sends or asks (`rule.id`, `rule.name`; only then), and for a task (`domain.tasks`) the task
(`task.id`, `task.callback`, `task.token`, `task.deadline`) and what the rule's steps before
brought (`steps.<name>`)."""


def template_values(
    document: Document,
    *,
    contact: str | None,
    document_type: str | None,
    space: str | None,
    uploaded_by: str | None,
    tags: Iterable[str],
    document_date: date | None,
    fields: Iterable[tuple[FieldDefinition, FieldValue | None]],
    contact_groups: Iterable[str] = (),
    document_type_groups: Iterable[str] = (),
    topic: str | None = None,
    kept_facts: Iterable[DocumentFact] = (),
    codes: Iterable[Code] = (),
) -> dict[str, TemplateValue]:
    """The values of `document` as a template sees them, the names already resolved (as rules
    leave them); what the document does not have is left out. `tags`: those set (not their
    ancestors); `topic`: its name (not its path); `contact_groups`, `document_type_groups`: the
    groups the contact and the type are in (not their ancestors). Lists are sorted by name.
    The facts (`kept_facts`, `codes`) as `facts` and `fact_list` (`facts_values`)."""

    def ordered(items: Iterable[str]) -> list[TemplateValue]:
        return [*sorted(items, key=sort_key)]

    given = _Given(
        title=document.title,
        filename=document.file_title,
        original_filename=document.original_filename,
        contact=contact,
        document_type=document_type,
        document_date=document_date,
        added=document.created_at.date(),
        tags=ordered(tags),
        topic=topic,
        contact_groups=ordered(contact_groups),
        document_type_groups=ordered(document_type_groups),
        space=space,
        uploaded_by=uploaded_by,
        channel=document.channel.value,
        pages=document.page_count,
        field={definition.key: _field(value) for definition, value in fields if value is not None},
        **facts_values(kept_facts, codes),
    )
    return {name: value for name in NAMES if (value := getattr(given, name)) is not None}


_ORIGINS = (FactOrigin.PERSON, FactOrigin.MODEL, FactOrigin.PATTERN, FactOrigin.CODE)


def facts_values(
    kept_facts: Iterable[DocumentFact], codes: Iterable[Code] = ()
) -> dict[str, TemplateValue | None]:
    """What templates see of the document's facts (`fakten.md`, decision 13), none a person
    rejected and none of a kind a person's alone (a rule's template writes into what others
    read):

    - `facts.<kind>`: the document's own value of the kind (no reference), the first as the
      text reads, as the text writes it (`{{ facts.invoice_number }}`);
    - `facts.refers.<kind>`: the first value of the kind that refers to another document;
    - `facts.girocode`: the first GiroCode on the pages, `name`, `iban`, `bic`, `amount`,
      `purpose` (`{{ facts.girocode.amount }}`);
    - `fact_list`: every fact with `kind`, `value` (normalised), `written`, `role` and
      `origin` (a person, the model, the patterns or a code, the first of these it has).

    None where there is nothing."""
    shown = sorted(
        (
            fact
            for fact in kept_facts
            if fact.state is not FactState.REJECTED and not person_only(fact.kind)
        ),
        key=reading_order,
    )
    own: dict[str, TemplateValue] = {}
    refers: dict[str, TemplateValue] = {}
    for fact in shown:
        target = refers if fact.role is FactRole.REFERS else own
        target.setdefault(fact.kind.value, fact.written or fact.value)
    facts: dict[str, TemplateValue] = dict(own)
    if refers:
        facts["refers"] = refers
    giro = next((found for code in codes if (found := giro_code(code.text)) is not None), None)
    if giro is not None:
        payment: dict[str, TemplateValue] = {"name": giro.name, "iban": giro.iban}
        for name, value in (("bic", giro.bic), ("amount", giro.amount), ("purpose", giro.purpose)):
            if value is not None:
                payment[name] = value
        facts["girocode"] = payment
    listed: list[TemplateValue] = [
        {
            "kind": fact.kind.value,
            "value": fact.value,
            "written": fact.written or fact.value,
            "role": fact.role.value,
            "origin": next(origin for origin in _ORIGINS if origin in fact.origins).value,
        }
        for fact in shown
    ]
    return {"facts": facts or None, "fact_list": listed or None}


def _field(value: FieldValue) -> TemplateValue:
    return value.value if isinstance(value, Url) else value


def writing_templates(values: Mapping[str, TemplateValue]) -> dict[str, str]:
    """For each of the `values` (`template_values`), the template that writes it:
    `{{ contact }}`, `{{ field.la_brutto }}`, a list joined (`{{ tags | join: ', ' }}`)."""
    paths: list[tuple[str, TemplateValue]] = []
    for name, value in values.items():
        if name == FIELD and isinstance(value, Mapping):
            paths.extend((f"{FIELD}.{key}", item) for key, item in value.items())
        elif name == FACTS and isinstance(value, Mapping):
            paths.extend(_flat(FACTS, value))
        elif name == FACT_LIST:
            continue  # a list of facts: the template filters it (`where`, `map`)
        else:
            paths.append((name, value))
    return {
        path: (
            f"{{{{ {path} | join: ', ' }}}}"
            if isinstance(value, Sequence) and not isinstance(value, str)
            else f"{{{{ {path} }}}}"
        )
        for path, value in paths
    }


def _flat(prefix: str, values: Mapping[str, TemplateValue]) -> list[tuple[str, TemplateValue]]:
    """The paths to the values of nested mappings (`facts.refers.invoice_number`)."""
    paths: list[tuple[str, TemplateValue]] = []
    for key, value in values.items():
        if isinstance(value, Mapping):
            paths.extend(_flat(f"{prefix}.{key}", value))
        else:
            paths.append((f"{prefix}.{key}", value))
    return paths


def unknown_values(
    paths: Iterable[str], field_keys: Collection[str], names: Collection[str] = NAMES
) -> list[str]:
    """The paths of a template (`TemplateRenderer.check`) that name nothing a template can
    use: an unknown name (not among `names`), or a field that is not among `field_keys`."""
    unknown: list[str] = []
    for path in sorted(paths):
        name, _, rest = path.partition(".")
        known_field = name != FIELD or rest.partition(".")[0] in field_keys
        if name not in names or not known_field:
            unknown.append(path)
    return unknown


def rename_field_key(template: str, old: str, new: str) -> str:
    """`template` with `field.<old>` written `field.<new>` (also `field["<old>"]`); a key that
    only begins the same (`field.<old>_x`) stays."""
    pattern = re.compile(
        rf"(?<![\w.]){FIELD}(?:\.{re.escape(old)}(?!\w)|\[(['\"]){re.escape(old)}\1\])"
    )
    return pattern.sub(f"{FIELD}.{new}", template)


def uses_field(paths: Iterable[str], key: str) -> bool:
    """Whether the paths a template uses (`TemplateRenderer.check`) name the field `key`."""
    return any(path == f"{FIELD}.{key}" or path.startswith(f"{FIELD}.{key}.") for path in paths)


def json_value(value: JsonValue) -> TemplateValue | None:
    """A JSON value from outside (an answer to a task) as templates see it: a fraction as a
    decimal number, objects and lists with their items; null is missing (left out)."""
    match value:
        case None:
            return None
        case bool() | int() | str():
            return value
        case float():
            return Decimal(repr(value))
        case list():
            return [item for entry in value if (item := json_value(entry)) is not None]
        case dict():
            return {
                key: item for key, entry in value.items() if (item := json_value(entry)) is not None
            }
    raise TypeError(f"not a JSON value: {value!r}")
