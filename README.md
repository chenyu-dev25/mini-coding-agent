# Mini-Coding-Agent

本仓库包含 **两套可运行入口**，阅卷时请按需选用：

| 入口 | 命令 | 用途 |
|------|------|------|
| **Skill 多 Skill 原型**（本题主交付） | `uv run mini-coding-agent` | Skill Router、多步流水线、Trace、`app.py` |
| **原版最小 Agent**（rasbt 单循环 + 工具 + 会话） | `uv run python mini_coding_agent.py` 或 `python mini_coding_agent.py` | 工作区快照、工具循环、审批、`--resume` 会话 |

下文 **优先说明 Skill 入口**；原版行为见后文「原版 harness」一节。

---

## Skill 运行时：安装与运行（推荐先看）

### 依赖

- Python **3.10+**
- 推荐使用 **[uv](https://github.com/astral-sh/uv)** 安装依赖（`pyproject.toml` 含 `pydantic`、`rich` 等）
- 模型后端任选其一：
  - **Ollama**（默认）：本机 `ollama serve`，并 `ollama pull qwen3.5:4b`（或更大模型）
  - **Moonshot**：`export MOONSHOT_API_KEY=...`，启动时 `--provider moonshot`

### 安装

```bash
cd mini-coding-agent
uv sync
```

### 交互 REPL（最常用）

```bash
uv run mini-coding-agent
```

- 默认：**直连聊天**；仅当强意图（如「分析 / 比较 / 需求整理」）、`/pipeline`、`--skill-pipeline` 或 `must_include` 等条件满足时才走多 Skill 流水线。
- **录屏 / 展示 Trace**：`uv run mini-coding-agent --trace`，或在 REPL 内输入 `/trace` 切换。
- **仅回答、不要终端颜色**：`--no-ansi`
- **不要分步进度行**：`--no-progress`
- **不要欢迎横幅**：`--no-banner`
- **工作区根目录**（读 `README.md` / `issue.md` 等）：`--root .`（默认即为当前目录）

REPL 内命令：`/skills` 查看说明；`/list-skills`；`/pipeline` / `/direct`；`/exit` 或 `quit` 退出。

### 一次性命令（脚本/CI）

```bash
# 只打印最终回答
uv run mini-coding-agent run --task "比较 pytest vs unittest，并给出推荐理由"

# 打印完整 trace（含每步摘要；非 REPL 下默认带 Final result）
uv run mini-coding-agent trace --task "分析 README.md 和 issue.md，然后给我一个方案，必须包含 Analysis 和 Testing 两节"

# 从 JSON 读 task（见 examples/skill_tasks/）
uv run mini-coding-agent trace --task-file examples/skill_tasks/comparison_task.json

# 列出 Skill schema
uv run mini-coding-agent schemas
uv run mini-coding-agent schemas --json
```

### Moonshot 示例

```bash
export MOONSHOT_API_KEY=your_key
uv run mini-coding-agent --provider moonshot --model kimi-k2.5 run --task "你好"
```

### 支持的任务类型（与评测题对应）

1. **需求整理型**：如「差不多」「整理需求」「规划」→ 多走 `planning`（必要时 `ask_back`）。
2. **分析生成型**：如「分析 README.md…」→ `analysis → generation → verification`。
3. **比较决策型**：如「比较 A vs B」→ `comparison → generation → verification`。

自然语言「你有哪些 skill」等为 **目录查询**，由 LLM 直接回答，不走路由流水线。

### Skill 列表（运行时）

| Skill | 作用概要 |
|-------|----------|
| `planning` | 澄清需求、结构化目标/约束/交付物 |
| `analysis` | 读仓库片段，产出观察与风险 |
| `comparison` | 多选项对比与推荐（JSON 结构化） |
| `generation` | 汇总上游结果，生成用户可见 Markdown |
| `verification` | 对照约束与章节做检查；失败可触发重写 |
| `ask_back` | 信息不足时生成追问 |

每个 Skill 的 **schema** 见 `skills/<name>/SKILL.md`；聚合定义可通过 `schemas` 子命令查看。

### 仓库结构（Skill 相关）

```text
app.py                 # Skill CLI 入口
executor/              # SkillAgent、fallback、retry、TraceRecord
router/                # 规则路由与任务分类
models/                # Schema、Ollama/Moonshot 客户端
skills/                # 目录式 SKILL.md + base.py 执行适配
tools/                 # 底层 Tool（读文件、shell 等）
trace_renderer.py      # 人类可读 trace 渲染
markdown_console.py    # 终端 Markdown（Rich）
DESIGN.md              # 设计说明（含 issue 九问）
BUILD_LOG.md           # 构建与 AI 协作记录
EVALUATION.md          # 自评与验收说明
examples/skill_tasks/  # 示例 task JSON
```

### 示例输入/输出

- 命令行：`run` / `trace` 见上文。
- JSON：`examples/skill_tasks/requirement_task.json`、`analysis_task.json`、`comparison_task.json`。
- 更长的交互 walkthrough 仍可参考 [EXAMPLE.md](EXAMPLE.md)（偏原版 Agent；Skill REPL 说明以本节为准）。

---

## 原版 harness（mini_coding_agent.py）

以下描述对应 **`mini_coding_agent.py`**：单 Agent 循环、工具调用、会话持久化，**不是** `app.py` 的 Skill 流水线。

- **Live repo context**、**Prompt shape**、**Structured tools**、**Context reduction**、**Transcripts/memory**、**Delegation** 等设计要点仍适用于原版；图示与长文教程见下。

<a href="https://magazine.sebastianraschka.com/p/components-of-a-coding-agent">
  <img src="https://substack-post-media.s3.amazonaws.com/public/images/49b97718-57f4-4977-99c8-8ad5c4d32af3_1548x862.png" width="500px">
</a>

<br>

**[The detailed tutorial: Components of a Coding Agent](https://magazine.sebastianraschka.com/p/components-of-a-coding-agent)**

&nbsp;
## Six Core Components（原版）

<a href="https://magazine.sebastianraschka.com/p/components-of-a-coding-agent">
  <img alt="Six core components of a coding agent" src="https://sebastianraschka.com/images/github/mini-coding-agent/six-components.webp" width="500px">
</a>

1. **Live repo context** — workspace、说明文件、git 状态等。
2. **Prompt shape and cache reuse** — 稳定前缀与可变对话分离。
3. **Structured tools, validation, and permissions** — 命名工具、路径校验、审批。
4. **Context reduction and output management** — 裁剪与压缩。
5. **Transcripts, memory, and resumption** — 会话与恢复。
6. **Delegation and bounded subagents** — 有界子 Agent。

&nbsp;
## Requirements

- Python 3.10+
- **Skill 入口**：按上文执行 `uv sync`；模型见 Ollama 或 Moonshot。
- **原版入口**：需要 Ollama；可直接 `python mini_coding_agent.py`，亦可用 `uv run python mini_coding_agent.py`。

&nbsp;
## Install Ollama

Install Ollama: [ollama.com/download](https://ollama.com/download)

```bash
ollama serve
ollama pull qwen3.5:4b
```

更多 Qwen 模型：[ollama.com/library/qwen3.5](https://ollama.com/library/qwen3.5)

&nbsp;
## Project Setup

```bash
git clone <your-fork-or-upstream-url>
cd mini-coding-agent
uv sync
```

&nbsp;
## 原版 Basic Usage

```bash
cd mini-coding-agent
uv run python mini_coding_agent.py
```

或：

```bash
python mini_coding_agent.py
```

默认示例：`--model qwen3.5:4b`、`--approval ask`。详细步骤见 [EXAMPLE.md](EXAMPLE.md)。

&nbsp;
## 原版 Approval Modes

- `--approval ask`（默认）
- `--approval auto`（高风险，仅可信环境）
- `--approval never`

```bash
uv run python mini_coding_agent.py --approval auto
```

&nbsp;
## 原版 Resume Sessions

会话目录：`.mini-coding-agent/sessions/`

```bash
uv run python mini_coding_agent.py --resume latest
uv run python mini_coding_agent.py --resume 20260401-144025-2dd0aa
```

&nbsp;
## 原版 Interactive Commands

在 **`mini_coding_agent.py`** 的 REPL 中：`/skills`、`/memory`、`/session`、`/reset`、`/exit`。

**Skill** 入口 `uv run mini-coding-agent` 的斜杠命令见上文「Skill 运行时」及 REPL 内 `/skills`。

&nbsp;
## 原版 Main CLI Flags

```bash
uv run python mini_coding_agent.py --help
```

常用：`--cwd`、`--model`、`--host`、`--ollama-timeout`、`--resume`、`--approval`、`--max-steps`、`--max-new-tokens`、`--temperature`、`--top-p`。

**Skill 入口**请使用：

```bash
uv run mini-coding-agent --help
```

主要参数：`--root`、`--provider`、`--model`、`--host`、`--timeout`、`--must-include`、`--skill-pipeline`、`--trace`、`--no-banner`、`--no-ansi`、`--no-progress`，以及子命令 `run` / `trace` / `schemas`。

&nbsp;
## Example

见 [EXAMPLE.md](EXAMPLE.md)（偏原版流程）。Skill 示例任务见 `examples/skill_tasks/*.json`。

&nbsp;
## Notes & Tips（原版行为）

- 原版 Agent 期望模型输出 `<tool>...</tool>` 或 `<final>...</final>`。
- 不同 Ollama 模型遵循指令的稳定度不同；可换更强指令遵循模型。
- Skill 运行时无此 XML 协议，由 `SkillAgent` + 各 skill 内 LLM 调用组织。
