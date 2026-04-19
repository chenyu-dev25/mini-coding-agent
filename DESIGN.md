# Skill-Centric 设计说明

## 继承了什么

这次实现仍然是基于 `rasbt/mini-coding-agent` 演化出来的，而不是把原仓库推翻重写。

- 保留了原始的 `mini_coding_agent.py`，原有最小化单 Agent CLI 仍然存在。
- 保留了 `tools/` 这层低层能力，继续把读文件、搜索、写文件、执行 shell 视为 Tool。
- 保留了轻量、本地优先、纯 Python 模块化的整体风格。

## 新增了什么

为了满足 `issue.md` 对 Skill 系统的要求，我额外增加了一套独立 runtime：

- `app.py`
  作为 skill runtime 的 CLI 入口，支持 `run`、`trace`、`chat`、`schemas`
- `router/`
  负责任务分类和 skill 选择
- `executor/`
  负责 skill 执行、fallback / retry、trace 记录
- `models/`
  负责 schema 和可选模型客户端
- `trace/`
  负责把 skill 执行过程渲染成可读 trace
- `skills/`
  现在不再放每个 skill 的 Python 类，而是放目录式 markdown skill

## Skill 现在是怎么定义的

这版里，Skill 的定义不再靠 `skills/*.py` 子类，而是靠：

- `skills/<skill-name>/SKILL.md`

每个 `SKILL.md` 都显式写出：

- `name`
- `description`
- `inputs`
- `outputs`
- `applicable_when`
- `not_applicable_when`
- `dependencies`
- `failure_strategy`
- `content`

运行时会扫描这些目录式 skill，把 markdown 解析成 `SkillDefinition`，再交给 `router / executor / trace` 使用。

也就是说：

- Skill 的**定义层**是 markdown 文档
- Skill 的**执行层**是统一的 runtime 适配器

这样比“一个 skill 一个 Python 类”更接近通用 skill 系统。

## 为什么这样改

### 1. 明确区分 Skill 和 Tool

这次最重要的边界是：

- Tool：底层能力
  - `read_file`
  - `list_files`
  - `search`
  - `write_file`
  - `patch_file`
  - `run_shell`

- Skill：高层任务阶段
  - `planning`
  - `analysis`
  - `comparison`
  - `generation`
  - `verification`
  - `ask_back`

Skill 不再是 Tool 的简单改名，而是面向任务意图的上层能力。

### 2. 让 Skill 定义更通用

如果 skill 只能靠 Python 类定义，那么：

- 可移植性差
- 不利于展示 schema
- 不利于像 DeepAgents / DeerFlow 那种目录式 skill 组织方式

改成 `SKILL.md` 后，新增 skill 的方式更清楚：

1. 新建一个目录
2. 写一个 `SKILL.md`
3. 运行时自动扫描注册
4. 如有需要，再补对应执行逻辑

### 3. 保留可解释的 runtime

虽然 Skill 改成了 markdown 定义，但 `router / executor / trace` 仍然保留。

这样仍然能满足题目要求里的：

- skill selection
- trace
- fallback / retry
- 可扩展性

## Router 设计

当前 router 仍然是规则式的，原因是：

- 可解释
- 稳定
- 在作业里容易展示 skill routing 的必要性

现在主要支持三类任务：

1. 需求整理型
   - `planning`
   - 必要时 `ask_back`
2. 分析生成型
   - `analysis -> generation -> verification`
3. 比较决策型
   - `comparison -> generation -> verification`

这说明系统不是所有任务都跑同一条固定流水线。

## 失败处理设计

当前有两条明确的保底路径：

### 1. Ask-back

当 `planning` 判断任务过于模糊时，不继续猜测，而是切到 `ask_back`，直接返回需要补充的问题。

### 2. Verify 后重生成

当 `verification` 发现缺少必要章节或比较理由时：

- executor 会带着缺失项重跑一次 `generation`
- 然后再次 `verification`

这样能避免系统把明显不满足约束的答案直接返回给用户。

## Trace 设计

每次运行都会记录：

- Router 怎么分类
- 选了哪些 skill
- 为什么选这些 skill
- 每个 skill 的输入摘要
- 每个 skill 的输出摘要
- 是否成功
- 是否 fallback / retry
- 最终结果是怎么得到的

因此这套 runtime 具备：

- 可解释性
- 可追踪性
- 可观测性

## 扩展性设计

这版扩展点主要有两个：

1. `skills/*/SKILL.md`
   新 skill 的定义入口
2. `SkillRegistry`
   负责扫描、注册、实例化 skill

所以增加一个新 skill，不需要大改 `executor` 主流程；只需要补 skill 定义和必要的执行逻辑。
