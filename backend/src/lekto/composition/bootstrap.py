"""The first admin, from `LEKTO_ADMIN_USERNAME` and `LEKTO_ADMIN_PASSWORD[_FILE]`.

Takes effect only while there is no admin at all; afterwards the variables are ignored and no
account is ever changed by them. So configuration cannot be used to take over an account later.
"""

import logging

from lekto.composition.errors import ConfigurationError
from lekto.composition.settings import Settings
from lekto.core.domain.errors import ConflictError, ValidationError
from lekto.core.services.users import UserService

log = logging.getLogger(__name__)


async def ensure_first_admin(users: UserService, settings: Settings) -> None:
    """Create the configured admin if there is no admin. ConfigurationError if the name is
    taken by another user or the password does not meet the policy."""
    if settings.admin_username is None or settings.admin_password is None:
        return
    try:
        created = await users.bootstrap_admin(
            settings.admin_username, settings.admin_password.get_secret_value()
        )
    except ConflictError as error:
        raise ConfigurationError(f"LEKTO_ADMIN_USERNAME: {error}") from None
    except ValidationError as error:
        raise ConfigurationError(f"LEKTO_ADMIN_PASSWORD: {error}") from None
    if created is None:
        log.info("an admin exists; LEKTO_ADMIN_USERNAME and LEKTO_ADMIN_PASSWORD are ignored")
