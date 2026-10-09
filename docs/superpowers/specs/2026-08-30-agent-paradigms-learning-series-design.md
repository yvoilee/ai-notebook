# Agent 范式精华技术文档系列设计

## 1. 目标

基于现有《开源 Agent / Agent Harness 项目梳理与研究路线》中提炼的 11 类范式，构建一套可独立阅读、可交叉检索、可持续更新的中文技术文档。

读者应能在每篇约 20–30 分钟内：

- 建立该范式的理论模型和工程直觉；
- 理解关键组件、状态和控制流；
- 通过代表项目的原生语言代码掌握核心设计；
- 比较热门项目在相同问题上的不同取舍；
- 把项目实现提升为可迁移的方法论；
- 判断该范式何时适用、如何落地、如何验证。

## 2. 受众与假设

主要受众是具备软件工程和基础 LLM 应用经验、希望系统学习 Agent Harness 的工程师或架构师。

文档不要求读者预先熟悉具体项目，但假设读者：

- 能阅读 Python、TypeScript 或 Rust 的短代码片段；
- 理解模型调用、消息、工具调用和 JSON Schema 等基础概念；
- 关注真实系统中的可靠性、安全性和可维护性，而不只关注 Demo 效果。

## 3. 交付结构

创建目录 `agent-paradigms/`，包含一个总览和 11 篇范式文档：

```text
agent-paradigms/
├── README.md
├── 01-极简-Agent-Loop.md
├── 02-Action-Model.md
├── 03-Workspace与Runtime隔离.md
├── 04-权限审批与Sandbox.md
├── 05-上下文装配压缩与外置.md
├── 06-Durable-State与恢复.md
├── 07-长期记忆与程序性技能.md
├── 08-子Agent委派与上下文隔离.md
├── 09-Gateway-Heartbeat与Scheduler.md
├── 10-可观测性回放与评测.md
└── 11-领域观察行动接口.md
```

`README.md` 负责：

- 解释 11 类范式之间的依赖关系；
- 给出快速、标准和专题三条学习路线；
- 提供统一术语表；
- 汇总项目—范式映射矩阵；
- 链接现有项目筛选报告，避免重复介绍项目背景。

每篇文档只负责一个范式，保持单一主题。

## 4. 单篇文档模板

每篇采用相同结构，以便横向阅读。

### 4.1 一句话掌握

用一条可复述的定义说明该范式解决什么问题，不使用项目营销术语。

### 4.2 为什么需要它

包含：

- 问题从何而来；
- 朴素实现为何会失败；
- 相关理论或理念；
- 该范式在 Agent Product、Harness、Runtime 中所处的位置。

### 4.3 最小概念模型

使用简洁状态机、时序或数据流表示：

- 核心对象；
- 状态变化；
- 控制权转移；
- 输入、输出和副作用。

同时给出语言无关伪代码，帮助读者先理解机制再进入项目代码。

### 4.4 关键设计决策

选择 3–5 个真正影响系统性质的决策，例如：

- 隐式循环还是显式状态机；
- 持久 Shell 还是独立进程；
- 原始历史还是编译后上下文；
- host 权限还是 sandbox capability；
- 消息 checkpoint 还是可恢复执行状态。

每个决策说明适用条件、收益、代价和失败模式。

### 4.5 代表项目代码佐证

代码遵循代表项目原生语言，选取或等价重写能证明核心设计的最短片段。

每段代码必须包含：

- 对应项目与源码路径；
- 代码在完整执行链中的位置；
- 需要关注的 2–4 个关键点；
- 哪些部分是源码事实，哪些是为教学简化的等价实现。

原则上每篇使用 1 个主项目深入说明，最多增加 1 个短对照片段。避免堆砌大量互不相干代码。

### 4.6 热门项目横向对比

每篇提供一个针对该范式的对比表，项目数量控制在 4–7 个。对比维度必须与范式相关，不复用泛化的“功能是否支持”表。

对比结果分成：

- 共同收敛的设计；
- 仍有分歧的设计；
- 项目特有但不可盲目迁移的设计。

### 4.7 方法论抽象

将项目实现提升为可迁移规则：

- 设计原则；
- 决策顺序；
- 可观察的不变量；
- 可复用接口或数据模型；
- 从最小实现演化到生产实现的路径。

### 4.8 实践与掌握检查

包含：

- 一个 30–60 分钟可完成的最小练习；
- 3–5 个自测问题；
- 生产落地检查清单；
- 常见误区和不适用边界。

## 5. 范式、主项目与代码语言

