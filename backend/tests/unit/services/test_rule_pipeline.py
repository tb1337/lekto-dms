"""The rules on arrival: the nodes `apply_rules` and `file`, and confirming in the inbox."""

import json
import logging
from collections import Counter
from decimal import Decimal
from typing import Any

import pytest

from lekto.core.domain.codes import Code, codes_to_json
from lekto.core.domain.document_facts import FactRole
from lekto.core.domain.documents import DocumentChanges
from lekto.core.domain.errors import OpenFieldsError, PermissionDeniedError
from lekto.core.domain.events import DocumentFiled
from lekto.core.domain.fields import FieldType
from lekto.core.domain.identifiers import IdentifierKind
from lekto.core.domain.locations import Box
from lekto.core.domain.master_data import Assignment
from lekto.core.domain.pipeline import (
    PERSON,
    RULES,
    Lane,
    Node,
    Outcome,
    ProcessingStatus,
)
from lekto.core.domain.rule_planner import Mode
from lekto.core.domain.rules import (
    AddTags,
    Condition,
    ConditionField,
    ForceReview,
    Operator,
    SetContact,
    SetDocumentType,
    SetField,
    SetSpace,
    SetTitle,
    Trigger,
)
from lekto.core.domain.spaces import SpaceRole
from lekto.core.services.classification.signals import FactsSignal
from lekto.core.services.fact_decisions import FactAction, FactDecision
from lekto.core.services.objects import codes_key
from lekto.core.services.rules.running import (
    PatternBudget,
    Prepared,
    active_rules,
    prepare,
    provenance,
)
from lekto.core.services.rules.steps import run_rules
from tests.builders import TEMPLATES
from tests.unit.services.rules_support import (
    Classifies,
    Titles,
    add_tags,
    channel_api,
    contact_is,
    definition,
    has_tag,
    incoming_pdf,
    notes,
    reports,
    rule_world,
    text_matches,
)
from tests.unit.services.support import World

CHANGE = (Trigger.CHANGE,)


async def test_rules_act_on_arrival_and_the_log_names_rule_and_version(world: World) -> None:
    r = await rule_world(world)
    owner, stranger = await world.user(), await world.user()
    acme = await r.contact("ACME")
    tax, checked, foreign = await r.tag("tax"), await r.tag("checked"), await r.tag("foreign")
    note = await world.master_data.create_field(r.admin.id, "Note", FieldType.TEXT)
    household = await world.spaces.create(owner.id, "Household")
    rule = await r.personal_rule(owner, definition("Draft", channel_api(), SetTitle("Draft")))
    rule = await r.rules.change(
        owner.id,
        rule.id,
        definition(
            "ACME",
            channel_api(),
            SetContact(acme.id),
            SetTitle("{{ contact }} {{ filename }}"),
            add_tags(tax.id),
            SetField(note.id, "from a rule"),
            SetSpace(household.id),
        ),
    )
    shared = await r.global_rule(definition("Checked", channel_api(), add_tags(checked.id)))
    # Another user's rule never acts on the owner's documents.
    await r.personal_rule(stranger, definition("Foreign", channel_api(), add_tags(foreign.id)))

    document = await r.arrive(owner, filename="Bill 2026.pdf")

    assert document.lane is Lane.GREEN
    assert (document.contact_id, document.title) == (acme.id, "ACME Bill 2026")
    assert document.tag_ids == {tax.id, checked.id}
    assert document.fields == {note.id: "from a rule"}
    assert document.space_id == household.id
    (entry,) = await r.rule_entries(document, RULES)
    assert entry.result.outcome is Outcome.OK
    assert entry.result.input == {
        "trigger": "ingest",
        "rules": [{"id": str(shared.id), "version": 1}, {"id": str(rule.id), "version": 2}],
    }
    by_rule = {report["rule_id"]: report for report in reports(entry.result.output)}
    assert by_rule[str(rule.id)]["version"] == 2
    assert by_rule[str(rule.id)]["name"] == "ACME"
    applied = by_rule[str(rule.id)]["applied"]
    assert isinstance(applied, list)
    assert {item["field"] for item in applied if isinstance(item, dict)} == {
        "contact",
        "title",
        "tags",
        f"field:{note.id}",
        "space",
    }


