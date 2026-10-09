# Agent 范式精华技术文档系列实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 生成一个学习索引和 11 篇 Agent 范式精华技术文档，使读者能通过理论、原生语言代码、项目横向对比和方法论抽象在 20–30 分钟内掌握每个范式。

**Architecture:** 文档按范式拆分，每篇遵循相同教学接口，使用一个主项目的原生语言代码作为核心证据，并用 4–7 个项目做范式特定比较。README 负责术语、依赖、学习路线和项目映射；现有项目筛选报告继续承担项目背景介绍。

**Tech Stack:** Markdown、Mermaid/文本流程图、Python/TypeScript/Rust 代码片段、官方 GitHub 仓库与官方文档的定向核验、`rg`/shell Markdown 结构校验。

**Spec:** `docs/superpowers/specs/2026-08-30-agent-paradigms-learning-series-design.md`

**Execution Status:** Complete（2026-08-30）。README 与 11 篇正文均已生成；逐篇审核、官方来源抽查、系列终审和本地可重复验收均已完成。最终验收命令见 `.superpowers/sdd/2026-08-30-agent-paradigms-learning-series/verify-series.zsh`。

## Global Constraints

- 不使用 deep-research 工作流。
- 只使用官方仓库、官方文档和具体源码路径核验技术事实。
- 每篇约 20–30 分钟阅读量，优先保留关键机制而不是功能大全。
- 每篇必须有理论/理念、语言无关伪代码、代表项目原生语言代码、项目横向对比、方法论、练习、自测和边界。
- 原生代码片段一般不超过 60 行；教学等价代码必须明确标注，不伪装成源码摘录。
- 统一区分 Agent、Harness、Runtime、Product，以及 history、context、checkpoint、memory。
- 当前目录没有 Git 元数据，任务使用逐篇验证检查点，不执行 commit。
- 正文 Task 2–12 使用本地 Claude Code CLI 子 Agent，显式指定 Anthropic Claude 模型。
- 子 Agent 只可使用 Read、Write、WebSearch、WebFetch；禁止 Bash，且只能修改分配给它的唯一文档文件。
- Task 2–12 可并行执行，因为它们不共享输出文件；Task 1 的 README 延后到正文完成后生成，Task 13 统一审核整合。

## Execution Mode

本计划采用本地 Claude Code CLI 作为隔离子 Agent。每个子 Agent 从任务 brief、设计规格和现有项目筛选报告获得完整上下文，通过定向官方资料核验后写入唯一目标文件。控制器负责批次调度、逐篇结构检查、事实抽查、修订和最终系列审阅。

为了避免共享文件冲突：

- 正文文件 01–11 分四个批次并行生成；
- README 不与正文并行写入；
- 子 Agent 不修改设计规格、实施计划、现有研究报告或其他范式文档；
- 审阅 Agent 只输出报告，不直接修改文件；修订由原实现 Agent 依据审阅意见完成。

---

### Task 1: 创建系列骨架与学习索引

**Files:**
- Create: `agent-paradigms/README.md`
- Create: `agent-paradigms/01-极简-Agent-Loop.md`
- Create: `agent-paradigms/02-Action-Model.md`
- Create: `agent-paradigms/03-Workspace与Runtime隔离.md`
- Create: `agent-paradigms/04-权限审批与Sandbox.md`
- Create: `agent-paradigms/05-上下文装配压缩与外置.md`
- Create: `agent-paradigms/06-Durable-State与恢复.md`
- Create: `agent-paradigms/07-长期记忆与程序性技能.md`
- Create: `agent-paradigms/08-子Agent委派与上下文隔离.md`
- Create: `agent-paradigms/09-Gateway-Heartbeat与Scheduler.md`
- Create: `agent-paradigms/10-可观测性回放与评测.md`
- Create: `agent-paradigms/11-领域观察行动接口.md`

**Interfaces:**
- Consumes: 设计规格和 `开源-Agent-Harness-项目梳理-2026-08.md` 中的 11 类范式。
- Produces: 稳定的文件名、统一术语、三条学习路线和供后续任务填充的章节结构。

