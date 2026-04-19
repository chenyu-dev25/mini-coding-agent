# Verification

- name: verification
- description: 检查生成结果是否满足显式约束、章节要求和比较结论质量。
- failure_strategy: 返回缺失项和检查清单，让 executor 决定是否触发一次 regenerate。
- applicable_when:
- A generated answer or comparison recommendation already exists.
- The workflow wants a quality gate before returning the final result.
- not_applicable_when:
- The task stopped early because clarification is required.
- dependencies:

## Inputs
- task: 原始任务，包括成功标准或章节要求。
- context: must_include、task_type、retry_count 等约束信息。
- previous_results: 尤其是最新一版 generation 的输出。

## Outputs
- result: PASS/FAIL 检查清单。
- summary: 简短的通过或失败结论。
- metadata: checklist、missing_sections、needs_retry 等字段。

## Content
这个 skill 的核心职责是做质量门禁，而不是重新生成内容。

检查重点：
- 必要章节是否出现
- 比较类答案是否给出明确推荐和原因
- 如果不通过，明确缺失了什么，方便 executor 重试 generation 一次
