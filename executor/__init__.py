"""Execution engine for the skill-centric agent runtime."""

from __future__ import annotations

import time
import uuid
from pathlib import Path
import re
from typing import Dict, List, Optional

from models.clients import ChatModelClient
from models.schemas import (
    RouterDecision,
    SkillExecutionRecord,
    SkillInput,
    SkillOutput,
    SkillStatus,
    TraceRecord,
)
from router import SkillRouter
from skills import build_default_registry
from skills.base import BaseSkill, SkillRegistry


class SkillAgent:
    """Run a task through routing, skill execution, fallback, and trace capture."""

    def __init__(
        self,
        root_path: Path,
        registry: Optional[SkillRegistry] = None,
        model_client: Optional[ChatModelClient] = None,
    ):
        self.root_path = Path(root_path).resolve()
        self.registry = registry or build_default_registry()
        self.router = SkillRouter(self.registry)
        self.model_client = model_client

    def run(self, task: str, context: Optional[Dict] = None) -> TraceRecord:
        context = dict(context or {})
        inferred_sections = self._infer_must_include_from_task(task)
        if inferred_sections:
            merged = list(dict.fromkeys(list(context.get("must_include", [])) + inferred_sections))
            context["must_include"] = merged
        task_input = SkillInput(task=task, context=context)
        started = time.time()
        trace = TraceRecord(
            session_id=uuid.uuid4().hex[:12],
            task=task,
            task_type=self.router.classify(task_input).task_type,
            timestamp=started,
        )

        route = self.router.select_skills(task_input)
        trace.router_decisions.append(route)
        context["task_type"] = route.task_type.value
        previous_results: List[Dict] = []
        final_result = ""

        for routed_skill in route.selected_skills:
            execution_input = SkillInput(task=task, context=context, previous_results=previous_results)
            record = self._execute_skill(routed_skill.name, routed_skill.reason, execution_input)
            trace.skill_executions.append(record)
            output = record.output or SkillOutput(success=False, result="", summary=record.output_summary or "", errors=[])
            previous_results.append(
                {
                    "skill": record.skill_name,
                    "result": output.result,
                    "summary": output.summary,
                    "metadata": output.metadata,
                    "success": output.success,
                }
            )

            if record.skill_name == "planning" and output.metadata.get("requires_clarification"):
                fallback = self._run_ask_back(task, context, output, trace)
                final_result = fallback.output.result if fallback.output else output.result
                break

            if record.skill_name == "verification" and not output.success:
                final_result = self._maybe_retry_generation(task, context, previous_results, trace, route, output)
                break

            if record.skill_name == "verification":
                final_result = previous_results[-2]["result"] if len(previous_results) >= 2 else output.result
            else:
                final_result = output.result

        trace.final_result = final_result
        trace.total_duration = round(time.time() - started, 4)
        return trace

    def _execute_skill(self, name: str, reason: str, skill_input: SkillInput) -> SkillExecutionRecord:
        skill = self.registry.create(
            name,
            self.root_path,
            session_id=uuid.uuid4().hex[:8],
            model_client=self.model_client,
        )
        start = time.time()
        output = skill.safe_execute(skill_input)
        end = time.time()
        status = SkillStatus.SUCCESS if output.success else SkillStatus.FAILED
        return SkillExecutionRecord(
            skill_name=name,
            skill_type=name,
            status=status,
            reason=reason,
            input_summary=self._summarize_input(skill_input),
            output_summary=output.summary,
            input=skill_input,
            output=output,
            start_time=start,
            end_time=end,
            duration=round(end - start, 4),
            tool_calls=skill.consume_tool_calls(),
            fallback_used=bool(output.metadata.get("fallback_skill")),
            retry_count=skill_input.context.get("_retry_count", 0),
        )

    def _run_ask_back(self, task: str, context: Dict, output: SkillOutput, trace: TraceRecord) -> SkillExecutionRecord:
        ask_context = dict(context)
        ask_context["questions"] = output.metadata.get("questions", [])
        ask_input = SkillInput(task=task, context=ask_context, previous_results=[])
        record = self._execute_skill("ask_back", "Fallback because planning determined the task is too ambiguous.", ask_input)
        record.status = SkillStatus.FALLBACK
        record.fallback_used = True
        trace.skill_executions.append(record)
        return record

    def _maybe_retry_generation(
        self,
        task: str,
        context: Dict,
        previous_results: List[Dict],
        trace: TraceRecord,
        route: RouterDecision,
        verification_output: SkillOutput,
    ) -> str:
        route_skill_names = [item.name for item in route.selected_skills]
        if "generation" not in route_skill_names or context.get("_retry_count", 0) >= 1:
            return previous_results[-2]["result"] if len(previous_results) >= 2 else previous_results[-1]["result"]

        retry_context = dict(context)
        retry_context["_retry_count"] = retry_context.get("_retry_count", 0) + 1
        retry_context["retry_missing_sections"] = verification_output.metadata.get("missing_sections", [])
        retry_input = SkillInput(task=task, context=retry_context, previous_results=previous_results[:-1])
        generation_record = self._execute_skill(
            "generation",
            "Retry generation because verification found missing required sections.",
            retry_input,
        )
        generation_record.status = SkillStatus.FALLBACK if generation_record.output and generation_record.output.success else generation_record.status
        generation_record.fallback_used = True
        generation_record.retry_count = retry_context["_retry_count"]
        trace.skill_executions.append(generation_record)

        retry_previous = previous_results[:-1] + [
            {
                "skill": "generation",
                "result": generation_record.output.result if generation_record.output else "",
                "summary": generation_record.output.summary if generation_record.output else "",
                "metadata": generation_record.output.metadata if generation_record.output else {},
                "success": generation_record.output.success if generation_record.output else False,
            }
        ]
        verification_retry = self._execute_skill(
            "verification",
            "Re-check the regenerated draft after the retry.",
            SkillInput(task=task, context=retry_context, previous_results=retry_previous),
        )
        verification_retry.retry_count = retry_context["_retry_count"]
        trace.skill_executions.append(verification_retry)
        if generation_record.output:
            return generation_record.output.result
        return previous_results[-1]["result"]

    def _summarize_input(self, skill_input: SkillInput) -> str:
        if len(skill_input.task) <= 80:
            return skill_input.task
        return skill_input.task[:77] + "..."

    def _infer_must_include_from_task(self, task: str) -> List[str]:
        inferred: List[str] = []
        patterns = [
            r"必须包含\s+([A-Za-z][A-Za-z0-9_-]*)\s*(?:和|and|,)\s*([A-Za-z][A-Za-z0-9_-]*)",
            r"must include\s+([A-Za-z][A-Za-z0-9_-]*)\s*(?:and|,)\s*([A-Za-z][A-Za-z0-9_-]*)",
        ]
        for pattern in patterns:
            match = re.search(pattern, task, re.IGNORECASE)
            if match:
                inferred.extend([match.group(1).lower(), match.group(2).lower()])
        return list(dict.fromkeys(inferred))
