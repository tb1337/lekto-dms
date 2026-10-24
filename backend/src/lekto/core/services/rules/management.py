"""Creating, changing, enabling, disabling and deleting rules.

Who may do what:

- A space rule belongs to its space: its editors read and change it. Admins read and change
  every rule (Tobi, 08.10.2026). Whoever saves a rule may let it file only into spaces they
  may file into, or hand documents over into another user's personal space; that is checked
  for the author of the current version whenever the rule runs. Users who do not edit a space
  do not learn that its rules exist (NotFoundError).
- Global rules are read by everyone and changed by admins only; they may do everything.
- A change may move a rule into another space or between a space and global (Tobi,
  22.10.2026): whoever moves it changes it where it is and edits where it goes (global:
  admins). The new version names the space, so the history shows the move.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace

from lekto.core.domain.documents import Document
from lekto.core.domain.errors import (
    ConflictError,
    MissingValueError,
    NotFoundError,
    PermissionDeniedError,
    SpaceWriteDeniedError,
    ValidationError,
)
from lekto.core.domain.fields import FieldDefinition, FieldType
from lekto.core.domain.ids import DocumentId, DocumentTypeId, RuleId, SpaceId, UserId
from lekto.core.domain.permissions import space_role
from lekto.core.domain.reasons import Action, ReasonCode, because
from lekto.core.domain.rules import (
    ForceReview,
    Rule,
    RuleDefinition,
    RuleScope,
    RuleVersion,
    SetField,
    SetTitle,
    check_fields,
)
from lekto.core.domain.spaces import SpaceRole
from lekto.core.domain.templates import (
    FIELD,
    NAMES,
    TemplateValue,
    rename_field_key,
    template_values,
    unknown_values,
    writing_templates,
)
from lekto.core.domain.templates import uses_field as field_used
from lekto.core.domain.users import User
from lekto.core.ports.clock import Clock
from lekto.core.ports.patterns import PatternMatcher
from lekto.core.ports.templates import TemplateRenderer
from lekto.core.ports.unit_of_work import UnitOfWork, UnitOfWorkFactory
from lekto.core.services._access import (
    admin_only,
    field_definitions,
    load_actor,
    load_lister,
    readable_document,
    space_label,
)
from lekto.core.services._tags import tag_tree


@dataclass(frozen=True)
class TemplatePreview:
    """What a template gives for a document: the values it uses, the rendered text
    (whitespace collapsed, as in a title), or the missing value or the error that stops it.
    `values`: what the document has, each value as a template writes it (by its path, such as
    `field.la_brutto`); None without a document."""

    used: tuple[str, ...] = ()
    rendered: str | None = None
    missing: str | None = None
    error: str | None = None
    values: Mapping[str, str] | None = None


class RuleService:
    def __init__(
        self,
        uow: UnitOfWorkFactory,
        clock: Clock,
        templates: TemplateRenderer,
        patterns: PatternMatcher,
    ) -> None:
        self._uow = uow
        self._clock = clock
        self._templates = templates
        self._patterns = patterns

    async def list_rules(
        self,
        actor: UserId,
        *,
        scope: RuleScope | None = None,
        space: SpaceId | None = None,
        include_disabled: bool = True,
        all_users: bool = False,
    ) -> list[Rule]:
        """The global rules and the rules of the spaces the caller edits, in the order they
        are applied; with `space`, only that space's (an admin's for any space). `all_users`:
        the rules of every space instead of the caller's (admins only)."""
        async with self._uow() as uow:
            user = await load_lister(uow, actor, all_users, Action.LIST_ALL_RULES)
            edited = None if all_users else await _edited_spaces(uow, user)
            if space is not None:
                anyone = edited is None or user.is_active_admin
                edited = [space] if anyone or space in (edited or ()) else []
            rules = await uow.rules.list_for(
                spaces=edited,
                include_global=scope is not RuleScope.SPACE and space is None,
            )
        return sorted(
            (
                rule
                for rule in rules
                if (scope is None or rule.scope is scope) and (include_disabled or rule.enabled)
            ),
            key=lambda rule: rule.order,
        )

    async def get(self, actor: UserId, id: RuleId) -> Rule:
        async with self._uow() as uow:
            rule = await visible_rule(uow, await load_actor(uow, actor), id)
            if rule.deleted_at is not None:
                raise NotFoundError("rule", id)
            return rule

    async def versions(self, actor: UserId, id: RuleId) -> list[RuleVersion]:
        """All versions, oldest first; also of a deleted rule, so the processing log can be
        read."""
        async with self._uow() as uow:
            await visible_rule(uow, await load_actor(uow, actor), id)
            return await uow.rules.versions(id)

    async def version(self, actor: UserId, id: RuleId, number: int) -> RuleVersion:
        async with self._uow() as uow:
            await visible_rule(uow, await load_actor(uow, actor), id)
            return await uow.rules.get_version(id, number)

    async def create(
        self,
        actor: UserId,
        scope: RuleScope,
        definition: RuleDefinition,
        *,
        space: SpaceId | None = None,
        enabled: bool = True,
    ) -> Rule:
        """A global rule needs an admin; a space rule belongs to `space`, which the caller
        edits (None: the caller's personal space). `enabled=False`: saved switched off, in the
        same transaction (to try it first; it never runs before it is switched on)."""
        async with self._uow() as uow:
            user = await load_actor(uow, actor)
            space = await _place(uow, user, scope, space)
            rule = Rule.create(
                scope=scope,
                space_id=space,
                definition=definition,
                by=user.id,
                now=self._clock.now(),
            )
            if not enabled:
                rule.disable(self._clock.now())
            await check_references(uow, rule.definition, author=user)
            check_patterns(self._patterns, rule.definition)
            await check_templates(uow, self._templates, rule.definition)
            await uow.rules.add(rule)
            await uow.commit()
        return rule

    async def preview_template(
        self,
        actor: UserId,
        template: str,
        *,
        document: DocumentId | None = None,
        document_type: DocumentTypeId | None = None,
    ) -> TemplatePreview:
        """`template` checked (syntax, values; the fields of `document_type`, or of the
        document's type, else all) and rendered with a document the caller may read, as it
        is, with the document's values whatever the template. Nothing is stored."""
        async with self._uow() as uow:
            user = await load_actor(uow, actor)
            found = None if document is None else (await readable_document(uow, user, document))[0]
            kind = document_type or (None if found is None else found.document_type_id)
            if kind is not None:
                await uow.document_types.get(kind)
            fields = await uow.fields.list_all()
            applying = [item for item in fields if kind is None or item.applies_to(kind)]
            values = None if found is None else await document_values(uow, found, kind, applying)
        written = None if values is None else self._written(values)
        try:
            used = self._templates.check(template)
        except ValidationError as invalid:
            return TemplatePreview(error=str(invalid), values=written)
        paths = tuple(sorted(used))
        unknown = unknown_values(used, {item.key for item in applying})
        if unknown:
            return TemplatePreview(used=paths, error=f"unknown value {unknown[0]}", values=written)
        if values is None:
            return TemplatePreview(used=paths)
        try:
            rendered = " ".join(self._templates.render(template, values).split())
        except MissingValueError as missing:
            return TemplatePreview(used=paths, missing=missing.path, values=written)
        except ValidationError as invalid:
            return TemplatePreview(used=paths, error=str(invalid), values=written)
        return TemplatePreview(used=paths, rendered=rendered, values=written)

    def _written(self, values: Mapping[str, TemplateValue]) -> dict[str, str]:
        """Each of a document's values as a template writes it."""
        written: dict[str, str] = {}
        for path, template in writing_templates(values).items():
            try:
                written[path] = self._templates.render(template, values)
            except (MissingValueError, ValidationError):
                continue
        return written

    async def change(
        self,
        actor: UserId,
        id: RuleId,
        definition: RuleDefinition,
        *,
        scope: RuleScope | None = None,
        space: SpaceId | None = None,
        enabled: bool | None = None,
    ) -> Rule:
        """A new version. With `scope` the rule moves (Tobi, 22.10.2026): into the space
        `space`, which the caller edits (None: the caller's personal space), or, by an admin,
        to global; whoever moves it may change it where it is, too. Without `scope` it stays
        where it is. `enabled`: switched on or off with it, in the same transaction (None: as
        it was); the new version is checked either way."""
        async with self._uow() as uow:
            user = await load_actor(uow, actor)
            rule = await _managed_rule(uow, user, id)
            if scope is None:
                if space is not None:
                    raise ValidationError("space_id: give the scope with it")
                rule.change(definition, user.id, self._clock.now())
            else:
                place = await _place(uow, user, scope, space)
                rule.change(definition, user.id, self._clock.now(), scope=scope, space_id=place)
            await check_references(uow, definition, author=user)
            check_patterns(self._patterns, definition)
            await check_templates(uow, self._templates, definition)
            if enabled is True:
                rule.enable(self._clock.now())
            elif enabled is False:
                rule.disable(self._clock.now())
            await uow.rules.update(rule)
            await uow.commit()
        return rule

    async def set_enabled(self, actor: UserId, id: RuleId, enabled: bool) -> Rule:
        """Enabling checks the references again (they may have been deleted meanwhile)."""
        async with self._uow() as uow:
            user = await load_actor(uow, actor)
            rule = await _managed_rule(uow, user, id)
            if enabled:
                await check_references(uow, rule.definition, author=await _author(uow, rule))
                await check_templates(uow, self._templates, rule.definition)
                rule.enable(self._clock.now())
            else:
                rule.disable(self._clock.now())
            await uow.rules.update(rule)
            await uow.commit()
        return rule

    async def delete(self, actor: UserId, id: RuleId) -> None:
        """Soft delete: the rule never runs again, its versions stay readable."""
        async with self._uow() as uow:
            rule = await _managed_rule(uow, await load_actor(uow, actor), id)
            rule.delete(self._clock.now())
            await uow.rules.update(rule)
            await uow.commit()


