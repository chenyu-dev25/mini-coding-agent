"""Planning skill for clarifying requirements and extracting execution structure."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from models import extract_json_object
from models.schemas import SkillDefinition, SkillInput, SkillOutput
from skills.base import BaseSkill, ToolExecutorMixin


class PlanningSkill(BaseSkill, ToolExecutorMixin):
    """Turn messy requirements into a structured brief or ask-back questions."""

    name = "planning"
    description = "Clarify requirements, extract constraints, and propose a next-step plan."
    applicable_conditions = ["unclear request", "requirement整理", "need plan"]
    not_applicable_conditions = ["request is already fully specified and only needs execution"]
    required_tools: List[str] = []
    fallback_skill = "ask_back"

    def __init__(self, root_path: Path, session_id: str, model_client=None):
        BaseSkill.__init__(self, root_path, session_id, model_client=model_client)
        ToolExecutorMixin.__init__(self, root_path)

    @classmethod
    def build_definition(cls) -> SkillDefinition:
        return SkillDefinition(
            name=cls.name,
            purpose=cls.description,
            inputs={
                "task": "Natural-language requirement or vague user request.",
                "context": "Optional task metadata such as deadlines or user constraints.",
                "previous_results": "Earlier skill outputs, usually empty for the first step.",
            },
            outputs={
                "result": "Structured requirement brief or clarification payload.",
                "summary": "One-line planning summary.",
                "metadata": "Clarity score, extracted constraints, and suggested next skills.",
            },
            applicable_when=[
                "The task is vague, messy, or mixes goals and constraints together.",
                "The agent needs to decide whether to ask back before executing.",
            ],
            not_applicable_when=[
                "The task already contains clear inputs, outputs, and evaluation criteria.",
                "The user is explicitly asking for a head-to-head option comparison.",
            ],
            dependencies=[],
            failure_strategy="Return clarification questions and stop the route before low-confidence execution.",
        )

    def execute(self, input_data: SkillInput) -> SkillOutput:
        if self.model_client and not input_data.context.get("disable_llm"):
            llm_output = self._llm_execute(input_data)
            if llm_output is not None:
                return llm_output

        task = input_data.task
        clarity = self._clarity_score(task)
        extracted = {
            "goal": self._extract_goal(task),
            "constraints": self._extract_constraints(task, input_data.context),
            "deliverables": self._extract_deliverables(task),
            "ambiguous_points": self._find_ambiguity(task),
        }
        suggested = self._suggest_next_skills(task, clarity)

        payload = {
            "clarity_score": clarity,
            "requirements": extracted,
            "suggested_next_skills": suggested,
        }

        if clarity < 0.45:
            questions = self._clarifying_questions(task, extracted)
            payload["questions"] = questions
            payload["status"] = "requires_clarification"
            return SkillOutput(
                success=False,
                result=json.dumps(payload, ensure_ascii=False, indent=2),
                summary="Requirements are too ambiguous; ask-back is required.",
                metadata={
                    "requires_clarification": True,
                    "clarity_score": clarity,
                    "questions": questions,
                    "fallback_skill": self.fallback_skill,
                },
                errors=["Requirements are not specific enough for confident execution."],
            )

        payload["status"] = "structured"
        return SkillOutput(
            success=True,
            result=json.dumps(payload, ensure_ascii=False, indent=2),
            summary=f"Structured the request with clarity score {clarity:.2f}.",
            metadata={
                "clarity_score": clarity,
                "requires_clarification": False,
                "suggested_skills": suggested,
                "structured_requirements": extracted,
            },
        )

    def _llm_execute(self, input_data: SkillInput) -> Optional[SkillOutput]:
        prompt = (
            "You are the planning skill in a skill-centric coding agent.\n"
            "Return JSON only with keys: clarity_score, requirements, suggested_next_skills, status, questions.\n"
            "requirements must include: goal, constraints, deliverables, ambiguous_points.\n"
            "If the task is too vague, set status to requires_clarification and provide up to 3 questions.\n"
            "If the task is clear enough, set status to structured and questions to []."
        )
        try:
            raw = self.model_client.complete(
                [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": input_data.task},
                ],
                max_tokens=900,
                temperature=0.1,
            )
            data = extract_json_object(raw)
        except Exception:
            return None

        clarity = float(data.get("clarity_score", 0.5))
        questions = data.get("questions", []) or []
        status = data.get("status", "structured")
        requires_clarification = status == "requires_clarification" or clarity < 0.45
        return SkillOutput(
            success=not requires_clarification,
            result=json.dumps(data, ensure_ascii=False, indent=2),
            summary=(
                "Requirements are too ambiguous; ask-back is required."
                if requires_clarification
                else f"Structured the request with clarity score {clarity:.2f}."
            ),
            metadata={
                "requires_clarification": requires_clarification,
                "clarity_score": clarity,
                "questions": questions[:3],
                "suggested_skills": data.get("suggested_next_skills", []),
                "structured_requirements": data.get("requirements", {}),
            },
            errors=[] if not requires_clarification else ["Requirements are not specific enough for confident execution."],
        )

    def _clarity_score(self, task: str) -> float:
        task_lower = task.lower()
        positive = sum(
            1
            for word in ["必须", "需要", "输出", "格式", "比较", "分析", "文件", "约束", "deadline", "must"]
            if word in task_lower
        )
        vague = sum(
            1
            for word in ["差不多", "随便", "大概", "某种", "看着办", "something", "whatever"]
            if word in task_lower
        )
        punctuation_bonus = 0.1 if any(mark in task for mark in ["\n", ":", "；", ";"]) else 0.0
        score = 0.35 + min(positive, 6) * 0.08 - min(vague, 4) * 0.12 + punctuation_bonus
        return max(0.0, min(1.0, round(score, 2)))

    def _extract_goal(self, task: str) -> str:
        patterns = [
            r"(?:目标|目的|需要|想要|请)\s*[:：]?\s*([^。！？\n]+)",
            r"(?:实现|完成|生成|分析|比较)\s*([^。！？\n]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, task, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return task.strip()[:80]

    def _extract_constraints(self, task: str, context: Dict[str, Any]) -> List[str]:
        constraints: List[str] = []
        for label, keywords in {
            "time": ["小时", "天", "deadline", "today", "tomorrow"],
            "quality": ["测试", "验证", "稳定", "可靠", "review"],
            "format": ["markdown", "json", "表格", "bullet"],
        }.items():
            if any(word in task.lower() for word in keywords):
                constraints.append(label)
        if context.get("must_include"):
            constraints.append(f"must_include={','.join(context['must_include'])}")
        return constraints

    def _extract_deliverables(self, task: str) -> List[str]:
        found: List[str] = []
        for keyword, deliverable in {
            "方案": "solution proposal",
            "计划": "execution plan",
            "比较": "decision memo",
            "代码": "implementation guidance",
            "测试": "verification notes",
        }.items():
            if keyword in task:
                found.append(deliverable)
        return found or ["final answer"]

    def _find_ambiguity(self, task: str) -> List[str]:
        points = []
        for word in ["差不多", "随便", "大概", "好一点", "更强"]:
            if word in task:
                points.append(f"Contains vague wording: {word}")
        if "文件" in task and not re.search(r"\b[\w./-]+\.\w+\b", task):
            points.append("Mentions files without naming a file path.")
        return points

    def _clarifying_questions(self, task: str, extracted: Dict[str, Any]) -> List[str]:
        questions = []
        if extracted["ambiguous_points"]:
            questions.append("你最在意的输出是什么：方案、代码、比较结论，还是问题清单？")
        if "文件" in task:
            questions.append("请指定需要分析的文件或目录路径。")
        questions.append("成功的判断标准是什么？请给 2-3 个必须满足的条件。")
        return questions[:3]

    def _suggest_next_skills(self, task: str, clarity: float) -> List[str]:
        if clarity < 0.45:
            return ["ask_back"]
        task_lower = task.lower()
        if any(word in task_lower for word in ["比较", "对比", "vs"]):
            return ["comparison", "verification"]
        if any(word in task_lower for word in ["分析", "readme", "文件", ".py", ".md"]):
            return ["analysis", "generation", "verification"]
        return ["generation", "verification"]
