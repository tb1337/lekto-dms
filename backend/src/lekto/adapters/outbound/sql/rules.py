"""Rule repositories on SQL tables: `rules` with the current version number, every version in
`rule_versions` (JSON definitions), the rules of title patterns in `title_pattern_rules`,
applications in `rule_applications`."""

from collections.abc import Collection, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import Row, and_, delete, insert, or_, select, tuple_

from lekto.adapters.outbound.sql import tables as t
from lekto.adapters.outbound.sql.repositories import SqlRepository, Values, via_columns
from lekto.core.domain.errors import NotFoundError
from lekto.core.domain.identity import ViaToken
from lekto.core.domain.ids import (
    DocumentId,
    DocumentTypeId,
    RuleApplicationId,
    RuleId,
    SpaceId,
    UserId,
)
from lekto.core.domain.json_value import JsonValue
from lekto.core.domain.reasons import (
    Reason,
    ReasonCode,
    because,
    reasons_from_json,
    reasons_to_json,
)
from lekto.core.domain.rules import (
    ApplicationStatus,
    Rule,
    RuleApplication,
    RuleScope,
    RuleVersion,
)
from lekto.core.domain.rules_json import definition_from_json, definition_to_json


class SqlRuleRepository(SqlRepository[RuleId, Rule]):
    kind = "rule"
    table = t.rules

    async def add(self, rule: Rule) -> None:
        await super().add(rule)
        await self._store_version(rule.current)
        await self._store_managed(rule)

    async def update(self, rule: Rule) -> None:
        await super().update(rule)
        await self._store_version(rule.current)
        await self._store_managed(rule)

    async def _store_managed(self, rule: Rule) -> None:
        """The link to the document type whose title pattern the rule is, while it lives."""
        links = t.title_pattern_rules
        await self._tx.write(delete(links).where(links.c.rule_id == rule.id))
        if rule.managed_by is not None and rule.deleted_at is None:
            await self._tx.write(
                insert(links).values(document_type_id=rule.managed_by, rule_id=rule.id)
            )

    async def list_for(
        self, *, spaces: Collection[SpaceId] | None, include_global: bool
    ) -> list[Rule]:
        rules = t.rules
        of_spaces = rules.c.scope == RuleScope.SPACE.value
        if spaces is not None:
            of_spaces = and_(of_spaces, rules.c.space_id.in_(list(spaces)))
        scopes = [of_spaces]
        if include_global:
            scopes.append(rules.c.scope == RuleScope.GLOBAL.value)
        return await self._load(and_(rules.c.deleted_at.is_(None), or_(*scopes)))

    async def versions(self, id: RuleId) -> list[RuleVersion]:
        await self.get(id)
        versions = t.rule_versions
        rows = await self._tx.read(
            select(versions).where(versions.c.rule_id == id).order_by(versions.c.number)
        )
        return [_version(row) for row in rows]

    async def get_version(self, id: RuleId, number: int) -> RuleVersion:
        await self.get(id)
        versions = t.rule_versions
        row = (
            await self._tx.read(
                select(versions).where(versions.c.rule_id == id, versions.c.number == number)
            )
        ).first()
        if row is None:
            raise NotFoundError(
                "rule version",
                id,
                because(ReasonCode.RULE_VERSION_NOT_FOUND, number=number, id=str(id)),
            )
        return _version(row)

    async def remove_for_space(self, space: SpaceId) -> int:
        """Versions and applications go with their rule (ON DELETE CASCADE)."""
        result = await self._tx.write(delete(t.rules).where(t.rules.c.space_id == space))
        return int(result.rowcount)

    async def remove_applications_by(self, user: UserId) -> int:
        applications = t.rule_applications
        result = await self._tx.write(delete(applications).where(applications.c.user_id == user))
        return int(result.rowcount)

    async def _entities(self, rows: Sequence[Row[Any]]) -> list[Rule]:
        if not rows:
            return []
        versions = t.rule_versions
        # Only the current versions: older ones are neither needed nor read again.
        current = {
            (row.rule_id, row.number): _version(row)
            for row in (
                await self._tx.read(
                    select(versions).where(
                        tuple_(versions.c.rule_id, versions.c.number).in_(
                            [(row.id, row.current_version) for row in rows]
                        )
                    )
                )
            ).all()
        }
        links = t.title_pattern_rules
        managed = {
            link.rule_id: DocumentTypeId(link.document_type_id)
            for link in (
                await self._tx.read(
                    select(links).where(links.c.rule_id.in_([row.id for row in rows]))
                )
            ).all()
        }
        return [
            Rule(
                id=RuleId(row.id),
                scope=RuleScope(row.scope),
                space_id=None if row.space_id is None else SpaceId(row.space_id),
                current=current[(row.id, row.current_version)],
                enabled=row.enabled,
                disabled_reason=next(
                    iter(reasons_from_json(row.disabled_reasons, row.disabled_reason)), None
                ),
                deleted_at=row.deleted_at,
                created_at=row.created_at,
                updated_at=row.updated_at,
                managed_by=managed.get(row.id),
                version=row.version,
            )
            for row in rows
        ]

    def _values(self, entity: Rule) -> Values:
        reason = entity.disabled_reason
        return {
            "id": entity.id,
            "scope": entity.scope.value,
            "space_id": entity.space_id,
            "current_version": entity.current.number,
            "enabled": entity.enabled,
            "disabled_reason": None if reason is None else reason.text,
            "disabled_reasons": None if reason is None else reasons_to_json([reason]),
            "deleted_at": entity.deleted_at,
            "created_at": entity.created_at,
            "updated_at": entity.updated_at,
            "version": entity.version,
        }

    async def _store_version(self, version: RuleVersion) -> None:
        versions = t.rule_versions
        exists = (
            await self._tx.read(
                select(versions.c.number).where(
                    versions.c.rule_id == version.rule_id, versions.c.number == version.number
                )
            )
        ).first()
        if exists is not None:
            return
        data = definition_to_json(version.definition)
        await self._tx.write(
            insert(versions).values(
                rule_id=version.rule_id,
                number=version.number,
                name=data["name"],
                priority=data["priority"],
                triggers=data["triggers"],
                conditions=data["conditions"],
                actions=data["actions"],
                created_at=version.created_at,
                created_by=version.created_by,
                space_id=version.space_id,
            )
        )