async def check_references(
    uow: UnitOfWork, definition: RuleDefinition, *, author: User | None
) -> None:
    """Everything the definition refers to exists (NotFoundError otherwise), field
    conditions and values fit their field, tags are of the scope their place asks for (groups
    in the conditions on groups, topics in those on the topic and in "set topic", document
    tags elsewhere; ValidationError), and the rule's `author` may file into the spaces it
    files into, unless one is the personal space of another, active user (handing over;
    PermissionDeniedError; checked again whenever it runs)."""
    references = definition.references()
    for contact in references.contacts:
        await uow.contacts.get(contact)
    for document_type in references.document_types:
        await uow.document_types.get(document_type)
    if references.tags:
        tree = await tag_tree(uow)
        for id in references.tags:
            tree.get(id)
        for id, scope in references.tag_scopes:
            tree.require(id, scope)
    if references.fields:
        fields = await field_definitions(uow)
        for field_id in references.fields:
            if field_id not in fields:
                raise NotFoundError("field", field_id)
        check_fields(definition, fields)
    for space_id in references.spaces:
        space = await uow.spaces.find(space_id)
        if (
            space is not None
            and space.personal_of is not None
            and (author is None or author.active)
        ):
            receiver = await uow.users.find(space.personal_of)
            if receiver is not None and receiver.active:
                continue  # handing over: no membership needed
        role = None if space is None or author is None else space_role(author, space)
        if space is None or role is None:
            raise NotFoundError("space", space_id)
        if not role.can_edit:
            raise SpaceWriteDeniedError(space.id, space.name)


