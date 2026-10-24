"""Who sees a contact's identifier (issue #82, Tobi 24.10.2026: "wenn Datenschutz dann
richtig")."""

from collections.abc import Collection

from lekto.core.domain.identifiers.identifier import Identifier, IdentifierSource
from lekto.core.domain.ids import SpaceId, UserId


def seen_by(identifier: Identifier, user: UserId, spaces: Collection[SpaceId]) -> bool:
    """Whether `user`, no admin, sees a contact's identifier (`spaces`: those they are a member
    of): one entered by hand that names nobody everyone; one that names a user only that user;
    a learned one whoever is a member of a space it was learned in; a rejected one nobody."""
    if identifier.source is IdentifierSource.REJECTED:
        return False
    if identifier.user_id is not None:
        return identifier.user_id == user
    if identifier.source is IdentifierSource.LEARNED:
        return not identifier.learned_in.isdisjoint(spaces)
    return True