def _version(row: Row[Any]) -> RuleVersion:
    definition = definition_from_json(
        {
            "name": row.name,
            "priority": row.priority,
            "triggers": row.triggers,
            "conditions": row.conditions,
            "actions": row.actions,
        }
    )
    return RuleVersion(
        rule_id=RuleId(row.rule_id),
        number=row.number,
        definition=definition,
        created_at=row.created_at,
        created_by=None if row.created_by is None else UserId(row.created_by),
        space_id=None if row.space_id is None else SpaceId(row.space_id),
    )


class SqlRuleApplicationRepository(SqlRepository[RuleApplicationId, RuleApplication]):
    kind = "rule application"
    table = t.rule_applications

    def _entity(self, row: Row[Any]) -> RuleApplication:
        return RuleApplication(
            id=RuleApplicationId(row.id),
            rule_id=RuleId(row.rule_id),
            rule_version=row.rule_version,
            user_id=UserId(row.user_id),
            documents=tuple(DocumentId(UUID(item)) for item in row.documents),
            via=ViaToken.stored(row.via_token_id, row.via_token_name),
            accept_conflicts=frozenset(DocumentId(UUID(item)) for item in row.accept_conflicts),
            status=ApplicationStatus(row.status),
            position=row.position,
            applied=row.applied,
            unchanged=row.unchanged,
            skipped=[_skipped(item) for item in row.skipped],
            error=row.error,
            created_at=row.created_at,
            finished_at=row.finished_at,
            version=row.version,
        )

    def _values(self, entity: RuleApplication) -> Values:
        # An entry from before codes has the document and the text only.
        skipped: list[JsonValue] = [
            [str(id), reason.text, reason.to_json()] for id, reason in entity.skipped
        ]
        return {
            "id": entity.id,
            "rule_id": entity.rule_id,
            "rule_version": entity.rule_version,
            "user_id": entity.user_id,
            "status": entity.status.value,
            "documents": [str(id) for id in entity.documents],
            **via_columns(entity.via),
            "accept_conflicts": sorted(str(id) for id in entity.accept_conflicts),
            "position": entity.position,
            "applied": entity.applied,
            "unchanged": entity.unchanged,
            "skipped": skipped,
            "error": entity.error,
            "created_at": entity.created_at,
            "finished_at": entity.finished_at,
            "version": entity.version,
        }


def _skipped(item: list[Any]) -> tuple[DocumentId, Reason]:
    """A skipped document of a rule application as stored: id, text and the reason with its
    code (an entry from before codes has the text alone)."""
    reasons = reasons_from_json(item[2:], str(item[1]))
    return DocumentId(UUID(item[0])), reasons[0]
