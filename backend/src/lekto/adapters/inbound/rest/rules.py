"""`/rules`: rules that tag, file and check documents; their versions."""

from uuid import UUID

from fastapi import APIRouter, Request, Response

from lekto.adapters.inbound.rest.auth import PROTECTED, CurrentUser
from lekto.adapters.inbound.rest.context import Context
from lekto.adapters.inbound.rest.cursors import decode_cursor, encode_cursor
from lekto.adapters.inbound.rest.params import AllRules
from lekto.adapters.inbound.rest.problems import problem_responses
from lekto.adapters.inbound.rest.schemas.rules import (
    ApplyOutcomeOut,
    ApplyPreviewItemOut,
    ApplyPreviewOut,
    ApplyPreviewRequest,
    ApplyRequest,
    RuleApplicationOut,
    RuleChange,
    RuleCreate,
    RuleOut,
    RulePatch,
    RuleVersionOut,
    TemplatePreviewIn,
    TemplatePreviewOut,
)
from lekto.adapters.inbound.schemas import ReasonOut, RuleEffectOut, RuleNoteOut, field_json
from lekto.core.domain.ids import (
    DocumentId,
    DocumentTypeId,
    FieldId,
    RuleApplicationId,
    RuleId,
    SpaceId,
)
from lekto.core.domain.rules import RuleScope
from lekto.core.domain.rules_json import definition_from_json

router = APIRouter(prefix="/rules", tags=["rules"], dependencies=PROTECTED)
templates = APIRouter(prefix="/templates", tags=["rules"], dependencies=PROTECTED)

WHO_CHANGES = (
    "A space rule: the editors of its space and admins (its references are checked for the "
    "caller, who saves it). A global rule: admins."
)
WHO_READS = (
    "Global rules: everyone; space rules: the editors of their space and admins. The rules of "
    "other spaces are not found (404)."
)
CHECKS = (
    " The content is checked: operators fit the field and the field's data type, patterns "
    "compile (422, the message names the place, such as `conditions.all[1].any[0]` or "
    "`actions[2]`); contacts, types, tags, fields and spaces exist (404); a rule files only "
    "into spaces the caller may file into (403), or hands documents over into another user's "
    "personal space."
)


@router.get(
    "",
    summary="List rules",
    description=(
        "The global rules and the rules of the spaces the caller edits (with `space_id`, only "
        "that space's), in the order they are applied (priority, then global before space "
        "rules, then older first). Deleted rules are not listed."
    ),
    response_model=list[RuleOut],
    responses=problem_responses(401, 403, 422),
)
async def list_rules(
    user: CurrentUser,
    context: Context,
    scope: RuleScope | None = None,
    space_id: UUID | None = None,
    include_disabled: bool = True,
    all_users: AllRules = False,
) -> list[RuleOut]:
    rules = await context.rules.list_rules(
        user,
        scope=scope,
        space=None if space_id is None else SpaceId(space_id),
        include_disabled=include_disabled,
        all_users=all_users,
    )
    return [RuleOut.of(rule) for rule in rules]


@router.post(
    "",
    status_code=201,
    summary="Create a rule",
    description=(
        "Global rules: admins only (403). A space rule needs edit rights on its space (403; "
        "404 for a space the caller is no member of)." + CHECKS
    ),
    response_model=RuleOut,
    responses=problem_responses(401, 403, 404, 422),
)
async def create_rule(body: RuleCreate, user: CurrentUser, context: Context) -> RuleOut:
    definition = definition_from_json(body.to_json())
    space = None if body.space_id is None else SpaceId(body.space_id)
    return RuleOut.of(
        await context.rules.create(user, body.scope, definition, space=space, enabled=body.enabled)
    )


@router.get(
    "/{id}",
    summary="A rule",
    description=WHO_READS,
    response_model=RuleOut,
    responses=problem_responses(401, 404, 422),
)
async def get_rule(id: UUID, user: CurrentUser, context: Context) -> RuleOut:
    return RuleOut.of(await context.rules.get(user, RuleId(id)))


@router.put(
    "/{id}",
    summary="Change a rule",
    description=(
        "Makes a new version; earlier ones stay readable. With `scope` the rule moves into "
        "another space or between a space and global: the caller changes it where it is and "
        "edits where it goes (global: admins); the version names the space. " + WHO_CHANGES + CHECKS
    ),
    response_model=RuleOut,
    responses=problem_responses(401, 403, 404, 409, 422),
)
async def change_rule(id: UUID, body: RuleChange, user: CurrentUser, context: Context) -> RuleOut:
    definition = definition_from_json(body.to_json())
    space = None if body.space_id is None else SpaceId(body.space_id)
    return RuleOut.of(
        await context.rules.change(
            user, RuleId(id), definition, scope=body.scope, space=space, enabled=body.enabled
        )
    )


@router.patch(
    "/{id}",
    summary="Enable or disable a rule",
    description=(
        WHO_CHANGES + " Makes no version. Enabling checks the references again: a rule "
        "disabled because something it uses was deleted stays disabled until it is changed."
    ),
    response_model=RuleOut,
    responses=problem_responses(401, 403, 404, 409, 422),
)
async def patch_rule(id: UUID, body: RulePatch, user: CurrentUser, context: Context) -> RuleOut:
    return RuleOut.of(await context.rules.set_enabled(user, RuleId(id), body.enabled))


@router.delete(
    "/{id}",
    status_code=204,
    summary="Delete a rule",
    description=(
        WHO_CHANGES + " The rule never runs again and is no longer listed; its versions stay "
        "readable, so the processing log can be read."
    ),
    responses=problem_responses(401, 403, 404, 409, 422),
)
async def delete_rule(id: UUID, user: CurrentUser, context: Context) -> None:
    await context.rules.delete(user, RuleId(id))