- [ ] **Step 1: 创建目录和 12 个 Markdown 文件**

使用 `apply_patch` 创建文件。每篇预置且仅预置以下正式标题，不写 `TBD`：

```markdown
# [范式名称]
## 1. 一句话掌握
## 2. 为什么需要它
## 3. 最小概念模型
## 4. 关键设计决策
## 5. 代表项目代码解读
## 6. 热门项目横向对比
## 7. 方法论抽象
## 8. 实践练习
## 9. 掌握检查
## 10. 边界与延伸阅读
```

- [ ] **Step 2: 编写 README 学习地图**

README 必须包含：

- Agent/Harness/Runtime/Product 四层术语；
- 11 篇相对链接；
- 默认、快速、Coding Agent、长期 Agent 四条路线；
- 范式依赖图；
- 项目—范式矩阵；
- “如何使用单篇文档”的阅读方法；
- 指向 `../开源-Agent-Harness-项目梳理-2026-08.md` 的背景链接。

- [ ] **Step 3: 校验文件骨架**

Run:

```bash
find agent-paradigms -maxdepth 1 -name '*.md' | wc -l
```

Expected: `12`

Run:

```bash
rg -L '^## 10\. 边界与延伸阅读$' agent-paradigms/[0-9][0-9]-*.md
```

Expected: no output.

---

### Task 2: 编写极简 Agent Loop

**Files:**
- Modify: `agent-paradigms/01-极简-Agent-Loop.md`

**Interfaces:**
- Consumes: mini-SWE-agent 的默认 Agent loop、消息轨迹和 budget 机制。
- Produces: 后续 Action Model、Context、Durability 文档共同依赖的 loop/state/step/stop 术语。

- [ ] **Step 1: 定向核验主项目**

核验 mini-SWE-agent 官方 README、`src/minisweagent/agents/default.py`、model/environment 接口和 interactive approval 入口。记录访问日期和源码链接。

- [ ] **Step 2: 完成理论与最小模型**

解释 ReAct、闭环控制、策略与环境、trajectory，以及 loop 的最小状态：

```text
RunState = {messages, step_count, cost, deadline, status}
```

伪代码必须展示 model call、action parse、environment execute、observation append、budget/stop check。

- [ ] **Step 3: 添加 Python 代码佐证**

用不超过 60 行的 Python 等价代码解释 mini-SWE-agent 的线性 loop、Bash action 和三类 budget；明确指出哪些是教学简化。

- [ ] **Step 4: 完成项目对比与方法论**

比较 mini-SWE-agent、Pi、Codex、OpenHands 在 loop 表示、状态载体、停止条件、错误反馈和可恢复性上的差异。提炼“先证明最小闭环，再增加状态和控制面”的演化方法。

- [ ] **Step 5: 运行单篇检查**

Run:

```bash
rg -n 'ReAct|RunState|step_count|mini-SWE-agent|Python|横向对比|实践练习|自测' agent-paradigms/01-极简-Agent-Loop.md
```

Expected: all concepts appear.

---

### Task 3: 编写 Action Model

**Files:**
- Modify: `agent-paradigms/02-Action-Model.md`

**Interfaces:**
- Consumes: Task 2 的 loop 和 observation 概念。
- Produces: ToolCall/ToolResult/ErrorEnvelope 术语，供权限、可观测性和领域接口文档复用。

- [ ] **Step 1: 定向核验主项目**

核验 Pi 的 agent core、read/write/edit/bash 工具与 tool-call 数据流；同时核验 Codex、mini-SWE-agent、当前/经典 Open Interpreter 的行动表达。

- [ ] **Step 2: 完成理论与决策空间**

解释 affordance、action space、typed tool、code-as-action、shell-as-action，以及工具粒度、组合性、验证成本和安全面的关系。

- [ ] **Step 3: 添加 TypeScript 代码佐证**

以 Pi 风格给出 Tool schema、dispatch、结构化成功/错误返回代码；伪代码展示模型输出到 ToolResult 再回到 loop 的完整路径。

- [ ] **Step 4: 完成横向对比**

按行动表达、组合能力、schema 约束、错误语义、并发、可审计性和安全边界比较 Pi、mini-SWE-agent、Codex、Open Interpreter、Agent Zero。

