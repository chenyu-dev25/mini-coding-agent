"""Comparison skill for option evaluation and recommendation."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List

from models import extract_json_object
from models.schemas import SkillDefinition, SkillInput, SkillOutput
from skills.base import BaseSkill


class ComparisonSkill(BaseSkill):
    """Evaluate multiple options with explicit criteria and a recommendation."""

    name = "comparison"
    description = "Compare candidate options, score them against criteria, and recommend one."
    applicable_conditions = ["multiple explicit options", "task asks which/better/vs/比较"]
    not_applicable_conditions = ["single-option implementation task", "pure file analysis"]
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
                "task": "Prompt containing at least two options or an explicit comparison request.",
                "context": "Optional options list and decision criteria.",
                "previous_results": "Planning output or earlier analysis to ground the criteria.",
            },
            outputs={
                "result": "JSON with options, criteria, scores, trade-offs, and recommendation.",
                "summary": "One-line winner and the main reason.",
                "metadata": "Recommended option and scoring table.",
            },
            applicable_when=[
                "The user asks to compare multiple choices or decide between alternatives.",
                "The system needs a recommendation instead of raw analysis only.",
            ],
            not_applicable_when=[
                "There is only one obvious solution path and no decision to make.",
                "The task is mainly about asking follow-up questions for clarity.",
            ],
            dependencies=[],
            failure_strategy="Fall back to planning if the options or criteria cannot be extracted confidently.",
        )

    def execute(self, input_data: SkillInput) -> SkillOutput:
        options = self._extract_options(input_data)
        criteria = self._extract_criteria(input_data.task, input_data.context)

        if len(options) < 2:
            return SkillOutput(
                success=False,
                result="",
                summary="Could not compare because fewer than two options were found.",
                metadata={"requires_clarification": True, "fallback_skill": self.fallback_skill},
                errors=["Need at least two candidate options for comparison."],
            )

        if self.model_client and not input_data.context.get("disable_llm"):
            llm_output = self._llm_compare(input_data.task, options, criteria)
            if llm_output is not None:
                return llm_output

        scores = []
        for option in options:
            score = 0
            reasoning = []
            for criterion in criteria:
                if criterion in {"speed", "simplicity"} and len(option) < 10:
                    score += 2
                    reasoning.append(f"strong on {criterion}")
                elif criterion in {"control", "extensibility"} and any(word in option.lower() for word in ["custom", "self", "manual"]):
                    score += 2
                    reasoning.append(f"strong on {criterion}")
                else:
                    score += 1
                    reasoning.append(f"acceptable on {criterion}")
            scores.append({"option": option, "score": score, "reasoning": reasoning})

        scores.sort(key=lambda item: (-item["score"], item["option"]))
        winner = scores[0]
        payload = {
            "options": options,
            "criteria": criteria,
            "scores": scores,
            "recommendation": {
                "winner": winner["option"],
                "reason": ", ".join(winner["reasoning"][:2]),
            },
        }

        return SkillOutput(
            success=True,
            result=json.dumps(payload, ensure_ascii=False, indent=2),
            summary=f"Recommended {winner['option']} based on {', '.join(criteria[:2])}.",
            metadata={"recommended_option": winner["option"], "criteria": criteria, "scores": scores},
        )

    def _llm_compare(self, task: str, options: List[str], criteria: List[str]) -> SkillOutput | None:
        prompt = (
            "You are the comparison skill in a skill-centric coding agent.\n"
            "Return JSON only with keys: options, criteria, scores, recommendation.\n"
            "recommendation must contain winner and reason.\n"
            "scores must be a list of objects with option, score, reasoning."
        )
        try:
            raw = self.model_client.complete(
                [
                    {"role": "system", "content": prompt},
                    {
                        "role": "user",
                        "content": f"Task: {task}\nOptions: {options}\nCriteria: {criteria}",
                    },
                ],
                max_tokens=1000,
                temperature=0.1,
            )
            payload = extract_json_object(raw)
            winner = payload.get("recommendation", {}).get("winner", options[0])
            return SkillOutput(
                success=True,
                result=json.dumps(payload, ensure_ascii=False, indent=2),
                summary=f"Recommended {winner} based on {', '.join(criteria[:2])}.",
                metadata={
                    "recommended_option": winner,
                    "criteria": payload.get("criteria", criteria),
                    "scores": payload.get("scores", []),
                },
            )
        except Exception:
            return None

    def _extract_options(self, input_data: SkillInput) -> List[str]:
        if input_data.context.get("options"):
            return [str(option).strip() for option in input_data.context["options"] if str(option).strip()]
        task = input_data.task
        if " vs " in task.lower():
            cleaned = []
            for part in re.split(r"\bvs\b", task, flags=re.IGNORECASE):
                part = part.strip(" .，。")
                part = re.sub(r"^(比较|对比)\s*", "", part)
                part = re.sub(r"(并给出.*|给出.*|哪个好.*)$", "", part).strip(" .，。")
                if part:
                    cleaned.append(part)
            return cleaned
        match = re.search(r"比较\s*(.+?)\s*和\s*(.+?)(?:[,，。]|$)", task)
        if match:
            return [match.group(1).strip(), match.group(2).strip()]
        return []

    def _extract_criteria(self, task: str, context: dict) -> List[str]:
        if context.get("criteria"):
            return list(context["criteria"])
        task_lower = task.lower()
        criteria = []
        keyword_map = {
            "speed": ["快", "speed", "performance"],
            "simplicity": ["简单", "easy", "simple"],
            "control": ["控制", "control", "自定义", "custom"],
            "extensibility": ["扩展", "extend", "maintain"],
        }
        for criterion, keywords in keyword_map.items():
            if any(word in task_lower for word in keywords):
                criteria.append(criterion)
        return criteria or ["speed", "simplicity", "extensibility"]
