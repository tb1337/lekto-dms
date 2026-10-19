"""SQL adapters on SQLite or Postgres (SQLAlchemy 2 Core, async): unit of work with all
repositories, processing log, outbox and job queue; event bus on the outbox; migrations.

The domain classes are not mapped by an ORM: `tables` defines the tables, the repositories
convert between rows and domain objects explicitly.
"""

from lekto.adapters.outbound.sql.database import Database
from lekto.adapters.outbound.sql.event_bus import SqlEventBus
from lekto.adapters.outbound.sql.migrations import SchemaState, migrate, schema_state
from lekto.adapters.outbound.sql.unit_of_work import SqlUnitOfWork, SqlUnitOfWorkFactory

__all__ = [
    "Database",
    "SchemaState",
    "SqlEventBus",
    "SqlUnitOfWork",
    "SqlUnitOfWorkFactory",
    "migrate",
    "schema_state",
]
