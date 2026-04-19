# DESIGN.md（对应 `issue.md` 九问）

本文按评测题 **强制提交物 § DESIGN.md** 的九个问题逐条回答，并与当前仓库实现一致。

---

## 1. 你如何定义一个 skill？

在本实现里，**skill 是面向任务阶段 / 意图的高层能力单元**：有显式 **schema（名称、用途、输入输出、适用/不适用条件、依赖与失败策略）**，由 **executor** 按路由结果调用；其内部可以编排 **tool** 调用与 **LLM** 调用，但对外呈现的是「完成某一阶段的产出」，而不是单次文件读写。

**落地形式：**

- **声明层**：`skills/<name>/SKILL.md`，解析为 `SkillDefinition`（`models/schemas.py`）。
- **执行层**：`skills/base.py` 中 `BaseSkill` 按 skill 名分发到 `_execute_planning`、`_execute_analysis` 等统一适配器，而不是「每个 skill 一个独立 Python 类文件」。

这样 skill 的**契约**在 markdown 里可读、可审，**行为**在单一适配器里维护，便于扩展与测试。

---

## 2. 你如何区分 skill 与 tool？

| 层级 | 含义 | 本仓库中的体现 |
|------|------|----------------|
| **Tool** | 底层、可复用的环境操作：读文件、列目录、搜索、写文件、打补丁、跑 shell 等。 | `tools/`（如 `read_file`、`list_files`、`run_shell`），由 `BaseSkill.execute_tool` 调用并记入 `ToolCall`。 |
| **Skill** | 面向「这一阶段要达成什么」：**规划、分析、对比、生成终稿、质检、追问** 等。 | `planning`、`analysis`、`comparison`、`generation`、`verification`、`ask_back`；每个 skill 内部按需调用多个 tool + LLM。 |

**边界原则：** 不把「读一个文件」单独当作 skill；读文件是 **analysis** 等 skill **内部**使用的 tool。Skill 的产出应是**结构化或成稿级**的中间结果（JSON/Markdown/追问列表），供下游 skill 或最终答案使用。

---

## 3. 为什么把 skill 划分成这几个？

划分依据是 **issue.md 要求覆盖的任务形态** 与 **一条可解释的流水线**：

- **planning**：需求整理、澄清目标/约束/交付物；与「混乱描述 → 结构化」对应。
- **analysis**：结合仓库片段做 grounded 观察与风险，再交给生成；与「分析生成型」对应。
- **comparison**：对多选项打分与推荐结构（JSON），再交给生成写成用户可读对比稿；与「比较决策型」对应。
- **generation**：把上游 skill 的产出统一写成 **面向用户的 Markdown**，并满足 `must_include` 等章节约束。
- **verification**：对照任务与草稿做检查清单；失败则触发 **重试 generation**（见第 7 节）。
- **ask_back**：planning 判断信息不足时 **不瞎猜**，返回最小追问集。

该集合能覆盖题目中的 **需求整理 / 分析生成 / 比较决策**，并留出 **追问** 与 **质检** 两条显式保底路径，而不必为每个题型单独写死一套无关联的 prompt。

---

## 4. 你的 skill 粒度为什么这样设计？

- **偏「阶段」而非「微操作」**：每个 skill 对应评测题里常见的一截工作流（澄清 → 取证分析 → 对比 → 成稿 → 质检），便于在 **trace** 里解释「为什么先 analysis 再 generation」。
- **避免过细**：若把「读 README」「写一段结论」拆成多个 skill，router 组合爆炸，且与「skill ≠ tool」易混淆。
- **避免过粗**：若只有一个 `do_everything` skill，则无法满足「多 skill 协同」与「可替换链路」的评分点。

当前粒度在 **可观测性**（每步有记录）与 **实现成本**（规则路由 + 统一 BaseSkill）之间折中。

---

## 5. router 是如何做决策的？

决策分 **两层**（均在 `router/__init__.py` 与 `executor/__init__.py`）：

**A. 是否进入「多 skill 流水线」**（`wants_skill_pipeline`）

- 上下文强制：`use_skill_pipeline`、CLI `--skill-pipeline`、`must_include`、环境变量 `SKILL_AGENT_PIPELINE`。
- 否则用 **启发式** `high_intent_skill_route`：如含「比较/对比/vs」「需求/整理/差不多」「分析/readme/.md/文件」等则进入流水线。
- 否则走 **DIRECT**（单次 LLM 聊天）。另有 **CHITCHAT**、**SKILL_CATALOG** 在 executor 前置处理，不经过 `SkillRouter.classify`。

**B. 流水线内任务类型与 skill 链**（`SkillRouter.classify` → `select_skills`）

- **COMPARISON**：`comparison → generation → verification`
- **REQUIREMENT**：`planning`（必要时 executor 内转 **ask_back**）
- **ANALYSIS**：`analysis → generation → verification`
- **GENERATION**（默认桶）：`planning → generation → verification`

每条链上的 skill 带 **被选原因**（`RoutedSkill.reason`），写入 `TraceRecord`，供 `trace_renderer.TraceRenderer` 展示。

---

## 6. 哪些情况下 router 可能误选或漏选？

**误选（典型）：**

