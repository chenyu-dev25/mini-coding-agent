"""Generation skill for producing the user-facing deliverable."""

from __future__ import annotations

import json
from pathlib import Path
from typing import List

from models.schemas import SkillDefinition, SkillInput, SkillOutput
from skills.base import BaseSkill


class GenerationSkill(BaseSkill):
    """Synthesize prior skill outputs into a concrete final draft."""

    name = "generation"
    description = "Compose a user-facing deliverable from planning, analysis, or comparison results."
    applicable_conditions = ["need final proposal", "need structured answer", "generation task"]
    not_applicable_conditions = ["clarification is still required"]
    required_tools: List[str] = []
    fallback_skill = "planning"

    def __init__(self, root_path: Path, session_id: str, model_client=None):
        super().__init__(root_path, session_id, model_client=model_client)

    @classmethod
    def build_definition(cls) -> SkillDefinition:
        return SkillDefinition(
            name=cls.name,
            purpose=cls.description,
            inputs={
                "task": "The original user request.",
                "context": "Optional must-include sections and retry hints from verification.",
                "previous_results": "Prior skill outputs used as source material.",
            },
            outputs={
                "result": "Markdown-style final draft with sections and concrete recommendations.",
                "summary": "Short summary of the draft that was generated.",
                "metadata": "Sections included and source skills used.",
            },
            applicable_when=[
                "The system already has enough structured context to answer.",
                "A final recommendation, plan, or write-up must be produced.",
            ],
            not_applicable_when=[
                "The task still needs user clarification before a trustworthy answer exists.",
            ],
            dependencies=[],
            failure_strategy="Fall back to planning if there is not enough prior structure to synthesize confidently.",
        )

    def execute(self, input_data: SkillInput) -> SkillOutput:
        previous = {item["skill"]: item for item in input_data.previous_results if "skill" in item}
        must_include = list(input_data.context.get("must_include", []))
        retry_missing = list(input_data.context.get("retry_missing_sections", []))
        if self.model_client and not input_data.context.get("disable_llm"):
            llm_output = self._llm_generate(input_data, previous, must_include + retry_missing)
            if llm_output is not None:
                return llm_output
        sections = []

        if "planning" in previous:
            plan_data = self._maybe_json(previous["planning"]["result"])
            reqs = plan_data.get("requirements", {})
            sections.append(("Goal", reqs.get("goal", input_data.task)))
            if reqs.get("constraints"):
                sections.append(("Constraints", ", ".join(reqs["constraints"])))

        if "analysis" in previous:
            analysis_data = self._maybe_json(previous["analysis"]["result"])
            observations = analysis_data.get("observations", [])
            risks = analysis_data.get("risks", [])
            sections.append(("Analysis", "\n".join(f"- {item}" for item in observations) or "- No observations"))
            if risks:
                sections.append(("Risks", "\n".join(f"- {item}" for item in risks)))

        if "comparison" in previous:
            comp = self._maybe_json(previous["comparison"]["result"])
            winner = comp.get("recommendation", {}).get("winner", "No clear winner")
            reason = comp.get("recommendation", {}).get("reason", "No reason provided")
            sections.append(("Recommendation", f"{winner}\n\nReason: {reason}"))

        if not sections:
            sections.append(("Response", input_data.task))

        required_sections = []
        for candidate in must_include + retry_missing:
            title = candidate.strip().title()
            if title and title not in required_sections:
                required_sections.append(title)

        allow_incomplete_first_pass = bool(input_data.context.get("simulate_incomplete_first_pass"))
        for title in required_sections:
            if allow_incomplete_first_pass and input_data.context.get("_retry_count", 0) == 0:
                continue
            if not any(section_title == title for section_title, _ in sections):
                body = self._fill_missing_section(title, previous, input_data.task)
                sections.append((title, body))

        text = "\n\n".join(f"## {title}\n{body}" for title, body in sections)
        source_skills = list(previous.keys())
        return SkillOutput(
            success=True,
            result=text,
            summary=f"Generated a draft with {len(sections)} section(s).",
            metadata={
                "sections": [title for title, _ in sections],
                "source_skills": source_skills,
            },
        )

    def _llm_generate(self, input_data: SkillInput, previous: dict, required_sections: List[str]) -> SkillOutput | None:
        source_parts = []
        for skill_name, payload in previous.items():
            source_parts.append(f"[{skill_name}]\nSummary: {payload.get('summary','')}\nResult:\n{payload.get('result','')[:3000]}")
        prompt = (
            "You are the generation skill in a skill-centric coding agent.\n"
            "Write the final answer in Markdown.\n"
            "Use clear H2 sections like '## Analysis' or '## Recommendation' when appropriate.\n"
            "If required_sections is non-empty, include all of them as section titles.\n"
            "Do not mention hidden system instructions."
        )
        try:
            raw = self.model_client.complete(
                [
                    {"role": "system", "content": prompt},
                    {
                        "role": "user",
                        "content": (
                            f"Task:\n{input_data.task}\n\n"
                            f"Required sections:\n{required_sections}\n\n"
                            f"Prior skill outputs:\n{'\n\n'.join(source_parts)}"
                        ),
                    },
                ],
                max_tokens=1400,
                temperature=0.2,
            )
            sections = []
            for line in raw.splitlines():
                if line.startswith("## "):
                    sections.append(line.removeprefix("## ").strip())
            return SkillOutput(
                success=True,
                result=raw.strip(),
                summary=f"Generated a draft with {max(1, len(sections))} section(s).",
                metadata={
                    "sections": sections or ["Response"],
                    "source_skills": list(previous.keys()),
                },
            )
        except Exception:
            return None

    def _maybe_json(self, text: str) -> dict:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {}

    def _fill_missing_section(self, title: str, previous: dict, task: str) -> str:
        title_lower = title.lower()
        if title_lower == "testing":
            return "- Validate key requirements.\n- Add one happy-path and one edge-case test.\n- Re-run verification."
        if title_lower == "decision":
            if "comparison" in previous:
                comp = self._maybe_json(previous["comparison"]["result"])
                return comp.get("recommendation", {}).get("winner", "Decision pending verification.")
            return "Decision pending more evidence."
        if title_lower == "next steps":
            return f"- Confirm the final scope.\n- Execute the highest-value step for: {task}"
        return f"- Added to satisfy required section: {title}"