@router.get(
    "/{id}/versions",
    summary="Versions of a rule",
    description="Oldest first; also of a deleted rule. " + WHO_READS,
    response_model=list[RuleVersionOut],
    responses=problem_responses(401, 404, 422),
)
async def list_rule_versions(id: UUID, user: CurrentUser, context: Context) -> list[RuleVersionOut]:
    return [RuleVersionOut.of(item) for item in await context.rules.versions(user, RuleId(id))]


@router.get(
    "/{id}/versions/{number}",
    summary="A version of a rule",
    description=WHO_READS,
    response_model=RuleVersionOut,
    responses=problem_responses(401, 404, 422),
)
async def get_rule_version(
    id: UUID, number: int, user: CurrentUser, context: Context
) -> RuleVersionOut:
    return RuleVersionOut.of(await context.rules.version(user, RuleId(id), number))


WHO_APPLIES = (
    "A space rule: the editors of its space and admins, on the documents in its space. A "
    "global rule: anyone, on the documents they may edit (admins: every document). Documents "
    "in processing are left out."
)


@router.post(
    "/{id}/apply/preview",
    summary="Preview applying a rule to existing documents",
    description=(
        "The documents the rule's current version would change, newest first, with what would "
        "change and the conflicts (a field that has another value). Each shows the chain as "
        "applying runs it: the rules of the spaces the rule files it into, and of the spaces "
        "those file it into (each at most once), and where it ends up; with conflicts also when "
        "they are accepted. Nothing is stored. " + WHO_APPLIES
    ),
    response_model=ApplyPreviewOut,
    responses=problem_responses(401, 403, 404, 422),
)
async def preview_apply(
    id: UUID, body: ApplyPreviewRequest, user: CurrentUser, context: Context
) -> ApplyPreviewOut:
    preview = await context.rule_applications.preview(
        user, RuleId(id), before=decode_cursor(body.cursor), limit=body.limit
    )
    return ApplyPreviewOut(
        rule_id=preview.rule.id,
        version=preview.rule.current.number,
        items=[
            ApplyPreviewItemOut(
                document_id=item.document.id,
                title=item.document.title,
                changes=[RuleEffectOut.of(effect) for effect in item.effects],
                conflicts=[RuleNoteOut.of(note) for note in item.conflicts],
                notes=[RuleNoteOut.of(note) for note in item.notes],
                outcome=ApplyOutcomeOut.of(item.outcome),
                accepted=None if item.accepted is None else ApplyOutcomeOut.of(item.accepted),
                sends=[send.webhook_id for send in item.sends],
                sends_refused=[ReasonOut.of(reason) for reason in item.refused],
            )
            for item in preview.items
        ],
        next_cursor=None if preview.next_cursor is None else encode_cursor(preview.next_cursor),
    )


@router.post(
    "/{id}/apply",
    status_code=202,
    summary="Apply a rule to existing documents",
    description=(
        "Applies the given version to the selected documents in the background; follow it at "
        "`GET /rule-applications/{id}`. Rights are checked again for every document. Conflicts "
        "are applied only for documents in `accept_conflicts`; forced reviews do not act. "
        + WHO_APPLIES
    ),
    response_model=RuleApplicationOut,
    responses=problem_responses(401, 403, 404, 422),
)
async def apply_rule(
    id: UUID,
    body: ApplyRequest,
    request: Request,
    response: Response,
    user: CurrentUser,
    context: Context,
) -> RuleApplicationOut:
    application = await context.rule_applications.start(
        user,
        RuleId(id),
        version=body.version,
        documents=[DocumentId(item) for item in body.document_ids],
        accept_conflicts=[DocumentId(item) for item in body.accept_conflicts],
    )
    response.headers["Location"] = str(request.url_for("get_application", id=application.id).path)
    return RuleApplicationOut.of(application)


applications = APIRouter(prefix="/rule-applications", tags=["rules"], dependencies=PROTECTED)


@applications.get(
    "/{id}",
    summary="Progress of a rule application",
    description="For the user who started it and admins.",
    response_model=RuleApplicationOut,
    responses=problem_responses(401, 404, 422),
)
async def get_application(id: UUID, user: CurrentUser, context: Context) -> RuleApplicationOut:
    return RuleApplicationOut.of(await context.rule_applications.get(user, RuleApplicationId(id)))


@templates.post(
    "/preview",
    summary="Check a template and render it with a document",
    description=(
        "For the editors of rules and title patterns: whether a template is valid and which "
        "values it uses, and, with a document the caller may read, what it gives for it as "
        "the document is now (or which missing value stops it). Nothing is stored. A "
        "template the caller may not save is shown as such (`error`), not refused."
    ),
    response_model=TemplatePreviewOut,
    responses=problem_responses(401, 404, 422),
)
async def preview_template(
    body: TemplatePreviewIn, user: CurrentUser, context: Context
) -> TemplatePreviewOut:
    preview = await context.rules.preview_template(
        user,
        body.template,
        document=None if body.document_id is None else DocumentId(body.document_id),
        document_type=(
            None if body.document_type_id is None else DocumentTypeId(body.document_type_id)
        ),
        webhook=body.purpose == "webhook",
        field=None if body.field_id is None else FieldId(body.field_id),
    )
    return TemplatePreviewOut(
        used=list(preview.used),
        rendered=preview.rendered,
        missing=preview.missing,
        error=preview.error,
        values=None if preview.values is None else dict(preview.values),
        read=None if preview.read is None else field_json(preview.read),
        unreadable=preview.unreadable,
    )
