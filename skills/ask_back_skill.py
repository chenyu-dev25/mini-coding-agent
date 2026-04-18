"""Ask-back skill used as a safe fallback when information is insufficient."""

from __future__ import annotations

import json
from pathlib import Path
from typing import List

from models.schemas import SkillDefinition, SkillInput, SkillOutput
from skills.base import BaseSkill


class AskBackSkill(BaseSkill):
    """Generate concise follow-up questions instead of guessing."""

    name = "ask_back"
    description = "Ask targeted clarification questions when the current evidence is not enough."
    applicable_conditions = ["missing critical information", "low-confidence upstream failure"]
    not_applicable_conditions = ["task already has enough detail for execution"]
    required_tools: List[str] = []
    fallback_skill = None

    def __init__(self, root_path: Path, session_id: str, model_client=None):
        super().__init__(root_path, session_id, model_client=model_client)

    @classmethod
    def build_definition(cls) -> SkillDefinition:
        return SkillDefinition(
            name=cls.name,
            purpose=cls.description,
            inputs={
                "task": "Original request that lacks a key detail.",
                "context": "Optional missing-info hints or upstream error metadata.",
                "previous_results": "Failed or low-confidence outputs from earlier skills.",
            },
            outputs={
                "result": "Clarification payload with questions and reason for stopping.",
                "summary": "Short note that the system is asking back.",
                "metadata": "Questions and blocked fields.",
            },
            applicable_when=[
                "A required file, option, or success criterion is missing.",
                "An upstream skill explicitly requests clarification.",
            ],
            not_applicable_when=[
                "The route already has enough information to answer responsibly.",
            ],
            dependencies=[],
            failure_strategy="Stop the workflow and return the clarification request directly to the user.",
        )

    def execute(self, input_data: SkillInput) -> SkillOutput:
        hints = list(input_data.context.get("questions", []))
        if not hints:
            hints = [
                "请补充你最在意的最终输出。",
                "请说明必须满足的成功标准。",
            ]

        payload = {
            "status": "needs_user_input",
            "questions": hints[:3],
        }
        return SkillOutput(
            success=True,
            result=json.dumps(payload, ensure_ascii=False, indent=2),
            summary="Asked the user for targeted clarification.",
            metadata={"questions": hints[:3], "blocked": True},
        )
