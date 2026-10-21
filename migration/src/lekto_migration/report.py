"""The reports of the commands: Markdown for people, JSON for machines. They name objects, ids
and reasons, never a key, a token or a password."""

import json
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from lekto_migration.masterdata import TITLES, Action
from lekto_migration.migrate import Totals
from lekto_migration.paperless import Snapshot
from lekto_migration.state import State

TITLE = {
    "plan": "Migration plan",
    "check": "Check (cold run)",
    "prepare": "Preparing Lekto",
    "run": "Migration",
}


def head(
    command: str, snapshot: Snapshot | None, paperless: str, lekto: str | None
) -> dict[str, Any]:
    return {
        "command": command,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "paperless": {"url": paperless, "version": snapshot.version if snapshot else None},
        "lekto": {"url": lekto},
    }


def source_counts(snapshot: Snapshot) -> dict[str, int]:
    return {
        "documents": len(snapshot.documents),
        "users": len(snapshot.users),
        "groups": len(snapshot.groups),
        "correspondents": len(snapshot.correspondents),
        "document_types": len(snapshot.document_types),
        "tags": len(snapshot.tags),
        "custom_fields": len(snapshot.custom_fields),
        "storage_paths": len(snapshot.storage_paths),
        **snapshot.counted,
    }


def actions(items: list[Action]) -> list[dict[str, Any]]:
    return [
        {
            "kind": a.kind,
            "name": a.name,
            "status": a.status,
            "source": a.source,
            "detail": a.detail,
            "notes": a.notes,
        }
        for a in items
    ]


def run_documents(state: State, selected: set[int]) -> list[dict[str, Any]]:
    """The state of every document the run looked at."""
    out = []
    for row in state.documents():
        if row.source_id not in selected:
            continue
        out.append(
            {
                "id": row.source_id,
                "title": row.detail.get("title"),
                # Before 0.5 the state kept only the Paperless owner.
                "uploaded_by": row.detail.get("uploaded_by", row.detail.get("owner")),
                "space": row.detail.get("space"),
                "status": row.status,
                "lekto_id": row.lekto_id,
                "lane": row.lane,
                "reason": row.reason,
                "notes": row.notes,
                "aligned": bool(row.detail.get("aligned")),
                "sha256": row.sha256,
                "upload_seconds": row.upload_seconds,
                "pipeline_seconds": row.pipeline_seconds,
            }
        )
    return out


def totals(value: Totals) -> dict[str, Any]:
    return {
        "documents": value.documents,
        "uploaded": value.uploaded,
        "aligned": value.aligned,
        "resumed": value.resumed,
        "duplicates": value.duplicates,
        "skipped": value.skipped,
        "deleted": value.deleted,
        "failed": value.failed,
        "stopped": value.stopped,
    }


def lanes(documents: list[dict[str, Any]]) -> dict[str, int]:
    return dict(Counter(d["lane"] for d in documents if d.get("lane")))


def to_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True, default=str) + "\n"


# --- Markdown ---------------------------------------------------------------------------------


def to_markdown(report: dict[str, Any]) -> str:
    command = report["command"]
    out = [f"# Paperless-ngx to Lekto: {TITLE[command]}", ""]
    version = report["paperless"].get("version")
    out.append(
        f"{report['generated_at']} · Paperless {version or ''} ({report['paperless']['url']})"
        f" · Lekto {report['lekto']['url'] or 'not read'}"
    )
    out.append("")
    problems = report.get("problems") or []
    if problems:
        out += ["## Problems", ""]
        out += [f"- {problem}" for problem in problems]
        out.append("")
    elif command in ("plan", "check"):
        out += ["No problems.", ""]
    if command == "plan":
        out += _plan(report)
    if report.get("actions"):
        out += _actions(report["actions"], command)
    if command == "check":
        out += _check(report)
    if command == "run":
        out += _run(report)
    if report.get("seconds"):
        seconds = ", ".join(f"{k} {v}" for k, v in report["seconds"].items())
        out += [f"Times (seconds): {seconds}", ""]
    return "\n".join(out) + "\n"


