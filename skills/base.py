"""Base types and helpers for explicit task-oriented skills."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional, Type

from models.clients import ChatModelClient
from models.schemas import SkillDefinition, SkillInfo, SkillInput, SkillOutput, ToolCall
from tools import clip, list_files, patch_file, read_file, resolve_path, run_shell, search, write_file


class BaseSkill(ABC):
    """Base class for every high-level skill."""

    name: str = ""
    description: str = ""
    applicable_conditions: List[str] = []
    not_applicable_conditions: List[str] = []
    required_tools: List[str] = []
    fallback_skill: Optional[str] = None

    def __init__(self, root_path: Path, session_id: str, model_client: Optional[ChatModelClient] = None):
        self.root_path = root_path
        self.session_id = session_id
        self.model_client = model_client
        self.tool_calls: List[ToolCall] = []
        self.logger = logging.getLogger(f"skill.{self.name}")

    @classmethod
    @abstractmethod
    def build_definition(cls) -> SkillDefinition:
        """Return the explicit schema for the skill."""

    @abstractmethod
    def execute(self, input_data: SkillInput) -> SkillOutput:
        """Run the skill."""

    def validate_input(self, input_data: SkillInput) -> bool:
        """Light applicability check before execution."""
        return bool(input_data.task.strip())

    def safe_execute(self, input_data: SkillInput) -> SkillOutput:
        """Execute with a consistent failure wrapper."""
        try:
            if not self.validate_input(input_data):
                return SkillOutput(
                    success=False,
                    result="",
                    summary=f"{self.name} rejected the input",
                    errors=[f"Input validation failed for skill {self.name}"],
                )
            result = self.execute(input_data)
            if not result.summary:
                result.summary = clip(result.result, 160)
            return result
        except Exception as exc:  # pragma: no cover - defensive path
            self.logger.exception("Skill %s failed", self.name)
            return self.fallback(input_data, str(exc))

    def fallback(self, input_data: SkillInput, error: str) -> SkillOutput:
        """Default fallback behaviour."""
        metadata: Dict[str, Any] = {"original_error": error}
        if self.fallback_skill:
            metadata["fallback_skill"] = self.fallback_skill
        return SkillOutput(
            success=False,
            result="",
            summary=f"{self.name} failed: {error}",
            metadata=metadata,
            errors=[f"Skill {self.name} failed: {error}"],
        )

    def record_tool_call(
        self,
        name: str,
        args: Dict[str, Any],
        result: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        """Store a tool call in the trace."""
        self.tool_calls.append(
            ToolCall(
                name=name,
                args=args,
                result=clip(result) if result else None,
                status="error" if error else "success",
                error=error,
            )
        )

    def consume_tool_calls(self) -> List[ToolCall]:
        """Return and clear the pending tool calls."""
        calls = list(self.tool_calls)
        self.tool_calls.clear()
        return calls

    def get_skill_info(self) -> SkillInfo:
        """Compatibility helper for older metadata views."""
        definition = self.build_definition()
        return SkillInfo(
            name=definition.name,
            description=definition.purpose,
            input_schema=definition.inputs,
            output_schema=definition.outputs,
            applicable_conditions=definition.applicable_when,
            not_applicable_conditions=definition.not_applicable_when,
            required_tools=definition.dependencies,
            fallback_skill=self.fallback_skill,
        )


class ToolExecutorMixin:
    """Small wrapper so skills can use low-level tools safely."""

    def __init__(self, root_path: Path):
        self.root_path = root_path

    def execute_tool(self, tool_name: str, args: Dict[str, Any]) -> str:
        if tool_name == "list_files":
            return list_files(args.get("path", "."), self.root_path)
        if tool_name == "read_file":
            return read_file(args["path"], args.get("start", 1), args.get("end", 200), self.root_path)
        if tool_name == "search":
            return search(args["pattern"], args.get("path", "."), self.root_path)
        if tool_name == "write_file":
            return write_file(args["path"], args["content"], self.root_path)
        if tool_name == "patch_file":
            return patch_file(args["path"], args["old_text"], args["new_text"], self.root_path)
        if tool_name == "run_shell":
            return run_shell(args["command"], args.get("timeout", 20), self.root_path)
        if tool_name == "resolve_path":
            return str(resolve_path(args["path"], self.root_path))
        raise ValueError(f"Unknown tool: {tool_name}")

    def record_tool_usage(self, skill: BaseSkill, tool_name: str, args: Dict[str, Any]) -> str:
        try:
            result = self.execute_tool(tool_name, args)
            skill.record_tool_call(tool_name, args, result=result)
            return result
        except Exception as exc:
            skill.record_tool_call(tool_name, args, error=str(exc))
            raise


class SkillRegistry:
    """Registry that keeps skill implementations loosely coupled to execution."""

    def __init__(self) -> None:
        self._skills: Dict[str, Type[BaseSkill]] = {}

    def register(self, skill_cls: Type[BaseSkill]) -> None:
        if not skill_cls.name:
            raise ValueError("Skill class must define a non-empty name")
        self._skills[skill_cls.name] = skill_cls

    def create(
        self,
        name: str,
        root_path: Path,
        session_id: str,
        model_client: Optional[ChatModelClient] = None,
    ) -> BaseSkill:
        try:
            skill_cls = self._skills[name]
        except KeyError as exc:
            raise KeyError(f"Unknown skill: {name}") from exc
        return skill_cls(root_path=root_path, session_id=session_id, model_client=model_client)

    def definitions(self) -> Dict[str, SkillDefinition]:
        return {name: skill_cls.build_definition() for name, skill_cls in self._skills.items()}

    def names(self) -> List[str]:
        return list(self._skills.keys())
