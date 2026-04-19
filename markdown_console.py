"""Terminal-friendly Markdown rendering (Rich) with plain-text fallbacks."""

from __future__ import annotations

import shutil
import sys
from io import StringIO
from typing import Optional, TextIO


def _terminal_width(default: int = 96) -> int:
    try:
        return max(60, min(120, shutil.get_terminal_size((default, 20)).columns))
    except OSError:
        return default


def _looks_like_markdown(text: str) -> bool:
    t = text.lstrip()
    if not t:
        return False
    if t.startswith("{") or t.startswith("["):
        return False
    if t.startswith("#"):
        return True
    if "\n## " in text or "\n### " in text:
        return True
    if "|" in text and "\n" in text:
        lines = text.splitlines()
        if any("|" in ln for ln in lines[:12]) and any("---" in ln for ln in lines[:15]):
            return True
    return False


def markdown_to_ansi(text: str, *, width: Optional[int] = None) -> str:
    """Render Markdown to ANSI-colored text for terminals (no trailing newline enforced)."""
    w = width if width is not None else _terminal_width()
    try:
        from rich.console import Console
        from rich.markdown import Markdown

        buf = StringIO()
        console = Console(file=buf, force_terminal=True, width=w, soft_wrap=True, highlight=False)
        console.print(Markdown(text))
        return buf.getvalue().rstrip("\n")
    except Exception:
        return text.rstrip("\n")


def indent_block(text: str, prefix: str = "        ") -> str:
    return "\n".join(prefix + line if line else prefix.rstrip() for line in text.splitlines())


def print_markdown(
    text: Optional[str],
    *,
    file: Optional[TextIO] = None,
    force_plain: bool = False,
) -> None:
    """Print user-visible Markdown: Rich when ``file`` is a TTY, else plain."""
    out = file or sys.stdout
    if text is None or not str(text).strip():
        print("(empty)", file=out)
        return
    body = str(text)
    if force_plain or not out.isatty():
        print(body, file=out)
        return
    try:
        from rich.console import Console
        from rich.markdown import Markdown

        width = _terminal_width()
        Console(file=out, force_terminal=True, width=width, soft_wrap=True, highlight=False).print(Markdown(body))
    except Exception:
        print(body, file=out)


def format_trace_preview(text: str, *, width: Optional[int] = None) -> str:
    """Format a skill output preview for trace: Markdown → ANSI when appropriate."""
    if _looks_like_markdown(text):
        return markdown_to_ansi(text, width=width)
    return text.rstrip("\n")
