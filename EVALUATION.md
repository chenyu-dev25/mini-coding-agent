# 评判标准与自检

这个文件做两件事：

1. 给 `issue.md` 里的每个目标定义清晰的评判标准。
2. 记录我在交付前做过的自检。

## 目标 1：显式区分 Skill 与 Tool

### 评判标准

- Tool 必须是低层、可复用、可执行能力。
- Skill 必须是面向任务阶段或任务意图的高层能力。
- 不能只是把现有 tool 函数改个名字就叫 skill。
- 代码结构上要能看出这两层边界。

### 自检结果

- 通过。
- Tool 在 `tools/`。
- Skill 在 `skills/*/SKILL.md`。
- runtime 中，skill 只是声明高层能力；真正的低层执行仍然通过 `tools/` 完成。

## 目标 2：至少 4 个 Skill，并且有清晰 Schema

### 评判标准

- 至少有 4 个 skill。
- 每个 skill 必须明确写出：
  - `name`
  - `description`
  - `inputs`
  - `outputs`
  - `applicable_when`
  - `not_applicable_when`
  - `dependencies`
  - `failure_strategy`
  - `content`

### 自检结果

- 通过。
- 当前实现了 6 个目录式 skill：
  - `planning`
  - `analysis`
  - `comparison`
  - `generation`
  - `verification`
  - `ask_back`
- 这些 schema 都来自对应目录下的 `SKILL.md`。
- 已用 `python app.py schemas --json` 验证可被 runtime 正确加载。

## 目标 3：实现 Skill Router / Skill Selection

### 评判标准

- 系统不能所有任务都走固定流水线。
- Router 必须根据任务类型选择不同 skill 路径。
- Router 的选择理由必须可解释。
- 不需要的 skill 必须能被跳过。

### 自检结果

- 通过。
- Router 在 `router/__init__.py`。
- 当前支持的主要路由有：
  - `planning`
  - `planning -> ask_back`
  - `analysis -> generation -> verification`
  - `comparison -> generation -> verification`
- Trace 中能看到 skill 选择理由和 skipped skill 理由。

## 目标 4：支持至少 3 类任务

### 评判标准

- 至少支持 3 类明显不同的任务。
- 至少 2 类任务需要多 skill 协同。

### 自检结果

- 通过。
- 当前支持的主要任务类型：
  - 需求整理型
  - 分析生成型
  - 比较决策型
- 其中多 skill 协同任务至少有两类：
  - 分析生成型
  - 比较决策型

## 目标 5：展示 Trace / Skill 调用轨迹

### 评判标准

- 输出中必须能看到：
  - 选了哪些 skill
  - 为什么选
  - 每个 skill 的输入摘要
  - 每个 skill 的输出摘要
  - skill 是否成功
  - 是否发生 fallback / retry
  - 最终结果如何由中间结果得到

### 自检结果

- 通过。
- `TraceRecord` 记录 router 决策、skill 执行、时长、tool calls、最终结果。
- `TraceRenderer` 提供文本和 JSON 两种展示形式。
- 已用 `python app.py trace --task '比较 pytest vs unittest，并给出推荐理由'` 验证。

## 目标 6：失败处理 / 保底机制

### 评判标准

- 至少存在一条明确的失败处理路径。
- 失败路径必须能在代码中看到，也能被测试覆盖。
- 系统不能在低置信度条件下静默继续执行。

### 自检结果

- 通过。
- 当前显式保底路径有：
  - `planning -> ask_back`
  - `verification -> regenerate -> verification`
- 对应测试已覆盖：
  - `test_requirement_route_asks_back_when_task_is_too_vague`
  - `test_verification_failure_triggers_regeneration_once`

## 目标 7：可扩展性

### 评判标准

- 新增一个 skill 不需要大改 executor 主流程。
- skill 的注册与发现方式清楚。
- router 和 executor 不应和某个具体 skill 实现强耦合。

### 自检结果

- 通过。
- `SkillRegistry` 负责扫描和注册目录式 skill。
- executor 只依赖 skill 名称和 schema，不依赖某个 skill 文件类名。
- 通过 `test_skill_registry_allows_adding_a_new_skill_without_executor_changes` 验证：
  新增一个目录式 `SKILL.md` 后，不需要改 executor。

## 目标 8：说明继承了什么、改了什么、为什么这样改

### 评判标准

- 必须有设计说明文档，解释继承、改动和原因。

### 自检结果

- 通过。
- 见 `DESIGN.md`。

## 我实际做过的验证

### 命令

```bash
python -m py_compile app.py executor/__init__.py router/__init__.py trace/__init__.py models/*.py skills/*.py tests/test_skill_agent.py
python app.py schemas --json
python app.py trace --task '比较 pytest vs unittest，并给出推荐理由'
python -m pytest -q tests/test_skill_agent.py tests/test_mini_coding_agent.py
```

### 结果

- `py_compile`：通过
- `schemas`：通过
- `trace`：通过
- 自动化测试：`26 passed`

## 总体结论

我在提交前按上面的标准重新检查过一遍。

- 总体状态：通过
- 置信度：高
- 当前限制：Router 仍然是规则式的，所以可解释性很强，但灵活性不如更复杂的 LLM Router
