"""Ask each task of `tasks.json` through Claude Code with Lekto's MCP server, and count the hits
and the tokens (Tobi, 01.11.2026, umsetzungsplan "MCP", decision 13).

    python run.py --url http://localhost:8010 --token lekto_... [--model sonnet] [--only t01,t05]

Runs `claude -p` once per task, with only Lekto's tools (`--strict-mcp-config`), and checks
whether the answer contains one of the task's `expect` (case, spaces and dots in numbers aside).
Writes `results.json` beside it and prints a table. Costs what the calls cost: run it by hand,
not in CI. Standard library only.
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent


def normal(text: str) -> str:
    return "".join(text.casefold().split())


def hit(answer: str, expect: list[str]) -> bool:
    said = normal(answer)
    return any(normal(item) in said for item in expect)


def ask(question: str, config: Path, model: str | None) -> dict[str, Any]:
    command = [
        "claude",
        "-p",
        question,
        "--mcp-config",
        str(config),
        "--strict-mcp-config",
        "--allowedTools",
        "mcp__lekto",
        "--output-format",
        "json",
    ]
    if model:
        command += ["--model", model]
    done = subprocess.run(command, capture_output=True, text=True, timeout=600, check=False)
    if done.returncode != 0:
        return {"result": "", "error": done.stderr.strip()[-500:]}
    return json.loads(done.stdout)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--url", required=True, help="the Lekto instance, e.g. http://localhost:8010"
    )
    parser.add_argument("--token", required=True, help="an API token of the user who asks")
    parser.add_argument("--model", help="the model Claude Code uses (default: its own)")
    parser.add_argument("--only", help="task ids, comma-separated")
    parser.add_argument("--tasks", type=Path, default=HERE / "tasks.json")
    arguments = parser.parse_args()
    tasks = json.loads(arguments.tasks.read_text())
    if arguments.only:
        wanted = set(arguments.only.split(","))
        tasks = [task for task in tasks if task["id"] in wanted]
    server = {
        "type": "http",
        "url": arguments.url.rstrip("/") + "/api/v1/mcp",
        "headers": {"Authorization": f"Bearer {arguments.token}"},
    }
    results = []
    with tempfile.TemporaryDirectory() as directory:
        config = Path(directory) / "mcp.json"
        config.write_text(json.dumps({"mcpServers": {"lekto": server}}))
        for task in tasks:
            answer = ask(task["question"], config, arguments.model)
            usage = answer.get("usage") or {}
            result = {
                "id": task["id"],
                "kind": task["kind"],
                "hit": hit(str(answer.get("result", "")), task["expect"]),
                "turns": answer.get("num_turns"),
                "input_tokens": usage.get("input_tokens", 0)
                + usage.get("cache_read_input_tokens", 0)
                + usage.get("cache_creation_input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
                "cost_usd": answer.get("total_cost_usd"),
                "answer": str(answer.get("result", ""))[:500],
                "error": answer.get("error"),
            }
            results.append(result)
            mark = "✓" if result["hit"] else "✗"
            print(
                f"{mark} {task['id']} {task['kind']:<7} turns {result['turns']} "
                f"in {result['input_tokens']} out {result['output_tokens']}",
                file=sys.stderr,
            )
    (HERE / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n")
    hits = sum(1 for result in results if result["hit"])
    tokens = sum(result["input_tokens"] + result["output_tokens"] for result in results)
    print(f"{hits} of {len(results)} right, {tokens} tokens")


if __name__ == "__main__":
    main()