| # | 范式 | 主项目/语言 | 重点对照项目 |
|---:|---|---|---|
| 1 | 极简 Agent Loop | mini-SWE-agent / Python | Pi、Codex |
| 2 | Action Model | Pi / TypeScript | mini-SWE-agent、Codex、Open Interpreter、Agent Zero |
| 3 | Workspace 与 Runtime 隔离 | OpenHands SDK / Python | Codex、Agent Zero、DeerFlow |
| 4 | 权限、审批与 Sandbox | Codex / Rust | Cline、OpenCode、Gemini CLI、Pi |
| 5 | 上下文装配、压缩与外置 | Letta Code / TypeScript | Pi、Codex、DeerFlow、OpenClaw |
| 6 | Durable State、Checkpoint 与恢复 | OpenHands SDK / Python | Codex、LangGraph、Cline |
| 7 | 长期记忆与程序性技能 | Letta Code / TypeScript | Hermes、OpenClaw、DeerFlow |
| 8 | 子 Agent 委派与上下文隔离 | Hermes Agent / Python | OpenHands、DeerFlow、OpenCode、goose、Codex |
| 9 | Gateway、Heartbeat 与 Scheduler | OpenClaw / TypeScript | Hermes、goose |
| 10 | 可观测性、回放与评测 | OpenHands SDK / Python | Codex、LangGraph、PydanticAI |
| 11 | 领域观察—行动接口 | browser-use / Python | Codex、Aider、Agent Zero |

如果项目的核心实现语言或仓库结构在核验时发生变化，以访问时官方仓库为准，并在文档中注明。

## 6. 学习依赖与推荐顺序

默认顺序是：

```text
Loop
  → Action Model
  → Workspace/Runtime
  → Permission/Sandbox
  → Context
  → Durable State
  → Memory/Skills
  → Subagents
  → Gateway/Scheduler
  → Observability/Eval
  → Domain Interface
```

其中存在三组强依赖：

- Action Model 依赖对 Loop 和 tool feedback 的理解；
- Durable State 依赖对 Runtime state 和 side effect 的理解；
- 长期记忆、子 Agent 和常驻运行依赖对 Context、权限与恢复的理解。

README 同时提供：

- **快速路线**：1 → 4 → 5 → 6 → 8；
- **Coding Agent 路线**：1 → 2 → 3 → 4 → 6 → 10；
- **长期 Agent 路线**：1 → 5 → 6 → 7 → 8 → 9。

## 7. 证据与引用规则

- 只做面向具体问题的官方仓库、官方文档和源码定向核验。
- 技术事实优先链接到具体源码文件或官方设计文档，而不是二手文章。
- 所有项目判断注明访问基准日期。
- 快速变化的实现固定到 commit、tag 或明确的 main 分支路径。
- 项目方 benchmark 只作为项目自述，不直接推导 Harness 优劣。
- 源码摘录保持短小；较长逻辑使用等价教学代码并明确标注。
- 推断、评价和方法论必须与源码事实分开表述。

## 8. 写作与代码规范

- 中文讲解为主，关键术语首次出现时给出英文。
- 每篇优先解释状态、控制流和边界，功能列表从简。
- 代码片段一般不超过 60 行，只保留证明设计所需的逻辑。
- 代码中的错误处理、终止条件和状态变化不能用省略号隐藏。
- 统一使用 `Agent`、`Harness`、`Runtime`、`Product` 四层术语。
- 区分 message history、context window、checkpoint 和 long-term memory。
- 区分 heartbeat、cron、scheduler 和 event subscription。
- 区分 agent-as-tool、handoff、subagent delegation 和并行 fan-out。

## 9. 质量检查

每篇完成后检查：

1. 读者能否用一句话解释该范式；
2. 是否有明确的最小状态/数据模型；
3. 代码是否真正佐证核心设计，而不是展示 API 用法；
4. 横向对比是否使用了范式特定维度；
5. 方法论是否可脱离具体项目复用；
6. 是否说明失败模式、安全边界和不适用场景；
7. 是否提供可执行练习与自测问题；
8. 源码事实、教学简化和作者推断是否被清楚区分。

系列级检查：

- 11 篇无概念冲突和定义漂移；
- README 的依赖、路线和链接完整；
- 同一项目在不同篇章中的定位一致；
- 无 TBD、TODO 或空占位；
- Markdown 标题、表格、代码围栏和相对链接有效；
- 不重复大段项目背景或通用 Agent 入门内容。

## 10. 完成标准

- README 与 11 篇文档全部存在；
- 每篇可在约 20–30 分钟完成阅读；
- 每篇至少有一段原生语言代码佐证和一段语言无关伪代码；
- 每篇至少有一张范式特定的项目对比表；
- 每篇包含理论、实践、方法论、误区、练习和自测；
- 所有内部链接和 Markdown 结构通过校验；
- 文档能回答现有研究报告中对应范式的核心问题。
