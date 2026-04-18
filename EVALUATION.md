# Evaluation Standards And Self-Check

This file does two things:

1. Defines a concrete pass/fail standard for each target in `issue.md`.
2. Records the self-check I ran before presenting the work.

## Goal 1: Explicit Skill vs Tool Boundary

### Pass Standard

- Tools are implemented as reusable low-level capabilities.
- Skills are implemented as higher-level task stages or intentions.
- No tool is merely renamed into a skill.
- The code structure makes the boundary visible.

### Self-Check

- Pass.
- Tools live in `tools/`.
- Skills live in `skills/`.
- Skill implementations call tools only through `ToolExecutorMixin`.
- `DESIGN.md` explicitly documents the distinction.

## Goal 2: At Least 4 Skills With Clear Schema

### Pass Standard

- There are at least 4 skills.
- Each skill exposes:
  - name
  - purpose
  - inputs
  - outputs
  - applicable conditions
  - not applicable conditions
  - dependencies
  - failure strategy

### Self-Check

- Pass.
- Implemented skills:
  - `planning`
  - `analysis`
  - `comparison`
  - `generation`
  - `verification`
  - `ask_back`
- Each skill implements `build_definition()` returning `SkillDefinition`.
- Verified via `python app.py schemas --json`.

## Goal 3: Skill Router / Skill Selection

### Pass Standard

- The system does not run one fixed pipeline for every task.
- The route changes for at least 3 task types.
- The router outputs explicit reasons for selected skills.
- Unneeded skills are skipped.

### Self-Check

- Pass.
- Router logic is in `router/__init__.py`.
- Current routes:
  - requirement: `planning` or `planning -> ask_back`
  - analysis: `analysis -> generation -> verification`
  - comparison: `comparison -> generation -> verification`
- Router trace includes skill-selection reasons and skipped-skill reasons.

## Goal 4: Support At Least 3 Task Types

### Pass Standard

- At least 3 task categories are supported.
- At least 2 categories require multi-skill collaboration.
- The categories are behaviorally distinct.

### Self-Check

- Pass.
- Supported categories:
  - requirement shaping
  - analysis + grounded synthesis
  - comparison + decision
- Multi-skill categories:
  - analysis
  - comparison

## Goal 5: Trace / Skill Call Observability

### Pass Standard

- Final trace shows:
  - selected skills
  - why they were selected
  - input summary per skill
  - output summary per skill
  - success/failure state
  - fallback/retry information
  - final result

### Self-Check

- Pass.
- `TraceRecord` stores router decisions, executions, outputs, timing, and final result.
- `TraceRenderer` exposes human-readable and JSON trace output.
- Verified with `python app.py trace --task '比较 pytest vs unittest，并给出推荐理由'`.

## Goal 6: Failure Handling / Safety Net

### Pass Standard

- At least one explicit failure strategy exists.
- The failure path is visible in code and testable.
- The system does not silently continue with low-confidence output.

### Self-Check

- Pass.
- Implemented safety paths:
  - ask-back after unclear planning
  - verify -> regenerate -> verify retry loop
- Covered by automated tests:
  - `test_requirement_route_asks_back_when_task_is_too_vague`
  - `test_verification_failure_triggers_regeneration_once`

## Goal 7: Extensibility

### Pass Standard

- Adding a new skill does not require changing the executor internals.
- Registration/discovery is explicit and simple.
- Router and executor are not tightly coupled to specific implementations.

### Self-Check

- Pass.
- `SkillRegistry` handles skill registration and creation.
- The executor only depends on skill names and definitions.
- Covered by `test_skill_registry_allows_adding_a_new_skill_without_executor_changes`.

## Goal 8: Documentation Of Inheritance And Change

### Pass Standard

- A design doc explains what was inherited, what changed, and why.

### Self-Check

- Pass.
- See `DESIGN.md`.

## Final Verification I Ran

### Commands

```bash
python -m py_compile app.py executor/__init__.py router/__init__.py trace/__init__.py skills/*.py models/schemas.py
python app.py schemas --json
python app.py trace --task '比较 pytest vs unittest，并给出推荐理由'
python -m pytest -q tests/test_skill_agent.py
python -m pytest -q tests/test_mini_coding_agent.py
```

### Results

- `py_compile`: passed
- `schemas`: passed
- `trace` demo: passed
- live Moonshot/Kimi trace: passed
- new skill-agent tests: `7 passed`
- original repo tests: `19 passed`

## Overall Verdict

I reviewed the implementation against the standards above after coding and before presenting it.

- Overall status: Pass
- Confidence: High
- Remaining limitation: routing is intentionally rule-based, so the prototype is explainable and deterministic, but less flexible than an LLM-based router would be in production.