- [ ] **Step 5: 运行单篇检查**

Run: `rg -n 'affordance|typed tool|code-as-action|shell-as-action|ToolResult|TypeScript|Agent Zero' agent-paradigms/02-Action-Model.md`

Expected: all concepts appear.

---

### Task 4: 编写 Workspace 与 Runtime 隔离

**Files:**
- Modify: `agent-paradigms/03-Workspace与Runtime隔离.md`

**Interfaces:**
- Consumes: Action Model 的 ToolResult。
- Produces: Workspace、Executor、Conversation/Event 边界，供权限与恢复文档复用。

- [ ] **Step 1: 定向核验 OpenHands SDK**

核验 Agent、Conversation、Event、Workspace、Tool、Agent Server 的官方源码入口，以及 local/container/Kubernetes workspace 描述。

- [ ] **Step 2: 完成理论模型**

解释 control plane/data plane、capability boundary、位置透明性和 side-effect ownership。给出 Agent→Conversation→Workspace→Executor 的数据流。

- [ ] **Step 3: 添加 Python 代码佐证**

给出 Workspace protocol 和 Local/Remote executor 的等价 Python 接口，展示 Agent 不感知部署拓扑时如何执行命令并接收结构化结果。

- [ ] **Step 4: 完成横向对比**

比较 OpenHands、Codex、Agent Zero、DeerFlow 在 workspace 生命周期、隔离级别、文件同步、进程模型和远程执行上的差异。

- [ ] **Step 5: 运行单篇检查**

Run: `rg -n 'control plane|data plane|Workspace|Executor|Conversation|OpenHands|Kubernetes|Python' agent-paradigms/03-Workspace与Runtime隔离.md`

Expected: all concepts appear.

---

### Task 5: 编写权限、审批与 Sandbox

**Files:**
- Modify: `agent-paradigms/04-权限审批与Sandbox.md`

**Interfaces:**
- Consumes: ToolCall 和 Workspace boundary。
- Produces: PolicyDecision、ApprovalRequest、CapabilitySet 模型，供常驻 Agent 和领域接口文档复用。

- [ ] **Step 1: 定向核验 Codex**

核验 Codex Rust 中 exec policy、approval、sandbox、workspace trust 和命令执行相关源码/协议；仅把子 Agent 能力描述为委派、并行、生命周期与汇总。

- [ ] **Step 2: 完成安全理论**

解释 reference monitor、least privilege、default deny、capability security、confused deputy 和 prompt 不是安全边界。

- [ ] **Step 3: 添加 Rust 代码佐证**

用 Rust enum/trait 展示 `Allow | Deny | Ask`、审批请求和 sandbox profile 选择；代码必须包含拒绝与错误路径。

- [ ] **Step 4: 完成横向对比**

比较 Codex、Cline、OpenCode、Gemini CLI、Pi 在审批粒度、workspace trust、文件/命令/网络限制、默认策略和外部 sandbox 依赖上的差异。

- [ ] **Step 5: 运行单篇检查**

Run: `rg -n 'reference monitor|least privilege|Allow|Deny|Ask|Rust|Codex|Pi' agent-paradigms/04-权限审批与Sandbox.md`

Expected: all concepts appear.

---

### Task 6: 编写上下文装配、压缩与外置

**Files:**
- Modify: `agent-paradigms/05-上下文装配压缩与外置.md`

**Interfaces:**
- Consumes: messages、ToolResult、workspace file。
- Produces: ContextCompiler、CompactionPolicy、ContextArtifact 模型。

- [ ] **Step 1: 定向核验 Letta Code**

核验 Letta Code 的 MemFS、context compilation、recall、compaction、reflection/dreaming 相关官方源码；对照 Pi、Codex、DeerFlow、OpenClaw。

- [ ] **Step 2: 完成理论模型**

解释 context window 是编译产物而非数据库，区分 source of truth、working set、cache、summary 和 externalized artifact。

- [ ] **Step 3: 添加 TypeScript 代码佐证**

用 TypeScript 展示按优先级和 token budget 组装 system/project/history/tool/memory，触发 compaction 并保留恢复指针。

