"""Execution engine for the skill-centric agent runtime."""

from __future__ import annotations

import time
import uuid
from pathlib import Path
import re
from typing import Callable, Dict, List, Optional, Tuple

from models.clients import ChatModelClient
from models.schemas import (
    RouterDecision,
    SkillExecutionRecord,
    SkillInput,
    SkillOutput,
    SkillStatus,
    TaskType,
    TraceRecord,
)
from router import (
    SkillRouter,
    is_pure_greeting,
    is_skill_catalog_query,
    wants_skill_pipeline,
)
from skills import build_default_registry
from skills.base import BaseSkill, SkillRegistry


class SkillAgent:
    """Run a task through routing, skill execution, fallback, and trace capture."""

    def __init__(
        self,
        root_path: Path,
        registry: Optional[SkillRegistry] = None,
        model_client: Optional[ChatModelClient] = None,
        use_skill_pipeline: bool = False,
    ):
        self.root_path = Path(root_path).resolve()
        self.registry = registry or build_default_registry()
        self.router = SkillRouter(self.registry)
        self.model_client = model_client
        self.use_skill_pipeline = use_skill_pipeline

    def run(
        self,
        task: str,
        context: Optional[Dict] = None,
        *,
        on_progress: Optional[Callable[[str], None]] = None,
    ) -> TraceRecord:
        context = dict(context or {})
        inferred_sections = self._infer_must_include_from_task(task)
        if inferred_sections:
            merged = list(dict.fromkeys(list(context.get("must_include", [])) + inferred_sections))
            context["must_include"] = merged
        started = time.time()
        session_id = uuid.uuid4().hex[:12]

        if is_pure_greeting(task):
            trace = TraceRecord(session_id=session_id, task=task, task_type=TaskType.CHITCHAT, timestamp=started)
            if on_progress:
                on_progress("… 寒暄 · 调用 LLM …")
            trace.final_result = self._render_chitchat(task)
            trace.total_duration = round(time.time() - started, 4)
            if on_progress:
                on_progress(f"✓ 完成 · {trace.total_duration}s")
            return trace

        if is_skill_catalog_query(task):
            trace = TraceRecord(session_id=session_id, task=task, task_type=TaskType.SKILL_CATALOG, timestamp=started)
            if on_progress:
                on_progress("… skill 目录 · 调用 LLM …")
            trace.final_result = self._render_skill_catalog(task)
            trace.total_duration = round(time.time() - started, 4)
            if on_progress:
                on_progress(f"✓ 完成 · {trace.total_duration}s")
            return trace

        if not wants_skill_pipeline(task, context, agent_default=self.use_skill_pipeline):
            trace = TraceRecord(session_id=session_id, task=task, task_type=TaskType.DIRECT, timestamp=started)
            if on_progress:
                on_progress("… 直连模式 · 调用 LLM …")
            trace.final_result = self._direct_reply(task)
            trace.total_duration = round(time.time() - started, 4)
            if on_progress:
                on_progress(f"✓ 完成 · {trace.total_duration}s")
            return trace

        task_input = SkillInput(task=task, context=context)
        route = self.router.select_skills(task_input)
        trace = TraceRecord(
            session_id=session_id,
            task=task,
            task_type=route.task_type,
            timestamp=started,
        )
        trace.router_decisions.append(route)
        context["task_type"] = route.task_type.value
        previous_results: List[Dict] = []
        final_result = ""
        chain = " → ".join(s.name for s in route.selected_skills)
        if on_progress:
            on_progress(f"路由: {route.task_type.value} · {chain}")

        n_skills = len(route.selected_skills)
        for i, routed_skill in enumerate(route.selected_skills, start=1):
            execution_input = SkillInput(task=task, context=context, previous_results=previous_results)
            record = self._execute_skill(
                routed_skill.name,
                routed_skill.reason,
                execution_input,
                on_progress=on_progress,
                step=(i, n_skills),
            )
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
                if on_progress:
                    on_progress("… 信息不足 · 追问 ask_back …")
                fallback = self._run_ask_back(task, context, output, trace, on_progress=on_progress)
                final_result = fallback.output.result if fallback.output else output.result
                break

            if record.skill_name == "verification" and not output.success:
                if on_progress:
                    on_progress("… verification 未通过 · 尝试重写 generation …")
                final_result = self._maybe_retry_generation(
                    task, context, previous_results, trace, route, output, on_progress=on_progress
                )
                break

            if record.skill_name == "verification":
                final_result = previous_results[-2]["result"] if len(previous_results) >= 2 else output.result
            else:
                final_result = output.result

        trace.final_result = final_result
        trace.total_duration = round(time.time() - started, 4)
        if on_progress:
            on_progress(f"✓ 流水线结束 · 总耗时 {trace.total_duration}s")
        return trace

    def _llm_reply(self, system: str, user: str, *, max_tokens: int = 1200, temperature: float = 0.25) -> str:
        """All user-visible replies in fast paths must go through the configured LLM API."""
        if not self.model_client:
            return (
                "此回复必须通过 LLM API 生成，但当前未配置模型客户端（例如使用了 `--provider none`）。\n"
                "请使用默认的 `--provider ollama` 或 `--provider moonshot` 并保证服务可用。"
            )
        try:
            text = self.model_client.complete(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except Exception as exc:
            return (
                f"LLM API 调用失败：{exc}\n\n"
                "请检查网络、API Key（moonshot）或本地 Ollama 是否在运行，然后重试。"
            )
        text = (text or "").strip()
        if not text:
            return (
                "模型返回了空正文（content 为空）。若使用 Ollama 的思考类模型，请确认已升级到支持请求体里 "
                "`think: false` 的版本，或换用非 thinking 变体模型；也可尝试其它 `--model`。\n"
                "仍为空时请查看 Ollama / API 日志中的原始响应字段（thinking / reasoning）。"
            )
        return text

    def _render_skill_catalog(self, user_task: str) -> str:
        """Answer skill-list questions via LLM; registry text is factual context only."""
        catalog_lines = []
        for name, definition in sorted(self.registry.definitions().items()):
            catalog_lines.append(f"- {name}: {definition.purpose}")
        bundle = "\n".join(catalog_lines)
        system = (
            "You are Mini Coding Agent. The user wants to know what skills exist.\n"
            "Using ONLY the registry lines below, answer in the same language as the user's message. "
            "List each skill with its purpose; do not invent skills. "
            "You may add one short line on how to run `schemas` for full schema if relevant."
        )
        user = f"Skill registry (authoritative):\n{bundle}\n\nUser message:\n{user_task}"
        return self._llm_reply(system, user, max_tokens=1400, temperature=0.2)

    def _render_chitchat(self, task: str) -> str:
        """Greeting/thanks path: must use LLM, not a hand-written template."""
        system = (
            "You are Mini Coding Agent, a skill-centric assistant for coding and tasks.\n"
            "The user sent a short greeting, thanks, or acknowledgement.\n"
            "Reply naturally in the user's language, briefly and warmly.\n"
            "Optionally mention they can describe a concrete task, or use /skills for commands, or ask what skills exist."
        )
        return self._llm_reply(system, task, max_tokens=600, temperature=0.35)

    def _direct_reply(self, task: str) -> str:
        """Default path: one chat completion via LLM API (no staged skill pipeline)."""
        system = (
            "You are a helpful assistant for software engineering and general questions.\n"
            "Answer concisely and accurately in the same language as the user."
        )
        return self._llm_reply(system, task, max_tokens=1200, temperature=0.2)

    def _execute_skill(
        self,
        name: str,
        reason: str,
        skill_input: SkillInput,
        *,
        on_progress: Optional[Callable[[str], None]] = None,
        step: Optional[Tuple[int, int]] = None,
    ) -> SkillExecutionRecord:
        if on_progress:
            label = f"[{step[0]}/{step[1]}] " if step else ""
            on_progress(f"▸ {label}{name} …")
        skill = self.registry.create(
            name,
            self.root_path,
            session_id=uuid.uuid4().hex[:8],
            model_client=self.model_client,
        )
        start = time.time()
        output = skill.safe_execute(skill_input)
        end = time.time()
        if on_progress:
            label = f"[{step[0]}/{step[1]}] " if step else ""
            mark = "OK" if output.success else "FAIL"
            on_progress(f"✓ {label}{name} · {mark} · {round(end - start, 2)}s")
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

    def _run_ask_back(
        self,
        task: str,
        context: Dict,
        output: SkillOutput,
        trace: TraceRecord,
        *,
        on_progress: Optional[Callable[[str], None]] = None,
    ) -> SkillExecutionRecord:
        ask_context = dict(context)
        ask_context["questions"] = output.metadata.get("questions", [])
        ask_input = SkillInput(task=task, context=ask_context, previous_results=[])
        record = self._execute_skill(
            "ask_back",
            "Fallback because planning determined the task is too ambiguous.",
            ask_input,
            on_progress=on_progress,
        )
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
        *,
        on_progress: Optional[Callable[[str], None]] = None,
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
            on_progress=on_progress,
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
            on_progress=on_progress,
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
