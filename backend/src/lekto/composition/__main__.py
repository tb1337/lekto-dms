"""`lekto [--env-file FILE] [check | migrate | check-schema | api | worker | evaluate |
evaluate-search | reindex | render-pages | read-facts | relate | fetch-logos | reparse |
train]`, the command line of Lekto (`[project.scripts]`; also `python -m lekto.composition`).

The settings come from the `LEKTO_` environment variables, in the image from the container's
environment. `--env-file FILE` takes them from a file of `KEY=value` lines instead
(`env_file`), for the development instance in the devcontainer. As root, `lekto` warns and
stops (in the image: `lekto-run lekto ...` runs it as `PUID:PGID`), unless `PUID=0` says root is
meant.

- `check` (default): validate the configuration and print it without secrets.
- `migrate`: validate, then bring the configured database to the newest schema. Run before the
  API and the worker start (in the image: `init-migrations`).
- `check-schema [--wait SECONDS]`: exit 0 if the database is at the newest schema of this
  version, otherwise 1; with `--wait`, keep looking for that long while it is older or not
  reachable. Never changes the database. The worker's start in the image waits with it for the
  API container's migration.
- `api`: serve the REST API until SIGTERM or SIGINT. Only with `LEKTO_ROLE` `all` or `api`.
- `worker`: run the worker service until SIGTERM or SIGINT. Only with `LEKTO_ROLE` `all` or
  `worker`.
- `evaluate [--fake] [--runs cold,trained] [--cases DIR] [--output FILE]`: run the evaluation
  set (default `evaluation`) against the configured language model, or with `--fake` against
  the set's fixed answers, cold and trained (after taking over its training corpus and
  training the classifier on it), or only the runs given, and write a Markdown report. Exits
  with status 1 if a document came out green that should not have or with a wrong value, or a
  field changed without a passed check.
- `evaluate-search [--fake] [--models A,B] [--ratios 0,0.5,1] [--queries FILE] [--cases DIR]
  [--output FILE]`: index the documents of the evaluation set with each embedding model (default
  `LEKTO_EMBEDDING_MODEL`) in a temporary Meilisearch index, run the queries (default
  `<cases>/search/queries.json`) at each semantic ratio and write a Markdown report. With
  `--fake`, bag-of-words vectors and the in-memory index stand in for both. Needs
  `LEKTO_MEILISEARCH_URL` and `LEKTO_EMBEDDING_BASE_URL`, and `LEKTO_EMBEDDING_DIMENSIONS` (any
  value; the real length is measured) as the configuration is checked first.
- `reindex`: rebuild the search index from the database and the object store, in the foreground,
  with progress. The search keeps working meanwhile. Needs `LEKTO_MEILISEARCH_URL`.
- `render-pages`: queue the page images of every document from before the pages node existed
  (its `pages` node is skipped); the worker renders them.
- `read-facts`: queue reading the facts of every document with a text again: the worker reads
  the codes on its pages and the identifiers its text shows, with whose an IBAN or a creditor
  ID is (after an update that reads facts differently, and for telling on how many contacts'
  documents an identifier stands).
- `relate`: queue finding the relations of every document not being processed: the worker
  relates it with the documents it refers to and those that refer to it (for documents from
  before the node `relate`, and after a document type became a relation target).
- `fetch-logos`: queue fetching the logo of every contact without one that has a domain entered
  among its identifiers (one whose fetch failed is not tried again); the worker asks the websites.
  Needs `LEKTO_LOGO_FETCH=true`.
- `reparse`: queue reading the text of every document again (after the update to 0.2, which
  reads the text as it is set instead of Docling's Markdown); the worker reads them, and the
  search index takes up the new texts. Train the classifier afterwards (`train`).
- `train`: train the classifier from the confirmed documents now, in the foreground, and learn
  identifiers of contacts from them (the worker does it on its own after enough confirmations).

Options follow their command. Exits with status 1 when the command fails: with the message on
stderr when the configuration (or the evaluation set) does not let it work, otherwise with the
error in the log, as when the command does not fit `LEKTO_ROLE`.
"""