- [ ] **Step 4: 完成横向对比**

比较 Letta Code、Pi、Codex、DeerFlow、OpenClaw 的装配单位、压缩触发、外置介质、恢复线索和记忆耦合方式。

- [ ] **Step 5: 运行单篇检查**

Run: `rg -n 'ContextCompiler|working set|source of truth|compaction|MemFS|TypeScript|token budget' agent-paradigms/05-上下文装配压缩与外置.md`

Expected: all concepts appear.

---

### Task 7: 编写 Durable State、Checkpoint 与恢复

**Files:**
- Modify: `agent-paradigms/06-Durable-State与恢复.md`

**Interfaces:**
- Consumes: loop state、event、workspace side effect。
- Produces: checkpoint、interrupt/resume、idempotency key、pending work 模型。

- [ ] **Step 1: 定向核验 OpenHands 与 LangGraph**

核验 OpenHands local conversation 的取消、stuck detection、state lock、event 与 server；对照 LangGraph checkpoint/interrupt、Codex session resume、Cline checkpoint。

- [ ] **Step 2: 完成理论模型**

解释 durable execution、event sourcing、checkpoint、write-ahead intent、幂等、at-least-once 与 exactly-once 幻觉。

- [ ] **Step 3: 添加 Python 代码佐证**

给出 checkpointed run loop：在副作用前持久化 intent，执行后记录 result，恢复时依据 idempotency key 去重。

- [ ] **Step 4: 完成横向对比**

比较 OpenHands、LangGraph、Codex、Cline 在保存粒度、中断语义、副作用恢复、人工审批等待和进程重启上的差异。

- [ ] **Step 5: 运行单篇检查**

Run: `rg -n 'durable execution|event sourcing|checkpoint|idempotency|pending work|OpenHands|LangGraph|Python' agent-paradigms/06-Durable-State与恢复.md`

Expected: all concepts appear.

---

### Task 8: 编写长期记忆与程序性技能

**Files:**
- Modify: `agent-paradigms/07-长期记忆与程序性技能.md`

**Interfaces:**
- Consumes: ContextCompiler 和 durable state。
- Produces: MemoryItem、SkillArtifact、write/recall/consolidate policy。

- [ ] **Step 1: 定向核验 Letta Code、Hermes、OpenClaw**

核验 Letta Code 的 memory/MemFS/reflection，Hermes 的 skill 生成与迭代，OpenClaw 的 skills/memory 机制；对照 DeerFlow。

- [ ] **Step 2: 完成理论模型**

解释 episodic/semantic/procedural memory、consolidation、retrieval、forgetting、provenance 和 memory poisoning。

- [ ] **Step 3: 添加 TypeScript 代码佐证**

用 TypeScript 展示带 provenance/confidence/expiry 的记忆写入与召回，以及将重复成功轨迹提炼为版本化 SkillArtifact。

- [ ] **Step 4: 完成横向对比**

比较 Letta Code、Hermes、OpenClaw、DeerFlow 在存储对象、写入主体、召回方式、技能格式、版本化和审计上的差异。

- [ ] **Step 5: 运行单篇检查**

Run: `rg -n 'episodic|semantic|procedural|consolidation|provenance|memory poisoning|SkillArtifact|TypeScript' agent-paradigms/07-长期记忆与程序性技能.md`

Expected: all concepts appear.

---

### Task 9: 编写子 Agent 委派与上下文隔离

**Files:**
- Modify: `agent-paradigms/08-子Agent委派与上下文隔离.md`

**Interfaces:**
- Consumes: ContextCompiler、CapabilitySet、checkpoint。
- Produces: DelegationContract、ChildBudget、ResultEnvelope、fan-out/fan-in 模型。

- [ ] **Step 1: 定向核验 Hermes 与对照项目**

核验 Hermes 子 Agent、任务传递与汇总；对照 OpenHands、DeerFlow、OpenCode、goose、Codex 的委派与并行能力。

- [ ] **Step 2: 完成理论模型**

解释 delegation vs handoff vs agent-as-tool，结构化并发、上下文隔离、预算隔离、取消传播和部分失败。