def check_patterns(patterns: PatternMatcher, definition: RuleDefinition) -> None:
    """The regular expressions of the conditions are patterns the matcher that runs them can
    run (ValidationError)."""
    for _, pattern, _ in sorted(definition.patterns()):
        patterns.validate(pattern)


async def check_templates(
    uow: UnitOfWork, templates: TemplateRenderer, definition: RuleDefinition
) -> None:
    """The templates of the actions (title, text field, review reason) are valid and use
    values a template has (ValidationError naming the action)."""
    fields = await uow.fields.list_all()
    keys = {field.key for field in fields}
    for index, template in action_templates(definition, fields):
        try:
            used = templates.check(template)
        except ValidationError as error:
            raise ValidationError(f"actions[{index}]: {error}") from None
        unknown = unknown_values(used, keys)
        if unknown:
            known = ", ".join(name for name in NAMES if name != FIELD)
            raise ValidationError(
                f"actions[{index}]: unknown value {unknown[0]}; templates know {known} and "
                "field.<key> of an existing field"
            )


def action_templates(
    definition: RuleDefinition, fields: Iterable[FieldDefinition]
) -> list[tuple[int, str]]:
    """The templates among the actions, with their place: a title, the value of a text field,
    a review's reason."""
    texts = {field.id for field in fields if field.data_type is FieldType.TEXT}
    found: list[tuple[int, str]] = []
    for index, action in enumerate(definition.actions):
        match action:
            case SetTitle(template=template) | ForceReview(reason=template):
                found.append((index, template))
            case SetField(field_id=field, value=str() as value) if field in texts:
                found.append((index, value))
    return found


def uses_field(
    templates: TemplateRenderer,
    definition: RuleDefinition,
    fields: Iterable[FieldDefinition],
    key: str,
) -> bool:
    """Whether a template of the definition uses the field with `key`."""
    return any(
        field_used(templates.check(template), key)
        for _, template in action_templates(definition, fields)
    )


def renamed_field(
    definition: RuleDefinition, fields: Iterable[FieldDefinition], old: str, new: str
) -> RuleDefinition:
    """The definition with `field.<old>` written `field.<new>` in its templates."""
    texts = {field.id for field in fields if field.data_type is FieldType.TEXT}
    actions = []
    for action in definition.actions:
        match action:
            case SetTitle(template=template):
                action = replace(action, template=rename_field_key(template, old, new))
            case ForceReview(reason=reason):
                action = replace(action, reason=rename_field_key(reason, old, new))
            case SetField(field_id=field, value=str() as value) if field in texts:
                action = replace(action, value=rename_field_key(value, old, new))
        actions.append(action)
    return replace(definition, actions=tuple(actions))


