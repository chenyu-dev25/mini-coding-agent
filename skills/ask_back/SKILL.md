# Ask Back

- name: ask_back
- description: 在关键信息缺失时，用最小问题集向用户追问，而不是继续猜测。
- failure_strategy: 直接停止当前链路，把需要补充的问题返回给用户。
- applicable_when:
- A required file, option, or success criterion is missing.
- An upstream skill explicitly requests clarification.
- not_applicable_when:
- The route already has enough information to answer responsibly.
- dependencies:

## Inputs
- task: 原始任务。
- context: 上游传下来的 questions 或缺失信息提示。
- previous_results: 低置信度或失败的上游结果。

## Outputs
- result: 包含 status 和 questions 的 JSON 追问载荷。
- summary: 一句话说明系统正在追问用户。
- metadata: questions、blocked 等字段。

## Content
这个 skill 是明确的保底路径。

目标：
- 少问，但问到点上
- 不在信息不足时继续猜测
- 把 workflow 安全地停在需要用户补充输入的位置
