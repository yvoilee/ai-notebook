# AI Agent / Agent Harness 开源项目重筛与研究路线

> 基准日期：2026-08-28  
> 目标：筛选可直接使用、又能用于系统拆解 Agent 架构和沉淀工程范式的开源项目。  
> 结论定位：这不是 GitHub 热度榜，也不是“框架大全”，而是一套可执行的源码研究样本集。

## 一、先给结论

围绕“可直接使用 + 能切入源码分析 + 能总结范式”这个目标，建议把研究对象收敛成三层：

1. **S 级核心研究集（7 个）**：mini-SWE-agent、OpenAI Agents SDK、Deep Agents、OpenHands Software Agent SDK、LangGraph、PydanticAI、Letta。
2. **A 级按专题选读（7 个）**：Google ADK、Microsoft Agent Framework、smolagents、Mastra、Cline SDK、OpenAI Codex CLI、OpenCode。
3. **B 级补充/对照（4 个）**：Agno、CrewAI、Claude Agent SDK、Aider。

同时做三项替换：

- **SWE-agent → mini-SWE-agent**：SWE-agent 官方已建议默认使用 mini-SWE-agent；旧项目保留为工具接口与历史处理器的对照样本。[官方说明](https://github.com/SWE-agent/SWE-agent)
- **AutoGen → Microsoft Agent Framework**：AutoGen 已进入 maintenance mode，官方推荐新项目使用 Microsoft Agent Framework。[AutoGen README](https://github.com/microsoft/autogen)
- **OpenAI Swarm → OpenAI Agents SDK**：Swarm 是教育性实验，Agents SDK 是其生产化继任者。[Agents SDK 文档](https://openai.github.io/openai-agents-python/)

最重要的认知调整是：**不要再把 Runtime、Harness、Framework 和 Product 放在同一条轴上比较。** LangGraph 和 Deep Agents 不是二选一；前者是状态化执行底座，后者是建立在底座上的 opinionated harness。Codex、OpenCode、Cline 则是包含 harness 的完整产品级系统。

## 二、重新定义研究对象

### 2.1 四个容易混用的概念

| 概念 | 负责什么 | 典型项目 |
|---|---|---|
| **Agent** | 目标、指令、模型、工具及决策策略构成的执行单元 | OpenAI `Agent`、PydanticAI `Agent`、ADK `LlmAgent` |
| **Agent Harness** | 把模型包进可工作的循环：上下文、工具、环境、权限、停止条件、恢复、交互 | mini-SWE-agent、Deep Agents、OpenHands SDK |
| **Agent Runtime** | 执行图、状态、事件、checkpoint、并发、调度、持久化、恢复 | LangGraph、Microsoft Agent Framework、ADK Workflow Runtime |
| **Agent Product** | 在 harness/runtime 上提供 CLI、IDE、UI、账号、分发和协作体验 | Codex CLI、OpenCode、Cline、OpenHands App |

可以把完整系统看成：

```text
Agent Product / Application
  └─ Agent Harness
       ├─ Control loop / policy
       ├─ Context + memory
       ├─ Tools + workspace + permissions
       └─ Agent composition
            └─ Agent Runtime
                 ├─ state / events / checkpoints
                 ├─ scheduling / concurrency / resume
                 └─ tracing / evaluation / operations
                      └─ Model provider + execution environment
```

这个分层直接决定源码阅读方法：分析 Deep Agents 时要继续下钻 LangChain/LangGraph；分析 Claude Agent SDK 时则必须意识到公开 SDK 主要是调用随包附带的 Claude Code CLI，完整执行 loop 并不在 SDK 仓库里。[Claude Agent SDK README](https://github.com/anthropics/claude-agent-sdk-python)

### 2.2 入选硬门槛

项目要进入当前研究池，至少满足：

1. **完整 loop**：能从用户目标出发，多轮调用模型和工具，并有明确终止语义。
2. **可以直接跑**：提供稳定的 SDK、CLI、server 或可复用应用入口，而不是论文伪代码。
3. **有可研究的开源实现**：核心 harness/runtime 逻辑有足够源代码；仅开放客户端 wrapper 的项目降级。
4. **可复用**：工具、模型、上下文或执行环境至少有一处可替换，不是单场景硬编码 Demo。
5. **维护状态明确**：仍活跃，或官方明确标记 maintenance/superseded 并只作为历史样本。
6. **许可边界清楚**：核心许可证、企业目录或服务条款可以确认。

### 2.3 评分尺度

每项 1–5 分，总分只用于同层粗排，不代表性能 benchmark：

- **U 直接使用**：安装、文档、示例、CLI/SDK 完整度。
- **L loop 透明度**：核心循环是否容易定位、理解、修改和观测。
- **H harness 完整度**：上下文、工具、环境、权限、状态、交互是否齐备。
- **X 可扩展性**：模型、工具、middleware、backend、protocol 的替换能力。
- **O 可运营性**：持久化、恢复、HITL、trace、eval、部署与多租户能力。

Stars 不进入评分。它混合了发布时间、品牌、最终用户数量和历史影响力，不能证明 harness 的架构质量。

## 三、S 级核心研究集

### 总览

| 项目 | 层 | U/L/H/X/O | 最值得研究的范式 | 为什么进入核心集 |
|---|---|---:|---|---|
| [mini-SWE-agent](https://github.com/SWE-agent/mini-swe-agent) | 最小 harness | 5/5/3/4/3 | 线性 loop、bash-only、trajectory 即 messages | 最清晰的基线和第一站 |
| [OpenAI Agents SDK](https://github.com/openai/openai-agents-python) | 通用 SDK | 5/4/4/5/4 | tool loop、handoff、guardrail、session、trace、sandbox | 小 primitives 到生产能力的平衡样本 |
| [Deep Agents](https://github.com/langchain-ai/deepagents) | 完整 harness | 5/4/5/5/5 | middleware、文件上下文、skills、subagent、backend | 当前最典型的 batteries-included harness |
| [OpenHands Software Agent SDK](https://github.com/OpenHands/software-agent-sdk) | 软件 Agent harness/runtime | 4/4/5/5/5 | event-driven conversation、workspace、local/remote | 最完整的开源软件工程 Agent SDK 样本之一 |
| [LangGraph](https://github.com/langchain-ai/langgraph) | 状态化 runtime | 3/4/4/5/5 | graph state、checkpoint、interrupt、durable execution | 研究长任务状态和恢复的基准底座 |
| [PydanticAI](https://github.com/pydantic/pydantic-ai) | 类型安全框架 | 5/4/4/5/5 | typed DI、structured output、tool scheduling、eval | 研究应用工程质量与 agent loop 结合 |
| [Letta](https://github.com/letta-ai/letta) | stateful agent 平台 | 4/3/5/4/5 | memory blocks、context window、agent identity、server persistence | 长期记忆和持续身份的专项代表 |

### 3.1 mini-SWE-agent：先建立“不可再简”的基线

官方把默认 agent class 控制在约百行 Python；只有 bash 作为动作接口，消息历史完全线性，每一步独立执行 subprocess。这使 trajectory 与送入模型的 messages 基本一致，特别适合 debugging、fine-tuning 和 RL 基线。[README](https://github.com/SWE-agent/mini-swe-agent)

源码切入：

1. [`src/minisweagent/agents/default.py`](https://github.com/SWE-agent/mini-swe-agent/blob/main/src/minisweagent/agents/default.py)：`DefaultAgent`、step/cost/time limit、messages、trajectory serialization。
2. `src/minisweagent/environments/`：把本地、Docker、远端环境压缩成 command execution 接口。
3. `src/minisweagent/models/`：模型响应如何被解析为 action。
4. [`interactive.py`](https://github.com/SWE-agent/mini-swe-agent/blob/main/src/minisweagent/agents/interactive.py)：human/confirm/yolo 三种权限模式。

应该提炼：

- “模型能力优先、harness 极简”与“复杂 scaffold 补偿模型不足”之间的边界。
- 为什么独立 command execution 比持久 shell 更容易 sandbox、扩缩容和复现。
- 线性 history 对 debug、训练和 replay 的价值。
- cost、step、wall time 三种 budget 如何成为 loop 的基础控制面。

不要照搬：仅有 bash 并不等于生产安全；它把大量正确性与安全责任转移给 sandbox 和 prompt。

### 3.2 OpenAI Agents SDK：小 primitives 的通用生产化

SDK 的基本抽象是 Agent、Tools、Agents-as-tools/Handoffs、Guardrails；当前还覆盖 HITL、Sessions、Tracing、Realtime 和 Sandbox agents。[官方 README](https://github.com/openai/openai-agents-python)

源码切入：

1. [`src/agents/run.py`](https://github.com/openai/openai-agents-python/blob/main/src/agents/run.py)：`Runner`、`AgentRunner`、run state、turn limit 和 streaming。
2. `src/agents/_run_impl.py`：模型输出解释、tool execution、handoff 与下一轮决策。
3. `src/agents/tool.py`：function/MCP/hosted tool 的统一抽象。
4. `src/agents/session/` 与 `tracing/`：跨 turn state 和可观测性。
5. `src/agents/sandbox/`：workspace manifest、sandbox client 和长任务执行。

应该提炼：

- **agent-as-tool 与 handoff 是两种不同控制权语义**：前者调用后返回父 Agent，后者转移当前会话控制权。
- guardrail 应作为 run lifecycle 的一等 hook，而不是只写进 system prompt。
- session state、provider response chaining 与本地 messages 三种历史承载方式如何取舍。
- 如何用少量公共 primitives 覆盖简单 Agent、多 Agent、语音和 sandbox Agent。

### 3.3 Deep Agents：完整 harness 的组件装配范式

Deep Agents 明确自称 batteries-included agent harness，默认提供 planning、filesystem、shell、context summarization/offload、subagents、memory、HITL、skills 和 MCP。[README](https://github.com/langchain-ai/deepagents)

最有价值的架构事实是：它不是另造 runtime，而是分层组合：

```text
Deep Agents  -> opinionated harness / middleware / backend / profiles
LangChain    -> model + tools + agent middleware
LangGraph    -> state / checkpoint / streaming / interrupts
```

这由官方[架构文档](https://github.com/langchain-ai/deepagents/blob/main/libs/ARCHITECTURE.md)明确说明。

源码切入：

1. [`libs/deepagents/deepagents/graph.py`](https://github.com/langchain-ai/deepagents/blob/main/libs/deepagents/deepagents/graph.py)：`create_deep_agent()` 装配点。
2. `middleware/filesystem.py`：工具输出如何落盘并减少上下文占用。
3. `middleware/summarization.py`：何时 compact、保留什么。
4. `middleware/subagents.py`：隔离上下文的任务委派。
5. `middleware/skills.py` 与 `memory.py`：渐进披露和跨会话状态。
6. `backends/`：local、store、sandbox 等环境差异如何被抽象。

应该提炼：

- harness 不一定是一个巨型 Agent class，可以是一组顺序敏感的 middleware。
- 文件系统既是行动空间，也是上下文外存；offload 工具结果是 context engineering 的核心机制。
- subagent 的主要价值不是“人格分工”，而是**上下文隔离、并行和预算隔离**。
- provider profile 与 harness profile 可以把模型差异收敛到配置层，而不污染业务调用点。

风险：官方安全说明采用 “trust the LLM” 模型，边界必须在 tool/sandbox 层实施，不能把 prompt 当权限系统。[安全说明](https://github.com/langchain-ai/deepagents#security)

### 3.4 OpenHands Software Agent SDK：事件、工作区和远程执行

OpenHands 将核心 agentic tech 抽成 Python/REST SDK，同一引擎支持一次性任务、维护工作、重构，以及 CLI/Cloud 产品；Agent 可以使用本机 workspace，也能运行在 Docker/Kubernetes 等临时环境。[SDK README](https://github.com/OpenHands/software-agent-sdk)

源码切入：

1. `openhands-sdk/openhands/sdk/agent/`：Agent 的 step/astep 和状态转换。
2. [`conversation/impl/local_conversation.py`](https://github.com/OpenHands/software-agent-sdk/blob/main/openhands-sdk/openhands/sdk/conversation/impl/local_conversation.py)：run loop、锁、取消、stuck detection、hooks。
3. `event/`：消息、工具、状态变化统一成事件的方式。
4. `workspace/` 与 `openhands-tools/`：本地/远程执行和工具边界。
5. `agent-server/`：把本地 conversation 提升为远程服务、stream 和并发执行。

应该提炼：

- 以 **Conversation + Event** 为中心比“把所有状态塞进 messages”更适合生产系统。
- Agent、Conversation、Workspace、Tool、Server 分离后，同一 harness 能服务本地嵌入、CLI 和云端执行。
- stop hook、stuck detector、cancellation、state lock 是长任务 loop 的基础，而不是外围功能。
- local/remote workspace 应保持同一执行语义，避免 Agent 感知部署拓扑。

许可与仓库边界：Software Agent SDK 本身是 MIT；当前官方把 SDK/Agent Server、TypeScript client、Agent Canvas 和 automation 拆到不同仓库，商业 Cloud/Enterprise 又是另一层。本报告只对 SDK/Agent Server 打分，产品与托管服务边界应在落地时另行核验。[SDK 仓库边界说明](https://github.com/OpenHands/software-agent-sdk)

### 3.5 LangGraph：状态机、持久化和可恢复执行

LangGraph 官方定位是构建长时间、状态化 Agent 的低层 orchestration framework，核心能力包括 durable execution、HITL、短期/长期 memory 和 checkpoint。[README](https://github.com/langchain-ai/langgraph)

源码切入：

1. `libs/langgraph/langgraph/graph/state.py`：StateGraph、node/edge、compile。
2. `libs/langgraph/langgraph/pregel/`：执行模型、superstep、channel update。
3. `libs/checkpoint/`：checkpoint 接口与持久化实现。
4. `libs/langgraph/langgraph/types.py`：interrupt、Command、Send 等控制对象。
5. 从一个 `create_react_agent`/`create_agent` 生成图反向追踪到 runtime。

应该提炼：

- “Agent loop” 可以表示成显式 graph，而不必藏在 `while` 中。
- checkpoint 不只是保存聊天记录，而是保存可恢复的执行状态和 pending work。
- HITL 的正确抽象是 interrupt + persisted state + resume command。
- deterministic workflow 与 agentic node 可以混合，不需要全系统都交给 LLM 决策。

### 3.6 PydanticAI：把类型系统带入 Agent 工程

PydanticAI 强调 model-agnostic、typed dependency injection、structured outputs、OTel observability、evals、HITL 和 durable execution。[README](https://github.com/pydantic/pydantic-ai)

源码切入：

1. `pydantic_ai_slim/pydantic_ai/agent/`：公共 Agent API 与 run/iter/stream 入口。
2. [`_agent_graph.py`](https://github.com/pydantic/pydantic-ai/blob/main/pydantic_ai_slim/pydantic_ai/_agent_graph.py)：`ModelRequestNode`、`CallToolsNode`、run state、结束策略。
3. `_tool_execution.py` 与 `tool_manager.py`：并行/顺序工具、retry、deferred result。
4. `output.py`：native/prompted/tool structured output 的统一。
5. `durable_exec/` 与 `pydantic_evals/`：生产恢复和行为评测。

应该提炼：

- 工具依赖、运行上下文、structured output 如何在编译/类型检查阶段暴露错误。
- 同一模型响应同时包含 final output 和 function calls 时，`early/graceful/exhaustive` 三种结束策略的差异。
- tool retry 应进入模型可见反馈，而不是只抛应用异常。
- Agent API 可以像 FastAPI app 一样复用，并通过 DI 保持可测试性。

### 3.7 Letta：把 Agent 当作长期存在的有状态实体

Letta 将 Agent 放在 server 内持久化，核心是 memory blocks、上下文管理、身份与跨会话学习；同时提供 CLI、REST API 和 Python/TypeScript SDK。[README](https://github.com/letta-ai/letta)

源码阅读应围绕数据流，而不是从 Web UI 开始：

1. Agent state / memory block schema。
2. message/event 进入 server 后如何加载 Agent。
3. context window 如何拼装 system、core memory、history、archival memory 和 tool state。
4. memory edit 工具如何修改 Agent 自身状态。
5. 持久化、序列化和 `.af` Agent File 如何支持迁移与版本化。[Agent File](https://github.com/letta-ai/agent-file)

应该提炼：

- memory 不是单一向量库，而是**核心常驻记忆 + 可检索外部记忆 + 对话事件**的分层。
- Agent 的 prompt、persona、memory、tool config 和 model settings 可以成为版本化实体。
- 长期 Agent 需要解决 memory write policy、冲突、遗忘、污染和可审计性，而不仅是 recall。

## 四、A 级：按研究专题选读

| 项目 | 最适合的专题 | 为什么不放 S 级 | 建议入口 |
|---|---|---|---|
| [Google ADK](https://github.com/google/adk-python) | Task API、agent hierarchy、event/session、workflow runtime、A2A | 能力面很全，但 ADK 2.0 正处于 breaking changes 后的新阶段 | `src/google/adk/agents/llm_agent.py`、`flows/`、`workflow/`、`sessions/` |
| [Microsoft Agent Framework](https://github.com/microsoft/agent-framework) | 企业多 Agent orchestration、middleware、checkpoint、治理、跨语言 | 代码面大，适合在理解基础 loop 后进入 | `python/packages/core/`、`orchestrations/`、workflow samples |
| [smolagents](https://github.com/huggingface/smolagents) | CodeAgent、code-as-action、sandbox、模型/工具无关 | 与 mini-SWE-agent 的“极简样本”角色部分重叠，runtime 能力较少 | `src/smolagents/agents.py`、`local_python_executor.py`、sandbox executors |
| [Mastra](https://github.com/mastra-ai/mastra) | TypeScript full stack、agent/workflow 双引擎、memory、eval、app integration | 对 Python 为主的研究路线不是第一优先；部分 `ee/` 目录单独许可 | `packages/core/src/agent/`、`workflows/`、`memory/` |
| [Cline](https://github.com/cline/cline) | SDK/CLI/IDE 共核、HITL、checkpoint、plugin、headless automation | 产品 monorepo 大且快速迭代，不适合第一站 | `sdk/`、`core/`、tool approval、task lifecycle、checkpoint |
| [OpenAI Codex CLI](https://github.com/openai/codex) | Rust 生产 Agent、sandbox/approval、protocol、streaming、exec policy | 非通用 SDK，规模大；适合作为工程成熟度样本 | `codex-rs/core/`、`protocol/`、`exec/`、`tui/` 分层 |
| [OpenCode](https://github.com/anomalyco/opencode) | TypeScript client/server、session、provider、permissions、plan/build mode | 更像完整 coding product，业务/UI 噪声高于纯 harness | `packages/opencode/src/session/`、`tool/`、`permission/`、`provider/` |

### 这些项目分别补齐什么

- **Google ADK**：同一个 Agent 在 `chat/task/single_turn` 模式下如何改变控制权；Task API 如何把委派从 prompt 惯例升级成结构化协议。ADK 2.0 官方已增加 graph-based workflow runtime、fan-out/fan-in、retry、HITL 和 nested workflows。[ADK README](https://github.com/google/adk-python)
- **Microsoft Agent Framework**：把 AutoGen 的 message-passing 经验与 Semantic Kernel 的 enterprise integration 合并后，如何提供 sequential/concurrent/handoff/group collaboration、time travel 和 OpenTelemetry。[MAF README](https://github.com/microsoft/agent-framework)
- **smolagents**：比较 CodeAgent 用 Python 表达多步 action 与 ToolCallingAgent 用 JSON 每步调用工具的 token、组合性和安全差异。官方核心 agent logic 约千行，适合精读。[smolagents README](https://github.com/huggingface/smolagents)
- **Mastra**：研究 Node/Next.js 生态中 Agent 与 graph workflow 如何共享 storage、suspend/resume、memory、evals 和 observability。[Mastra README](https://github.com/mastra-ai/mastra)
- **Cline / Codex / OpenCode**：不再只看 loop，而是看真正产品如何处理权限、终端流、diff、session、取消、MCP、后台进程、UI 事件和升级兼容。

## 五、B 级：补充、对照或直接使用

| 项目 | 保留理由 | 降级原因 |
|---|---|---|
| [Agno](https://github.com/agno-agi/agno) | SDK + AgentOS runtime + UI，覆盖 API、storage、RBAC、scheduling、interfaces 和部署 | 研究目标容易被平台运营能力稀释；核心 loop 的独特性不及 S/A 样本 |
| [CrewAI](https://github.com/crewAIInc/crewAI) | role/goal/backstory、Task、Crew、Flows 是经典角色化多 Agent 范式 | 隐喻强、抽象高，与更通用 runtime/harness 重叠；适合研究任务分工而非基础 loop |
| [Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk-python) | 直接获得 Claude Code 工具集、permissions、hooks、subagents 和 in-process MCP | 公开 SDK 主要驱动 bundled Claude Code CLI，完整 loop 源码透明度不足；使用还受 Anthropic 商业条款约束 |
| [Aider](https://github.com/Aider-AI/aider) | repo map、edit format、git workflow、architect/editor model split 仍非常值得研究 | 更偏成熟 pair-programming 产品，不是通用可嵌入 harness；与新一代 coding agent 产品有重叠 |

B 级不是“差”，而是相对于本次**源码范式研究**目标，单位时间产生的新架构信息更少。若实际技术栈或产品形态匹配，Mastra、Agno、Cline 或 Claude Agent SDK 可能比 S 级更适合直接落地。

## 六、历史参考与明确排除

### 6.1 保留为历史/迁移样本

| 项目 | 处理 | 仍值得看的内容 |
|---|---|---|
| [AutoGen](https://github.com/microsoft/autogen) | 不作为新项目首选；迁移到 Microsoft Agent Framework | AgentChat/Core 分层、message bus、group chat、Magentic-One |
| [SWE-agent](https://github.com/SWE-agent/SWE-agent) | 默认改用 mini-SWE-agent | ACI、工具接口设计、history processor、研究 benchmark plumbing |
| [OpenAI Swarm](https://github.com/openai/swarm) | 用 Agents SDK 替代 | routines/handoffs 的极简教学表达 |

### 6.2 从主研究池排除

- **BabyAGI、AgentGPT、SuperAGI**：历史意义大于当前可复用 harness 价值。
- **MetaGPT、ChatDev**：更适合研究角色化软件过程模拟，不适合作为通用 Agent harness 基线。
- **纯 workflow/RPA 项目**：如果 LLM 不拥有持续的 observe–decide–act loop，就不进入本研究池。
- **纯 protocol 项目**：MCP、A2A、ACP、AG-UI 很重要，但它们是互操作协议，不是 Agent harness；应作为横切专题研究。
- **只开放 API client 的服务**：可以进入技术选型表，但不能作为“完整 loop 源码样本”。

## 七、跨项目应提炼的 11 个 Agent 范式

这是后续分析每个项目时应保持一致的坐标系。

### 7.1 Control loop

关注：输入如何进入、模型何时调用、工具结果如何回填、何时停止、max turns/cost/time 如何限制、异常/取消/retry 如何处理。

对照：mini-SWE-agent 的显式线性 loop、OpenAI `Runner`、PydanticAI graph nodes、LangGraph state machine。

### 7.2 控制权转移

至少区分：

- tool call：父 Agent 保持控制权；
- agent-as-tool/delegation：子 Agent 完成子任务并返回；
- handoff/transfer：把当前对话控制权交给另一个 Agent；
- workflow routing：由确定性代码选择下一节点；
- event/message bus：Agent 通过异步消息协作。

“多 Agent”不是一个模式，而是这些控制语义的组合。

### 7.3 Context engineering

关注 system prompt、当前任务、消息历史、tool result、文件、retrieval、skills、memory 的装配顺序，以及 compact/offload 触发条件。

对照：Deep Agents 的文件外存与 summarization、Letta 的 memory blocks、Aider 的 repo map。

### 7.4 Tool contract

关注 schema、description、dynamic availability、并发/顺序、幂等性、timeout、错误返回、retry、artifact 输出、MCP 适配。

重要经验：工具错误应尽量转换为模型可修正的结构化反馈，但权限拒绝、系统异常和业务失败不能混成同一种 tool result。

### 7.5 Workspace / environment

关注 local process、persistent shell、stateless subprocess、Docker、Kubernetes、remote sandbox 如何保持一致接口；文件、进程、网络、secret 的能力边界如何实现。

对照：mini-SWE-agent、OpenHands、Deep Agents、Codex。

### 7.6 Permission / HITL

关注 allow/deny/ask 策略在哪一层执行，审批后如何 resume，是否可按 tool + arguments 动态判断，权限事件是否可审计。

HITL 不是一个 `input()`；长任务中它需要 persisted interrupt、审批上下文和可重入执行。

### 7.7 State / persistence / durability

区分：聊天历史、Agent state、execution checkpoint、workspace state、long-term memory、artifact store。把它们全叫 memory 会掩盖不同一致性需求。

### 7.8 Concurrency / delegation

关注并行 tool calls、并行 subagents、fan-out/fan-in、取消传播、budget 分配、结果合并和上下文隔离。

### 7.9 Observability / evaluation / replay

最低要求：model call、tool call、state transition、token/cost/latency、error、approval、final outcome 可追踪。进一步比较 trace replay、trajectory eval、deterministic test 和 benchmark harness。

### 7.10 Extension model

比较 inheritance、middleware、hooks、plugins、skills、MCP、backend adapter、provider profile。优先研究能把扩展点放在明确 lifecycle boundary 上的项目。

### 7.11 Product protocol and UX

CLI/IDE/remote server 需要 streaming event protocol、session resume、cancel、diff、background process、artifact、notification。产品级 Agent 的难点大多不在模型调用本身。

## 八、推荐源码研究顺序

### 阶段 0：建立最小心智模型（2–3 天）

1. 精读 mini-SWE-agent 的 `DefaultAgent`。
2. 画出 20–30 行伪代码：observe → model → parse action → env.execute → append → stop。
3. 用 smolagents `CodeAgent` 对照 code-as-action。

产物：`minimal-loop.md`，明确最少状态、最少接口和三类停止条件。

### 阶段 1：通用 Agent SDK（4–5 天）

1. OpenAI Agents SDK：Runner、tool、handoff、guardrail、session、trace。
2. PydanticAI：Agent API、graph nodes、tool execution、structured output。
3. 用同一个“带两个工具的研究 Agent”分别实现，比较 public API 和内部 loop。

产物：`general-agent-loop-comparison.md`，重点比较 control flow、错误语义和类型边界。

### 阶段 2：完整 harness（1 周）

1. Deep Agents：middleware、filesystem、summarization、skills、subagents、backend。
2. OpenHands SDK：Conversation、events、workspace、hooks、server。
3. 实现同一个 coding/research task，记录 context、tool、workspace、approval、resume 的路径。

产物：`full-harness-patterns.md` 和一张 capability-to-component map。

### 阶段 3：状态与长期任务（4–5 天）

1. LangGraph：state、checkpoint、interrupt/resume、subgraph。
2. Letta：memory blocks、context assembly、agent persistence。
3. 明确 checkpoint、memory 和 workspace 三者的不同生命周期。

产物：`state-memory-durability.md`。

### 阶段 4：生产与多 Agent（1 周）

按实际技术栈二选一：

- Google 生态：Google ADK；
- Microsoft/.NET/企业治理：Microsoft Agent Framework；
- TypeScript 应用：Mastra；
- 完整 Agent 平台：Agno。

产物：`production-runtime-selection.md`，包含部署、治理、trace、HITL、协议和升级风险。

### 阶段 5：产品级 coding Agent（持续专题）

从 Codex、OpenCode、Cline 中选 1–2 个，不做全仓通读，按垂直链路追踪：

```text
user input
  → session/protocol event
  → context assembly
  → model request
  → tool proposal
  → approval/policy
  → sandbox/terminal/file edit
  → tool result/diff
  → next turn or final
```

产物：`product-agent-control-plane.md`，重点不是 prompt，而是 protocol、permission、execution 和 UX 状态机。

## 九、统一项目拆解模板

后续每分析一个项目都用同一模板，避免最后只得到一组互不可比的 README 摘要。

```markdown
# <Project> Agent Harness Analysis

## 1. 定位
- 它属于 Agent / Harness / Runtime / Product 哪一层？
- 直接用户是谁？最小运行入口是什么？

## 2. 一条完整执行链
- 从 user input 到 final output 的逐步调用路径
- 核心类、函数、状态对象和事件

## 3. Loop
- observe / decide / act / feedback / stop
- turns、cost、time、retry、cancel、stuck

## 4. Context
- system、history、files、retrieval、skills、memory
- compact、truncate、offload、cache

## 5. Tools 与 Environment
- schema、dispatch、parallel、error、artifact
- local/sandbox/remote、filesystem/process/network/secret

## 6. State 与 Durability
- conversation、agent state、checkpoint、workspace、long-term memory
- persistence、resume、replay、一致性

## 7. Multi-agent
- delegation / agent-as-tool / handoff / graph / message bus
- context isolation、budget、cancel、merge

## 8. Safety 与 HITL
- policy enforcement point
- approval lifecycle、audit、rollback

## 9. Observability 与 Eval
- traces、events、metrics、trajectory、deterministic tests

## 10. Extension Surface
- tools、middleware、hooks、skills、plugins、MCP、backend/provider adapter

## 11. 三类结论
- 可直接复用的设计
- 只适用于该项目约束的设计
- 应避免或需要验证的设计
```

## 十、选型决策树

| 需求 | 首选 | 次选/补充 |
|---|---|---|
| 最快理解 Agent loop | mini-SWE-agent | smolagents |
| 轻量通用 Python Agent SDK | OpenAI Agents SDK | PydanticAI |
| 强类型、DI、structured output、测试 | PydanticAI | OpenAI Agents SDK |
| 开箱即用的长任务 harness | Deep Agents | OpenHands SDK |
| 自定义状态机、durable execution、HITL | LangGraph | Microsoft Agent Framework |
| 软件工程 Agent / remote workspace | OpenHands SDK | Cline SDK、Codex CLI |
| 长期记忆和 Agent identity | Letta | Deep Agents memory/store |
| Google Cloud / A2A / Agent Engine | Google ADK | LangGraph |
| Microsoft/.NET/企业治理 | Microsoft Agent Framework | Semantic Kernel 相关生态 |
| TypeScript 全栈应用 | Mastra | Cline SDK、OpenCode |
| 完整自托管 Agent 平台 | Agno | OpenHands、Letta |
| 角色化多 Agent 快速编排 | CrewAI | ADK、MAF |
| 直接程序化使用 Claude Code 能力 | Claude Agent SDK | OpenHands ACP/其他 CLI bridge |

## 十一、研究时最容易踩的坑

1. **把功能清单当架构**：都支持 tools/memory/multi-agent，不代表控制语义相同。
2. **只看公共 API**：易用 API 可能隐藏最关键的 state、retry 和 permission；必须追一条完整调用链。
3. **把 memory 当一个组件**：history、checkpoint、semantic memory、workspace、artifact store 的一致性完全不同。
4. **把多 Agent 当默认答案**：先证明上下文隔离、并行或权限隔离确实有价值，否则单 Agent + tools 更简单。
5. **忽略继任关系**：AutoGen、SWE-agent、Swarm 仍很有名，但不再是新项目默认入口。
6. **把 CLI 开源等同于核心透明**：Claude Agent SDK 就是典型反例；SDK 可用不等于核心 loop 可研究。
7. **忽略 license 分层**：Mastra `ee/`、OpenHands enterprise 目录、Claude SDK 商业条款必须单独核验。
8. **跨项目比较 benchmark 数字**：模型、prompt、环境、预算和任务集不同，不能支持 harness 架构优劣结论。
9. **从 UI 开始读大仓**：先定位 loop、state、tool、workspace 和 protocol，再回到产品层。
10. **把 prompt 当安全边界**：真正的能力控制必须发生在 tool dispatch、sandbox、network、secret 和 approval policy 层。

## 十二、最终建议的研究组合

如果只允许投入一个月，采用以下“七项目、六范式”组合：

| 范式 | 主项目 | 对照项目 |
|---|---|---|
| 最小线性 loop | mini-SWE-agent | smolagents |
| 通用 Agent primitives | OpenAI Agents SDK | PydanticAI |
| 完整 context/tool harness | Deep Agents | OpenHands SDK |
| durable state runtime | LangGraph | Microsoft Agent Framework |
| 长期 memory/identity | Letta | Deep Agents store/memory |
| 产品级执行控制面 | OpenHands SDK | Codex / OpenCode / Cline 三选一 |

这套组合的优势是互补，而不是重复：

- mini-SWE-agent 告诉你什么可以删；
- OpenAI Agents SDK 告诉你通用 primitives 如何收敛；
- PydanticAI 告诉你类型和测试如何进入 loop；
- Deep Agents 告诉你完整 harness 如何通过 middleware 组合；
- OpenHands 告诉你事件、工作区和远程执行如何产品化；
- LangGraph 告诉你长任务如何持久化和恢复；
- Letta 告诉你 Agent 如何跨会话持续存在。

## 来源与边界

本报告优先使用各项目官方仓库、官方文档和源码，所有链接于 2026-08-28 核验。项目处于快速演进期，评分是针对“直接使用 + 源码范式研究”目标的架构判断，不是性能、社区规模或商业成熟度排名。详细可复用矩阵见同目录 `agent-harness-project-matrix.csv`。
