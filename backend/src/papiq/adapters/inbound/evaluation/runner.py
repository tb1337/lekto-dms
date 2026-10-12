"""Running the evaluation set through the pipeline's classification and extraction steps.

Each case becomes a document of one owner, whose text is stored as if the parse step had
produced it. OCR, parsing, rules and filing pass through; classification and field
extraction are the same steps as in the pipeline, with the given model.
"""

import secrets
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from papiq.adapters.inbound.evaluation.cases import Case, EvaluationSet, MasterDataSpec
from papiq.core.domain.classification import FieldCheck, field_key, field_to_json
from papiq.core.domain.documents import Document
from papiq.core.domain.fields import FieldDefinition
from papiq.core.domain.ids import ContactId, DocumentId, DocumentTypeId, FieldId, TagId, UserId
from papiq.core.domain.json_value import JsonValue
from papiq.core.domain.pipeline import Lane, ProcessingStatus, Step, StepRun
from papiq.core.domain.users import Role, User
from papiq.core.ports import ObjectStore
from papiq.core.services.documents import DocumentService
from papiq.core.services.inbox import field_checks, open_steps
from papiq.core.services.master_data import MasterDataService
from papiq.core.services.objects import markdown_key
from papiq.core.services.pipeline import IncomingFile, PipelineService
from papiq.core.services.users import UserService

ADMIN = "evaluation-admin"  # creates the master data
OWNER = "evaluation"  # owns the documents
_MAX_JOBS = 50  # per case; the pipeline needs one per step


@dataclass(frozen=True)
class Environment:
    """Where the cases run: the services on a database and an object store of their own (in
    memory, or the real ones in the integration test), built by the composition root.

    `pipeline_for(case)` is the pipeline the case runs through: classification and field
    extraction with the case's model, the other steps pass through, and no automatic retries,
    so a model that cannot be reached ends the case red at once.
    """

    store: ObjectStore  # the text of a case is stored as the parse step would have
    users: UserService
    master_data: MasterDataService
    documents: DocumentService
    pipeline_for: Callable[[Case], PipelineService]


@dataclass(frozen=True)
class MasterData:
    """The seeded master data, by id."""

    contacts: dict[ContactId, str]
    document_types: dict[DocumentTypeId, str]
    tags: dict[TagId, str]
    fields: dict[FieldId, FieldDefinition]


@dataclass(frozen=True)
class CaseResult:
    """What became of a case: the document's state, the field checks and the run time."""

    case: Case
    document_id: DocumentId
    owner_id: UserId
    lane: Lane | None
    status: ProcessingStatus
    contact: str | None
    document_type: str | None
    tags: frozenset[str]
    document_date: str | None
    fields: dict[str, JsonValue]
    checks: dict[str, FieldCheck]  # by field; fields by their name
    proposed: dict[str, JsonValue]  # by field as `checks`: the value, else the suggestion, by name
    reasons: dict[Step, str]  # steps that are uncertain or failed
    seconds: float
    violations: tuple[str, ...]  # changes no check backs, or of fields the model must not touch
    truncated: bool


async def evaluate(
    evaluation: EvaluationSet,
    environment: Environment,
    *,
    filename_for: Callable[[Case], str] | None = None,
    progress: Callable[[CaseResult], None] | None = None,
) -> list[CaseResult]:
    """Run every case; the cases share the owner and the master data. `filename_for`: the
    file name a case is received with (default: the case's name)."""
    admin, owner = await _accounts(environment)
    master = await _seed(environment, evaluation.master_data, admin)
    results = []
    for case in evaluation.cases:
        filename = f"{case.name}.pdf" if filename_for is None else filename_for(case)
        result = await _run(case, environment, master, owner, filename)
        if progress is not None:
            progress(result)
        results.append(result)
    return results


async def _accounts(environment: Environment) -> tuple[User, User]:
    """An admin, who creates the master data, and a user, who owns the documents. The database
    has to be empty: the admin can only be the first one."""
    admin = await environment.users.bootstrap_admin(ADMIN, secrets.token_urlsafe(24))
    if admin is None:
        raise RuntimeError("the evaluation needs a database without an admin")
    owner = await environment.users.create_user(admin.id, OWNER, Role.USER)
    return admin, owner


async def _seed(environment: Environment, spec: MasterDataSpec, admin: User) -> MasterData:
    master_data = environment.master_data
    contacts = [
        await master_data.create_contact(admin.id, name, spec.contact_aliases.get(name, ()))
        for name in spec.contacts
    ]
    types = [
        await master_data.create_document_type(admin.id, name, spec.type_descriptions.get(name))
        for name in spec.document_types
    ]
    tags = [await master_data.create_tag(admin.id, name) for name in spec.tags]
    type_ids = {item.name: item.id for item in types}
    fields = [
        await master_data.create_field(
            admin.id,
            item.name,
            item.data_type,
            document_type_ids=(
                None
                if item.document_types is None
                else [type_ids[name] for name in item.document_types]
            ),
            choices=item.choices,
        )
        for item in spec.fields
    ]
    return MasterData(
        contacts={item.id: item.name for item in contacts},
        document_types={item.id: item.name for item in types},
        tags={item.id: item.name for item in tags},
        fields={item.id: item for item in fields},
    )