def _table(headers: list[str], rows: list[list[Any]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(_cell(cell) for cell in row) + " |")
    return [*lines, ""]


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        value = "; ".join(str(item) for item in value)
    elif isinstance(value, dict):
        value = ", ".join(f"{k}: {v}" for k, v in value.items())
    return str(value).replace("|", "\\|").replace("\n", " ")


def _plan(report: dict[str, Any]) -> list[str]:
    out = []
    changes = report.get("changes") or {}
    if report.get("written"):
        out += [f"The plan was written to `{report['path']}`.", ""]
    elif changes.get("added") or changes.get("gone"):
        out += ["The plan was **not** written.", ""]
    else:
        out += ["The plan is up to date with Paperless.", ""]
    for key, title in (
        ("added", "Added (new in Paperless)"),
        ("gone", "Marked (not in Paperless)"),
    ):
        if changes.get(key):
            out += [f"## {title}", ""] + [f"- {name}" for name in changes[key]] + [""]
    if report.get("entries"):
        out += ["## Entries", ""]
        out += _table(
            ["Section", "Entries", "Dropped"],
            [[k, v["entries"], v["dropped"]] for k, v in report["entries"].items()],
        )
    return out


def _actions(items: list[dict[str, Any]], command: str) -> list[str]:
    title = "What Lekto needs" if command == "check" else "Master data"
    counts = Counter((a["kind"], a["status"]) for a in items)
    out = [f"## {title}", ""]
    rows = []
    for kind, label in TITLES.items():
        found = {status: n for (k, status), n in counts.items() if k == kind}
        if found:
            rows.append([label, ", ".join(f"{s} {n}" for s, n in sorted(found.items()))])
    out += _table(["Kind", "Status"], rows)
    shown = [a for a in items if a["status"] != "exists" or a["notes"]]
    if shown:
        out += _table(
            ["Kind", "Name", "Status", "Where the plan names it", "Detail", "Notes"],
            [
                [TITLES[a["kind"]], a["name"], a["status"], a["source"], a["detail"], a["notes"]]
                for a in shown
            ],
        )
    return out


def _check(report: dict[str, Any]) -> list[str]:
    documents = report["documents"]
    out = ["## Documents", ""]
    out += _table(
        ["Status", "Count"], [[k, v] for k, v in sorted(report["document_results"].items())]
    )
    differs = [d for d in documents if d["status"] == "differs"]
    if differs:
        out += [f"## Migrated documents that differ ({len(differs)})", ""]
        rows = []
        for d in differs:
            for diff in d.get("differences", []):
                rows.append(
                    [d["id"], d["title"], diff["what"], diff["lekto"], diff["plan"], diff["action"]]
                )
        out += _table(["Paperless", "Title", "What", "Lekto", "Plan", "Alignment"], rows)
        ruled = [d for d in differs if d.get("rules")]
        if ruled:
            out += ["Rules the alignment sets off:", ""]
            out += _table(
                ["Paperless", "Title", "Rules"], [[d["id"], d["title"], d["rules"]] for d in ruled]
            )
    new = [d for d in documents if d["status"] == "new"]
    if new:
        out += [f"## New documents ({len(new)})", ""]
        out += _table(
            [
                "Paperless",
                "Title",
                "Uploaded by",
                "Space",
                "Members",
                "Contact",
                "Type",
                "Topic",
                "Tags",
                "Review",
            ],
            [
                [
                    d["id"],
                    d["title"],
                    d["becomes"]["uploaded_by"],
                    d["becomes"]["space"],
                    d["becomes"]["members"],
                    d["becomes"]["contact"],
                    d["becomes"]["document_type"],
                    d["becomes"]["topic"],
                    d["becomes"]["tags"],
                    d["becomes"]["review"],
                ]
                for d in new
            ],
        )
    for status, title in (
        ("deleted in Lekto", "Migrated, deleted in Lekto"),
        ("gone from Paperless", "Migrated, gone from Paperless"),
        ("skipped", "Not taken over"),
        ("not aligned", "Not aligned"),
    ):
        items = [d for d in documents if d["status"] == status]
        if items:
            out += [f"## {title} ({len(items)})", ""]
            out += _table(
                ["Paperless", "Title", "Lekto", "Reason"],
                [[d["id"], d["title"], d["lekto_id"], d["reason"]] for d in items],
            )
    noted = [d for d in documents if d.get("notes")]
    if noted:
        out += ["## Remarks on documents", ""]
        out += _table(
            ["Paperless", "Title", "Remarks"], [[d["id"], d["title"], d["notes"]] for d in noted]
        )
    if report.get("texts"):
        out += ["## Texts to look at", ""]
        out.append(
            "Lekto read fewer words than the share the plan sets of what Paperless read, or "
            "would itself advise reading with the vision language model (in Lekto, a person "
            "asks for that)."
        )
        out.append("")
        out += _table(
            ["Paperless", "Title", "Lekto", "Words in Paperless", "Words in Lekto", "Advice"],
            [
                [
                    t["id"],
                    t["title"],
                    t["lekto_id"],
                    t["words_paperless"],
                    t["words_lekto"],
                    t["advice"],
                ]
                for t in report["texts"]
            ],
        )
    if report.get("files"):
        out += ["## Files", ""]
        out += _table(
            ["Paperless", "Title", "Problem", "Note"],
            [[f["id"], f["title"], f.get("problem"), f.get("note")] for f in report["files"]],
        )
    return out


def _run(report: dict[str, Any]) -> list[str]:
    documents = report["documents"]
    out = ["## Summary", ""]
    out += _table(["", "Count"], [[k, v] for k, v in report["totals"].items()])
    if report.get("lanes"):
        out += ["Lanes: " + ", ".join(f"{k} {v}" for k, v in sorted(report["lanes"].items())), ""]
    for title, items in (
        (
            "Documents that failed or are not finished",
            [d for d in documents if d["status"] in ("failed", "uploaded")],
        ),
        ("Documents not taken over", [d for d in documents if d["status"] == "skipped"]),
        ("Documents in yellow or red", [d for d in documents if d["lane"] in ("yellow", "red")]),
        (
            "Documents with a reason",
            [
                d
                for d in documents
                if d["reason"] and d["status"] in ("done", "duplicate") and d["lane"] == "green"
            ],
        ),
    ):
        if items:
            out += [f"## {title} ({len(items)})", ""]
            out += _table(
                ["Paperless", "Title", "Lekto", "Reason"],
                [[d["id"], d["title"], d["lekto_id"], d["reason"]] for d in items],
            )
    noted = [d for d in documents if d["notes"]]
    if noted:
        out += ["## Remarks on documents", ""]
        out += _table(
            ["Paperless", "Title", "Remarks"], [[d["id"], d["title"], d["notes"]] for d in noted]
        )
    out += ["## All documents", ""]
    out += _table(
        ["Paperless", "Title", "Uploaded by", "Space", "Lekto", "Result", "Lane", "Aligned"],
        [
            [
                d["id"],
                d["title"],
                d["uploaded_by"] or "(executing admin)",
                d["space"],
                d["lekto_id"],
                d["status"],
                d["lane"],
                "yes" if d["aligned"] else "",
            ]
            for d in documents
        ],
    )
    return out