async def visible_rule(uow: UnitOfWork, user: User, id: RuleId) -> Rule:
    """Global rules and the rules of the spaces the caller edits; all rules for admins.
    Includes deleted rules."""
    rule = await uow.rules.find(id)
    if rule is None or not (
        rule.space_id is None or user.is_active_admin or await _edits(uow, user, rule.space_id)
    ):
        raise NotFoundError("rule", id)
    return rule


async def _managed_rule(uow: UnitOfWork, user: User, id: RuleId) -> Rule:
    """The rule, if the user may change, switch or delete it; the rule of a title pattern
    nobody does (ConflictError): it follows its document type."""
    rule = await visible_rule(uow, user, id)
    if rule.deleted_at is not None:
        raise NotFoundError("rule", id)
    if rule.managed_by is not None:
        document_type = await uow.document_types.find(rule.managed_by)
        name = rule.definition.name if document_type is None else document_type.name
        raise ConflictError(because(ReasonCode.RULE_FOLLOWS_TYPE, type=name))
    if user.is_active_admin:
        return rule
    if rule.scope is RuleScope.GLOBAL:
        raise PermissionDeniedError(
            because(ReasonCode.ADMINS_ONLY, action=Action.CHANGE_GLOBAL_RULES.value)
        )
    return rule  # visible: the caller edits its space


async def _author(uow: UnitOfWork, rule: Rule) -> User | None:
    """Who saved the rule's current version, for checking its references; None if their
    account is gone."""
    by = rule.current.created_by
    return None if by is None else await uow.users.find(by)


async def _place(
    uow: UnitOfWork, user: User, scope: RuleScope, space: SpaceId | None
) -> SpaceId | None:
    """Where a rule of `scope` the user makes or moves belongs: global (admins only, no space)
    or the space `space`, which they edit (None: their personal space)."""
    if scope is RuleScope.GLOBAL:
        admin_only(user, Action.MAKE_GLOBAL_RULES)
        if space is not None:
            raise ValidationError("space_id: a global rule belongs to no space")
        return None
    if space is None:
        return (await uow.spaces.get_personal(user.id)).id
    await _edited_space(uow, user, space)
    return space


async def _edits(uow: UnitOfWork, user: User, space: SpaceId) -> bool:
    found = await uow.spaces.find(space)
    role = None if found is None else space_role(user, found)
    return role is not None and role.can_edit


async def _edited_space(uow: UnitOfWork, user: User, id: SpaceId) -> None:
    """NotFoundError unless the user is a member of the space (or an admin),
    PermissionDeniedError unless they edit it."""
    space = await uow.spaces.find(id)
    role = None if space is None else space_role(user, space)
    if space is None or role is None:
        raise NotFoundError("space", id)
    if not role.can_edit:
        raise PermissionDeniedError(
            because(ReasonCode.EDITORS_ONLY, action=Action.MAKE_SPACE_RULES.value)
        )


async def _edited_spaces(uow: UnitOfWork, user: User) -> list[SpaceId]:
    """The spaces the user edits (without the rights of an admin)."""
    return [
        space.id
        for space in await uow.spaces.list_accessible(user.id)
        if space.role_of(user.id) is SpaceRole.EDIT
    ]


async def document_values(
    uow: UnitOfWork,
    document: Document,
    document_type: DocumentTypeId | None,
    fields: Iterable[FieldDefinition],
) -> dict[str, TemplateValue]:
    """The values a template sees of `document` as it is (`templates.template_values`)."""
    contact = None if document.contact_id is None else await uow.contacts.find(document.contact_id)
    kind = None if document_type is None else await uow.document_types.find(document_type)
    space = await uow.spaces.find(document.space_id)
    users = {user.id: user for user in await uow.users.list_all()}
    uploader = None if document.uploaded_by is None else users.get(document.uploaded_by)
    names = {tag.id: tag.name for tag in await uow.tags.list_all()}
    tags = [names[id] for id in document.tag_ids if id in names]
    return template_values(
        document,
        contact=None if contact is None else contact.name,
        document_type=None if kind is None else kind.name,
        space=None if space is None else space_label(space, users),
        uploaded_by=None if uploader is None else uploader.label,
        tags=tags,
        document_date=document.document_date,
        fields=[(item, document.fields.get(item.id)) for item in fields],
        contact_groups=[names[id] for id in (contact.group_ids if contact else ()) if id in names],
        document_type_groups=[names[id] for id in (kind.group_ids if kind else ()) if id in names],
        topic=names.get(document.topic_id) if document.topic_id is not None else None,
    )
