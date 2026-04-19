# Build Log

## 开发过程记录

这次评测题我主要分成两个阶段完成。

### 第一阶段：使用 Codex 完成整体方案搭建

一开始我主要使用 **Codex** 来快速理解原始仓库 `mini-coding-agent` 的结构，并完成第一版多 Skill Agent 原型的设计与实现。这个阶段的重点是先把核心骨架搭出来，确认整体方案可行。

这一阶段主要完成了以下内容：

- 梳理原始仓库中哪些部分可以继承，哪些部分需要重构
- 设计 Skill 与 Tool 的边界
- 增加新的 runtime 结构，包括：
  - `app.py`
  - `executor/`
  - `router/`
  - `models/`
  - `trace/`
- 实现最初的 Skill Router、Trace、失败处理和可扩展机制
- 补齐测试，验证多种任务链路能够正常执行

简单来说，Codex 阶段更偏向于：

- 快速搭建系统结构
- 验证思路
- 把题目要求先完整覆盖起来

### 第二阶段：使用 Cursor 做整理、收敛和重构

在整体结构跑通之后，我再使用 **Cursor** 对实现做进一步整理和收敛，让最终代码更符合题目要求，也更适合作为交付版本。

这一阶段主要集中在以下几件事：

- 对照 `issue.md` 逐条检查，确认实现是否真正满足要求
- 收敛和清理相对 `main` 的无关改动，尽量减少多余 diff
- 将原本的 Python 类 Skill 逐步替换为目录式 markdown Skill
- 把 Skill 定义统一整理成更清晰的 schema 形式
- 调整 CLI 启动方式，使其更接近原仓使用习惯
- 补充和修正文档，包括：
  - `DESIGN.md`
  - `EVALUATION.md`
  - `README.md`
- 增加示例任务，方便直接演示需求整理、分析生成和比较决策三类任务

简单来说，Cursor 阶段更偏向于：

- 做细节打磨
- 做结构收敛
- 对齐交付要求
- 提升可读性和可演示性

## 最终结果

最后形成的是一个基于 `mini-coding-agent` 演化出来的多 Skill Agent 原型，具备以下能力：

- 显式区分 Skill 和 Tool
- 使用目录式 markdown Skill 定义 skill schema
- 具备 Skill Router / Skill Selection
- 支持至少三类任务
- 具备 Trace / 可观测性
- 具备 ask-back 和 verify/retry 等失败处理机制
- 保留了原始 CLI 风格，同时新增了 skill-centric runtime

## 总结

整个开发过程可以概括为：

- **Codex** 负责把大框架和核心能力先搭起来
- **Cursor** 负责对照题目要求做收敛、重构和最终整理

这样的协作方式让我可以先快速完成可运行版本，再逐步把实现打磨成更符合评测要求的最终交付。 
