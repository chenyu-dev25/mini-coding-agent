"""Verification skill for checking generated outputs against explicit criteria."""

from __future__ import annotations

from pathlib import Path
from typing import List

from models import extract_json_object
from models.schemas import SkillDefinition, SkillInput, SkillOutput
from skills.base import BaseSkill


class VerificationSkill(BaseSkill):
    """Check whether the current draft meets the requested constraints."""

    name = "verification"
    description = "Verify that the generated result satisfies required sections, evidence, and decision quality."
    applicable_conditions = ["task requests checks/tests/reliability", "system has a draft to verify"]
    not_applicable_conditions = ["there is no draft output yet"]
    required_tools: List[str] = []
    fallback_skill = "ask_back"

    def __init__(self, root_path: Path, session_id: str, model_client=None):
        super().__init__(root_path, session_id, model_client=model_client)

    @classmethod
    def build_definition(cls) -> SkillDefinition:
        return SkillDefinition(
            name=cls.name,
            purpose=cls.description,
            inputs={
                "task": "Original user request including explicit success criteria.",
                "context": "Required sections, task type, and retry settings.",
                "previous_results": "Earlier skill outputs, especially the latest generated draft.",
            },
            outputs={
                "result": "Verification notes with pass/fail checks.",
                "summary": "Short pass/fail verdict.",
                "metadata": "Checklist, missing sections, and retry advice.",
            },
            applicable_when=[
                "A generated answer or comparison recommendation already exists.",
                "The workflow wants a quality gate before returning the final result.",
            ],
            not_applicable_when=[
                "The task stopped early because clarification is required.",
            ],
            dependencies=[],
            failure_strategy="Return a concrete list of missing elements so the executor can retry generation once.",
        )

    def execute(self, input_data: SkillInput) -> SkillOutput:
        draft = ""
        previous_skill = ""
        if input_data.previous_results:
            draft = input_data.previous_results[-1].get("result", "")
            previous_skill = input_data.previous_results[-1].get("skill", "")

        required_sections = [section.title() for section in input_data.context.get("must_include", [])]
        if input_data.context.get("task_type") == "comparison":
            required_sections.extend(["Recommendation"])
        if previous_skill == "analysis":
            required_sections.append("Analysis")

        if self.model_client and not input_data.context.get("disable_llm"):
            llm_output = self._llm_verify(input_data.task, draft, required_sections)
            if llm_output is not None:
                return llm_output

        checklist = []
        missing = []
        for section in required_sections:
            ok = f"## {section}" in draft
            checklist.append({"item": f"contains section {section}", "passed": ok})
            if not ok:
                missing.append(section)

        if input_data.context.get("task_type") == "comparison" and "Reason:" not in draft:
            checklist.append({"item": "includes recommendation reason", "passed": False})
            missing.append("Decision")
        else:
            checklist.append({"item": "includes recommendation reason", "passed": True})

        success = not missing
        result_lines = [f"- {'PASS' if item['passed'] else 'FAIL'} {item['item']}" for item in checklist]

        return SkillOutput(
            success=success,
            result="\n".join(result_lines),
            summary="Verification passed." if success else f"Verification failed; missing {', '.join(dict.fromkeys(missing))}.",
            metadata={
                "checklist": checklist,
                "missing_sections": list(dict.fromkeys(missing)),
                "needs_retry": not success,
            },
            errors=[] if success else [f"Missing required sections: {', '.join(dict.fromkeys(missing))}"],
        )

    def _llm_verify(self, task: str, draft: str, required_sections: List[str]) -> SkillOutput | None:
        prompt = (
            "You are the verification skill in a skill-centric coding agent.\n"
            "Return JSON only with keys: passed, checklist, missing_sections, summary.\n"
            "checklist must be a list of {item, passed} objects."
        )
        try:
            raw = self.model_client.complete(
                [
                    {"role": "system", "content": prompt},
                    {
                        "role": "user",
                        "content": f"Task:\n{task}\n\nRequired sections:\n{required_sections}\n\nDraft:\n{draft[:5000]}",
                    },
                ],
                max_tokens=900,
                temperature=0.1,
            )
            data = extract_json_object(raw)
            checklist = data.get("checklist", [])
            missing = list(data.get("missing_sections", []) or [])
            for section in required_sections:
                if f"## {section}" not in draft and section not in missing:
                    missing.append(section)
                    checklist.append({"item": f"contains section {section}", "passed": False})
            success = bool(data.get("passed", False)) and not missing
            result_lines = [f"- {'PASS' if item.get('passed') else 'FAIL'} {item.get('item')}" for item in checklist]
            return SkillOutput(
                success=success,
                result="\n".join(result_lines),
                summary=(
                    data.get("summary", "Verification complete.")
                    if success
                    else f"Verification failed; missing {', '.join(missing)}."
                ),
                metadata={
                    "checklist": checklist,
                    "missing_sections": missing,
                    "needs_retry": not success,
                },
                errors=[] if success else [f"Missing required sections: {', '.join(missing)}"],
            )
        except Exception:
            return None