import argparse
import asyncio
import os
import sys
from collections.abc import Callable, Coroutine, Mapping, Sequence
from pathlib import Path

import structlog

from lekto.adapters.inbound.evaluation import EvaluationSetError, Run
from lekto.adapters.outbound.sql import SchemaState
from lekto.composition.api import run_api
from lekto.composition.database import check_schema, migrate_database
from lekto.composition.endpoints import external_endpoints
from lekto.composition.env_file import apply_env_file
from lekto.composition.errors import ConfigurationError
from lekto.composition.evaluation import run_evaluation
from lekto.composition.facts import run_read_facts
from lekto.composition.logging_setup import configure_logging
from lekto.composition.logos import run_fetch_logos
from lekto.composition.pages import run_render_pages
from lekto.composition.reindex import run_reindex
from lekto.composition.relate import run_relate
from lekto.composition.reparse import run_reparse
from lekto.composition.search_evaluation import (
    DEFAULT_RATIOS,
    parse_ratios,
    run_search_evaluation,
)
from lekto.composition.settings import (
    API_ROLES,
    WORKER_ROLES,
    Settings,
    find_unknown_variables,
    load_settings,
)
from lekto.composition.train import run_training
from lekto.composition.worker import run_worker

log = structlog.get_logger("lekto.composition")

# Services and the roles that run them.
SERVICES = {"api": API_ROLES, "worker": WORKER_ROLES}

type Command = Callable[[Settings, argparse.Namespace], int]


def main(argv: Sequence[str] = ()) -> int:
    arguments = _parser().parse_args(argv)
    command: str = arguments.command or "check"

    if _as_root():
        print(ROOT_WARNING, file=sys.stderr)
        return 1
    try:
        if arguments.env_file is not None:
            apply_env_file(arguments.env_file)
        settings = load_settings()
    except ConfigurationError as error:
        print(error, file=sys.stderr)
        return 1

    configure_logging(settings)
    for variable in find_unknown_variables():
        log.warning("unknown configuration variable", variable=variable)
    log.info("configuration valid", **settings.describe())
    for variable, host in external_endpoints(settings).items():
        log.warning(
            f"document content is sent to {host}, outside the local network",
            variable=variable,
            host=host,
        )

    if command in SERVICES and settings.role not in SERVICES[command]:
        log.error(
            f"the {command} does not run with LEKTO_ROLE={settings.role}",
            command=command,
            role=settings.role,
        )
        return 1
    return COMMANDS[command](settings, arguments)


def cli() -> None:
    """The `lekto` command (`[project.scripts]`)."""
    sys.exit(main(sys.argv[1:]))


ROOT_WARNING = (
    "warning: lekto runs as root, and what it writes would belong to root: stopped. In the "
    "image, run it as `lekto-run lekto ...` (as PUID:PGID); with PUID=0, root is meant."
)


def _as_root() -> bool:
    """Root, and not as the image's `PUID=0` asks for."""
    return os.geteuid() == 0 and os.environ.get("PUID") != "0"


HELP: Mapping[str, str] = {
    "check": "validate the configuration and print it without secrets (the default)",
    "migrate": "bring the database to the newest schema",
    "check-schema": "exit 0 if the database is at the newest schema",
    "api": "serve the REST API until SIGTERM or Ctrl-C",
    "worker": "run the worker until SIGTERM or Ctrl-C",
    "evaluate": "run the evaluation set against the language model and write a report",
    "evaluate-search": "compare embedding models on the evaluation set",
    "reindex": "rebuild the search index, in the foreground",
    "render-pages": "queue the page images of documents from before the pages node",
    "read-facts": "queue reading the facts of every document again",
    "relate": "queue finding the relations of every document",
    "fetch-logos": "queue fetching the logos of contacts without one",
    "reparse": "queue reading the text of every document again",
    "train": "train the classifier from the confirmed documents now",
}
ENV_FILE = (
    "take the LEKTO_ settings from this file of KEY=value lines instead of the environment "
    "(the development instance: .devcontainer/dev.local.env)"
)


