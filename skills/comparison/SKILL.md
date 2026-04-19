# Comparison

- name: comparison
- description: 对多个候选方案进行对比、评分，并给出推荐结论。
- failure_strategy: 如果抽不出至少两个候选项，就停止比较并回退到 planning 重新澄清。
- applicable_when:
- The user asks to compare multiple choices or decide between alternatives.
- The system needs a recommendation instead of raw analysis only.
- not_applicable_when:
- There is only one obvious solution path and no decision to make.
- The task is mainly about asking follow-up questions for clarity.
- dependencies:

## Inputs
- task: 含有比较、对比、哪个更好、vs 等表达的任务。
- context: 可选 options 或 criteria。
- previous_results: 上游 planning 或 analysis 的结果，用于补充决策依据。

## Outputs
- result: 包含 options、criteria、scores、recommendation 的 JSON 结果。
- summary: 一句话说明推荐结论和主要依据。
- metadata: recommended_option、criteria、scores 等字段。

## Content
这个 skill 的目标不是“描述差异”，而是“做出决策”。

最低要求：
- 抽取候选项
- 建立比较维度
- 给出推荐对象
- 说明推荐依据

下游 generation 负责把结构化比较结果写成更适合用户阅读的结论。
