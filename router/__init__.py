"""Rule-based skill router for the multi-skill runtime."""

from __future__ import annotations

from typing import Dict, List

from models.schemas import RoutedSkill, RouterDecision, SkillInput, TaskClassification, TaskType
from skills.base import SkillRegistry


class SkillRouter:
    """Choose a skill chain based on task type, clarity, and route needs."""

    def __init__(self, registry: SkillRegistry):
        self.registry = registry

    def classify(self, task_input: SkillInput) -> TaskClassification:
        task = task_input.task.lower()
        reasons: List[str] = []

        if any(word in task for word in ["比较", "对比", " vs ", "which", "better"]):
            reasons.append("The task explicitly asks for a comparison or decision.")
            return TaskClassification(
                task_type=TaskType.COMPARISON,
                confidence=0.93,
                suggested_skills=["comparison", "generation", "verification"],
                reasoning=" ".join(reasons),
            )

        if any(word in task for word in ["分析", "inspect", "review", "readme", ".py", ".md", "文件"]):
            reasons.append("The task references artifacts or asks for analysis before answering.")
            return TaskClassification(
                task_type=TaskType.ANALYSIS,
                confidence=0.87,
                suggested_skills=["analysis", "generation", "verification"],
                reasoning=" ".join(reasons),
            )

        if any(word in task for word in ["需求", "整理", "规划", "计划", "怎么做", "clarify"]) or any(
            word in task for word in ["差不多", "随便", "大概"]
        ):
            reasons.append("The task sounds like a requirement-shaping request.")
            return TaskClassification(
                task_type=TaskType.REQUIREMENT,
                confidence=0.84,
                suggested_skills=["planning"],
                reasoning=" ".join(reasons),
            )

        reasons.append("Defaulting to a generate-and-verify path.")
        return TaskClassification(
            task_type=TaskType.GENERATION,
            confidence=0.65,
            suggested_skills=["planning", "generation", "verification"],
            reasoning=" ".join(reasons),
        )

    def select_skills(self, task_input: SkillInput) -> RouterDecision:
        classification = self.classify(task_input)
        available = self.registry.definitions()
        selected = []
        skipped: List[Dict[str, str]] = []

        for name in classification.suggested_skills:
            if name in available:
                selected.append(
                    RoutedSkill(
                        name=name,
                        reason=self._selection_reason(classification.task_type, name),
                    )
                )

        for name, definition in available.items():
            if name in {skill.name for skill in selected}:
                continue
            skipped.append(
                {
                    "name": name,
                    "reason": f"Skipped because the current task type is {classification.task_type.value}, so {definition.name} is not on the shortest useful route.",
                }
            )

        return RouterDecision(
            task_type=classification.task_type,
            confidence=classification.confidence,
            selected_skills=selected,
            skipped_skills=skipped,
            reasoning=classification.reasoning,
            context={"suggested_skills": classification.suggested_skills},
        )

    def _selection_reason(self, task_type: TaskType, skill_name: str) -> str:
        reasons = {
            (TaskType.REQUIREMENT, "planning"): "Need to structure ambiguous requirements before any other step.",
            (TaskType.ANALYSIS, "analysis"): "Need grounded observations from local artifacts first.",
            (TaskType.ANALYSIS, "generation"): "Need to transform the analysis into a concrete deliverable.",
            (TaskType.ANALYSIS, "verification"): "Need to verify that the deliverable includes the requested evidence.",
            (TaskType.GENERATION, "planning"): "Use planning to surface hidden constraints before drafting.",
            (TaskType.GENERATION, "generation"): "Need a user-facing deliverable.",
            (TaskType.GENERATION, "verification"): "Need a quality gate before returning the answer.",
            (TaskType.COMPARISON, "comparison"): "Need explicit scoring and recommendation across options.",
            (TaskType.COMPARISON, "generation"): "Need to turn the comparison table into a user-facing recommendation.",
            (TaskType.COMPARISON, "verification"): "Need to ensure the recommendation includes evidence and a clear winner.",
        }
        return reasons.get((task_type, skill_name), "Selected by the router as part of the current task route.")