def _parser() -> argparse.ArgumentParser:
    """A subcommand each, with its own options; none is `check`. `--env-file` goes before or
    after the command."""
    parser = argparse.ArgumentParser(
        prog="lekto",
        description="Lekto's commands, with the settings of the LEKTO_ environment variables.",
    )
    parser.add_argument("--env-file", type=Path, metavar="FILE", help=ENV_FILE)
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument(
        "--env-file", type=Path, metavar="FILE", help=ENV_FILE, default=argparse.SUPPRESS
    )
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")
    parsers = {
        name: commands.add_parser(name, parents=[shared], help=HELP[name], description=HELP[name])
        for name in COMMANDS
    }
    parsers["check-schema"].add_argument(
        "--wait", type=float, default=0, help="seconds to wait (default: 0)"
    )
    evaluate, evaluate_search = parsers["evaluate"], parsers["evaluate-search"]
    for each in (evaluate, evaluate_search):
        each.add_argument("--cases", type=Path, help="the set (default: evaluation)")
        each.add_argument("--output", type=Path, help="where to write the report")
    evaluate.add_argument("--fake", action="store_true", help="use the fixed answers")
    evaluate.add_argument(
        "--runs",
        type=_runs,
        default=list(Run),
        help="cold, trained or both (default), comma separated",
    )
    evaluate_search.add_argument("--fake", action="store_true", help="fake embeddings and index")
    evaluate_search.add_argument("--models", help="embedding models, comma separated")
    evaluate_search.add_argument("--ratios", help="semantic ratios (default: 0,0.5,1)")
    evaluate_search.add_argument("--queries", type=Path, help="the queries file")
    return parser


def _run[T](
    settings: Settings,
    command: Callable[[Settings], Coroutine[object, object, T]],
    *,
    failed: str,
    done: str | None = None,
    fields: Callable[[T], Mapping[str, object]] = lambda _: {},
    status: Callable[[T], int] = lambda _: 0,
) -> int:
    """Run `command` to its end; log `done` with the `fields` of its result and exit with its
    `status`. A configuration or an evaluation set it cannot work with exits with 1 and the
    message on stderr, anything else that goes wrong with 1 and `failed` in the log."""
    try:
        result = asyncio.run(command(settings))
    except (ConfigurationError, EvaluationSetError) as error:
        print(error, file=sys.stderr)
        return 1
    except Exception:
        log.exception(failed)
        return 1
    if done is not None:
        log.info(done, **fields(result))
    return status(result)


def _check(settings: Settings, arguments: argparse.Namespace) -> int:
    return 0  # the configuration is valid and logged


def _migrate(settings: Settings, arguments: argparse.Namespace) -> int:
    return _run(
        settings,
        migrate_database,
        failed="database migration failed",
        done="database migrated",
        fields=lambda _: {"db_type": settings.db_type},
    )


def _check_schema(settings: Settings, arguments: argparse.Namespace) -> int:
    def status(state: SchemaState) -> int:
        if state == "current":
            log.info("database schema is current", db_type=settings.db_type)
            return 0
        if state == "newer":
            log.error("the database was migrated by a newer version of Lekto: update this image")
        else:
            log.error("the database schema is not migrated", db_type=settings.db_type)
        return 1

    return _run(
        settings,
        lambda settings: check_schema(settings, wait=arguments.wait),
        failed="checking the database schema failed",
        status=status,
    )


def _service(name: str, run: Callable[[Settings], Coroutine[object, object, None]]) -> Command:
    """Serve until SIGTERM or SIGINT."""
    return lambda settings, arguments: _run(settings, run, failed=f"{name} failed")


