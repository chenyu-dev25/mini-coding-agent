# Analysis

- name: analysis
- description: 检查本地文件或仓库上下文，提炼后续生成所需的关键观察和风险。
- failure_strategy: 如果缺少关键文件或上下文不足，则返回浅层分析结果，并提示后续补充信息。
- applicable_when:
- The task mentions concrete files, code, repo docs, or asks for analysis before a recommendation.
- Downstream generation should be grounded in repository facts.
- not_applicable_when:
- The task is purely a vague request that first needs clarification.
- The task is a direct option comparison with no repository context needed.
- dependencies:
- list_files
- read_file
- search

## Inputs
- task: 提到文件、代码、README、issue 或分析需求的任务。
- context: 可选文件提示、分析重点、must_include 等信息。
- previous_results: 上游 planning 等 skill 的中间结果。

## Outputs
- result: 包含 inspected_artifacts、observations、risks 的 JSON 结果。
- summary: 一句话总结分析覆盖面和最关键发现。
- metadata: inspected_files、missing_files、observations 等字段。

## Content
这个 skill 的职责是先把“证据”拿到手，再让下游 generation 用这些证据组织最终答案。

优先做的事：
- 找出任务中提到的文件
- 读取最相关的本地内容
- 归纳观察点和风险

不要直接产出最终面向用户的答案；这一步更偏“取证”和“归纳”。
