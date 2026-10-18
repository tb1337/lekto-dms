"""Every contract suite in `tests/contracts` runs against the in-memory adapter of its port and
against at least one real adapter (CLAUDE.md, Architecture rules). The test reads the test
modules instead of importing them: a class that names a suite, directly or through a class of the
same module, among its bases runs it."""

import ast
from collections.abc import Iterator
from pathlib import Path

TESTS = Path(__file__).parents[1]
CONTRACTS = TESTS / "contracts"
MEMORY = TESTS / "unit" / "adapters" / "memory"
ADAPTER_TESTS = (TESTS / "unit" / "adapters", TESTS / "integration" / "adapters")

# The ports without an in-memory adapter: their real adapters need no service and serve the
# memory container too (architektur.md, Ports und Adapter).
WITHOUT_MEMORY_ADAPTER = {"PatternMatcherContract", "TemplateRendererContract"}


def _classes(path: Path) -> Iterator[ast.ClassDef]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    yield from (node for node in tree.body if isinstance(node, ast.ClassDef))


def _name(base: ast.expr) -> str | None:
    if isinstance(base, ast.Name):
        return base.id
    return base.attr if isinstance(base, ast.Attribute) else None


def contracts() -> set[str]:
    return {
        cls.name
        for path in CONTRACTS.glob("*.py")
        for cls in _classes(path)
        if cls.name.endswith("Contract")
    }


def suites_run_by(path: Path, suites: set[str]) -> set[str]:
    """The suites the classes of the module at `path` inherit."""
    inherited: dict[str, set[str]] = {}
    for cls in _classes(path):  # a base is defined before the classes that use it
        names = {name for base in cls.bases if (name := _name(base)) is not None}
        inherited[cls.name] = (names & suites).union(
            *(inherited.get(name, set()) for name in names)
        )
    return set().union(*inherited.values())


def heirs(suites: set[str]) -> tuple[set[str], set[str]]:
    """The suites with an in-memory heir, and those with a heir for a real adapter."""
    memory: set[str] = set()
    real: set[str] = set()
    for root in ADAPTER_TESTS:
        for path in root.rglob("*.py"):
            run = suites_run_by(path, suites)
            (memory if path.is_relative_to(MEMORY) else real).update(run)
    return memory, real


def test_the_suites_are_found() -> None:
    suites = contracts()
    assert {"UnitOfWorkContract", "ObjectStoreContract", "SearchIndexContract"} <= suites
    assert suites >= WITHOUT_MEMORY_ADAPTER


def test_every_suite_runs_against_the_memory_adapter() -> None:
    suites = contracts()
    memory, _ = heirs(suites)
    assert sorted(suites - WITHOUT_MEMORY_ADAPTER - memory) == []


def test_the_exceptions_have_no_memory_adapter() -> None:
    memory, _ = heirs(contracts())
    assert sorted(WITHOUT_MEMORY_ADAPTER & memory) == []


def test_every_suite_runs_against_a_real_adapter() -> None:
    suites = contracts()
    _, real = heirs(suites)
    assert sorted(suites - real) == []
