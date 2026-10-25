"""Table definitions. The domain classes are not mapped: the repositories convert rows
explicitly (`repositories` and the modules by area).

Names that are unique regardless of case are stored twice: as entered, and as `name_key`
(`lekto.core.domain.validation.name_key`, Unicode case folding) with a unique index. The key is
computed in Python, so "Ärzte" and "ärzte" collide on SQLite and Postgres alike, independent of
collations.

The migrations in `migrations/versions` must create exactly these tables; a test compares them.
"""

from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    Double,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    false,
    true,
)

from lekto.adapters.outbound.sql.types import ExactDecimal, UtcDateTime, json_type
from lekto.core.domain.documents import Channel
from lekto.core.domain.jobs import JobStatus
from lekto.core.domain.master_data import Assignment, TagScope

metadata = MetaData(
    naming_convention={
        "ix": "ix_%(table_name)s_%(column_0_N_name)s",
        "uq": "uq_%(table_name)s_%(column_0_N_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)

# Auto-increment primary keys. On SQLite, BIGINT would not become an alias of the rowid.
_SEQUENCE = BigInteger().with_variant(Integer(), "sqlite")

# Job statuses that block another job with the same dedup key.
ACTIVE_JOB_STATUSES = tuple(status.value for status in JobStatus if status.is_active)

users = Table(
    "users",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("username", Text, nullable=False),
    Column("username_key", Text, nullable=False, unique=True),
    Column("role", Text, nullable=False),
    Column("created_at", UtcDateTime, nullable=False),
    Column("active", Boolean, nullable=False, server_default=true()),
    Column("version", Integer, nullable=False),
    # How others see the user; unique regardless of case, also against the aliases of others
    # (checked by the service).
    Column("display_name", Text, nullable=True),
    Column("display_name_key", Text, nullable=True, unique=True, index=True),
)

# The private part of a user: birth date and e-mail, with their aliases and identifiers.
user_profiles = Table(
    "user_profiles",
    metadata,
    Column("user_id", Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("birth_date", Date, nullable=True),
    Column("email", Text, nullable=True),
    Column("version", Integer, nullable=False),
)

# Other names of a user (a maiden name); unique per user only: an alias is private, a conflict
# would tell whose it is.
user_aliases = Table(
    "user_aliases",
    metadata,
    Column("user_id", Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("name", Text, nullable=False),
    Column("name_key", Text, primary_key=True),
    Column("position", Integer, nullable=False),
)

# A person's own numbers (IBAN, tax ID, ...). Several users may hold one (a joint account); a
# contact never (checked by the services).
user_identifiers = Table(
    "user_identifiers",
    metadata,
    Column("user_id", Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("kind", Text, primary_key=True),
    Column("value", Text, primary_key=True),
    Index("ix_user_identifiers_kind_value", "kind", "value"),
)

spaces = Table(
    "spaces",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("name", Text, nullable=False),
    Column("name_key", Text, nullable=False),
    # The user whose personal space it is (`Space.personal_of`); None for every other space.
    Column("personal_of", Uuid, ForeignKey("users.id"), nullable=True, unique=True),
    # What belongs in the space, for the language model (`Space.description`).
    Column("description", Text, nullable=True),
    Column("created_at", UtcDateTime, nullable=False),
    Column("version", Integer, nullable=False),
)
# Names are unique among the spaces that are nobody's personal one.
Index(
    "uq_spaces_name_key",
    spaces.c.name_key,
    unique=True,
    sqlite_where=spaces.c.personal_of.is_(None),
    postgresql_where=spaces.c.personal_of.is_(None),
)

space_members = Table(
    "space_members",
    metadata,
    Column("space_id", Uuid, ForeignKey("spaces.id", ondelete="CASCADE"), primary_key=True),
    Column("user_id", Uuid, ForeignKey("users.id"), primary_key=True, index=True),
    Column("role", Text, nullable=False),  # `SpaceRole`
)


def _master_data(name: str, *columns: Column[Any]) -> Table:
    return Table(
        name,
        metadata,
        Column("id", Uuid, primary_key=True),
        Column("name", Text, nullable=False),
        Column("name_key", Text, nullable=False, unique=True),
        *columns,
        Column("created_at", UtcDateTime, nullable=False),
        Column("version", Integer, nullable=False),
    )


contacts = _master_data(
    "contacts",
    # The stored logo (`objects.logo_key`): `uploaded` or `fetched` (`LogoSource`), the domain
    # of a fetched one, when it was stored; none without a logo.
    Column("logo_source", Text, nullable=True),
    Column("logo_domain", Text, nullable=True),
    Column("logo_stored_at", UtcDateTime, nullable=True),
    # The domains whose fetch found no logo (apart by spaces) and when the last did.
    Column("logo_failed_domains", Text, nullable=True),
    Column("logo_failed_at", UtcDateTime, nullable=True),
)
document_types = _master_data(
    "document_types",
    Column("description", Text, nullable=True),
    # A pattern the title of the type's documents is rendered from (see `domain.titles`).
    Column("title_pattern", Text, nullable=True),
    # The name of a Lucide icon.
    Column("icon", Text, nullable=True),
)
# Names are unique per scope (a contact group may be named like a document tag).
tags = Table(
    "tags",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("name", Text, nullable=False),
    Column("name_key", Text, nullable=False),
    # `document`, `contact` (a contact group), `document_type` (a type group) or `topic`:
    # `TagScope`.
    Column("scope", Text, nullable=False, server_default=TagScope.DOCUMENT.value),
    # The tag it is nested under, of the same scope (checked by the service, as cycles are).
    Column("parent_id", Uuid, ForeignKey("tags.id"), nullable=True, index=True),
    # `auto` (classification proposes it) or `manual` (`Assignment`; groups always).
    Column("assignment", Text, nullable=False, server_default=Assignment.AUTO.value),
    # Whether documents show it.
    Column("shown", Boolean, nullable=False, server_default=true()),
    # The name of a Lucide icon; a colour of the palette or `#rrggbb`.
    Column("icon", Text, nullable=True),
    Column("color", Text, nullable=True),
    Column("created_at", UtcDateTime, nullable=False),
    Column("version", Integer, nullable=False),
    UniqueConstraint("scope", "name_key"),
)

# The groups a contact or a document type is in (tags of scope `contact`, `document_type`).
contact_groups = Table(
    "contact_groups",
    metadata,
    Column("contact_id", Uuid, ForeignKey("contacts.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", Uuid, ForeignKey("tags.id"), primary_key=True, index=True),
)
document_type_groups = Table(
    "document_type_groups",
    metadata,
    Column(
        "document_type_id",
        Uuid,
        ForeignKey("document_types.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("tag_id", Uuid, ForeignKey("tags.id"), primary_key=True, index=True),
)
# The topics a contact enables (tags of scope `topic`).
contact_topics = Table(
    "contact_topics",
    metadata,
    Column("contact_id", Uuid, ForeignKey("contacts.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", Uuid, ForeignKey("tags.id"), primary_key=True, index=True),
)

# Other names of a contact; unique across contacts. That no alias is another contact's name is
# checked by the service.
contact_aliases = Table(
    "contact_aliases",
    metadata,
    Column(
        "contact_id",
        Uuid,
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    Column("name", Text, nullable=False),
    Column("name_key", Text, primary_key=True),
    # The order in which the aliases were given.
    Column("position", Integer, nullable=False),
)

# The trained classifiers; the models themselves are files in the object store.
classifier_models = Table(
    "classifier_models",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("number", Integer, nullable=False, unique=True),
    Column("trained_at", UtcDateTime, nullable=False),
    Column("examples", Integer, nullable=False),
    Column("examples_until", UtcDateTime, nullable=True),
    Column("object_key", Text, nullable=False),
    Column("summary", json_type(), nullable=False),
    Column("version", Integer, nullable=False),
)

# Values a contact's documents carry (IBAN, VAT number, ...); kind and value are unique across
# contacts. `source`: entered by hand, learned by training, or learned and rejected. `topic_id`:
# the contact's topic it points to (one the contact enables, checked by the domain); `user_id`:
# the user it names.
contact_identifiers = Table(
    "contact_identifiers",
    metadata,
    Column(
        "contact_id",
        Uuid,
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    Column("kind", Text, primary_key=True),
    Column("value", Text, primary_key=True),
    Column("source", Text, nullable=False),
    Column("topic_id", Uuid, ForeignKey("tags.id"), nullable=True),
    # The user a customer or personnel number belongs to, if one does; it goes with them.
    Column("user_id", Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
    # A learned one: the ids of the spaces it was learned in (a JSON list; null: none).
    Column("learned_in", json_type(), nullable=True),
)

field_definitions = Table(
    "field_definitions",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("name", Text, nullable=False),
    Column("name_key", Text, nullable=False, unique=True),
    Column("data_type", Text, nullable=False),
    # False: the field applies to the types in `field_document_types` only (maybe none).
    Column("is_global", Boolean, nullable=False),
    # Whether a global field is required (typed ones: `field_document_types.required`).
    Column("required", Boolean, nullable=False, server_default=false()),
    Column("choices", json_type(), nullable=False),
    # What belongs in the field, for the language model.
    Column("description", Text, nullable=True),
    # `auto` (the language model reads it) or `manual` (set by hand only, `Assignment`).
    Column("assignment", Text, nullable=False, server_default=Assignment.AUTO.value),
    Column("created_at", UtcDateTime, nullable=False),
    Column("version", Integer, nullable=False),
)

field_document_types = Table(
    "field_document_types",
    metadata,
    Column(
        "field_id",
        Uuid,
        ForeignKey("field_definitions.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("document_type_id", Uuid, ForeignKey("document_types.id"), primary_key=True),
    # Whether the field is required for documents of the type; assignments made before
    # revision 0013 were.
    Column("required", Boolean, nullable=False, server_default=true()),
)

documents = Table(
    "documents",
    metadata,
    Column("id", Uuid, primary_key=True),
    # Who uploaded it (`Document.uploaded_by`): information only; cleared with their account.
    Column(
        "uploaded_by", Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    ),
    Column("space_id", Uuid, ForeignKey("spaces.id"), nullable=False, index=True),
    Column("sha256", String(64), nullable=False),
    Column("title", Text, nullable=False),
    # The title as lists sort it (`sort_key`): case and accents aside.
    Column("title_key", Text, nullable=False, server_default=""),
    Column("original_filename", Text, nullable=False),
    Column("media_type", Text, nullable=False),
    Column("contact_id", Uuid, ForeignKey("contacts.id"), nullable=True, index=True),
    Column("document_type_id", Uuid, ForeignKey("document_types.id"), nullable=True, index=True),
    # A tag of scope `topic` the contact enables (checked by the services).
    Column("topic_id", Uuid, ForeignKey("tags.id"), nullable=True, index=True),
    Column("document_date", Date, nullable=True),
    # Intake channel (`Channel`); documents from before M7 count as `api`.
    Column("channel", Text, nullable=False, server_default=Channel.API.value),
    Column("lane", Text, nullable=True, index=True),
    # The lane the first processing run ended in (`Document.first_lane`), for reports; unknown
    # for documents from before revision 0036 whose log does not tell.
    Column("first_lane", Text, nullable=True),
    Column("processing_status", Text, nullable=False),
    Column("processing_run", Integer, nullable=False),
    # State of every node in the current run: {node: {status, outcome, started_at, finished_at}},
    # a delegated node with its `deadline`.
    # The default is for the column's addition (revision 0010); every row is written in full.
    Column("processing_nodes", json_type(), nullable=False, server_default="{}"),
    # The current run reads the pages with the vision language model (`Processing.vision`).
    Column("processing_vision", Boolean, nullable=False, server_default=false()),
    # What decides whether the current run makes the document new (`Processing.baseline`,
    # `Processing.decided`); runs started before revision 0030 have no baseline.
    Column("processing_baseline", Text, nullable=True),
    Column("processing_decided", Boolean, nullable=False, server_default=false()),
    # Set once the pages node rendered the page images.
    Column("page_count", Integer, nullable=True),
    # When a person last set or confirmed the metadata (see `Document.confirmed_at`).
    Column("confirmed_at", UtcDateTime, nullable=True, index=True),
    # When a person last decided its space (see `Document.space_confirmed_at`).
    Column("space_confirmed_at", UtcDateTime, nullable=True),
    # When processing last made it new for the inbox (see `Document.new_at`). No index: most
    # green documents keep it, and the inbox queries go by space and lane with the viewer's
    # seen marks.
    Column("new_at", UtcDateTime, nullable=True),
    Column("created_at", UtcDateTime, nullable=False),
    Column("updated_at", UtcDateTime, nullable=False),
    Column("version", Integer, nullable=False),
    # Every file exists once per installation, also against concurrent uploads.
    Index(None, "sha256", unique=True),
    # Lists sorted by date, title or when documents came in page by these and the id.
    Index(None, "document_date", "id"),
    Index(None, "title_key", "id"),
    Index(None, "created_at", "id"),
)

document_tags = Table(
    "document_tags",
    metadata,
    Column("document_id", Uuid, ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", Uuid, ForeignKey("tags.id"), primary_key=True, index=True),
)

# One typed column per kind of value; `kind` says which one is set and how to read it.
document_fields = Table(
    "document_fields",
    metadata,
    Column("document_id", Uuid, ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True),
    Column("field_id", Uuid, ForeignKey("field_definitions.id"), primary_key=True, index=True),
    Column("kind", Text, nullable=False),  # `documents.ValueKind`
    Column("value_text", Text, nullable=True),
    Column("value_decimal", ExactDecimal, nullable=True),
    Column("value_currency", String(3), nullable=True),
    Column("value_date", Date, nullable=True),  # also a period's start
    Column("value_date_end", Date, nullable=True),  # a period's end
    Column("value_boolean", Boolean, nullable=True),
)

# What the facts signal last found a document to show, in its text or its codes (kind and
# normalised value of an identifier): on how many contacts' confirmed documents a value stands.
document_identifiers = Table(
    "document_identifiers",
    metadata,
    Column(
        "document_id",
        Uuid,
        ForeignKey("documents.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("kind", Text, primary_key=True),
    Column("value", Text, primary_key=True),
    Index(None, "kind", "value"),
)

processing_log = Table(
    "processing_log",
    metadata,
    Column("seq", _SEQUENCE, primary_key=True, autoincrement=True),
    Column(
        "document_id",
        Uuid,
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    Column("node", Text, nullable=False),
    Column("run", Integer, nullable=False),
    Column("outcome", Text, nullable=False),
    Column("reason", Text, nullable=True),
    # The reasons with their codes (`Reason.to_json`); null in entries from before them.
    Column("reasons", json_type(), nullable=True),
    Column("confidence", Double, nullable=True),
    Column("model_version", Text, nullable=True),
    Column("input", json_type(), nullable=False),
    Column("output", json_type(), nullable=False),
    Column("pipeline_version", Text, nullable=False),
    Column("started_at", UtcDateTime, nullable=False),
    Column("duration_us", BigInteger, nullable=False),
)

# --- what processing facts keep (`domain.first_runs`): rows go with their document --------------

# A document's first run: when its receiving began, when the run first stopped, and how long each
# node worked in it (JSON: node to microseconds).
first_runs = Table(
    "first_runs",
    metadata,
    Column("document_id", Uuid, ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True),
    Column("started_at", UtcDateTime, nullable=False),
    Column("stopped_at", UtcDateTime, nullable=False, index=True),
    Column("steps", json_type(), nullable=False),
)

# A person's verdict on a field of a document, at their first decision on it; per signal (a
# column named as its node) whether it named the person's value, another (false) or none (null).
field_verdicts = Table(
    "field_verdicts",
    metadata,
    Column("document_id", Uuid, ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True),
    Column("field", Text, primary_key=True),
    Column("verdict", Text, nullable=False),
    Column("decided_at", UtcDateTime, nullable=False, index=True),
    Column("decision", Text, nullable=False),
    Column("signal_llm", Boolean, nullable=True),
    Column("signal_classifier", Boolean, nullable=True),
    Column("signal_neighbours", Boolean, nullable=True),
    Column("signal_facts", Boolean, nullable=True),
)

# --- the inbox (`domain.inbox`): rows go with their document ------------------------------------

# When a user saw a document last; it is new for them again once it became new after
# (`documents.new_at`). The rows also go with their user.
inbox_seen = Table(
    "inbox_seen",
    metadata,
    Column("user_id", Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column(
        "document_id",
        Uuid,
        ForeignKey("documents.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    ),
    Column("seen_at", UtcDateTime, nullable=False),
    # Set by a move for someone who knew the document already: it is not new for them, but
    # they did not look at it, so it does not stand under done.
    Column("silent", Boolean, nullable=False, server_default=false()),
)

# Who confirmed a document out of yellow or red last, and when: for "done", removed by the
# cleanup after `DONE_PERIOD`. `confirmed_by` has no foreign key: the account may be deleted,
# the record stays.
inbox_confirmations = Table(
    "inbox_confirmations",
    metadata,
    Column("document_id", Uuid, ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True),
    Column("confirmed_by", Uuid, nullable=False),
    Column("confirmed_at", UtcDateTime, nullable=False, index=True),
)

# --- rules --------------------------------------------------------------------------------------

# A rule and the number of its current version; the definitions are in `rule_versions`.
rules = Table(
    "rules",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("scope", Text, nullable=False),
    # The space a space rule belongs to; None for global rules. Its rules go with the space.
    Column(
        "space_id", Uuid, ForeignKey("spaces.id", ondelete="CASCADE"), nullable=True, index=True
    ),
    Column("current_version", Integer, nullable=False),
    Column("enabled", Boolean, nullable=False),
    Column("disabled_reason", Text, nullable=True),
    # The same with its code (`Reason.to_json`, a list of one); null before revision 0039.
    Column("disabled_reasons", json_type(), nullable=True),
    Column("deleted_at", UtcDateTime, nullable=True),
    Column("created_at", UtcDateTime, nullable=False),
    Column("updated_at", UtcDateTime, nullable=False),
    Column("version", Integer, nullable=False),
)

# Every version of a rule; never changed once written. `created_by` has no foreign key: the
# author may be deleted, the version stays.
rule_versions = Table(
    "rule_versions",
    metadata,
    Column("rule_id", Uuid, ForeignKey("rules.id", ondelete="CASCADE"), primary_key=True),
    Column("number", Integer, primary_key=True),
    Column("name", Text, nullable=False),
    Column("priority", Integer, nullable=False),
    Column("triggers", json_type(), nullable=False),
    Column("conditions", json_type(), nullable=False),
    Column("actions", json_type(), nullable=False),
    Column("created_at", UtcDateTime, nullable=False),
    Column("created_by", Uuid, nullable=True),
    # The space the rule belonged to with this version (None: global); no foreign key, the
    # history keeps it after the space is gone.
    Column("space_id", Uuid, nullable=True),
)

# The rule of a document type's title pattern (`Rule.managed_by`), while it is not deleted.
title_pattern_rules = Table(
    "title_pattern_rules",
    metadata,
    Column(
        "document_type_id",
        Uuid,
        ForeignKey("document_types.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "rule_id",
        Uuid,
        ForeignKey("rules.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    ),
)

rule_applications = Table(
    "rule_applications",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("rule_id", Uuid, ForeignKey("rules.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("rule_version", Integer, nullable=False),
    Column("user_id", Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("status", Text, nullable=False),
    Column("documents", json_type(), nullable=False),
    Column("accept_conflicts", json_type(), nullable=False),
    Column("position", Integer, nullable=False),
    Column("applied", Integer, nullable=False),
    Column("unchanged", Integer, nullable=False),
    Column("skipped", json_type(), nullable=False),
    Column("error", Text, nullable=True),
    Column("created_at", UtcDateTime, nullable=False),
    Column("finished_at", UtcDateTime, nullable=True),
    Column("version", Integer, nullable=False),
)

jobs = Table(
    "jobs",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("kind", Text, nullable=False),
    Column("payload", json_type(), nullable=False),
    Column("dedup_key", Text, nullable=True),
    Column("status", Text, nullable=False),
    Column("attempts", Integer, nullable=False),
    # Claims given back unfinished; they do not count against the retry policy.
    Column("releases", Integer, nullable=False, server_default="0"),
    Column("run_at", UtcDateTime, nullable=False),
    Column("locked_until", UtcDateTime, nullable=True),
    Column("last_error", Text, nullable=True),
    # Set only while the job is queued: claiming clears it (`Job.coalesce_key`).
    Column("coalesce_key", Text, nullable=True),
    # When the latest claim took it, when it was done or given up, and what a done job reports
    # (`Job.result`); none in jobs from before revision 0041.
    Column("started_at", UtcDateTime, nullable=True),
    Column("finished_at", UtcDateTime, nullable=True),
    Column("result", json_type(), nullable=True),
    Index(None, "status", "run_at"),
    # The durations of the jobs done lately (`JobQueue.finished`).
    Index(None, "finished_at"),
    # Claims of running jobs whose lease ran out.
    Index(None, "status", "locked_until"),
)
# At most one queued or running job per dedup key.
Index(
    "uq_jobs_active_dedup_key",
    jobs.c.dedup_key,
    unique=True,
    sqlite_where=jobs.c.status.in_(ACTIVE_JOB_STATUSES),
    postgresql_where=jobs.c.status.in_(ACTIVE_JOB_STATUSES),
)
# At most one queued job per coalesce key (only queued jobs carry one).
Index("uq_jobs_coalesce_key", jobs.c.coalesce_key, unique=True)

# Committed domain events. `seq` follows commit order (see `unit_of_work`); on SQLite,
# AUTOINCREMENT keeps it from reusing the numbers of deleted rows.
outbox = Table(
    "outbox",
    metadata,
    Column("seq", _SEQUENCE, primary_key=True, autoincrement=True),
    Column("event_id", Uuid, nullable=False, unique=True),
    Column("type", Text, nullable=False),
    Column("occurred_at", UtcDateTime, nullable=False),
    Column("payload", json_type(), nullable=False),
    # When the event was written (system time); places new subscriptions, see `event_bus`.
    Column("recorded_at", UtcDateTime, nullable=False, index=True),
    sqlite_autoincrement=True,
)

# Durable subscriptions: every event with `seq <= position` has been handled; failed ones wait
# in `event_retries` until `retry_at`.
event_subscriptions = Table(
    "event_subscriptions",
    metadata,
    Column("name", Text, primary_key=True),
    Column("position", BigInteger, nullable=False),
    Column("created_at", UtcDateTime, nullable=False),
)

event_retries = Table(
    "event_retries",
    metadata,
    Column(
        "subscriber",
        Text,
        ForeignKey("event_subscriptions.name", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("seq", _SEQUENCE, ForeignKey("outbox.seq", ondelete="CASCADE"), primary_key=True),
    Column("attempts", Integer, nullable=False),
    Column("last_error", Text, nullable=False),
    # When the delivery is due again; NULL: at once.
    Column("retry_at", UtcDateTime, nullable=True, index=True),
)

# --- identity: rows go with their user (ON DELETE CASCADE) ---------------------------------------

credentials = Table(
    "credentials",
    metadata,
    Column("user_id", Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("password_hash", Text, nullable=True),
    Column("password_changed_at", UtcDateTime, nullable=True),
    # TOTP: the secret encrypted (SecretCipher); NULL if TOTP is off.
    Column("totp_secret", LargeBinary, nullable=True),
    Column("totp_confirmed", Boolean, nullable=False),
    Column("totp_last_step", BigInteger, nullable=True),
    Column("version", Integer, nullable=False),
)

recovery_codes = Table(
    "recovery_codes",
    metadata,
    Column(
        "user_id",
        Uuid,
        ForeignKey("credentials.user_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("code_hash", String(64), primary_key=True),
)

sessions = Table(
    "sessions",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("user_id", Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("token_hash", String(64), nullable=False, unique=True),
    Column("method", Text, nullable=False),
    Column("created_at", UtcDateTime, nullable=False),
    Column("last_seen_at", UtcDateTime, nullable=False, index=True),
    Column("expires_at", UtcDateTime, nullable=False, index=True),
    Column("version", Integer, nullable=False),
)

api_tokens = Table(
    "api_tokens",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("user_id", Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("name", Text, nullable=False),
    Column("scope", Text, nullable=False),
    Column("token_hash", String(64), nullable=False, unique=True),
    Column("created_at", UtcDateTime, nullable=False),
    Column("expires_at", UtcDateTime, nullable=True),
    Column("last_used_at", UtcDateTime, nullable=True),
    Column("version", Integer, nullable=False),
)

external_identities = Table(
    "external_identities",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("issuer", Text, nullable=False),
    Column("subject", Text, nullable=False),
    Column("user_id", Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("created_at", UtcDateTime, nullable=False),
    Column("version", Integer, nullable=False),
    Index(None, "issuer", "subject", unique=True),
)

# Failed sign-ins per key (`account:<name>`, `source:<address>`).
login_failures = Table(
    "login_failures",
    metadata,
    Column("key", Text, primary_key=True),
    Column("failures", Integer, nullable=False),
    Column("first_failure_at", UtcDateTime, nullable=False),
    Column("blocked_until", UtcDateTime, nullable=True),
    Column("version", Integer, nullable=False),
)

# --- webhooks: rows go with their owner (ON DELETE CASCADE) ---------------------------------------

webhooks = Table(
    "webhooks",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "owner_id", Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    ),
    Column("name", Text, nullable=False),
    Column("url", Text, nullable=False),
    Column("event_types", json_type(), nullable=False),
    # The signing secrets as `SecretCipher` made them, none if the webhook does not sign; the
    # previous one only during the grace period after renewing.
    Column("secret", LargeBinary, nullable=True),
    # The webhook's own headers: their names (a JSON list, in order) and their values
    # (`webhooks.headers_to_bytes`, encrypted; NULL without headers).
    Column("header_names", json_type(), nullable=False, server_default="[]"),
    Column("headers", LargeBinary, nullable=True),
    # What the requests carry (`webhooks.BodyFormat`), and the template of a `template` body.
    Column("body", Text, nullable=False, server_default="thin"),
    Column("body_template", Text, nullable=True),
    Column("previous_secret", LargeBinary, nullable=True),
    Column("previous_valid_until", UtcDateTime, nullable=True),
    # How many tasks the webhook takes at the same time (`Webhook.max_open_tasks`).
    Column("max_open_tasks", Integer, nullable=False, server_default="4"),
    # The model call the webhook serves as (`webhooks.ModelCallKind`) and its consumer's time
    # to answer; both NULL for none.
    Column("model_call", Text, nullable=True),
    Column("model_call_timeout_seconds", Integer, nullable=True),
    Column("active", Boolean, nullable=False),
    Column("disabled_reason", Text, nullable=True),
    Column("failed_streak", Integer, nullable=False),
    Column("created_at", UtcDateTime, nullable=False),
    Column("updated_at", UtcDateTime, nullable=False),
    Column("version", Integer, nullable=False),
)

# A user's lenses (`domain.lenses`). The filter and the card fields are JSON; the ids in them
# have no foreign keys: master data may go, and the services drop what is gone.
lenses = Table(
    "lenses",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("owner_id", Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("name", Text, nullable=False),
    Column("name_key", Text, nullable=False),
    Column("position", Integer, nullable=False),
    Column("filter", json_type(), nullable=False),
    Column("query", Text, nullable=True),
    Column("sort", Text, nullable=True),
    Column("sort_field_id", Uuid, nullable=True),
    Column("grouping", Text, nullable=False),
    Column("layout", Text, nullable=False),
    Column("card_field_ids", json_type(), nullable=False),
    Column("due_field_id", Uuid, nullable=True),
    Column("created_at", UtcDateTime, nullable=False),
    Column("updated_at", UtcDateTime, nullable=False),
    Column("version", Integer, nullable=False),
    Index(None, "owner_id", "name_key", unique=True),
)

# The log of delivery attempts. The answer of the receiver is not kept. `document_id` has no
# foreign key: the document may be deleted while its log lives on.
webhook_deliveries = Table(
    "webhook_deliveries",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("webhook_id", Uuid, ForeignKey("webhooks.id", ondelete="CASCADE"), nullable=False),
    Column("event_id", Uuid, nullable=False),
    Column("event_type", Text, nullable=False),
    Column("document_id", Uuid, nullable=True),
    Column("attempt", Integer, nullable=False),
    Column("started_at", UtcDateTime, nullable=False),
    Column("duration_ms", Integer, nullable=False),
    Column("outcome", Text, nullable=False),
    Column("status_code", Integer, nullable=True),
    Column("error", Text, nullable=True),
    Column("next_attempt_at", UtcDateTime, nullable=True),
    Index(None, "webhook_id", "id"),
    Index(None, "started_at"),
)

# Tasks (`domain.tasks`): requests through a webhook that expect an answer. No foreign keys:
# a task outlives its webhook (it runs to its deadline) and its document (a late answer is
# refused as stale). `step` names the rule step that asks (JSON), `reason` why a task did not
# get its answer (a reason's JSON); `request` is the request with the one-time token,
# encrypted, until it is delivered; `token_hash` stays.
tasks = Table(
    "tasks",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("kind", Text, nullable=False),
    Column("document_id", Uuid, nullable=False),
    Column("node", Text, nullable=False),
    Column("run", Integer, nullable=False),
    Column("webhook_id", Uuid, nullable=False),
    Column("owner_id", Uuid, nullable=False),
    Column("step", json_type(), nullable=True),
    Column("timeout_seconds", Integer, nullable=False),
    Column("status", Text, nullable=False),
    Column("token_hash", Text, nullable=True),
    Column("request", LargeBinary, nullable=True),
    # What the node needs to read the answer (`Task.context`), a JSON object.
    Column("context", json_type(), nullable=False, server_default="{}"),
    Column("answer", json_type(), nullable=True),
    Column("producer", Text, nullable=True),
    Column("reason", json_type(), nullable=True),
    Column("created_at", UtcDateTime, nullable=False),
    Column("opened_at", UtcDateTime, nullable=True),
    Column("deadline", UtcDateTime, nullable=True),
    Column("settled_at", UtcDateTime, nullable=True),
    Column("version", Integer, nullable=False),
    Index(None, "document_id", "node", "run"),
    Index(None, "webhook_id", "status", "created_at"),
    Index(None, "settled_at"),
)