- [ ] **Step 3: 添加 Python 代码佐证**

用 Python dataclass/async 展示 DelegationContract、子上下文构造、并行执行、超时取消和父级聚合。

- [ ] **Step 4: 完成横向对比**

比较 Hermes、OpenHands、DeerFlow、OpenCode、goose、Codex 在触发方式、隔离边界、并行、预算、汇总和失败处理上的差异。

- [ ] **Step 5: 运行单篇检查**

Run: `rg -n 'delegation|handoff|agent-as-tool|structured concurrency|DelegationContract|部分失败|Python' agent-paradigms/08-子Agent委派与上下文隔离.md`

Expected: all concepts appear.

---

### Task 10: 编写 Gateway、Heartbeat 与 Scheduler

**Files:**
- Modify: `agent-paradigms/09-Gateway-Heartbeat与Scheduler.md`

**Interfaces:**
- Consumes: session identity、CapabilitySet、durable state。
- Produces: EventEnvelope、SessionRoute、HeartbeatPolicy、ScheduledJob 模型。

- [ ] **Step 1: 定向核验 OpenClaw**

核验 OpenClaw session routing、gateway、heartbeat 和 cron 官方文档/源码；对照 Hermes 和 goose recipe scheduler。

- [ ] **Step 2: 完成理论模型**

区分 event-driven、polling heartbeat、cron、scheduler、queue consumer；解释幂等投递、租约、去重、背压和身份路由。

- [ ] **Step 3: 添加 TypeScript 代码佐证**

用 TypeScript 展示 EventEnvelope 路由、session key、heartbeat lease 和 scheduled job 去重；必须包含重复投递处理。

- [ ] **Step 4: 完成横向对比**

比较 OpenClaw、Hermes、goose 在主动循环、定时任务、渠道接入、会话隔离、通知和恢复上的差异，明确 goose 更偏 scheduler/recipe automation。

- [ ] **Step 5: 运行单篇检查**

Run: `rg -n 'event-driven|heartbeat|cron|scheduler|backpressure|EventEnvelope|OpenClaw|TypeScript' agent-paradigms/09-Gateway-Heartbeat与Scheduler.md`

Expected: all concepts appear.

---

### Task 11: 编写可观测性、回放与评测

**Files:**
- Modify: `agent-paradigms/10-可观测性回放与评测.md`

**Interfaces:**
- Consumes: trajectory、event、ToolResult、checkpoint、artifact。
- Produces: TraceEvent、FailureTaxonomy、EvalCase 和 replay contract。

- [ ] **Step 1: 定向核验 OpenHands 与对照项目**

核验 OpenHands Event/Conversation 可观测入口；对照 Codex protocol/event、LangGraph tracing/checkpoint、PydanticAI eval。

- [ ] **Step 2: 完成理论模型**

解释 logs/metrics/traces、trajectory、causal replay、deterministic assertion、LLM judge、offline/online eval 和 failure taxonomy。

- [ ] **Step 3: 添加 Python 代码佐证**

用 Python 展示统一 TraceEvent、工具 span、token/cost 统计、可重放输入和结构化 EvalCase；明确不可确定性来源。

- [ ] **Step 4: 完成横向对比**

比较 OpenHands、Codex、LangGraph、PydanticAI 在事件模型、trace 粒度、replay、eval、成本和隐私上的差异。

- [ ] **Step 5: 运行单篇检查**

Run: `rg -n 'logs|metrics|traces|trajectory|causal replay|FailureTaxonomy|EvalCase|Python' agent-paradigms/10-可观测性回放与评测.md`

Expected: all concepts appear.

---

### Task 12: 编写领域观察—行动接口

**Files:**
- Modify: `agent-paradigms/11-领域观察行动接口.md`

**Interfaces:**
- Consumes: Action Model、ToolResult、CapabilitySet、TraceEvent。
- Produces: Observation、Action、Transition、DomainError 契约。

- [ ] **Step 1: 定向核验 browser-use**

核验 browser-use 的页面观察、DOM/视觉状态、动作、浏览器状态、认证和失败恢复入口；对照 Codex/Aider 的代码库环境与 Agent Zero 的桌面环境。

