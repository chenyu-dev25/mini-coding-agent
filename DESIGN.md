# Skill-Centric Redesign

## What I Inherited

This prototype still clearly evolves from `rasbt/mini-coding-agent` rather than replacing it wholesale.

- I kept the original `mini_coding_agent.py` intact as the minimal single-agent harness.
- I reused the existing low-level tool concepts in `tools/`, especially file reads, search, patching, and shell execution.
- I kept the repo lightweight and local-first: simple Python modules, no service dependencies, no database, no framework-heavy runtime.

## What I Changed

I added a parallel, explicit skill-centric runtime instead of forcing the original single-loop agent to absorb every concern.

- `skills/`
  Defines explicit skill schemas and implementations.
- `router/`
  Classifies the task and chooses a skill route with reasons.
- `executor/`
  Runs the chosen route, records trace data, and handles fallback/retry.
- `trace/`
  Renders execution traces in human-readable or JSON form.
- `app.py`
  Adds a CLI for `run`, `trace`, `chat`, and `schemas`.

This gives the repo two layers:

1. The original minimal coding harness for backward compatibility.
2. A new skill-centric prototype that satisfies the evaluation task.

## Why This Structure

I chose additive evolution instead of invasive rewrite for three reasons.

### 1. Preserve the origin story

The assignment explicitly asks for an evolution of the original repo. Keeping the original file intact makes the lineage obvious.

### 2. Make Skill vs Tool explicit

Tools remain low-level capabilities:

- `read_file`
- `list_files`
- `search`
- `write_file`
- `patch_file`
- `run_shell`

Skills are higher-level task stages:

- `planning`
- `analysis`
- `comparison`
- `generation`
- `verification`
- `ask_back`

This boundary is enforced in code by putting tool invocation in `ToolExecutorMixin` and task-oriented behavior in individual skill classes.

### 3. Keep extensibility cheap

`SkillRegistry` is the main extension seam. Adding a new skill only requires:

1. Create a new `BaseSkill` subclass.
2. Implement `build_definition()` and `execute()`.
3. Register it.

The executor and trace logic do not need to know the implementation details of the new skill.

## Routing Design

The current router is rule-based on purpose.

- It is deterministic.
- It is easy to inspect in a take-home exercise.
- It makes routing reasons easy to expose in the trace.

The router supports three clearly different task families:

1. Requirement-shaping tasks
   Route: `planning` or `planning -> ask_back`
2. Analysis/generation tasks
   Route: `analysis -> generation -> verification`
3. Comparison/decision tasks
   Route: `comparison -> generation -> verification`

This proves that the runtime is not a fixed single pipeline.

## Failure Handling Design

There are two explicit safety paths.

### Ask-back fallback

If `planning` finds the request too vague, it marks the result as requiring clarification and the executor switches to `ask_back`.

### Verify-then-regenerate

If `verification` fails after generation, the executor retries `generation` once with concrete missing sections in context, then verifies again.

This keeps the runtime from silently returning low-confidence output.

## Trace Design

Each run records:

- the router decision
- selected skills and reasons
- per-skill input summary
- per-skill output summary
- tool calls
- fallback and retry state
- final result

This is enough to explain not only what happened, but why it happened.
