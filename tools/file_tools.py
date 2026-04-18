"""文件相关工具"""

import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Any
import json


# 忽略的目录名
IGNORED_PATH_NAMES = {".git", ".mini-coding-agent", "__pycache__", ".pytest_cache", ".ruff_cache", ".venv", "venv"}


def clip(text, limit=4000):
    """截断长文本"""
    text = str(text)
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...[truncated {len(text) - limit} chars]"


def validate_path_within_root(path: Path, root: Path) -> bool:
    """验证路径是否在项目根目录内"""
    probe = path
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    for candidate in (probe, *probe.parents):
        try:
            if candidate.samefile(root):
                return True
        except OSError:
            continue
    return False


def resolve_path(raw_path: str, root: Path) -> Path:
    """解析并验证路径"""
    path = Path(raw_path)
    path = path if path.is_absolute() else root / path
    resolved = path.resolve()
    if not validate_path_within_root(resolved, root):
        raise ValueError(f"path escapes workspace: {raw_path}")
    return resolved


def list_files(path: str = ".", root: Path = None) -> str:
    """列出目录中的文件"""
    if root is None:
        raise ValueError("root path is required")

    target_path = resolve_path(path, root)
    if not target_path.is_dir():
        raise ValueError("path is not a directory")

    entries = [
        item for item in sorted(target_path.iterdir(), key=lambda item: (item.is_file(), item.name.lower()))
        if item.name not in IGNORED_PATH_NAMES
    ]

    lines = []
    for entry in entries[:200]:
        kind = "[D]" if entry.is_dir() else "[F]"
        lines.append(f"{kind} {entry.relative_to(root)}")

    return "\n".join(lines) or "(empty)"


def read_file(path: str, start: int = 1, end: int = 200, root: Path = None) -> str:
    """读取文件内容"""
    if root is None:
        raise ValueError("root path is required")

    target_path = resolve_path(path, root)
    if not target_path.is_file():
        raise ValueError("path is not a file")

    if start < 1 or end < start:
        raise ValueError("invalid line range")

    lines = target_path.read_text(encoding="utf-8", errors="replace").splitlines()
    body = "\n".join(
        f"{number:>4}: {line}"
        for number, line in enumerate(lines[start - 1:end], start=start)
    )

    return f"# {target_path.relative_to(root)}\n{body}"


def search(pattern: str, path: str = ".", root: Path = None) -> str:
    """在工作区中搜索模式"""
    if root is None:
        raise ValueError("root path is required")

    pattern = pattern.strip()
    if not pattern:
        raise ValueError("pattern must not be empty")

    target_path = resolve_path(path, root)

    # 优先使用 ripgrep
    if shutil.which("rg"):
        result = subprocess.run(
            ["rg", "-n", "--smart-case", "--max-count", "200", pattern, str(target_path)],
            cwd=root,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip() or result.stderr.strip() or "(no matches)"

    # 备用：Python 实现
    matches = []
    files = [target_path] if target_path.is_file() else [
        item for item in target_path.rglob("*")
        if item.is_file() and not any(part in IGNORED_PATH_NAMES for part in item.relative_to(root).parts)
    ]

    for file_path in files:
        try:
            for number, line in enumerate(file_path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
                if pattern.lower() in line.lower():
                    matches.append(f"{file_path.relative_to(root)}:{number}:{line}")
                    if len(matches) >= 200:
                        return "\n".join(matches)
        except:
            continue

    return "\n".join(matches) or "(no matches)"


def write_file(path: str, content: str, root: Path = None) -> str:
    """写入文件"""
    if root is None:
        raise ValueError("root path is required")

    target_path = resolve_path(path, root)
    if target_path.exists() and target_path.is_dir():
        raise ValueError("path is a directory")

    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(content, encoding="utf-8")

    return f"wrote {target_path.relative_to(root)} ({len(content)} chars)"


def patch_file(path: str, old_text: str, new_text: str, root: Path = None) -> str:
    """替换文件中的文本"""
    if root is None:
        raise ValueError("root path is required")

    target_path = resolve_path(path, root)
    if not target_path.is_file():
        raise ValueError("path is not a file")

    if not old_text:
        raise ValueError("old_text must not be empty")

    text = target_path.read_text(encoding="utf-8")
    count = text.count(old_text)

    if count != 1:
        raise ValueError(f"old_text must occur exactly once, found {count}")

    target_path.write_text(text.replace(old_text, new_text, 1), encoding="utf-8")

    return f"patched {target_path.relative_to(root)}"


def get_workspace_info(root: Path) -> Dict[str, Any]:
    """获取工作区信息"""
    return {
        "root": str(root),
        "files": [str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()],
        "directories": [str(p.relative_to(root)) for p in root.rglob("*") if p.is_dir()]
    }