- [ ] **Step 2: 完成理论模型**

解释 POMDP、state representation、grounding、action affordance、closed-loop correction 和 domain-specific failure。

- [ ] **Step 3: 添加 Python 代码佐证**

用 Python protocol/dataclass 展示 Observation→Policy→Action→Transition，包含 stale element、navigation、authentication 等结构化错误。

- [ ] **Step 4: 完成横向对比**

比较 browser-use、Codex、Aider、Agent Zero 在观察表示、动作空间、状态持久化、反馈延迟、认证和领域失败恢复上的差异。

- [ ] **Step 5: 运行单篇检查**

Run: `rg -n 'POMDP|grounding|affordance|Observation|Transition|DomainError|browser-use|Python' agent-paradigms/11-领域观察行动接口.md`

Expected: all concepts appear.

---

### Task 13: 系列整合、事实检查与读者测试

**Files:**
- Modify: `agent-paradigms/README.md`
- Modify: `agent-paradigms/01-极简-Agent-Loop.md`
- Modify: `agent-paradigms/02-Action-Model.md`
- Modify: `agent-paradigms/03-Workspace与Runtime隔离.md`
- Modify: `agent-paradigms/04-权限审批与Sandbox.md`
- Modify: `agent-paradigms/05-上下文装配压缩与外置.md`
- Modify: `agent-paradigms/06-Durable-State与恢复.md`
- Modify: `agent-paradigms/07-长期记忆与程序性技能.md`
- Modify: `agent-paradigms/08-子Agent委派与上下文隔离.md`
- Modify: `agent-paradigms/09-Gateway-Heartbeat与Scheduler.md`
- Modify: `agent-paradigms/10-可观测性回放与评测.md`
- Modify: `agent-paradigms/11-领域观察行动接口.md`

**Interfaces:**
- Consumes: Tasks 1–12 的完整文档。
- Produces: 定义一致、链接有效、可按路线学习的最终系列。

- [ ] **Step 1: 统一术语与交叉引用**

逐篇检查 Agent/Harness/Runtime/Product、history/context/checkpoint/memory、handoff/delegation/agent-as-tool、heartbeat/cron/scheduler 的定义。首次出现时链接到 README 术语表或前置篇章。

- [ ] **Step 2: 核验项目事实与源码链接**

逐篇检查主项目语言、仓库路径、功能描述和版本日期。删除不能由官方材料支持的确定性表述，将分析性内容标成“方法论推断”。

- [ ] **Step 3: 运行系列结构检查**

Run:

```bash
find agent-paradigms -maxdepth 1 -name '*.md' | wc -l
```

Expected: `12`

Run:

```bash
rg -L '^## 1\. 一句话掌握$' agent-paradigms/[0-9][0-9]-*.md
```

Expected: no output.

Run:

```bash
rg -L '^## 10\. 边界与延伸阅读$' agent-paradigms/[0-9][0-9]-*.md
```

Expected: no output.

Run:

```bash
rg -n 'TBD|TODO|\[To be written\]|\[Content here\]' agent-paradigms
```

Expected: no output.

- [ ] **Step 4: 检查 Markdown 围栏与内部链接**

对每个文件用 `awk` 检查代码围栏成对；提取 README 的相对链接并用 `test -e` 验证目标存在。

- [ ] **Step 5: 进行读者问题测试**

用以下问题逐篇自测并记录缺口：

1. 这个范式解决的核心矛盾是什么？
2. 最小状态和控制流是什么？
3. 代表项目用什么设计证明了它？
4. 不同项目的分歧来自什么约束？
5. 如何从最小实现演进到生产实现？
6. 最常见的失败和安全边界是什么？
7. 读者能否在 30–60 分钟内完成练习？

发现无法仅凭文档回答的问题时，回到对应篇章补充，而不是在 README 堆叠解释。

- [ ] **Step 6: 最终验收**

确认每篇包含至少一个伪代码块、一个原生语言代码块、一个项目对比表、一个练习和三个自测问题。报告总文件数、总行数、各篇主项目和所有验证命令结果。
