"""Analysis skill that inspects local context before synthesis."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List

from models import extract_json_object
from models.schemas import SkillDefinition, SkillInput, SkillOutput
from skills.base import BaseSkill, ToolExecutorMixin


class AnalysisSkill(BaseSkill, ToolExecutorMixin):
    """Inspect files, repo context, and task details to produce observations."""

    name = "analysis"
    description = "Inspect relevant files or workspace context and extract actionable observations."
    applicable_conditions = ["task mentions files/code/analysis", "generation needs grounded context"]
    not_applicable_conditions = ["pure requirement clarification with no concrete artifact to inspect"]
    required_tools = ["list_files", "read_file", "search"]
    fallback_skill = "planning"

    def __init__(self, root_path: Path, session_id: str, model_client=None):
        BaseSkill.__init__(self, root_path, session_id, model_client=model_client)
        ToolExecutorMixin.__init__(self, root_path)

    @classmethod
    def build_definition(cls) -> SkillDefinition:
        return SkillDefinition(
            name=cls.name,
            purpose=cls.description,
            inputs={
                "task": "Prompt that references files, code, repo docs, or asks for analysis.",
                "context": "Optional file hints, named paths, or explicit analysis focus areas.",
                "previous_results": "Outputs from planning or prior analysis passes.",
            },
            outputs={
                "result": "JSON bundle with inspected artifacts, observations, and risks.",
                "summary": "One-line summary of what was inspected and what matters most.",
                "metadata": "Touched files, missing files, and suggested follow-up actions.",
            },
            applicable_when=[
                "The task mentions concrete files, code, README content, or asks for analysis before a recommendation.",
                "Downstream generation should be grounded in repository facts.",
            ],
            not_applicable_when=[
                "The task is purely a vague request that first needs clarification.",
                "The task is a direct option comparison with no repository context needed.",
            ],
            dependencies=["list_files", "read_file", "search"],
            failure_strategy="Fall back to planning if the task references missing or insufficient artifacts.",
        )

    def execute(self, input_data: SkillInput) -> SkillOutput:
        file_hints = self._extract_file_hints(input_data)
        files = file_hints or self._default_files()
        inspected = []
        missing = []

        for path in files[:3]:
            try:
                content = self.record_tool_usage(self, "read_file", {"path": path, "start": 1, "end": 80})
                inspected.append({"path": path, "snippet": content})
            except Exception:
                missing.append(path)

        if not inspected:
            workspace = self.record_tool_usage(self, "list_files", {"path": "."})
            inspected.append({"path": ".", "snippet": workspace})

        observations = self._build_observations(input_data.task, inspected)
        risks = self._build_risks(input_data.task, inspected, missing)
        if self.model_client and not input_data.context.get("disable_llm"):
            llm_bundle = self._llm_analyze(input_data.task, inspected, missing)
            if llm_bundle:
                observations = llm_bundle.get("observations", observations)
                risks = llm_bundle.get("risks", risks)

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

    def _llm_analyze(self, task: str, inspected: List[dict], missing: List[str]) -> dict:
        snippets = "\n\n".join(
            f"FILE: {item['path']}\n{item['snippet'][:1800]}"
            for item in inspected
        )
        prompt = (
            "You are the analysis skill in a skill-centric coding agent.\n"
            "Return JSON only with keys: observations, risks.\n"
            "Each value must be a short list of concise strings.\n"
            "Ground every point in the provided snippets."
        )
        try:
            raw = self.model_client.complete(
                [
                    {"role": "system", "content": prompt},
                    {
                        "role": "user",
                        "content": f"Task:\n{task}\n\nMissing artifacts: {missing}\n\nSnippets:\n{snippets}",
                    },
                ],
                max_tokens=900,
                temperature=0.1,
            )
            return extract_json_object(raw)
        except Exception:
            return {}

    def _extract_file_hints(self, input_data: SkillInput) -> List[str]:
        if input_data.context.get("files"):
            return list(input_data.context["files"])
        matches = re.findall(r"\b[\w./-]+\.\w+\b", input_data.task)
        return matches

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