async def test_conflicting_rules_wait_in_the_inbox_until_the_owner_decides(world: World) -> None:
    r = await rule_world(world)
    owner = await world.user()
    acme, beta = await r.contact("ACME"), await r.contact("Beta")
    await r.personal_rule(owner, definition("A", channel_api(), SetContact(acme.id), priority=200))
    await r.personal_rule(owner, definition("B", channel_api(), SetContact(beta.id)))

    document = await r.arrive(owner)

    assert document.lane is Lane.YELLOW
    assert document.contact_id is None  # priority orders, but never decides
    (item,) = await world.inbox.items(owner.id)
    (open,) = item.open
    assert open.node is Node.APPLY_RULES
    (check,) = open.fields
    assert (check.field, check.suggestion) == ("contact", str(acme.id))
    assert ("contact", "conflict") in notes(
        (await r.rule_entries(document, RULES))[0].result.output
    )

    await r.pipeline().confirm(owner.id, document.id, DocumentChanges(), accept_suggestions=True)
    await world.drain(r.pipeline())

    document = await r.stored(document)
    assert (document.lane, document.contact_id) == (Lane.GREEN, acme.id)
    # The rules ran again on the decided field: still in conflict, but nothing is open.
    again = (await r.rule_entries(document, RULES))[-1]
    assert again.result.outcome is Outcome.OK
    assert notes(again.result.output) == [("contact", "conflict"), ("contact", "conflict")]
    assert again.result.output["fields"] == []


async def test_a_required_field_set_by_hand_waits_for_a_person(world: World) -> None:
    """Issue #52: after the rules, a required field set by hand without a value keeps the
    document yellow; confirming without a value is no decision, with one it files."""
    r = await rule_world(world)
    owner = await world.user()
    asn = await world.master_data.create_field(
        r.admin.id, "ASN", FieldType.NUMBER, required=True, assignment=Assignment.MANUAL
    )

    document = await r.arrive(owner)

    assert document.lane is Lane.YELLOW
    (item,) = await world.inbox.items(owner.id)
    (open,) = item.open
    assert open.node is Node.APPLY_RULES
    (check,) = open.fields
    assert check.reason == "'ASN' is set by hand and has no value yet"
    with pytest.raises(OpenFieldsError, match="ASN"):
        await r.pipeline().confirm(owner.id, document.id, DocumentChanges(fields={asn.id: None}))
    await r.pipeline().confirm(
        owner.id, document.id, DocumentChanges(fields={asn.id: Decimal(4711)})
    )
    await world.drain(r.pipeline())

    document = await r.stored(document)
    assert document.lane is Lane.GREEN
    assert document.fields == {asn.id: Decimal(4711)}


async def test_a_rule_gives_a_field_set_by_hand_its_value(world: World) -> None:
    r = await rule_world(world)
    owner = await world.user()
    asn = await world.master_data.create_field(
        r.admin.id, "ASN", FieldType.TEXT, required=True, assignment=Assignment.MANUAL
    )
    await r.personal_rule(owner, definition("ASN", channel_api(), SetField(asn.id, "A-1")))

    document = await r.arrive(owner)

    assert document.lane is Lane.GREEN
    assert document.fields == {asn.id: "A-1"}


async def test_a_rule_replaces_the_machines_title(world: World) -> None:
    """The title the machine gave is no value the model checked: a rule sets another one
    without the document becoming uncertain."""
    r = await rule_world(world)
    owner = await world.user()
    await r.personal_rule(
        owner, definition("Title", channel_api(), SetTitle("{{ filename }} (rule)"))
    )

    document = await r.arrive(owner, fields=Titles("Stromrechnung März 2026"))
    assert (document.lane, document.title) == (Lane.GREEN, "scan (rule)")


async def test_a_rule_does_not_replace_the_models_value(world: World) -> None:
    r = await rule_world(world)
    owner = await world.user()
    model, rule = await r.contact("Model"), await r.contact("Rule")
    await r.personal_rule(owner, definition("Rule", channel_api(), SetContact(rule.id)))

    document = await r.arrive(owner, classify=Classifies(contact=model.id))

    assert (document.lane, document.contact_id) == (Lane.YELLOW, model.id)
    ((check,),) = [open.fields for open in (await r.documents.review(owner.id, document.id)).open]
    assert check.field == "contact"
    assert check.reason == "rules: the model set another value ('Model')"
    assert check.suggestion == str(rule.id)

    # The owner takes the rule's value; it is not yellow again.
    await r.pipeline().confirm(owner.id, document.id, DocumentChanges(contact_id=rule.id))
    await world.drain(r.pipeline())
    document = await r.stored(document)
    assert (document.lane, document.contact_id) == (Lane.GREEN, rule.id)
    # The confirmation records the model's value the owner corrected.
    (confirmed,) = await r.rule_entries(document, PERSON)
    assert confirmed.result.output["corrected"] == ["contact"]


