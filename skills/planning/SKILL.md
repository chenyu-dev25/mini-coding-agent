# Planning

- name: planning
- description: 澄清模糊需求，提取目标、约束和交付物，并决定是否需要追问。
- failure_strategy: 当需求仍然模糊时，不继续猜测，转交 ask_back 收集缺失信息。
- applicable_when:
- The task is vague, messy, or mixes goals and constraints together.
- The agent needs to decide whether to ask back before executing.
- not_applicable_when:
- The task already contains clear inputs, outputs, and evaluation criteria.
- The user is explicitly asking for a head-to-head option comparison.
- dependencies:

## Inputs
- task: 自然语言任务描述，可能含糊或混杂多个要求。
- context: 可选上下文，例如 must_include、deadline 或其他显式约束。
- previous_results: 上游 skill 的结果，通常是空列表。

## Outputs
- result: 结构化的需求摘要或需要追问的 JSON 载荷。
- summary: 一句话说明这次规划结果。
- metadata: clarity_score、structured_requirements、questions 等补充字段。

## Content
这个 skill 负责把“先做什么、缺什么、能不能继续做”说清楚。

优先产出：
- 目标
- 约束
- 交付物
- 模糊点

如果任务描述过于模糊，不要继续往下执行，而是明确指出缺什么，并把问题交给 ask_back。
