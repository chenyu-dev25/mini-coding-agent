"""CLI entry point for the skill-centric agent prototype."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

from executor import SkillAgent
from markdown_console import print_markdown
from models import build_ollama_client, build_moonshot_client_from_env
from skills import build_default_registry
from trace_renderer import TraceRenderer

# Same mascot as legacy `mini_coding_agent.py` REPL so the entrypoints feel familiar.
WELCOME_ART = (
    "/\\     /\\\\",
    "{  `---'  }",
    "{  O   O  }",
    "~~>  V  <~~",
    "\\\\  \\|/  /",
    "`-----'__",
)


def _middle(text: str, limit: int) -> str:
    """Truncate long one-line labels to fit the banner (same idea as legacy REPL)."""
    text = str(text).replace("\n", " ")
    if len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    left = (limit - 3) // 2
    right = limit - 3 - left
    return text[:left] + "..." + text[-right:]


def _git_branch(root: Path) -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=3,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return "n/a"


def build_skill_repl_welcome(args: argparse.Namespace) -> str:
    """Boxed banner aligned with ``mini_coding_agent.build_welcome`` layout."""
    width = max(68, min(shutil.get_terminal_size((80, 20)).columns, 84))
    inner = width - 4
    gap = 3
    left_width = (inner - gap) // 2
    right_width = inner - gap - left_width
    root = Path(args.root).resolve()

    def row(text: str) -> str:
        body = _middle(text, width - 4)
        return f"| {body.ljust(width - 4)} |"

    def divider(char: str = "-") -> str:
        return "+" + char * (width - 2) + "+"

    def center(text: str) -> str:
        body = _middle(text, inner)
        return f"| {body.center(inner)} |"

    def cell(label: str, value: str, size: int) -> str:
        body = _middle(f"{label:<9} {value}", size)
        return body.ljust(size)

    def pair(left_label: str, left_value: str, right_label: str, right_value: str) -> str:
        left = cell(left_label, left_value, left_width)
        right = cell(right_label, right_value, right_width)
        return f"| {left}{' ' * gap}{right} |"

    line = divider("=")
    rows = [center(t) for t in WELCOME_ART]
    trace_cell = "on" if args.trace else "off"
    pipeline = "always" if args.skill_pipeline else "auto"
    host_cell = _middle(args.host, right_width - 10) if args.provider == "ollama" else "—"
    rows.extend(
        [
            center("MINI CODING AGENT · SKILL ROUTER"),
            divider("-"),
            row(""),
            row("WORKSPACE " + _middle(str(root), inner - 11)),
            pair("MODEL", args.model, "BRANCH", _git_branch(root)),
            pair("PROVIDER", args.provider, "PIPELINE", pipeline),
            pair("TRACE", trace_cell, "HOST", host_cell),
            row(""),
        ]
    )
    return "\n".join([line, *rows, line])


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
    parser.add_argument(
        "--provider",
        choices=["none", "ollama", "moonshot"],
        default="ollama",
        help="Model provider for LLM-backed skills",
    )
    parser.add_argument("--model", default="qwen3.5:4b", help="Model name when --provider is enabled")
    parser.add_argument("--host", default="http://127.0.0.1:11434", help="Model server host for ollama")
    parser.add_argument("--timeout", type=int, default=60, help="Model request timeout in seconds")
    parser.add_argument("--api-key-env", default="MOONSHOT_API_KEY", help="Environment variable that stores the provider API key")
    parser.add_argument("--must-include", nargs="*", default=[], help="Sections to require during verification")
    parser.add_argument(
        "--skill-pipeline",
        action="store_true",
        help="Always run multi-skill router (default: direct chat unless env, /pipeline, or strong task cues)",
    )
    parser.add_argument(
        "--trace",
        action="store_true",
        help="REPL: after each reply, print skill trace (default: answer only, like legacy CLI; use /trace to toggle)",
    )
    parser.add_argument(
        "--no-banner",
        action="store_true",
        help="REPL: skip startup welcome art and hints",
    )
    parser.add_argument(
        "--no-ansi",
        action="store_true",
        help="Plain text only: disable Rich Markdown colors/formatting in the terminal",
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="Do not print step-by-step progress lines while waiting for the model",
    )

    subparsers = parser.add_subparsers(dest="command")
    for command in ("run", "trace"):
        sub = subparsers.add_parser(command)
        sub.add_argument("--task", help="Task text to run")
        sub.add_argument("--task-file", help="Path to a JSON file with task/context")
        if command == "trace":
            sub.add_argument("--json", action="store_true", help="Render the trace as JSON")

    schemas = subparsers.add_parser("schemas")
    schemas.add_argument("--json", action="store_true", help="Render schemas as JSON")
    return parser


def build_model_client(args: argparse.Namespace):
    if args.provider == "none":
        return None
    if args.provider == "ollama":
        return build_ollama_client(model=args.model, host=args.host, timeout=args.timeout)
    model_client = build_moonshot_client_from_env(model=args.model, api_key_env=args.api_key_env)
    if model_client is None:
        raise SystemExit(f"Missing API key in environment variable: {args.api_key_env}")
    return model_client


INTERACTIVE_HELP = """\
命令:
  /exit, quit     退出
  /skills         显示本说明
  /trace          切换是否在每次回复后打印 skill 执行轨迹（默认关闭，接近原版 REPL）
  /list-skills    通过 LLM 列举已注册 skill（等同自然语言问「有哪些 skill」）
  /pipeline       本会话开启多 skill 路由（planning/analysis/… 流水线）
  /direct         本会话恢复默认直连（只聊天，不走路由流水线）