async def _run(
    case: Case, environment: Environment, master: MasterData, owner: User, filename: str
) -> CaseResult:
    pipeline = environment.pipeline_for(case)
    with tempfile.TemporaryDirectory(prefix="papiq-evaluation-") as directory:
        path = Path(directory) / "case.pdf"
        # A distinct file per case: the owner cannot have the same file twice.
        path.write_bytes(f"%PDF-1.7\n% evaluation case {case.name}\n%%EOF\n".encode())
        received = await pipeline.receive(owner.id, IncomingFile.of(path), filename=filename)
    await environment.store.put(
        markdown_key(received.id),
        case.text.encode("utf-8"),
        content_type="text/markdown; charset=utf-8",
    )
    started = time.perf_counter()
    for _ in range(_MAX_JOBS):
        if not await pipeline.run_next_job():
            break
    seconds = time.perf_counter() - started
    document = await environment.documents.get(owner.id, received.id)
    log = await environment.documents.processing_log(owner.id, received.id)
    return _result(case, received, document, log, master, seconds)


def _result(
    case: Case,
    before: Document,
    after: Document,
    log: list[StepRun],
    master: MasterData,
    seconds: float,
) -> CaseResult:
    checks = {_field_label(field, master): check for field, check in field_checks(log).items()}
    truncated = any(
        entry.result.input.get("truncated") is True
        for entry in log
        if entry.step in (Step.CLASSIFY, Step.EXTRACT_FIELDS)
    )
    return CaseResult(
        case=case,
        document_id=after.id,
        owner_id=after.owner_id,
        lane=after.lane,
        status=after.processing.status,
        contact=None if after.contact_id is None else master.contacts[after.contact_id],
        document_type=(
            None
            if after.document_type_id is None
            else master.document_types[after.document_type_id]
        ),
        tags=frozenset(master.tags[tag] for tag in after.tag_ids),
        document_date=None if after.document_date is None else after.document_date.isoformat(),
        fields={master.fields[id].name: field_to_json(value) for id, value in after.fields.items()},
        checks=checks,
        proposed={label: _resolved(check, master) for label, check in checks.items()},
        reasons={item.step: item.reason or "" for item in open_steps(after, log)},
        seconds=seconds,
        violations=_violations(before, after, field_checks(log)),
        truncated=truncated,
    )


def _resolved(check: FieldCheck, master: MasterData) -> JsonValue:
    """The checked value, or else the suggestion, with contact, type and tag ids as names."""
    value = check.value if check.ok else check.suggestion
    names: dict[str, str]
    match check.field:
        case "contact":
            names = {str(id): name for id, name in master.contacts.items()}
        case "document_type":
            names = {str(id): name for id, name in master.document_types.items()}
        case "tags":
            names = {str(id): name for id, name in master.tags.items()}
            tags: list[JsonValue] = []
            tags.extend(sorted(names.get(item, item) for item in _strings(value)))
            return tags
        case _:
            return value
    return names.get(value, value) if isinstance(value, str) else value


def _field_label(field: str, master: MasterData) -> str:
    for id, definition in master.fields.items():
        if field == field_key(id):
            return definition.name
    return field


def _violations(
    before: Document, after: Document, checks: dict[str, FieldCheck]
) -> tuple[str, ...]:
    """Changes the checks do not back: every changed field must have an OK check with the
    applied value; drawer, owner and title must stay."""
    problems = []
    for name in ("owner_id", "drawer_id", "title"):
        if getattr(before, name) != getattr(after, name):
            problems.append(f"{name} changed")

    def backed(field: str, value: JsonValue) -> bool:
        check = checks.get(field)
        return check is not None and check.ok and check.value == value

    if after.contact_id != before.contact_id and not backed(
        "contact", None if after.contact_id is None else str(after.contact_id)
    ):
        problems.append("contact changed without a passed check")
    if after.document_type_id != before.document_type_id and not backed(
        "document_type", None if after.document_type_id is None else str(after.document_type_id)
    ):
        problems.append("document type changed without a passed check")
    if after.tag_ids != before.tag_ids:
        check = checks.get("tags")
        if (
            check is None
            or not check.ok
            or set(_strings(check.value)) != {str(tag) for tag in after.tag_ids}
        ):
            problems.append("tags changed without a passed check")
    if after.document_date != before.document_date and not backed(
        "document_date", None if after.document_date is None else after.document_date.isoformat()
    ):
        problems.append("document date changed without a passed check")
    for id, value in after.fields.items():
        if before.fields.get(id) != value and not backed(field_key(id), field_to_json(value)):
            problems.append(f"field {id} changed without a passed check")
    return tuple(problems)


def _strings(value: JsonValue) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []
