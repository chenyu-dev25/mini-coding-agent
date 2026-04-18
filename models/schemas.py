"""Shared schemas for the skill-centric agent runtime."""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class TaskType(str, Enum):
    """Supported high-level task categories."""

    REQUIREMENT = "requirement"
    ANALYSIS = "analysis"
    GENERATION = "generation"
    COMPARISON = "comparison"
    UNKNOWN = "unknown"


class SkillStatus(str, Enum):
    """Execution state for an individual skill run."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    FALLBACK = "fallback"
    SKIPPED = "skipped"


class ToolCall(BaseModel):
    """Observed low-level tool invocation."""

    name: str
    args: Dict[str, Any]
    result: Optional[str] = None
    status: str = "pending"
    error: Optional[str] = None


class SkillInput(BaseModel):
    """Input passed into a skill."""

    task: str
    context: Dict[str, Any] = Field(default_factory=dict)
    previous_results: List[Dict[str, Any]] = Field(default_factory=list)


class SkillOutput(BaseModel):
    """Output returned by a skill."""

    success: bool
    result: str
    summary: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)
    errors: List[str] = Field(default_factory=list)


class SkillDefinition(BaseModel):
    """Explicit skill schema used for docs and routing."""

    name: str
    purpose: str
    inputs: Dict[str, str]
    outputs: Dict[str, str]
    applicable_when: List[str]
    not_applicable_when: List[str]
    dependencies: List[str]
    failure_strategy: str


class SkillInfo(BaseModel):
    """Backward-compatible metadata view for a skill."""

    name: str
    description: str
    input_schema: Dict[str, Any]
    output_schema: Dict[str, Any]
    applicable_conditions: List[str]
    not_applicable_conditions: List[str]
    required_tools: List[str]
    fallback_skill: Optional[str]


class TaskClassification(BaseModel):
    """Task classification result from the router."""

    task_type: TaskType
    confidence: float
    suggested_skills: List[str]
    reasoning: str
    context: Dict[str, Any] = Field(default_factory=dict)


class RoutedSkill(BaseModel):
    """A selected skill plus the reason it was chosen."""

    name: str
    reason: str


class RouterDecision(BaseModel):
    """Router output for a single task."""

    task_type: TaskType
    confidence: float
    selected_skills: List[RoutedSkill]
    skipped_skills: List[Dict[str, str]] = Field(default_factory=list)
    reasoning: str
    context: Dict[str, Any] = Field(default_factory=dict)


class SkillExecutionRecord(BaseModel):
    """Detailed trace for one skill invocation."""

    skill_name: str
    skill_type: str
    status: SkillStatus
    reason: str
    input_summary: str
    output_summary: Optional[str] = None
    input: SkillInput
    output: Optional[SkillOutput] = None
    start_time: float
    end_time: Optional[float] = None
    duration: Optional[float] = None
    tool_calls: List[ToolCall] = Field(default_factory=list)
    fallback_used: bool = False
    retry_count: int = 0


class TraceRecord(BaseModel):
    """End-to-end trace for a task run."""

    session_id: str
    task: str
    task_type: TaskType
    timestamp: float
    router_decisions: List[RouterDecision] = Field(default_factory=list)
    skill_executions: List[SkillExecutionRecord] = Field(default_factory=list)
    final_result: Optional[str] = None
    total_duration: Optional[float] = None
