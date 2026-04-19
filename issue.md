# Vibe Coding 评测题：基于 mini-coding-agent 实现一个具备 Skill Router 的多 Skill Agent

## 背景

请你基于开源仓库 **[`rasbt/mini-coding-agent`](https://github.com/rasbt/mini-coding-agent)**，在 **24 小时内**完成一次有明确方向的重构与增强。

本题的重点不是把它做成“更强的代码助手”，也不是简单加几个 prompt 或工具，而是考察你是否能够把一个 **minimal coding harness** 演化为一个 **skill-centric agent system**。

我们希望看到你围绕以下问题进行设计与实现：

- 什么是一个 skill？
- skill 和 tool 的边界是什么？
- 一个任务到来时，如何决定调用哪些 skill？
- skill 之间如何协同，而不是所有任务都走固定链路？
- 如何让 skill 的执行过程可解释、可追踪、可扩展？
- 如何在 skill 失败或结果不可靠时做 fallback / retry / verify？

---

## 任务目标

请基于 `rasbt/mini-coding-agent`，将其改造成一个 **具备显式 Skill Schema、Skill Router、Trace 与失败处理机制** 的多 Skill Agent 原型。

你的重点应放在：

1. 将原本偏“单 agent loop + tool 调用”的结构，提升为“skill 驱动”的结构
2. 让 Agent 能针对不同任务，选择不同 skill 链路
3. 明确展示 skill 的设计、调用原因、中间结果与最终结论之间的关系
4. 体现你对系统边界、扩展性与工程结构的思考

---

## 起始代码仓

请以以下仓库为起点进行开发：

- `https://github.com/rasbt/mini-coding-agent`

你可以自由 fork、复制、重构或裁剪该仓库，但需要保留“基于其进行演化”的基本事实。

> 注意：
> - 你不需要保留原仓的所有实现细节
> - 你可以对目录结构做较大重构
> - 你可以新增模块、删除不必要逻辑、重写部分实现
> - 但请在 `DESIGN.md` 中说明：你继承了什么、改掉了什么、为什么这样改

---

## 核心要求

### 1. 必须显式区分 Skill 与 Tool

请不要直接把已有工具函数重命名为 skill。

你需要清楚地区分：

- **Tool**：底层可执行能力，例如文件读取、搜索、代码执行、shell 命令等
- **Skill**：面向任务阶段或任务意图的更高层能力，例如规划、检索、分析、生成、验证、比较、追问等

你需要在系统中体现这种边界。

---

### 2. 必须定义 Skill Schema

请至少实现 **4 个 skill**，并为每个 skill 定义清晰的 schema，至少包括：

- Skill 名称
- Skill 作用
- 输入
- 输出
- 适用条件
- 不适用条件
- 可依赖哪些 tool 或其他上下文
- 失败时的处理方式

你需要回答：

- 什么情况下应该调用这个 skill？
- 什么情况下不应该调用这个 skill？
- 它和其他 skill 的边界在哪里？

---

### 3. 必须实现 Skill Router / Skill Selection 机制

你的系统必须具备 **skill selection** 能力。

不接受以下情况：

- 所有任务都固定执行同一条流水线
- 只是把 skill 顺序写死
- 不管任务类型如何都调用全部 skill

至少需要体现以下能力中的一种或多种：

- 根据任务类型选择 skill
- 根据中间结果动态调整 skill 顺序
- 跳过不必要的 skill
- 在多个 skill 候选之间做决策
- 在某个 skill 失败后切换备用策略

实现方式不限，例如：

- 规则 / 启发式 router
- classifier / router model
- LLM-based router
- 混合 routing

---

### 4. 必须支持至少 3 类任务

请让你的 Agent 至少支持 **3 类不同任务**，并展示 skill routing 的必要性。

其中至少 **2 类任务**必须需要多 skill 协同。

任务类型可以自选，但建议具有明显差异。示例包括：

- **需求整理型**：从混乱描述中提取目标、约束、待办事项
- **分析生成型**：先分析输入内容，再给出方案或生成结果
- **比较决策型**：比较多个候选方案并给出推荐结论
- **信息不足型**：识别缺失信息并 ask-back 或基于假设继续
- **验证修正型**：生成后检查，再重写或修正

> 你不需要把它做成一个“全能 agent”，但必须展示 skill routing 确实在发挥作用。

---

### 5. 必须展示 Trace / Skill 调用轨迹

系统最终输出时，必须能够展示至少以下内容：

- 选择了哪些 skill
- 为什么选择这些 skill
- 每个 skill 的输入摘要
- 每个 skill 的输出摘要
- skill 是否成功执行
- 如果失败，是否发生 fallback / retry / ask-back
- 最终结果是如何由中间结果得到的

也就是说，系统需要具备基本的：

- 可解释性
- 可追踪性
- 可观测性

---

### 6. 必须有失败处理 / 保底机制

至少实现以下一种机制：

- skill 执行失败后的 fallback
- verify 不通过后的 regenerate / rewrite
- 信息不足时 ask-back
- 检索无结果时降级策略
- 输出不满足约束时切换 skill 链路

我们希望看到你考虑的是“系统如何稳一点”，而不是“理想路径能跑一次”。

---

### 7. 必须体现可扩展性

你的系统需要体现：

- 新增一个 skill 时，不需要大改主流程
- skill 的注册、发现或接入方式尽量清晰
- skill router 不应与具体 skill 实现强耦合到无法扩展

不要求插件系统做到很完整，但应至少体现出 **可扩展的设计意识**。

---

## 建议实现方向

你可以自由设计，但我们建议你至少考虑以下结构层次：

- `tools/`：底层工具能力
- `skills/`：skill schema 与 skill 实现
- `router/`：skill selection / routing
- `executor/`：skill 执行与状态管理
- `trace/`：skill 调用记录与可视化输出
- `app/`：CLI 或 Web 入口

这不是硬性要求，你也可以设计自己的结构。

---

## 交付形式

你可以选择以下任意一种方式完成：

### 方案 A：CLI
例如支持类似命令：

```bash
python app.py chat
python app.py run --task examples/task_1.json
python app.py trace --task examples/task_2.json
```

### 方案 B：轻量 Web Demo
至少展示：

- 用户输入
- Router 选择的 skill 链
- skill 执行过程
- 中间结果摘要
- 最终输出

> 我们不要求精美 UI。  
> 清晰、可运行、可观察比界面包装更重要。

---

## 测试任务要求

请至少准备并展示以下 **3 类测试任务**。

### 任务类型 1：需求整理型
输入一段混乱描述，让 Agent：

- 提取关键信息
- 总结目标与约束
- 输出结构化结果

建议考察 skill：

- `plan`
- `summarize`
- `structure`
- `ask_back`

---

### 任务类型 2：分析生成型
输入一组文本、样本、案例或输入内容，让 Agent：

- 检索或组织相关信息
- 分析要点
- 生成建议、方案或产出
- 做一轮验证或自检

建议考察 skill：

- `retrieve`
- `analyze`
- `generate`
- `verify`

---

### 任务类型 3：比较决策型
输入两个或多个候选方案，让 Agent：

- 比较差异
- 分析优缺点
- 给出推荐结论
- 说明依据

建议考察 skill：

- `compare`
- `analyze`
- `summarize`
- `verify`

---

> 你可以自定义任务，但必须保证任务之间有明显差异，并能体现 skill routing 的价值。

---

## 强制提交物

### 1. 可运行代码仓
请提交完整代码，要求可在本地运行。

---

### 2. `README.md`
至少包括：

- 项目简介
- 安装方式
- 运行方式
- 支持的任务类型
- skill 列表
- 系统结构说明
- 示例输入输出

---

### 3. `DESIGN.md`
请至少回答以下问题：

1. 你如何定义一个 skill？
2. 你如何区分 skill 与 tool？
3. 为什么把 skill 划分成这几个？
4. 你的 skill 粒度为什么这样设计？
5. router 是如何做决策的？
6. 哪些情况下 router 可能误选或漏选？
7. 你如何处理失败、冗余调用和错误链路？
8. 你对 mini-coding-agent 的哪些部分做了继承、重构或替换？为什么？
9. 如果再给你 2 天，你会如何继续扩展这个系统？

---

### 4. `BUILD_LOG.md`
请简要记录你的实现过程，尤其是：

- 你如何使用 AI coding assistant（如 ChatGPT、Claude Code、Cursor、Copilot 等）
- 哪些代码或设计由 AI 辅助生成
- 哪些关键取舍是你自己做出的
- 哪些 AI 建议你没有采纳，为什么

> 我们会通过这个文件判断你的 vibe coding 判断力，而不只是完成速度。

---

### 5. 演示视频（建议 5～10 分钟）
建议展示：

- 一个完整任务流程
- 一次 skill routing 决策过程
- 一个多 skill 协同案例
- 一次失败处理 / fallback / verify / ask-back 案例
- trace 的查看方式

---

## 评分标准

总分 100。

### 1. Skill 抽象质量（25 分）
重点看：

- skill 边界是否清晰
- skill 是否独立可复用
- 是否有清晰输入输出
- 是否定义了适用 / 不适用条件
- 是否真正体现出 “skill ≠ tool”

### 2. Skill Selection / Routing 能力（25 分）
重点看：

- 是否真的存在“选择”
- 是否能根据任务变化调整 skill 链路
- 是否避免所有任务固定流水线
- 是否考虑误选、漏选、冗余调用
- 是否有一定 fallback 或保底逻辑

### 3. 多 Skill 协同设计（20 分）
重点看：

- skill 之间接口是否自然
- 中间结果是否被有效利用
- 是否形成完整闭环
- 是否能看出明确的系统分层

### 4. 可解释性与 Trace（10 分）
重点看：

- trace 是否清晰
- 为什么调用某个 skill 是否可说明
- 最终结果是否能追溯到中间结果

### 5. 工程完成度（10 分）
重点看：

- 是否可运行
- 项目结构是否清晰
- README 是否可复现
- demo 是否完整

### 6. 思考深度（10 分）
重点看：

- 是否意识到 skill 粒度问题
- 是否讨论 router 的局限
- 是否思考扩展性、鲁棒性与失败处理
- 是否体现出自己的判断，而不是只做 prompt 套壳

---

## 加分项

以下内容不是必须，但会明显加分：

- skill 注册机制 / registry / 配置驱动接入
- 区分 task router 与 skill router
- skill trace 的可视化展示
- 对“何时不该调用某个 skill”有显式控制
- skill 执行成本控制（避免无意义调用）
- skill 结果缓存或中间结果复用
- 对 routing 做简单评测或日志统计
- 明确讨论 mini-coding-agent 原设计的局限与改造取舍

---

## 不建议的实现方式

以下方式不推荐，也可能被认为没有完成本题核心目标：

- 所有任务都直接丢给一个大模型回答
- 所有任务都固定走一条硬编码流水线
- skill 只是换了名字的 prompt 模板
- 没有 trace，无法解释 skill 为什么被调用
- 没有失败处理或保底机制
- 只做 UI 包装，没有真正的 skill 系统改造
- 只是给 mini-coding-agent 加几个工具，并未显式引入 skill abstraction

---

## 时间限制

请在 **24 小时内**完成并提交。

我们不要求它成为生产级系统，但希望你能够在有限时间内完成一个：

- 结构清晰
- skill 边界明确
- routing 合理
- 可解释
- 可扩展
- 能体现个人判断力

的 Agent 原型。

---

## 我们最想看到的

相比“做得很大”，我们更想看到你是否能够把一个小而真实的 agent harness，重构成一个：

- 有 skill schema
- 有 router
- 有 trace
- 有 fallback
- 有扩展意识

的小而完整的系统。

一个结构扎实、边界清晰、能解释自己行为的实现，通常会优于一个功能很多但核心架构模糊的 demo。

祝你玩得开心。