async def test_a_forced_review_holds_the_document_once(world: World) -> None:
    r = await rule_world(world)
    owner = await world.user()
    await r.personal_rule(owner, definition("Mine", channel_api(), ForceReview("look at it")))
    await r.global_rule(definition("Everyone's", channel_api(), ForceReview("audit")))

    document = await r.arrive(owner)

    assert document.lane is Lane.YELLOW
    (entry,) = await r.rule_entries(document, RULES)
    assert entry.result.reason is not None
    assert "rule 'Mine': look at it" in entry.result.reason
    assert "rule 'Everyone's': audit" in entry.result.reason

    await r.pipeline().confirm(owner.id, document.id, DocumentChanges())
    await world.drain(r.pipeline())

    document = await r.stored(document)
    assert document.lane is Lane.GREEN
    again = (await r.rule_entries(document, RULES))[-1]
    assert notes(again.result.output) == [("review", "overruled"), ("review", "overruled")]
    confirmed = [entry for entry in await r.log(document) if entry.result.model_version == PERSON]
    assert [entry.node for entry in confirmed] == [Node.APPLY_RULES]


async def test_unconfirmed_model_values_do_not_file_into_a_space_others_see(
    world: World,
) -> None:
    r = await rule_world(world)
    owner, reader = await world.user(), await world.user()
    acme = await r.contact("ACME")
    shared = await world.spaces.create(owner.id, "Shared")
    await world.spaces.set_member(owner.id, shared.id, reader.id, SpaceRole.READ)
    await r.personal_rule(owner, definition("ACME", contact_is(acme.id), SetSpace(shared.id)))

    document = await r.arrive(owner, classify=Classifies(contact=acme.id))

    assert document.lane is Lane.YELLOW
    assert document.space_id == (await world.personal_space(owner)).id
    (open,) = (await r.documents.review(owner.id, document.id)).open
    assert [(check.field, check.suggestion) for check in open.fields] == [("contact", str(acme.id))]
    (entry,) = await r.rule_entries(document, RULES)
    assert notes(entry.result.output) == [("space", "refused")]
    assert await world.documents.list_visible(reader.id) == []

    # Confirmed by the owner, the contact is trusted: the rule files.
    await r.pipeline().confirm(owner.id, document.id, DocumentChanges())
    await world.drain(r.pipeline())
    document = await r.stored(document)
    assert (document.lane, document.space_id) == (Lane.GREEN, shared.id)
    assert [item.id for item in await world.documents.list_visible(reader.id)] == [document.id]


async def test_unconfirmed_model_values_still_file_into_a_private_space(world: World) -> None:
    r = await rule_world(world)
    owner = await world.user()
    acme = await r.contact("ACME")
    private = await world.spaces.create(owner.id, "Private")
    await r.personal_rule(owner, definition("ACME", contact_is(acme.id), SetSpace(private.id)))

    document = await r.arrive(owner, classify=Classifies(contact=acme.id))

    assert (document.lane, document.space_id) == (Lane.GREEN, private.id)


async def test_unconfirmed_model_tags_do_not_file_into_another_users_space(
    world: World,
) -> None:
    r = await rule_world(world)
    owner, colleague = await world.user(), await world.user()
    tax = await r.tag("tax")
    office = await world.spaces.create(colleague.id, "Office")
    await world.spaces.set_member(colleague.id, office.id, owner.id, SpaceRole.EDIT)
    await r.personal_rule(owner, definition("Tax", has_tag(tax.id), SetSpace(office.id)))

    document = await r.arrive(owner, classify=Classifies(tags=[tax.id]))

    assert document.lane is Lane.YELLOW
    assert document.space_id == (await world.personal_space(owner)).id
    (open,) = (await r.documents.review(owner.id, document.id)).open
    assert [check.field for check in open.fields] == ["tags"]


