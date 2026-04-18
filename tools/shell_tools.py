"""Shell执行相关工具"""

import subprocess
from pathlib import Path
from typing import Dict, Any


def run_shell(command: str, timeout: int = 20, cwd: Path = None) -> str:
    """运行shell命令"""
    command = command.strip()
    if not command:
        raise ValueError("command must not be empty")

    if timeout < 1 or timeout > 120:
        raise ValueError("timeout must be in [1, 120]")

    # 设置工作目录
    work_dir = cwd if cwd else Path.cwd()

    result = subprocess.run(
        command,
        cwd=work_dir,
        shell=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )

    output_lines = [
        f"exit_code: {result.returncode}",
        "stdout:",
        result.stdout.strip() or "(empty)",
        "stderr:",
        result.stderr.strip() or "(empty)",
    ]

    return "\n".join(output_lines)


def check_command_exists(command: str) -> bool:
    """检查命令是否存在"""
    try:
        subprocess.run(
            ["which", command],
            capture_output=True,
            check=True
        )
        return True
    except:
        return False


def get_python_env_info() -> Dict[str, Any]:
    """获取Python环境信息"""
    import sys
    import platform

    return {
        "python_version": sys.version,
        "platform": platform.platform(),
        "executable": sys.executable,
        "path": sys.path[:5],  # 只显示前5个路径
    }
