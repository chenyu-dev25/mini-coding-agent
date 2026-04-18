import json

from executor import SkillAgent
from models import FakeChatModelClient
from skills import build_default_registry
from skills.base import BaseSkill
from models.schemas import SkillDefinition, SkillInput, SkillOutput


def test_requirement_route_asks_back_when_task_is_too_vague(tmp_path):
    agent = SkillAgent(tmp_path)

    trace = agent.run("帮我搞一个差不多的方案，随便就行")

    assert trace.task_type.value == "requirement"
    assert [record.skill_name for record in trace.skill_executions] == ["planning", "ask_back"]
    assert trace.skill_executions[0].output.metadata["requires_clarification"] is True
    payload = json.loads(trace.final_result)
    assert payload["status"] == "needs_user_input"
    assert payload["questions"]


def test_analysis_route_uses_multiple_skills_and_preserves_generated_final_result(tmp_path):
    (tmp_path / "README.md").write_text("project docs\n", encoding="utf-8")
    (tmp_path / "issue.md").write_text("task details\n", encoding="utf-8")
    agent = SkillAgent(tmp_path)

    trace = agent.run(
        "分析 README.md 和 issue.md，然后给我一个方案",
        context={"must_include": ["analysis", "testing"]},
    )

    assert trace.task_type.value == "analysis"
    assert [record.skill_name for record in trace.skill_executions] == ["analysis", "generation", "verification"]
    assert "## Analysis" in trace.final_result
    assert "## Testing" in trace.final_result
    assert trace.skill_executions[-1].output.success is True


def test_comparison_route_uses_comparison_generation_and_verification(tmp_path):
    agent = SkillAgent(tmp_path)

    trace = agent.run("比较 pytest vs unittest，并给出推荐理由")

    assert trace.task_type.value == "comparison"
    assert [record.skill_name for record in trace.skill_executions] == ["comparison", "generation", "verification"]
    assert "## Recommendation" in trace.final_result
    assert "Reason:" in trace.final_result


def test_verification_failure_triggers_regeneration_once(tmp_path):
    (tmp_path / "README.md").write_text("project docs\n", encoding="utf-8")
    agent = SkillAgent(tmp_path)

    trace = agent.run(
        "分析 README.md，然后给我一个方案",
        context={
            "must_include": ["analysis", "testing"],
            "simulate_incomplete_first_pass": True,
        },
    )

    skill_names = [record.skill_name for record in trace.skill_executions]
    assert skill_names == ["analysis", "generation", "verification", "generation", "verification"]
    assert trace.skill_executions[2].output.success is False
    assert trace.skill_executions[3].fallback_used is True
    assert "## Testing" in trace.final_result
    assert trace.skill_executions[4].output.success is True


def test_skill_registry_allows_adding_a_new_skill_without_executor_changes(tmp_path):
    class DummySkill(BaseSkill):
        name = "dummy"
        description = "dummy"

        @classmethod
        def build_definition(cls) -> SkillDefinition:
            return SkillDefinition(
                name="dummy",
                purpose="dummy",
                inputs={"task": "task"},
                outputs={"result": "result"},
                applicable_when=["for tests"],
                not_applicable_when=["never"],
                dependencies=[],
                failure_strategy="none",
            )

        def execute(self, input_data: SkillInput) -> SkillOutput:
            return SkillOutput(success=True, result="dummy")

    registry = build_default_registry()
    registry.register(DummySkill)

    agent = SkillAgent(tmp_path, registry=registry)
    definitions = agent.registry.definitions()

    assert "dummy" in definitions
    assert definitions["dummy"].purpose == "dummy"


def test_generation_uses_llm_when_model_client_is_present(tmp_path):
    (tmp_path / "README.md").write_text("project docs\n", encoding="utf-8")
    client = FakeChatModelClient(
        [
            '{"observations":["LLM grounded observation"],"risks":["LLM risk"]}',
            "## Analysis\n- LLM grounded observation\n\n## Testing\n- LLM test plan",
            '{"passed": true, "summary": "Verification passed.", "missing_sections": [], "checklist": [{"item": "contains section Analysis", "passed": true}]}',
        ]
    )
    agent = SkillAgent(tmp_path, model_client=client)

    trace = agent.run(
        "分析 README.md，然后给我一个方案",
        context={"must_include": ["analysis", "testing"]},
    )

    assert len(client.prompts) == 3
    assert "## Testing" in trace.final_result
    assert trace.skill_executions[-1].output.success is True


def test_planning_uses_llm_and_can_trigger_ask_back(tmp_path):
    client = FakeChatModelClient(
        [
            '{"clarity_score": 0.2, "requirements": {"goal": "unknown", "constraints": [], "deliverables": [], "ambiguous_points": ["too vague"]}, "suggested_next_skills": ["ask_back"], "status": "requires_clarification", "questions": ["请补充成功标准"]}'
        ]
    )
    agent = SkillAgent(tmp_path, model_client=client)

    trace = agent.run("随便搞个东西")

    assert [record.skill_name for record in trace.skill_executions] == ["planning", "ask_back"]
    assert json.loads(trace.final_result)["status"] == "needs_user_input"