终端下回答与 trace 中的 Markdown 会尽量用 Rich 美化；不需要颜色时可加 `--no-ansi`。
等待模型时会打印「路由 / 每步 skill」进度行；不需要时可加 `--no-progress`。

说明: 本入口是 skill-centric 原型。带会话记忆与工具循环的原版请运行:
  uv run python mini_coding_agent.py
  （或 python mini_coding_agent.py）
"""


def _print_repl_banner(args: argparse.Namespace) -> None:
    if args.no_banner:
        return
    print(build_skill_repl_welcome(args))
    print("  命令见 /skills ；/trace 可开关每次回复后的轨迹预览。")
    print()


def _progress_printer(msg: str) -> None:
    print(f"  {msg}", flush=True)


def run_interactive_chat(
    agent: SkillAgent,
    must_include: list[str],
    *,
    show_trace: bool,
    rich_output: bool = True,
    show_progress: bool = True,
) -> None:
    trace_verbose = show_trace
    trace_ansi: bool | None = False if not rich_output else None
    while True:
        try:
            task = input("\nmini-coding-agent> ").strip()
        except EOFError:
            print()
            break
        if not task or task in {"/exit", "exit", "quit"}:
            break
        if task == "/skills":
            print(INTERACTIVE_HELP)
            continue
        if task == "/trace":
            trace_verbose = not trace_verbose
            print("已" + ("开启" if trace_verbose else "关闭") + "每次回复后的 trace 输出。")
            continue
        if task == "/pipeline":
            agent.use_skill_pipeline = True
            print("已开启多 skill 路由（本会话）。输入 /direct 可恢复直连。")
            continue
        if task == "/direct":
            agent.use_skill_pipeline = False
            print("已切换为直连模式（本会话）。强意图任务仍会自动走路由。")
            continue
        if task == "/list-skills":
            task = "你有哪些 skill"
        trace = agent.run(
            task,
            context={"must_include": must_include},
            on_progress=_progress_printer if show_progress else None,
        )
        print_markdown(trace.final_result, force_plain=not rich_output)
        if trace_verbose:
            print("\n--- trace ---")
            print(TraceRenderer.to_text(trace, ansi_markdown_previews=trace_ansi))


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    model_client = build_model_client(args)
    agent = SkillAgent(
        Path(args.root),
        model_client=model_client,
        use_skill_pipeline=bool(args.skill_pipeline),
    )

    if args.command == "schemas":
        definitions = build_default_registry().definitions()
        if args.json:
            print(json.dumps({name: definition.model_dump() for name, definition in definitions.items()}, ensure_ascii=False, indent=2))
        else:
            for name, definition in definitions.items():
                print(f"[{name}] {definition.purpose}")
        return

    if args.command is None:
        _print_repl_banner(args)
        run_interactive_chat(
            agent,
            args.must_include,
            show_trace=bool(args.trace),
            rich_output=not args.no_ansi,
            show_progress=sys.stdout.isatty() and not args.no_progress,
        )
        return

    payload = load_task(args.task, args.task_file)
    context = dict(payload.get("context", {}))
    if args.must_include:
        context["must_include"] = list(dict.fromkeys(list(context.get("must_include", [])) + list(args.must_include)))
    show_progress = sys.stdout.isatty() and not args.no_progress
    trace = agent.run(
        payload["task"],
        context,
        on_progress=_progress_printer if show_progress else None,
    )
    if args.command == "run":
        print_markdown(trace.final_result, force_plain=args.no_ansi)
        return
    if args.json:
        print(TraceRenderer.to_json(trace))
    else:
        ansi_pv = False if args.no_ansi else None
        print(TraceRenderer.to_text(trace, include_final_result=True, ansi_markdown_previews=ansi_pv))


if __name__ == "__main__":
    main()
