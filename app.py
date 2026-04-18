"""CLI entry point for the skill-centric agent prototype."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

from executor import SkillAgent
from models import build_moonshot_client_from_env
from skills import build_default_registry
from trace import TraceRenderer


def load_task(task: str | None, task_file: str | None) -> Dict[str, Any]:
    if task_file:
        payload = json.loads(Path(task_file).read_text(encoding="utf-8"))
        if isinstance(payload, str):
            return {"task": payload, "context": {}}
        return {"task": payload["task"], "context": payload.get("context", {})}
    if task:
        return {"task": task, "context": {}}
    raise ValueError("Provide either --task or --task-file")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Skill-centric mini coding agent")
    parser.add_argument("--root", default=".", help="Workspace root for the skill agent")
    parser.add_argument("--provider", choices=["none", "moonshot"], default="none", help="Optional model provider for LLM-backed skills")
    parser.add_argument("--model", default="kimi-k2.5", help="Model name when --provider is enabled")
    parser.add_argument("--api-key-env", default="MOONSHOT_API_KEY", help="Environment variable that stores the provider API key")

    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("run", "trace"):
        sub = subparsers.add_parser(command)
        sub.add_argument("--task", help="Task text to run")
        sub.add_argument("--task-file", help="Path to a JSON file with task/context")
        if command == "trace":
            sub.add_argument("--json", action="store_true", help="Render the trace as JSON")

    chat = subparsers.add_parser("chat")
    chat.add_argument("--must-include", nargs="*", default=[], help="Sections to require during verification")

    schemas = subparsers.add_parser("schemas")
    schemas.add_argument("--json", action="store_true", help="Render schemas as JSON")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    model_client = None
    if args.provider == "moonshot":
        model_client = build_moonshot_client_from_env(model=args.model, api_key_env=args.api_key_env)
        if model_client is None:
            raise SystemExit(f"Missing API key in environment variable: {args.api_key_env}")

    agent = SkillAgent(Path(args.root), model_client=model_client)

    if args.command == "schemas":
        definitions = build_default_registry().definitions()
        if args.json:
            print(json.dumps({name: definition.model_dump() for name, definition in definitions.items()}, ensure_ascii=False, indent=2))
        else:
            for name, definition in definitions.items():
                print(f"[{name}] {definition.purpose}")
        return

    if args.command == "chat":
        while True:
            task = input("task> ").strip()
            if not task or task in {"/exit", "exit", "quit"}:
                break
            trace = agent.run(task, context={"must_include": args.must_include})
            print(trace.final_result)
            print("\n--- trace ---")
            print(TraceRenderer.to_text(trace))
        return

    payload = load_task(args.task, args.task_file)
    trace = agent.run(payload["task"], payload.get("context", {}))
    if args.command == "run":
        print(trace.final_result)
        return
    if args.json:
        print(TraceRenderer.to_json(trace))
    else:
        print(TraceRenderer.to_text(trace))


if __name__ == "__main__":
    main()