def _reindex(settings: Settings, arguments: argparse.Namespace) -> int:
    return _run(
        settings,
        lambda settings: run_reindex(settings, progress=True),
        failed="rebuilding the search index failed",
        done="reindex finished",
        fields=lambda result: {
            "documents": result.documents,
            "queued": result.queued,
            "removed": result.removed,
        },
    )


def _train(settings: Settings, arguments: argparse.Namespace) -> int:
    return _run(
        settings,
        run_training,
        failed="training the classifier failed",
        done="classifier trained",
        fields=lambda model: {
            "number": model.number,
            "examples": model.examples,
            "summary": model.summary,
        },
    )


def _queue(
    run: Callable[[Settings], Coroutine[object, object, int]],
    *,
    counted: str,
    failed: str,
) -> Command:
    """A command that queues jobs for the worker; it logs how many (as `counted`)."""

    def command(settings: Settings, arguments: argparse.Namespace) -> int:
        name: str = arguments.command
        done = f"{name} queued"
        return _run(settings, run, failed=failed, done=done, fields=lambda n: {counted: n})

    return command


QUEUES: dict[str, Command] = {
    "render-pages": _queue(
        run_render_pages, counted="documents", failed="queueing the page images failed"
    ),
    "read-facts": _queue(run_read_facts, counted="documents", failed="queueing the facts failed"),
    "relate": _queue(run_relate, counted="documents", failed="queueing the relations failed"),
    "fetch-logos": _queue(run_fetch_logos, counted="contacts", failed="queueing the logos failed"),
    "reparse": _queue(
        run_reparse, counted="documents", failed="queueing the texts to read again failed"
    ),
}


def _evaluate(settings: Settings, arguments: argparse.Namespace) -> int:
    return _run(
        settings,
        lambda settings: run_evaluation(
            settings,
            cases=arguments.cases or Path("evaluation"),
            fake=arguments.fake,
            output=arguments.output,
            progress=True,
            runs=arguments.runs,
        ),
        failed="evaluation failed",
        done="evaluation finished",
        fields=lambda result: {
            "report": str(result.report),
            "cases": len(result.results),
            "false_green": result.false_green,
            "green_but_wrong": result.green_but_wrong,
            "violations": result.violations,
        },
        status=lambda result: (
            1 if result.false_green or result.green_but_wrong or result.violations else 0
        ),
    )


def _evaluate_search(settings: Settings, arguments: argparse.Namespace) -> int:
    return _run(
        settings,
        lambda settings: run_search_evaluation(
            settings,
            cases=arguments.cases or Path("evaluation"),
            queries=arguments.queries,
            fake=arguments.fake,
            models=_names(arguments.models),
            ratios=parse_ratios(arguments.ratios) if arguments.ratios else DEFAULT_RATIOS,
            output=arguments.output,
            progress=True,
        ),
        failed="search evaluation failed",
        done="search evaluation finished",
        fields=lambda result: {"report": str(result.report), "models": len(result.models)},
    )


def _names(text: str | None) -> list[str]:
    return [name.strip() for name in (text or "").split(",") if name.strip()]


def _runs(text: str) -> list[Run]:
    """`--runs`: the runs named, each once; all if none is."""
    names = _names(text)
    if unknown := set(names) - {run.value for run in Run}:
        raise argparse.ArgumentTypeError(f"unknown {', '.join(sorted(unknown))}")
    return [Run(name) for name in dict.fromkeys(names)] or list(Run)


COMMANDS: dict[str, Command] = {
    "check": _check,
    "migrate": _migrate,
    "check-schema": _check_schema,
    "api": _service("api", run_api),
    "worker": _service("worker", run_worker),
    "evaluate": _evaluate,
    "evaluate-search": _evaluate_search,
    "reindex": _reindex,
    **QUEUES,
    "train": _train,
}


if __name__ == "__main__":
    cli()