- **关键词串线**：用户随口说「随便分析下」但真实意图是闲聊 → 可能进 **ANALYSIS** 流水线；反之强意图句子里没触发词 → 可能 **DIRECT** 掉。
- **中英混写 / 缩写**：规则未覆盖的表达可能落入默认 **GENERATION** 桶，导致多跑 **planning**。
- **比较型但未出现显式选项名**：`comparison` skill 内部若抽不出两个选项，会失败或 fallback（与 router「选了 comparison」不完全一致）。

**漏选（典型）：**

- 用户希望「只要验证不要生成」等 **细粒度控制**，当前没有自然语言级 **负向路由**（仅能通过 `/direct`、环境变量等关闭流水线）。
- **动态重路由**：除 planning→ask_back、verification→retry generation 外，**不会在执行中途**根据中间结果整体改写成另一条链（例如从 analysis 链切到 comparison 链）。

改进方向（未实现）：LLM router、二次确认、或基于日志统计调规则权重。

---

## 7. 你如何处理失败、冗余调用和错误链路？

| 机制 | 行为 |
|------|------|
| **planning → ask_back** | `requires_clarification` 或清晰度过低时，executor **中断主链**，执行 `ask_back`，避免继续 generation。 |
| **verification 失败 → regeneration** | `_maybe_retry_generation`：带 `retry_missing_sections` 再跑 **generation**，再 **verification** 一次（有次数上限，避免死循环）。 |
| **analysis JSON 解析失败** | `extract_json_object` 异常时 **回退**到启发式 observations/risks，**不使整个 analysis 崩溃**（`skills/base.py`）。 |
| **skill 安全执行** | `BaseSkill.safe_execute` 捕获异常，返回失败 `SkillOutput`，由 trace 记录状态。 |
| **冗余调用** | 未做全局去重缓存；通过 **默认 DIRECT**、**must_include 才强制流水线** 等减少无意义多步。错误链路由 **TraceRecord + 进度回调** 可观测。 |

---

## 8. 你对 mini-coding-agent 的哪些部分做了继承、重构或替换？为什么？

**继承 / 保留：**

- **`mini_coding_agent.py`**：原版「单 Agent + 工具循环 + 会话存储」CLI **仍保留**，作为与题目「基于原仓演化」的对照入口。
- **`tools/`**：底层能力延续，避免把 IO/shell 逻辑塞进 skill 定义。

**新增 / 并行一套 runtime：**

- **`app.py`**：`uv run mini-coding-agent` 的入口；**REPL**、`run` / `trace` / `schemas` 子命令。
- **`executor/`**：`SkillAgent.run`、进度回调、`TraceRecord` 组装、fallback/retry。
- **`router/`**：规则分类与选链。
- **`models/`**：`SkillDefinition`、`TraceRecord`、`RouterDecision`、Moonshot/Ollama 客户端等。
- **`trace_renderer.py`**：人类可读 trace（调用链、每步摘要、Markdown 预览等）；仓库内另有 **`trace/`** 包为早期占位，**当前 CLI 以 `trace_renderer` 为准**。
- **`markdown_console.py`**：终端 Rich Markdown 渲染（可选 `--no-ansi`）。
- **`skills/`**：由「每 skill 一个 `*_skill.py`」**替换为**「`skills/<name>/SKILL.md` + `BaseSkill` 分发」，便于 schema 展示与注册扩展。

**原因简述：** 题目要的是 **skill-centric、可路由、可追踪** 的原型，而非在旧单循环上贴 prompt；独立 runtime 更清晰，同时保留原 CLI 证明「演化而非另起炉灶」。

---

## 9. 如果再给你 2 天，你会如何继续扩展这个系统？

1. **Router**：引入 **轻量 LLM router** 或 **可学习权重**，与现有规则 **混合**；记录 **误路由样本** 做离线调参。
2. **评测**：对路由与章节约束做 **小型黄金集 + 断言**，回归 `pytest` 与人工 spot-check。
3. **Trace**：导出 **JSON/Mermaid** 流程图；或 Web 只读页展示同一次 `TraceRecord`。
4. **成本与冗余**：skill 级 **缓存**（相同文件哈希 + 任务摘要）、跳过不必要的 verification。
5. **Tool 能力**：受控 **git diff / ast** 等，仍严格放在 tool 层，由 analysis 等 skill 调用。
6. **与旧 CLI 融合**：可选「同一会话里切换 legacy / skill 模式」或共享 workspace 上下文。

---

## 附录：模块索引（便于阅卷对照代码）

| 路径 | 职责 |
|------|------|
| `app.py` | CLI、REPL、`--trace` / `--no-ansi` / `--no-progress` 等 |
| `executor/__init__.py` | `SkillAgent`、流水线循环、ask_back / retry |
| `router/__init__.py` | `wants_skill_pipeline`、`SkillRouter` |
| `skills/base.py` | Skill 执行适配、tool 调用、LLM JSON 技能体 |
| `skills/*/SKILL.md` | 各 skill 的显式 schema |
| `tools/` | 底层 tool |
| `trace_renderer.py` | Trace 文本渲染 |
| `models/schemas.py` | Trace、Router、Skill 相关数据结构 |
