"""Tests for trace text rendering."""

from __future__ import annotations

from models.schemas import (
    RouterDecision,
    RoutedSkill,
    SkillExecutionRecord,
    SkillInput,
    SkillOutput,
    SkillStatus,
    TaskType,
    TraceRecord,
)
from trace_renderer import TraceRenderer


def test_trace_renderer_shows_planned_chain_and_steps():
    trace = TraceRecord(
        session_id="sess1",
        task="比较 pytest vs unittest",
        task_type=TaskType.COMPARISON,
        timestamp=0.0,
        total_duration=2.5,
        router_decisions=[
            RouterDecision(
                task_type=TaskType.COMPARISON,
                confidence=0.93,
                selected_skills=[
                    RoutedSkill(name="comparison", reason="Need scoring."),
                    RoutedSkill(name="generation", reason="Draft for user."),
                    RoutedSkill(name="verification", reason="QA gate."),
                ],
                skipped_skills=[],
                reasoning="User asked for comparison.",
            )
        ],
        skill_executions=[
            SkillExecutionRecord(
                skill_name="comparison",
                skill_type="comparison",
                status=SkillStatus.SUCCESS,
                reason="Need scoring.",
                input_summary="比较 pytest vs unittest",
                output_summary="Recommended pytest.",
                input=SkillInput(task="比较 pytest vs unittest"),
                output=SkillOutput(success=True, result="{}", summary="Recommended pytest."),
                start_time=0.0,
                duration=0.1,
            ),
            SkillExecutionRecord(
                skill_name="generation",
                skill_type="generation",
                status=SkillStatus.SUCCESS,
                reason="Draft for user.",
                input_summary="比较 pytest vs unittest",
                output_summary="Generated 2 sections.",
                input=SkillInput(task="比较 pytest vs unittest"),
                output=SkillOutput(success=True, result="## A\n", summary="Generated 2 sections."),
                start_time=0.1,
                duration=1.0,
            ),
            SkillExecutionRecord(
                skill_name="verification",
                skill_type="verification",
                status=SkillStatus.SUCCESS,
                reason="QA gate.",
                input_summary="比较 pytest vs unittest",
                output_summary="Verification passed.",
                input=SkillInput(task="比较 pytest vs unittest"),
                output=SkillOutput(success=True, result="checklist", summary="Verification passed."),
                start_time=1.1,
                duration=0.2,
            ),
        ],
        final_result="## Comparison\n...\n## Recommendation\n...",
    )
    text = TraceRenderer.to_text(trace)
    assert "Skill 调用链（路由计划）" in text
    assert "comparison → generation → verification" in text
    assert "[task]" in text
    assert "执行记录（共 3 步，含每步产出预览）" in text
    assert "[1/3] comparison" in text
    assert "[3/3] verification" in text
    assert "可见答案来源" in text
    assert "generation" in text
    assert "本步产出" in text
    assert '"observations"' in text or "{}" in text  # comparison JSON preview
    assert "## A" in text  # generation markdown preview
    assert "checklist" in text or "Verification passed" in text
    assert "Final result" not in text

    full = TraceRenderer.to_text(trace, include_final_result=True)
    assert "Final result" in full
    assert "## Comparison" in full


def test_direct_mode_trace():
    trace = TraceRecord(
        session_id="s2",
        task="hello",
        task_type=TaskType.DIRECT,
        timestamp=0.0,
        final_result="Hi.",
    )
    text = TraceRenderer.to_text(trace)
    assert "direct" in text
    assert "无 skill 步骤" in text
