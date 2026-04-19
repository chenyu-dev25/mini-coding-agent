"""Standalone trace renderer module to avoid stdlib name conflicts."""

from __future__ import annotations

import json
import shutil
import sys
from typing import List, Optional

from markdown_console import format_trace_preview, indent_block
from models.schemas import RoutedSkill, SkillExecutionRecord, SkillStatus, TaskType, TraceRecord


def _clip(text: Optional[str], max_len: int = 140) -> str:
    if not text:
        return "—"
    t = text.replace("\n", " ").strip()
    if len(t) <= max_len:
        return t
    return t[: max_len - 1] + "…"


def _indent_lines(text: str, prefix: str = "        ") -> str:
    """Preserve newlines for multiline step previews."""
    lines = text.splitlines()
    if len(lines) > 80:
        lines = lines[:80] + ["… [truncated: too many lines]"]
    return "\n".join(prefix + (ln if ln else "") for ln in lines)


def _step_body_preview(result: Optional[str], max_chars: int) -> Optional[str]:
    if not result or not str(result).strip():
        return None
    body = str(result).strip()
    if len(body) > max_chars:
        return body[:max_chars] + "\n… [truncated]"
    return body


def _status_mark(status: SkillStatus) -> str:
    return {
        SkillStatus.SUCCESS: "OK",
        SkillStatus.FAILED: "FAIL",
        SkillStatus.FALLBACK: "FALLBACK",
        SkillStatus.SKIPPED: "SKIP",
        SkillStatus.PENDING: "PEND",
        SkillStatus.RUNNING: "RUN",
    }.get(status, status.value)


class TraceRenderer:
    """Render execution traces in a human-readable way."""

    @staticmethod
    def to_text(
        trace: TraceRecord,
        *,
        include_final_result: bool = False,
        step_output_max_chars: int = 6000,
        ansi_markdown_previews: Optional[bool] = None,
    ) -> str:
        use_ansi_previews = sys.stdout.isatty() if ansi_markdown_previews is None else ansi_markdown_previews
        lines: List[str] = []
        width = 52
        lines.append("═" * width)
        head = f" Task · {trace.task_type.value}"
        if trace.total_duration is not None:
            head += f" · {trace.total_duration}s"
        head += f" · {trace.session_id}"
        lines.append(head)
        lines.append("═" * width)

        # --- Router / fast path ---
        if trace.task_type == TaskType.DIRECT:
            lines.append(
                "Mode: **direct**（单次 LLM，未走 skill 流水线）\n"
                "  开启流水线: `--skill-pipeline`、`/pipeline`、`SKILL_AGENT_PIPELINE=1`，"
                "或强意图词如 分析/比较/整理需求。"
            )
        elif trace.task_type in (TaskType.CHITCHAT, TaskType.SKILL_CATALOG):
            kind = "寒暄/致谢" if trace.task_type == TaskType.CHITCHAT else "skill 目录"
            lines.append(f"Mode: **{kind}**（直连 LLM，未经过 router 选链）")
        elif trace.router_decisions:
            decision = trace.router_decisions[-1]
            planned = " → ".join(s.name for s in decision.selected_skills) or "(none)"
            lines.append("Router 决策")
            lines.append(f"  task_type: {decision.task_type.value}")
            lines.append(f"  confidence: {decision.confidence:.2f}")
            lines.append(f"  reasoning: {decision.reasoning}")
            lines.append("")
            lines.append("Skill 调用链（路由计划）")
            lines.append(f"  {planned}")
            lines.append("")
            lines.append(_TraceRendererInternals._planned_chain_ascii(decision.selected_skills))

        # --- Execution log ---
        if trace.skill_executions:
            lines.append("─" * width)
            lines.append(f"执行记录（共 {len(trace.skill_executions)} 步，含每步产出预览）")
            for i, record in enumerate(trace.skill_executions, start=1):
                lines.extend(
                    _TraceRendererInternals._format_step(
                        i,
                        len(trace.skill_executions),
                        record,
                        step_output_max_chars=step_output_max_chars,
                        ansi_markdown_preview=use_ansi_previews,
                    )
                )
            lines.append("")
            lines.append(_TraceRendererInternals._answer_provenance(trace))
        else:
            lines.append("─" * width)
            lines.append("执行记录:（无 skill 步骤）")

        lines.append("═" * width)
        if include_final_result:
            lines.append("Final result")
            lines.append("─" * width)
            lines.append(trace.final_result or "(empty)")
        return "\n".join(lines)

    @staticmethod
    def to_json(trace: TraceRecord) -> str:
        return json.dumps(trace.model_dump(mode="json"), ensure_ascii=False, indent=2)


class _TraceRendererInternals:
    """Helpers kept out of the public class surface."""

    @staticmethod
    def _planned_chain_ascii(selected: List[RoutedSkill]) -> str:
        if not selected:
            return "  (no skills selected)"
        parts = ["  [task]"]
        for s in selected:
            parts.append("      │")
            parts.append(f"      ▼  {s.name}")
        parts.append("      │")
        parts.append("  [final → user]")
        return "\n".join(parts)

    @staticmethod
    def _format_step(
        i: int,
        total: int,
        record: SkillExecutionRecord,
        *,
        step_output_max_chars: int,
        ansi_markdown_preview: bool,
    ) -> List[str]:
        out: List[str] = []
        dur = f"{record.duration}s" if record.duration is not None else "—"
        mark = _status_mark(record.status)
        fb = " · fallback" if record.fallback_used else ""
        out.append(f"  [{i}/{total}] {record.skill_name} · {mark} · {dur}{fb}")
        out.append(f"        why: {_clip(record.reason, 200)}")
        summary = record.output_summary or (record.output.summary if record.output else None)
        out.append(f"        summary: {_clip(summary, 200)}")
        if record.tool_calls:
            names = ", ".join(tc.name for tc in record.tool_calls[:6])
            more = f" (+{len(record.tool_calls) - 6} more)" if len(record.tool_calls) > 6 else ""
            out.append(f"        tools: {names}{more}")
        if record.retry_count:
            out.append(f"        retry_count: {record.retry_count}")
        raw = record.output.result if record.output else None
        preview = _step_body_preview(raw, step_output_max_chars)
        if preview:
            n = len(raw) if raw else 0
            if ansi_markdown_preview:
                out.append(f"        本步产出（Markdown 渲染预览，约 {min(n, step_output_max_chars)} / {n} 字符）:")
                try:
                    tw = max(52, shutil.get_terminal_size((88, 20)).columns - 14)
                    pretty = format_trace_preview(preview, width=tw)
                    out.append(indent_block(pretty))
                except Exception:
                    out.append(_indent_lines(preview))
            else:
                out.append(f"        本步产出（原文预览，约 {min(n, step_output_max_chars)} / {n} 字符）:")
                out.append(_indent_lines(preview))
        elif record.output and not record.output.success and record.output.errors:
            out.append("        errors: " + "; ".join(record.output.errors[:3]))
        out.append("")
        return out

    @staticmethod
    def _answer_provenance(trace: TraceRecord) -> str:
        names = [r.skill_name for r in trace.skill_executions]
        if not names:
            return "▶ 可见答案: 由上方面「Mode」对应的单次 LLM 路径直接生成。"
        if names[-1] == "verification" and len(names) >= 2:
            src = names[-2]
            return (
                f"▶ 可见答案来源: 步骤「{src}」的产出。"
                "「verification」只做质检/清单，不改写正文；若 verify 失败会触发 regeneration。"
            )
        return f"▶ 可见答案来源: 最后一步「{names[-1]}」的产出。"
