"""Trace helpers for the skill-centric runtime."""

from __future__ import annotations

import json
from typing import List

from models.schemas import TraceRecord


class TraceRenderer:
    """Render execution traces in a human-readable way."""

    @staticmethod
    def to_text(trace: TraceRecord) -> str:
        lines: List[str] = []
        lines.append(f"Task: {trace.task}")
        lines.append(f"Task type: {trace.task_type.value}")
        if trace.router_decisions:
            decision = trace.router_decisions[-1]
            lines.append("Router:")
            lines.append(f"- confidence: {decision.confidence:.2f}")
            lines.append(f"- reasoning: {decision.reasoning}")
            lines.append(
                "- selected skills: "
                + ", ".join(f"{skill.name} ({skill.reason})" for skill in decision.selected_skills)
            )
        lines.append("Trace:")
        for record in trace.skill_executions:
            lines.append(
                f"- {record.skill_name}: {record.status.value} | reason={record.reason} | input={record.input_summary} | output={record.output_summary or '-'}"
            )
            if record.fallback_used:
                lines.append(f"  fallback_used=True retry_count={record.retry_count}")
        lines.append("Final Result:")
        lines.append(trace.final_result or "(empty)")
        return "\n".join(lines)

    @staticmethod
    def to_json(trace: TraceRecord) -> str:
        return json.dumps(trace.model_dump(mode="json"), ensure_ascii=False, indent=2)
