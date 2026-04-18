"""Skill registry helpers and built-in skills."""

from skills.analysis_skill import AnalysisSkill
from skills.ask_back_skill import AskBackSkill
from skills.base import BaseSkill, SkillRegistry, ToolExecutorMixin
from skills.comparison_skill import ComparisonSkill
from skills.generation_skill import GenerationSkill
from skills.planning_skill import PlanningSkill
from skills.verification_skill import VerificationSkill


def build_default_registry() -> SkillRegistry:
    """Register the built-in skill set."""
    registry = SkillRegistry()
    for skill_cls in [
        PlanningSkill,
        AnalysisSkill,
        ComparisonSkill,
        GenerationSkill,
        VerificationSkill,
        AskBackSkill,
    ]:
        registry.register(skill_cls)
    return registry


__all__ = [
    "AnalysisSkill",
    "AskBackSkill",
    "BaseSkill",
    "ComparisonSkill",
    "GenerationSkill",
    "PlanningSkill",
    "SkillRegistry",
    "ToolExecutorMixin",
    "VerificationSkill",
    "build_default_registry",
]
