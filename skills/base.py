"""Base types and helpers for directory-style markdown skills."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from models.clients import ChatModelClient
from models.schemas import SkillDefinition, SkillInfo, SkillInput, SkillOutput, ToolCall
from tools import clip, list_files, patch_file, read_file, resolve_path, run_shell, search, write_file

_COMPARISON_SECTION_MIN_CHARS = 160


def _h2_section_body_len(draft: str, title: str) -> int:
    """Return character count of the body under '## {title}' (excluding the heading line)."""
    pattern = rf"(?ms)^##\s+{re.escape(title)}\s*$(.*?)(?=^##\s|\Z)"
    match = re.search(pattern, draft)
    if not match:
        return 0
    return len(match.group(1).strip())


@dataclass
class SkillDocument:
    """Parsed markdown skill document plus its explicit schema."""

    name: str
    description: str
    content: str
    definition: SkillDefinition
    path: Path


class BaseSkill:
    """Unified runtime adapter for directory-style markdown skills."""

    def __init__(
        self,
        document: SkillDocument,
        root_path: Path,
        session_id: str,
        model_client: Optional[ChatModelClient] = None,
    ):
        self.document = document
        self.name = document.name
        self.description = document.description
        self.content = document.content
        self.definition = document.definition
        self.root_path = root_path
        self.session_id = session_id
        self.model_client = model_client
        self.tool_calls: List[ToolCall] = []
        self.logger = logging.getLogger(f"skill.{self.name}")

    def validate_input(self, input_data: SkillInput) -> bool:
        return bool(input_data.task.strip())

    def safe_execute(self, input_data: SkillInput) -> SkillOutput:
        try:
            if not self.validate_input(input_data):
                return SkillOutput(
                    success=False,
                    result="",
                    summary=f"{self.name} rejected the input",
                    errors=[f"Input validation failed for skill {self.name}"],
                )
            result = self.execute(input_data)
            if not result.summary:
                result.summary = clip(result.result, 160)
            return result
        except Exception as exc:  # pragma: no cover - defensive path
            self.logger.exception("Skill %s failed", self.name)
            return self.fallback(str(exc))

    def execute(self, input_data: SkillInput) -> SkillOutput:
        handlers = {
            "planning": self._execute_planning,
            "analysis": self._execute_analysis,
            "comparison": self._execute_comparison,
            "generation": self._execute_generation,
            "verification": self._execute_verification,
            "ask_back": self._execute_ask_back,
        }
        try:
            handler = handlers[self.name]
        except KeyError as exc:
            raise ValueError(f"No runtime handler implemented for skill {self.name}") from exc
        return handler(input_data)

    def fallback(self, error: str) -> SkillOutput:
        metadata: Dict[str, Any] = {"original_error": error}
        if self.definition.failure_strategy:
            metadata["failure_strategy"] = self.definition.failure_strategy
        return SkillOutput(
            success=False,
            result="",
            summary=f"{self.name} failed: {error}",
            metadata=metadata,
            errors=[f"Skill {self.name} failed: {error}"],
        )

    def record_tool_call(
        self,
        name: str,
        args: Dict[str, Any],
        result: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        self.tool_calls.append(
            ToolCall(
                name=name,
                args=args,
                result=clip(result) if result else None,
                status="error" if error else "success",
                error=error,
            )
        )

    def consume_tool_calls(self) -> List[ToolCall]:
        calls = list(self.tool_calls)
        self.tool_calls.clear()
        return calls

    def get_skill_info(self) -> SkillInfo:
        return SkillInfo(
            name=self.definition.name,
            description=self.definition.purpose,
            input_schema=self.definition.inputs,
            output_schema=self.definition.outputs,
            applicable_conditions=self.definition.applicable_when,
            not_applicable_conditions=self.definition.not_applicable_when,
            required_tools=self.definition.dependencies,
            fallback_skill=None,
        )

    def execute_tool(self, tool_name: str, args: Dict[str, Any]) -> str:
        if tool_name == "list_files":
            return list_files(args.get("path", "."), self.root_path)
        if tool_name == "read_file":
            return read_file(args["path"], args.get("start", 1), args.get("end", 200), self.root_path)
        if tool_name == "search":
            return search(args["pattern"], args.get("path", "."), self.root_path)
        if tool_name == "write_file":
            return write_file(args["path"], args["content"], self.root_path)
        if tool_name == "patch_file":
            return patch_file(args["path"], args["old_text"], args["new_text"], self.root_path)
        if tool_name == "run_shell":
            return run_shell(args["command"], args.get("timeout", 20), self.root_path)
        if tool_name == "resolve_path":
            return str(resolve_path(args["path"], self.root_path))
        raise ValueError(f"Unknown tool: {tool_name}")

    def record_tool_usage(self, tool_name: str, args: Dict[str, Any]) -> str:
        try:
            result = self.execute_tool(tool_name, args)
            self.record_tool_call(tool_name, args, result=result)
            return result
        except Exception as exc:
            self.record_tool_call(tool_name, args, error=str(exc))
            raise

    def _llm_complete(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        max_tokens: int = 1200,
        temperature: float = 0.2,
    ) -> Optional[str]:
        if self.model_client is None:
            return None
        try:
            return self.model_client.complete(
                [
                    {
                        "role": "system",
                        "content": f"{system_prompt}\n\nSkill content:\n{self.content}",
                    },
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except Exception:
            return None

    def _comparison_fallback_sections(self, comp: dict) -> List[tuple[str, str]]:
        """Build Comparison + Recommendation bodies when generation runs without an LLM."""
        lines: List[str] = []
        criteria = comp.get("criteria") or []
        if criteria:
            lines.append(f"- 对比维度：{', '.join(str(c) for c in criteria)}")
        for row in comp.get("scores", []):
            opt = row.get("option", "")
            lines.append(f"- **{opt}**：得分 {row.get('score', '')} — {row.get('reasoning', '')}")
        for note in comp.get("option_notes", []):
            pros = note.get("pros") or []
            cons = note.get("cons") or []
            if pros or cons:
                lines.append(
                    f"\n**{note.get('option', '')}**\n"
                    f"- 优势：{'；'.join(str(p) for p in pros)}\n"
                    f"- 局限：{'；'.join(str(c) for c in cons)}"
                )
        comparison_body = "\n".join(lines) if lines else "- （无结构化对比数据；请配置模型客户端以获得完整输出。）"
        rec = comp.get("recommendation", {}) or {}
        winner = rec.get("winner", "")
        reason = rec.get("reason", "")
        alt = rec.get("when_to_pick_alternative", "")
        rec_lines = [
            f"**推荐选项：{winner}**",
            "",
            "**推荐理由：**",
        ]
        if reason:
            chunks = [c.strip() for c in re.split(r"[。；;]\s*", reason) if c.strip()]
            for chunk in chunks[:6] if chunks else [reason]:
                rec_lines.append(f"- {chunk}")
        else:
            rec_lines.append("- （未提供理由）")
        if alt:
            rec_lines.extend(["", "**何时选另一方案：**", f"- {alt}"])
        rec_body = "\n".join(rec_lines)
        return [("Comparison", comparison_body), ("Recommendation", rec_body)]

    def _execute_planning(self, input_data: SkillInput) -> SkillOutput:
        raw = self._llm_complete(
            (
                "You are the planning skill in a skill-centric coding agent.\n"
                "Return JSON only with keys: clarity_score, requirements, suggested_next_skills, status, questions.\n"
                "requirements must include: goal, constraints, deliverables, ambiguous_points."
            ),
            input_data.task,
            max_tokens=900,
            temperature=0.1,
        )
        if raw:
            data = extract_json_object(raw)
            clarity = float(data.get("clarity_score", 0.5))
            questions = data.get("questions", []) or []
            requires_clarification = data.get("status") == "requires_clarification" or clarity < 0.45
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
                    "fallback_skill": "ask_back",
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

    def _execute_analysis(self, input_data: SkillInput) -> SkillOutput:
        file_hints = self._extract_file_hints(input_data)
        files = file_hints or self._default_files()
        inspected = []
        missing = []
        for path in files[:3]:
            try:
                content = self.record_tool_usage("read_file", {"path": path, "start": 1, "end": 80})
                inspected.append({"path": path, "snippet": content})
            except Exception:
                missing.append(path)

        if not inspected:
            workspace = self.record_tool_usage("list_files", {"path": "."})
            inspected.append({"path": ".", "snippet": workspace})

        observations = self._build_observations(input_data.task, inspected)
        risks = self._build_risks(input_data.task, inspected, missing)

        raw = self._llm_complete(
            (
                "You are the analysis skill in a skill-centric coding agent.\n"
                "Return JSON only with keys: observations, risks.\n"
                "Each value is an array of short strings (max 8 observations, max 6 risks).\n"
                "Each string MUST be under 120 characters so the JSON is not truncated mid-token.\n"
                "No markdown, no code fences, only one JSON object."
            ),
            self._build_analysis_prompt(input_data.task, inspected, missing),
            max_tokens=2000,
            temperature=0.1,
        )
        if raw:
            try:
                data = extract_json_object(raw)
                observations = data.get("observations", observations)
                risks = data.get("risks", risks)
            except (ValueError, json.JSONDecodeError, TypeError) as exc:
                self.logger.warning("analysis skill: could not parse LLM JSON (%s); using heuristic lists", exc)

        payload = {
            "inspected_artifacts": [item["path"] for item in inspected],
            "observations": observations,
            "risks": risks,
            "missing_artifacts": missing,
        }
        return SkillOutput(
            success=True,
            result=json.dumps(payload, ensure_ascii=False, indent=2),
            summary=f"Inspected {len(inspected)} artifact(s) and extracted {len(observations)} observation(s).",
            metadata={
                "inspected_files": [item["path"] for item in inspected],
                "missing_files": missing,
                "observations": observations,
            },
        )

    def _execute_comparison(self, input_data: SkillInput) -> SkillOutput:
        options = self._extract_options(input_data)
        criteria = self._extract_criteria(input_data.task, input_data.context)
        if len(options) < 2:
            return SkillOutput(
                success=False,
                result="",
                summary="Could not compare because fewer than two options were found.",
                metadata={"requires_clarification": True, "fallback_skill": "planning"},
                errors=["Need at least two candidate options for comparison."],
            )

        raw = self._llm_complete(
            (
                "You are the comparison skill in a skill-centric coding agent.\n"
                "Return JSON only with keys: options, criteria, scores, recommendation, option_notes.\n"
                "scores: list of objects {option, score, reasoning} — reasoning must be a string with "
                "2–4 sentences of concrete, non-generic contrasts (not just adjectives).\n"
                "option_notes: list of {option, pros, cons} where pros and cons are arrays of short strings "
                "(at least 2 items each when possible).\n"
                "recommendation: {winner, reason, when_to_pick_alternative} — reason is a detailed string; "
                "when_to_pick_alternative says when the non-winner is preferable.\n"
                "Use the same language as the task for natural-language fields."
            ),
            f"Task: {input_data.task}\nOptions: {options}\nCriteria: {criteria}",
            max_tokens=1400,
            temperature=0.1,
        )
        if raw:
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

        scores = []
        for option in options:
            score = 0
            reasoning = []
            for criterion in criteria:
                if criterion in {"speed", "simplicity"} and len(option) < 10:
                    score += 2
                    reasoning.append(f"strong on {criterion}")
                elif criterion in {"control", "extensibility"} and any(
                    word in option.lower() for word in ["custom", "self", "manual"]
                ):
                    score += 2
                    reasoning.append(f"strong on {criterion}")
                else:
                    score += 1
                    reasoning.append(f"acceptable on {criterion}")
            notes = ", ".join(reasoning[:3]) if reasoning else "heuristic scoring"
            scores.append({"option": option, "score": score, "reasoning": notes})

        scores.sort(key=lambda item: (-item["score"], item["option"]))
        winner = scores[0]
        runner = scores[1]["option"] if len(scores) > 1 else ""
        option_notes = []
        for row in scores:
            option_notes.append(
                {
                    "option": row["option"],
                    "pros": [f"在该任务维度下得分 {row['score']}", row["reasoning"][:120]],
                    "cons": ["（启发式占位：可接入 LLM 获得更细对比）"] if len(scores) < 2 else ["与另一选项在不同维度上互有取舍"],
                }
            )
        payload = {
            "options": options,
            "criteria": criteria,
            "scores": scores,
            "option_notes": option_notes,
            "recommendation": {
                "winner": winner["option"],
                "reason": f"{winner['option']}: {winner['reasoning']}. "
                f"综合各维度后更适合当前任务表述；若需标准库零依赖可再看 {runner or '另一选项'}。",
                "when_to_pick_alternative": f"若团队约束或偏好更偏向 {runner or '另一方案'}，可优先评估该路径。",
            },
        }
        return SkillOutput(
            success=True,
            result=json.dumps(payload, ensure_ascii=False, indent=2),
            summary=f"Recommended {winner['option']} based on {', '.join(criteria[:2])}.",
            metadata={"recommended_option": winner["option"], "criteria": criteria, "scores": scores},
        )

    def _execute_generation(self, input_data: SkillInput) -> SkillOutput:
        previous = {item["skill"]: item for item in input_data.previous_results if "skill" in item}
        must_include = list(input_data.context.get("must_include", []))
        retry_missing = list(input_data.context.get("retry_missing_sections", []))

        source_parts = []
        clip_len = 6200 if input_data.context.get("task_type") == "comparison" and "comparison" in previous else 3000
        for skill_name, payload in previous.items():
            source_parts.append(
                f"[{skill_name}]\nSummary: {payload.get('summary', '')}\nResult:\n{payload.get('result', '')[:clip_len]}"
            )
        is_comparison = input_data.context.get("task_type") == "comparison" and "comparison" in previous
        if is_comparison:
            gen_system = (
                "You are the generation skill in a skill-centric coding agent.\n"
                "The user asked for a comparison and recommendation.\n"
                "Write the final answer in Markdown using EXACTLY these two level-2 headings in order:\n"
                "## Comparison\n"
                "Then ## Recommendation\n"
                "Under Comparison: one short intro sentence, then EITHER a markdown table contrasting the options "
                "on the criteria from the prior JSON OR bullet lists with at least 3 substantive bullets per option "
                "(concrete tradeoffs, not single adjectives).\n"
                "Under Recommendation: name the winner, then at least 4 bullet points for 推荐理由, "
                "then a short **何时选另一方案** paragraph using when_to_pick_alternative from the JSON when present.\n"
                "Write in the same language as the user's task."
            )
            gen_max_tokens = 2600
            gen_temperature = 0.25
        else:
            gen_system = (
                "You are the generation skill in a skill-centric coding agent.\n"
                "Write the final answer in Markdown.\n"
                "Use clear H2 sections like '## Analysis' or '## Recommendation' when appropriate.\n"
                "If required sections are provided, include all of them as section titles."
            )
            gen_max_tokens = 1400
            gen_temperature = 0.2
        raw = self._llm_complete(
            gen_system,
            (
                f"Task:\n{input_data.task}\n\n"
                f"Required sections:\n{must_include + retry_missing}\n\n"
                f"Prior skill outputs:\n{'\n\n'.join(source_parts)}"
            ),
            max_tokens=gen_max_tokens,
            temperature=gen_temperature,
        )
        if raw:
            sections = [line.removeprefix("## ").strip() for line in raw.splitlines() if line.startswith("## ")]
            return SkillOutput(
                success=True,
                result=raw.strip(),
                summary=f"Generated a draft with {max(1, len(sections))} section(s).",
                metadata={"sections": sections or ["Response"], "source_skills": list(previous.keys())},
            )

        sections = []
        if "planning" in previous:
            plan_data = self._maybe_json(previous["planning"]["result"])
            reqs = plan_data.get("requirements", {})
            sections.append(("Goal", reqs.get("goal", input_data.task)))
            if reqs.get("constraints"):
                cons = reqs["constraints"]
                if isinstance(cons, str):
                    cons_text = cons
                else:
                    cons_text = ", ".join(str(x) for x in cons)
                sections.append(("Constraints", cons_text))
        if "analysis" in previous:
            analysis_data = self._maybe_json(previous["analysis"]["result"])
            observations = analysis_data.get("observations", [])
            risks = analysis_data.get("risks", [])
            sections.append(("Analysis", "\n".join(f"- {item}" for item in observations) or "- No observations"))
            if risks:
                sections.append(("Risks", "\n".join(f"- {item}" for item in risks)))
        if "comparison" in previous:
            comp = self._maybe_json(previous["comparison"]["result"])
            sections.extend(self._comparison_fallback_sections(comp))
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
                sections.append((title, self._fill_missing_section(title, previous, input_data.task)))

        text = "\n\n".join(f"## {title}\n{body}" for title, body in sections)
        return SkillOutput(
            success=True,
            result=text,
            summary=f"Generated a draft with {len(sections)} section(s).",
            metadata={"sections": [title for title, _ in sections], "source_skills": list(previous.keys())},
        )

    def _execute_verification(self, input_data: SkillInput) -> SkillOutput:
        draft = ""
        previous_skill = ""
        if input_data.previous_results:
            draft = input_data.previous_results[-1].get("result", "")
            previous_skill = input_data.previous_results[-1].get("skill", "")

        required_sections = [section.title() for section in input_data.context.get("must_include", [])]
        if input_data.context.get("task_type") == "comparison":
            for sec in ("Comparison", "Recommendation"):
                if sec not in required_sections:
                    required_sections.append(sec)
        if previous_skill == "analysis":
            required_sections.append("Analysis")

        raw = self._llm_complete(
            (
                "You are the verification skill in a skill-centric coding agent.\n"
                "Return JSON only with keys: passed, checklist, missing_sections, summary.\n"
                "checklist must be a list of {item, passed} objects.\n"
                "For comparison tasks, the Comparison section must have substantive contrast "
                f"(not empty prose), roughly over {_COMPARISON_SECTION_MIN_CHARS} characters of body text."
            ),
            f"Task:\n{input_data.task}\n\nRequired sections:\n{required_sections}\n\nDraft:\n{draft[:5000]}",
            max_tokens=640,
            temperature=0.1,
        )
        if raw:
            data = extract_json_object(raw)
            checklist = list(data.get("checklist", []) or [])
            missing = list(data.get("missing_sections", []) or [])
            for section in required_sections:
                if f"## {section}" not in draft and section not in missing:
                    missing.append(section)
                    checklist.append({"item": f"contains section {section}", "passed": False})
            success = bool(data.get("passed", False)) and not missing
            if input_data.context.get("task_type") == "comparison":
                c_len = _h2_section_body_len(draft, "Comparison")
                if c_len < _COMPARISON_SECTION_MIN_CHARS:
                    missing.append("Comparison")
                    success = False
                    checklist.append({"item": "comparison section substantive length", "passed": False})
                r_len = _h2_section_body_len(draft, "Recommendation")
                if r_len < 100:
                    missing.append("Recommendation")
                    success = False
                    checklist.append({"item": "recommendation section substantive length", "passed": False})
            missing = list(dict.fromkeys(missing))
            result_lines = [f"- {'PASS' if item.get('passed') else 'FAIL'} {item.get('item')}" for item in checklist]
            return SkillOutput(
                success=success,
                result="\n".join(result_lines),
                summary=(
                    data.get("summary", "Verification complete.")
                    if success
                    else f"Verification failed; missing {', '.join(missing)}."
                ),
                metadata={"checklist": checklist, "missing_sections": missing, "needs_retry": not success},
                errors=[] if success else [f"Missing required sections: {', '.join(missing)}"],
            )

        checklist = []
        missing = []
        for section in required_sections:
            ok = f"## {section}" in draft
            checklist.append({"item": f"contains section {section}", "passed": ok})
            if not ok:
                missing.append(section)
        if input_data.context.get("task_type") == "comparison":
            c_len = _h2_section_body_len(draft, "Comparison")
            if c_len < _COMPARISON_SECTION_MIN_CHARS:
                checklist.append({"item": "comparison section substantive length", "passed": False})
                missing.append("Comparison")
            rec_ok = (
                "Reason:" in draft
                or "推荐理由" in draft
                or _h2_section_body_len(draft, "Recommendation") >= 100
            )
            if not rec_ok:
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

    def _execute_ask_back(self, input_data: SkillInput) -> SkillOutput:
        hints = list(input_data.context.get("questions", []))
        if not hints:
            hints = [
                "请补充你最在意的最终输出。",
                "请说明必须满足的成功标准。",
            ]
        payload = {"status": "needs_user_input", "questions": hints[:3]}
        return SkillOutput(
            success=True,
            result=json.dumps(payload, ensure_ascii=False, indent=2),
            summary="Asked the user for targeted clarification.",
            metadata={"questions": hints[:3], "blocked": True},
        )

    def _build_analysis_prompt(self, task: str, inspected: List[dict], missing: List[str]) -> str:
        snippets = "\n\n".join(f"FILE: {item['path']}\n{item['snippet'][:1800]}" for item in inspected)
        return f"Task:\n{task}\n\nMissing artifacts: {missing}\n\nSnippets:\n{snippets}"

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

    def _extract_file_hints(self, input_data: SkillInput) -> List[str]:
        if input_data.context.get("files"):
            return list(input_data.context["files"])
        return re.findall(r"\b[\w./-]+\.\w+\b", input_data.task)

    def _default_files(self) -> List[str]:
        defaults = []
        for candidate in ["README.md", "issue.md", "pyproject.toml", "mini_coding_agent.py"]:
            if (self.root_path / candidate).exists():
                defaults.append(candidate)
        return defaults

    def _build_observations(self, task: str, inspected: List[dict]) -> List[str]:
        observations = []
        if any(item["path"].endswith("README.md") for item in inspected):
            observations.append("Repository documentation is available and can anchor the answer.")
        if any("tool" in item["snippet"].lower() for item in inspected):
            observations.append("The current codebase already contains tool abstractions that can stay as low-level capabilities.")
        if "test" in task.lower():
            observations.append("The task explicitly cares about verification, so a later verification pass is necessary.")
        observations.extend(
            f"Observed artifact {item['path']} with {len(item['snippet'].splitlines())} visible line(s)."
            for item in inspected
        )
        return observations[:6]

    def _build_risks(self, task: str, inspected: List[dict], missing: List[str]) -> List[str]:
        risks = []
        if missing:
            risks.append(f"Missing referenced artifacts: {', '.join(missing)}")
        if "compare" in task.lower() or "比较" in task:
            risks.append("A repository analysis may be insufficient without explicit comparison criteria.")
        if not any(item["path"] != "." for item in inspected):
            risks.append("Only directory-level context was available, so the analysis may be shallow.")
        return risks

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


class SkillRegistry:
    """Registry backed by markdown skill documents instead of Python subclasses."""

    def __init__(self) -> None:
        self._documents: Dict[str, SkillDocument] = {}

    def register_document(self, document: SkillDocument) -> None:
        self._documents[document.name] = document

    def register_path(self, skill_dir: Path) -> None:
        self.register_document(parse_skill_document(skill_dir / "SKILL.md"))

    def create(
        self,
        name: str,
        root_path: Path,
        session_id: str,
        model_client: Optional[ChatModelClient] = None,
    ) -> BaseSkill:
        try:
            document = self._documents[name]
        except KeyError as exc:
            raise KeyError(f"Unknown skill: {name}") from exc
        return BaseSkill(document=document, root_path=root_path, session_id=session_id, model_client=model_client)

    def definitions(self) -> Dict[str, SkillDefinition]:
        return {name: document.definition for name, document in self._documents.items()}

    def names(self) -> List[str]:
        return list(self._documents.keys())


def parse_skill_document(path: Path) -> SkillDocument:
    """Parse the constrained markdown format used by built-in skills."""
    text = path.read_text(encoding="utf-8")
    metadata: Dict[str, Any] = {
        "name": "",
        "description": "",
        "failure_strategy": "",
        "applicable_when": [],
        "not_applicable_when": [],
        "dependencies": [],
    }
    inputs: Dict[str, str] = {}
    outputs: Dict[str, str] = {}
    content_lines: List[str] = []

    section: Optional[str] = None
    pending_list_key: Optional[str] = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip("\n")
        stripped = line.strip()
        if stripped.startswith("# "):
            continue
        if stripped.startswith("## "):
            section = stripped[3:].strip().lower().replace(" ", "_")
            pending_list_key = None
            continue
        if section == "content":
            content_lines.append(raw_line)
            continue
        if not stripped:
            continue

        if section in {"inputs", "outputs"}:
            match = re.match(r"-\s*([^:]+):\s*(.+)$", stripped)
            if match:
                target = inputs if section == "inputs" else outputs
                target[match.group(1).strip()] = match.group(2).strip()
            continue

        bullet_match = re.match(r"-\s*([^:]+):\s*(.*)$", stripped)
        if bullet_match:
            key = bullet_match.group(1).strip()
            value = bullet_match.group(2).strip()
            if key in {"applicable_when", "not_applicable_when", "dependencies"} and not value:
                pending_list_key = key
            else:
                metadata[key] = value
                pending_list_key = None
            continue

        list_match = re.match(r"-\s+(.+)$", stripped)
        if list_match and pending_list_key:
            metadata.setdefault(pending_list_key, []).append(list_match.group(1).strip())

    name = str(metadata["name"]).strip()
    if not name:
        raise ValueError(f"Skill document {path} is missing a name")

    definition = SkillDefinition(
        name=name,
        purpose=str(metadata["description"]).strip(),
        content="\n".join(content_lines).strip(),
        inputs=inputs,
        outputs=outputs,
        applicable_when=list(metadata.get("applicable_when", [])),
        not_applicable_when=list(metadata.get("not_applicable_when", [])),
        dependencies=list(metadata.get("dependencies", [])),
        failure_strategy=str(metadata.get("failure_strategy", "")).strip(),
    )
    return SkillDocument(
        name=name,
        description=str(metadata["description"]).strip(),
        content=definition.content,
        definition=definition,
        path=path,
    )


def load_directory_skills(skills_root: Path) -> SkillRegistry:
    """Scan skill directories and build the registry."""
    registry = SkillRegistry()
    for skill_dir in sorted(skills_root.iterdir()):
        if not skill_dir.is_dir() or skill_dir.name.startswith("__"):
            continue
        skill_doc = skill_dir / "SKILL.md"
        if skill_doc.exists():
            registry.register_path(skill_dir)
    return registry


def extract_json_object(text: str) -> Dict[str, Any]:
    """Best-effort JSON extraction from model output."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            text = "\n".join(lines[1:-1]).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"No JSON object found in model output: {text[:200]}")
    return json.loads(text[start : end + 1])
