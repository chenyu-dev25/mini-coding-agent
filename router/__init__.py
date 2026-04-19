"""Rule-based skill router for the multi-skill runtime."""

from __future__ import annotations

import os
import re
import unicodedata
from typing import Dict, List

from models.schemas import RoutedSkill, RouterDecision, SkillInput, TaskClassification, TaskType
from skills.base import SkillRegistry


def is_skill_catalog_query(text: str) -> bool:
    """True when the user only wants to know which skills exist (no pipeline)."""
    raw = unicodedata.normalize("NFKC", (text or "").strip())
    if not raw:
        return False
    low = raw.lower()

    if any(k in raw for k in ("哪些技能", "什么技能", "列出技能", "技能列表", "可用技能", "支持哪些技能")):
        return True
    if "技能" in raw and any(w in raw for w in ("哪些", "什么", "列出", "有什么", "有啥", "会什么")):
        return True
    if "skill" in low and any(w in raw for w in ("哪些", "什么", "列出", "有什么", "有啥")):
        return True
    if any(e in low for e in ("what skills", "list skills", "available skills", "which skills", "show skills")):
        return True
    return False


def is_pure_greeting(text: str) -> bool:
    """True for short greetings / thanks only — not a task for planning."""
    raw = unicodedata.normalize("NFKC", (text or "").strip())
    if not raw or len(raw) > 48:
        return False
    stripped = re.sub(r"[，。！？!?,、.~～…]+$", "", raw.strip())
    if not stripped:
        return False
    low = stripped.lower()
    if re.match(
        r"^(你好|您好|嗨|哈喽|哈喽|hello|hi|hey|早上好|下午好|晚上好|在吗|在么)([啦呀啊呢哇哦噢\u3000\s!！.,，?？]*)$",
        stripped,
        re.IGNORECASE,
    ):
        return True
    if low in {"hello", "hi", "hey", "yo", "hiya", "ok", "okay", "thanks", "thx", "ty"}:
        return True
    if stripped in {"嗯", "嗯嗯", "好", "好的", "明白", "收到", "谢谢", "多谢", "感恩"}:
        return True
    if stripped.startswith("谢谢") and len(stripped) <= 6:
        return True
    return False


def high_intent_skill_route(text: str) -> bool:
    """Strong cues that match the multi-skill router buckets (not generic chat)."""
    raw = unicodedata.normalize("NFKC", (text or "").strip())
    if not raw:
        return False
    task = raw.lower()

    if any(word in task for word in ["比较", "对比", " vs ", "which", "better"]):
        return True
    if any(word in raw for word in ["需求", "整理", "规划", "计划", "怎么做"]) or any(
        word in raw for word in ["差不多", "随便", "大概"]
    ):
        return True
    if "clarify" in task:
        return True
    if any(word in task for word in ["分析", "inspect", "review", "readme", ".py", ".md", "文件"]):
        return True
    return False


def wants_skill_pipeline(task: str, context: dict, *, agent_default: bool = False) -> bool:
    """Multi-skill router runs only when opted in or the task clearly needs structured skills."""

    if context.get("use_skill_pipeline") is True:
        return True
    if context.get("use_skill_pipeline") is False:
        return False

    if context.get("must_include"):
        return True

    if agent_default:
        return True

    env = os.environ.get("SKILL_AGENT_PIPELINE", "").strip().lower()
    if env in ("1", "true", "yes", "on", "always"):
        return True
    if env in ("0", "false", "no", "off", "never"):
        return False

    return high_intent_skill_route(task)


class SkillRouter:
    """Choose a skill chain based on task type, clarity, and route needs."""

    def __init__(self, registry: SkillRegistry):
        self.registry = registry

    def classify(self, task_input: SkillInput) -> TaskClassification:
        """Classify only when the multi-skill pipeline is already enabled (see ``wants_skill_pipeline``)."""
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

        if any(word in task for word in ["分析", "inspect", "review", "readme", ".py", ".md", "文件"]):
            reasons.append("The task references artifacts or asks for analysis before answering.")
            return TaskClassification(
                task_type=TaskType.ANALYSIS,
                confidence=0.87,
                suggested_skills=["analysis", "generation", "verification"],
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