async def test_a_withdrawn_edit_right_stops_the_rule_from_filing(world: World) -> None:
    r = await rule_world(world)
    owner, colleague = await world.user(), await world.user()
    office = await world.spaces.create(colleague.id, "Office")
    await world.spaces.set_member(colleague.id, office.id, owner.id, SpaceRole.EDIT)
    await r.personal_rule(owner, definition("Office", channel_api(), SetSpace(office.id)))
    await world.spaces.set_member(colleague.id, office.id, owner.id, SpaceRole.READ)

    document = await r.arrive(owner)

    default = await world.personal_space(owner)
    assert (document.lane, document.space_id) == (Lane.YELLOW, default.id)
    (open,) = (await r.documents.review(owner.id, document.id)).open
    (check,) = open.fields
    assert check.field == "space"
    assert check.reason == "rule 'Office': no right to file into space 'Office' (any more)"

    # Keeping the space: the rule is refused again, but the document is filed.
    await r.pipeline().confirm(owner.id, document.id, DocumentChanges())
    await world.drain(r.pipeline())
    document = await r.stored(document)
    assert (document.lane, document.space_id) == (Lane.GREEN, default.id)


async def test_filing_holds_after_the_uploader_lost_the_space(world: World) -> None:
    """Rights hang on the space: who uploaded a document has none, so filing never asks
    them again."""
    r = await rule_world(world)
    owner, colleague = await world.user(), await world.user()
    office = await world.spaces.create(colleague.id, "Office")
    await world.spaces.set_member(colleague.id, office.id, owner.id, SpaceRole.EDIT)
    pipeline = r.pipeline()
    received = await pipeline.receive(owner.id, incoming_pdf(), filename="a.pdf", space=office.id)
    await world.spaces.remove_member(colleague.id, office.id, owner.id)

    await world.drain(pipeline)

    document = await r.stored(received)
    assert (document.lane, document.space_id) == (Lane.GREEN, office.id)
    assert document.processing.outcomes[Node.FILE] is Outcome.OK
    assert DocumentFiled.type in world.event_types()
    assert (await world.documents.get(colleague.id, document.id)).uploaded_by == owner.id


async def test_the_rules_of_a_space_run_whoever_wrote_them(world: World) -> None:
    """Rules belong to a space, not to a user: a deactivated author does not stop them
    (filing checks the author: a deactivated one files nowhere but into personal spaces)."""
    r = await rule_world(world)
    owner = await world.user()
    mine, everyone = await r.tag("mine"), await r.tag("everyone")
    personal = await r.personal_rule(owner, definition("Mine", channel_api(), add_tags(mine.id)))
    shared = await r.global_rule(definition("All", channel_api(), add_tags(everyone.id)))
    pipeline = r.pipeline()
    received = await pipeline.receive(owner.id, incoming_pdf(), filename="a.pdf")
    await r.deactivate(owner)

    await world.drain(pipeline)

    document = await r.stored(received)
    assert document.tag_ids == {mine.id, everyone.id}
    (entry,) = await r.rule_entries(document, RULES)
    assert entry.result.input["rules"] == [
        {"id": str(shared.id), "version": 1},
        {"id": str(personal.id), "version": 1},
    ]


async def test_a_global_rule_acts_on_every_document_but_never_moves_it(world: World) -> None:
    r = await rule_world(world)
    owner, colleague = await world.user(), await world.user()
    office = await world.spaces.create(colleague.id, "Office")
    await world.spaces.set_member(colleague.id, office.id, owner.id, SpaceRole.EDIT)
    seen = await r.tag("seen")
    await r.global_rule(definition("Seen", channel_api(), add_tags(seen.id)))

    mine = await r.arrive(owner)
    theirs = await r.arrive(colleague)
    filed = await r.arrive(owner, space=office.id)

    for document, space in (
        (mine, (await world.personal_space(owner)).id),
        (theirs, (await world.personal_space(colleague)).id),
        (filed, office.id),
    ):
        assert (document.lane, document.space_id, document.tag_ids) == (
            Lane.GREEN,
            space,
            {seen.id},
        )


