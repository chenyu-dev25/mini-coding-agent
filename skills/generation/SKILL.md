# Generation

- name: generation
- description: 基于上游 skill 的中间结果，生成面向用户的最终交付内容。
- failure_strategy: 如果上游结构不足以支撑回答，就回退到 planning 或等待更多上下文。
- applicable_when:
- The system already has enough structured context to answer.
- A final recommendation, plan, or write-up must be produced.
- not_applicable_when:
- The task still needs user clarification before a trustworthy answer exists.
- dependencies:

## Inputs
- task: 原始用户任务。
- context: must_include、retry_missing_sections、simulate_incomplete_first_pass 等控制项。
- previous_results: planning、analysis、comparison 等上游 skill 的结果。

## Outputs
- result: Markdown 风格的最终草稿，包含分节和结论。
- summary: 一句话概括这次生成了什么。
- metadata: sections、source_skills 等字段。

## Content
这个 skill 负责把上游结构化结果组织成最终可读答案。

要求：
- 输出面向用户，而不是中间 JSON
- 尽量保留上游分析依据
- 如果有 must_include，要确保这些章节真的出现在最终文稿里

它不负责判断答案是否达标；这件事交给 verification。