async def test_a_pattern_that_times_out_does_not_match(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    r = await rule_world(world)
    owner = await world.user()
    slow, bill = await r.tag("slow"), await r.tag("bill")
    r.matcher.slow.add("(a+)+$")
    await r.personal_rule(owner, definition("Slow", text_matches("(a+)+$"), add_tags(slow.id)))
    await r.personal_rule(owner, definition("Bill", text_matches(r"Rech\w+"), add_tags(bill.id)))

    with caplog.at_level(logging.WARNING):
        document = await r.arrive(owner, text="# Rechnung\n\naaaaaaaaaaaaaaaaaaaaaaaab")

    assert document.processing.status is ProcessingStatus.COMPLETED
    assert (document.lane, document.tag_ids) == (Lane.GREEN, {bill.id})
    (entry,) = await r.rule_entries(document, RULES)
    assert entry.result.output["problems"] == ["pattern '(a+)+$' took longer than 0.2 s"]
    assert "rule pattern skipped" in caplog.messages


async def test_rules_do_not_set_each_other_off_on_arrival(world: World) -> None:
    """Conditions see the state before any rule acts: a tag added by one rule does not make
    another rule match in the same run."""
    r = await rule_world(world)
    owner = await world.user()
    first, second = await r.tag("first"), await r.tag("second")
    await r.personal_rule(owner, definition("First", channel_api(), add_tags(first.id)))
    await r.personal_rule(owner, definition("Second", has_tag(first.id), add_tags(second.id)))

    document = await r.arrive(owner)

    assert document.tag_ids == {first.id}


async def test_patterns_stop_when_their_time_is_used_up(world: World) -> None:
    r = await rule_world(world)
    owner = await world.user()
    rule = await r.personal_rule(
        owner, definition("Bill", text_matches("Rech"), SetTitle("Bill"), triggers=CHANGE)
    )
    document = await r.arrive(owner, text="# Rechnung")

    prepared = await prepare(
        world.object_store,
        r.matcher,
        [rule],
        document,
        max_text=1000,
        budget=PatternBudget(0),
    )

    assert prepared.patterns == {}
    assert prepared.problems == ("pattern 'Rech' skipped: the time for patterns is used up",)
    assert r.matcher.searched == []


class Counting:
    """A repository that counts the calls of its methods, by name."""

    def __init__(self, inner: object) -> None:
        self._inner = inner
        self.calls: Counter[str] = Counter()

    def __getattr__(self, name: str) -> Any:
        found = getattr(self._inner, name)
        if not callable(found):
            return found

        def counted(*args: Any, **kwargs: Any) -> Any:
            self.calls[name] += 1
            return found(*args, **kwargs)

        return counted


async def test_a_rule_run_loads_contacts_types_and_tags_once(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run loads the contacts and types it looks at and the tag tree once; the names its
    templates and reasons use come from there."""
    r = await rule_world(world)
    owner = await world.user()
    acme = await r.contact("ACME")
    invoice = await world.master_data.create_document_type(r.admin.id, "Invoice")
    tax = await r.tag("tax")
    document = await r.arrive(owner, classify=Classifies(tags=[tax.id]))
    await r.personal_rule(
        owner,
        definition(
            "Invoice",
            has_tag(tax.id),
            SetContact(acme.id),
            SetDocumentType(invoice.id),
            SetTitle("{{ contact }} {{ document_type }} {{ tags | join }}"),
        ),
    )

    async with world.uow() as uow:
        counted = {
            name: Counting(getattr(uow, name)) for name in ("contacts", "document_types", "tags")
        }
        for name, repository in counted.items():
            monkeypatch.setattr(uow, name, repository)
        stored = await uow.documents.get(document.id)
        run = await run_rules(
            uow,
            r.matcher,
            TEMPLATES,
            mode=Mode.INGEST,
            document=stored,
            rules=await active_rules(uow, stored.space_id, Trigger.INGEST),
            prepared=Prepared(),
            origin=provenance(await uow.processing_log.list_for(stored.id), stored),
            definitions={},
        )

    changes = run.plan.changes
    assert (changes.contact_id, changes.document_type_id) == (acme.id, invoice.id)
    assert changes.title == "ACME Invoice tax"
    assert counted["contacts"].calls == {"find": 1}
    assert counted["document_types"].calls == {"find": 1}
    assert counted["tags"].calls == {"list_all": 1}


async def test_a_rule_reads_the_facts_into_a_field(world: World) -> None:
    """A reminder: the rule looks for an invoice it refers to and writes its number into a
    field; a document without one the rule leaves alone."""
    r = await rule_world(world)
    owner = await world.user()
    note = await world.master_data.create_field(r.admin.id, "Bezug", FieldType.TEXT)
    refers = Condition(
        field=ConditionField.FACT,
        op=Operator.PRESENT,
        fact_kind=IdentifierKind.INVOICE_NUMBER,
        fact_role=FactRole.REFERS,
    )
    await r.personal_rule(
        owner,
        definition(
            "Mahnung",
            refers,
            SetField(note.id, "Rechnung {{ facts.refers.invoice_number }}"),
        ),
    )
    facts = FactsSignal(world.uow, world.object_store)
    text = "Ihre Rechnung Nr. R-4711 ist noch offen."
    reminder = await r.arrive(owner, text=text, facts=facts)
    assert reminder.fields[note.id] == "Rechnung R-4711"
    invoice = await r.arrive(owner, text="Rechnungsnummer: R-4711", facts=facts)
    assert note.id not in invoice.fields


async def test_a_persons_fact_decision_runs_the_change_rules(world: World) -> None:
    """Corrected facts give the person's value (`fakten.md`, decision 13): the change rules run
    on the facts before and after the decision, so a field a rule fills follows it."""
    r = await rule_world(world)
    owner = await world.user()
    note = await world.master_data.create_field(r.admin.id, "Bezug", FieldType.TEXT)
    refers = Condition(
        field=ConditionField.FACT,
        op=Operator.MATCHES,
        value="^R",
        fact_kind=IdentifierKind.INVOICE_NUMBER,
        fact_role=FactRole.REFERS,
    )
    await r.personal_rule(
        owner,
        definition(
            "Mahnung",
            refers,
            SetField(note.id, "Rechnung {{ facts.refers.invoice_number }}"),
            triggers=(Trigger.CHANGE,),
        ),
    )
    facts = FactsSignal(world.uow, world.object_store)
    reminder = await r.arrive(owner, text="Ihre Rechnung Nr. 4711 ist noch offen.", facts=facts)
    assert note.id not in reminder.fields  # on arrival the change rule does not run
    await r.documents.decide_fact(
        owner.id,
        reminder.id,
        FactDecision(
            action=FactAction.CORRECT,
            kind=IdentifierKind.INVOICE_NUMBER,
            value="4711",
            new_value="R-4711",
        ),
    )
    assert (await r.stored(reminder)).fields[note.id] == "Rechnung R-4711"


async def test_only_admins_write_and_apply_rules_on_a_persons_facts(world: World) -> None:
    """As only admins find documents by them (`_access.check_fact_filter`)."""
    r = await rule_world(world)
    editor = await world.user()
    shared = await world.spaces.create(r.admin.id, "Haushalt")
    await world.spaces.set_member(r.admin.id, shared.id, editor.id, SpaceRole.EDIT)
    tax_id = Condition(
        field=ConditionField.FACT,
        op=Operator.IS,
        value="86095742001",
        fact_kind=IdentifierKind.TAX_ID,
    )
    of_a_person = Condition(
        field=ConditionField.FACT,
        op=Operator.PRESENT,
        fact_kind=IdentifierKind.IBAN,
        fact_role=FactRole.PERSON,
    )
    paid = await r.tag("bezahlt")
    for condition in (tax_id, of_a_person):
        with pytest.raises(PermissionDeniedError):
            await r.space_rule(
                editor, shared.id, definition("Steuer", condition, AddTags(frozenset({paid.id})))
            )
    rule = await r.space_rule(
        r.admin, shared.id, definition("Steuer", tax_id, AddTags(frozenset({paid.id})))
    )
    with pytest.raises(PermissionDeniedError):
        await r.applications.preview(editor.id, rule.id)
    await r.applications.preview(r.admin.id, rule.id)


async def test_the_preview_sees_the_girocode(world: World) -> None:
    """`facts.girocode` in the preview of a rule's and of a webhook's template, as in a run."""
    r = await rule_world(world)
    owner = await world.user()
    invoice = await r.arrive(owner, text="Rechnung")
    giro = Code(
        page=1,
        format="QR Code",
        text="BCD\n002\n1\nSCT\n\nStadtwerke\nDE89370400440532013000\nEUR84.20\n\n\nStrom",
        box=Box(0.1, 0.1, 0.1, 0.1),
    )
    await world.object_store.put(
        codes_key(invoice.id),
        json.dumps(codes_to_json([giro])).encode(),
        content_type="application/json",
    )
    for webhook, template, shown in (
        (False, "{{ facts.girocode.name }}", "Stadtwerke"),
        (True, '{"iban": "{{ facts.girocode.iban }}"}', "DE89370400440532013000"),
    ):
        preview = await r.rules.preview_template(
            owner.id, template, document=invoice.id, webhook=webhook
        )
        assert preview.missing is None and preview.error is None, preview
        assert shown in (preview.rendered or "")
