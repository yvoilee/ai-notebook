# 开源 Agent / Agent Harness 项目梳理与研究路线

> 基准日期：2026-08-29  
> 目标：筛选可直接使用、核心实现可拆解，并能用于沉淀 Agent Harness 工程范式的开源项目。  
> 定位：这不是 GitHub 热度榜，也不是通用 Agent 框架大全，而是一份后续源码研究的样本集与分析提纲。
>
> 配套学习产物：[`agent-paradigms/README.md`](agent-paradigms/README.md)——按 11 类范式组织的精华技术文档，包含理论、伪代码、代表项目代码佐证、横向对比、方法论、练习与掌握检查。

## 一、结论

筛选逻辑应从“谁更热门”切换为“谁更能暴露真实 Harness 决策”。Stars 只适合作为生态信号，不应作为主排序依据。

研究样本不宜放在一条单一榜单中，更适合分成两组：

- **基础必读**：用来建立从最小 loop 到生产 runtime 的完整认知。
- **专项选读**：分别深入记忆、常驻运行、浏览器环境、自成长和协议互操作。

建议的基础必读是：

1. [mini-SWE-agent](https://github.com/SWE-agent/mini-swe-agent)
2. [Pi Agent Harness](https://github.com/earendil-works/pi)
3. [OpenAI Codex](https://github.com/openai/codex)
4. [OpenHands Software Agent SDK](https://github.com/OpenHands/software-agent-sdk)
5. [DeerFlow](https://github.com/bytedance/deer-flow)

建议的专项核心样本是：

- [Hermes Agent](https://github.com/NousResearch/hermes-agent)：技能、反思、子 Agent 与长期运行。
- [Letta Code](https://github.com/letta-ai/letta-code)：上下文编译、长期记忆与 Agent 身份。
- [OpenClaw](https://github.com/openclaw/openclaw)：Gateway、渠道、会话路由、Heartbeat 与 Cron。
- [browser-use](https://github.com/browser-use/browser-use)：浏览器观察—行动接口与失败恢复。

如果只能精读 5 个，默认选择：

`mini-SWE-agent → Pi → Codex → OpenHands SDK → Hermes Agent`

这组比“mini-SWE-agent、Pi、Codex、Hermes、Letta Code”更均衡：后者在认知、技能和记忆上形成漂亮的演进线，但 Hermes 与 Letta 的研究面有部分重叠，同时缺少 Workspace/Runtime 解耦与生产恢复这一层。若长期记忆是绝对重点，可以用 Letta Code 替换 Hermes；若长任务编排是重点，可以用 DeerFlow 替换 Hermes。

## 二、先统一研究对象

### 2.1 四个容易混用的层次

| 层次 | 核心职责 | 典型样本 |
|---|---|---|
| **Agent** | 目标、模型、工具与决策策略构成的执行单元 | 各 SDK 中的 `Agent` 抽象 |
| **Agent Harness** | 把模型包进可工作的循环：上下文、工具、环境、权限、停止、恢复和交互 | mini-SWE-agent、Pi、Deep Agents |
| **Agent Runtime / Control Plane** | 状态、事件、checkpoint、并发、调度、持久化和恢复 | OpenHands SDK、LangGraph、DeerFlow |
| **Agent Product** | 在 Harness/Runtime 上增加 CLI、IDE、TUI、桌面端、账号与渠道体验 | Codex、OpenCode、Cline、OpenClaw |

一个成熟系统通常是这些层的组合，而不是四选一：

```text
Agent Product
  └─ Agent Harness
       ├─ control loop / policy
       ├─ context / memory
       ├─ tools / workspace / permissions
       └─ delegation / interaction
            └─ Agent Runtime
                 ├─ state / events / checkpoints
                 ├─ scheduling / concurrency / resume
                 └─ tracing / evaluation / operations
```

因此，LangGraph 和 Codex 不应直接比较“谁更强”：前者主要是状态化执行底座，后者是包含 Harness 的完整 Coding Agent 产品。

### 2.2 真正要回答的问题

一个项目是否值得进入核心研究集，取决于它能否帮助回答：

1. Agent loop 如何组织，继续和终止条件是什么？
2. 上下文如何装配、压缩、外置和恢复？
3. 工具如何定义、调用、并发执行和返回错误？
4. 文件、Shell、浏览器、网络和密钥权限如何控制？
5. 长期记忆和程序性技能如何沉淀、版本化和召回？
6. 子 Agent 如何隔离、委派、限额和汇总？
7. Agent 如何常驻、定时运行、跨渠道接收任务和主动通知？
8. 失败、重试、中断、审批、进程重启和任务恢复如何处理？
9. trajectory、event、token/cost、artifact 和 checkpoint 如何观测？
10. 如何通过 eval、回放和失败分类防止能力回退？

### 2.3 入选标准

- 有完整、多轮的模型—工具—环境反馈循环。
- 有可直接运行的 CLI、SDK、Server 或应用入口。
- 核心 Harness/Runtime 有足够开源实现，而不只是客户端 wrapper。
- 模型、工具、上下文或执行环境至少有一处可替换。
- 项目仍活跃，或维护/继任状态被明确标注。
- 能暴露真实工程取舍，而不只是展示概念 Demo。

## 三、核心研究样本

### 3.1 基础必读：建立完整 Harness 心智模型

| 项目 | 对应范式 | 最值得拆解的部分 | 主要限制 |
|---|---|---|---|
| [mini-SWE-agent](https://github.com/SWE-agent/mini-swe-agent) | 极简 Agent Loop | 约百行核心 Agent、线性消息轨迹、模型—Shell—环境反馈、step/cost/time budget | 极简不等于生产安全，大量责任交给模型、prompt 与外部 sandbox |
| [Pi Agent Harness](https://github.com/earendil-works/pi) | 极简、可扩展 Harness | Agent Core、模型适配、Tool Call、会话状态、TUI 的清晰拆包；默认 read/write/edit/bash | 默认不是完整安全边界；文件、进程、网络和凭证权限继承启动用户，生产使用需外置 sandbox/container/policy |
| [OpenAI Codex](https://github.com/openai/codex) | 生产级 Coding Agent | Rust 事件驱动运行时、命令执行、文件修改、审批、Sandbox、会话恢复和协议分层 | 仓库规模大、产品层较重，不适合作为第一站；多 Agent 更准确地说是子 Agent 委派、并行执行、生命周期和父级汇总 |
| [OpenHands Software Agent SDK](https://github.com/OpenHands/software-agent-sdk) | Agent Server + Workspace | Agent、Conversation、Event、Tool、Workspace、Server 分层；本地、容器和 Kubernetes 临时环境 | 系统较大，需要按 loop→event→workspace→server 的顺序阅读 |
| [DeerFlow](https://github.com/bytedance/deer-flow) | 长任务 Super-Agent Harness | planning、skills、subagents、memory、context engineering、artifact 与长任务编排 | 高层能力较多，需下钻其 runtime/框架依赖才能判断哪些能力属于自身 |

这五个项目覆盖：最小循环、可扩展内核、生产执行控制、Workspace 解耦和长任务编排。

### 3.2 专项核心：深入特定范式

| 项目 | 对应范式 | 最值得拆解的部分 | 研究边界 |
|---|---|---|---|
| [Hermes Agent](https://github.com/NousResearch/hermes-agent) | 自成长通用 Agent | 会话记忆、技能生成与迭代、反思循环、子 Agent、Cron、消息网关和跨平台长期运行 | 功能面广，研究时要区分核心 loop、技能系统与外围集成 |
| [Letta Code](https://github.com/letta-ai/letta-code) | Memory-first Agent | Git-backed MemFS、上下文编译、Recall、Compaction、Reflection/Dreaming，以及模型可替换时如何维持 Agent 身份 | 适合作为记忆专项，不应代替对通用 runtime、权限和 workspace 的研究 |
| [OpenClaw](https://github.com/openclaw/openclaw) | 常驻型个人 Agent | Channel 路由、会话隔离、Gateway、Heartbeat、Cron、主动通知与跨消息平台运维 | 重点是系统与运维层，不要只读模型 loop；远程暴露、密钥和陌生消息是关键风险面 |
| [browser-use](https://github.com/browser-use/browser-use) | Browser Agent | 页面观察表示、DOM/视觉结合、浏览器状态、动作执行、认证、失败恢复和远程浏览器 | 它是领域 Agent 样本，结论不能不加区分地推广到代码或桌面环境 |

“基础必读 + 专项核心”比单一第一梯队更准确：前一组建立通用 Harness 结构，后一组提供记忆、常驻与领域环境的深挖样本。

## 四、对照研究样本

| 项目 | 主要研究价值 | 不作为第一站的原因 |
|---|---|---|
| [OpenCode](https://github.com/anomalyco/opencode) | Plan/Build Agent、权限策略、通用子 Agent、TUI/桌面端/Server 多前端架构 | 产品代码量大，适合与 Codex 做同任务对照 |
| [goose](https://github.com/aaif-goose/goose) | MCP 扩展、ACP Server、外部 ACP Agent Provider、Recipe 与子任务编排 | 核心价值偏协议互操作和工具生态；其 scheduler/cron/recipe automation 不应与 Heartbeat 主动循环混为一谈 |
| [Agent Zero](https://github.com/agent0ai/agent-zero) | 完整 Linux 系统作为工具、Docker 隔离、桌面控制、动态工具和层级子 Agent | 系统变量多，不利于最初识别最小范式 |
| [Cline](https://github.com/cline/cline) | IDE 内 HITL、逐步审批、Checkpoint、Plan/Act、MCP 与多 Agent UX | IDE、CLI、SDK 和服务端混在大型 monorepo，阅读成本高 |
| [Aider](https://github.com/Aider-AI/aider) | Repo Map、代码编辑格式、Git 自动提交、Lint/Test 修复循环 | 更接近经典 AI Pair Programming，是优秀历史/工程基线，但不是完整常驻 Agent |
| [Gemini CLI](https://github.com/google-gemini/gemini-cli) | Workspace Trust、Sandbox、Extensions、MCP、Skills、Subagents 与大上下文管理 | 与 Gemini 生态结合较深，适合和 Codex 对照 |
| [Deep Agents](https://github.com/langchain-ai/deepagents) | Middleware、filesystem/context offload、skills、subagent、backend 与 HITL | 它是 batteries-included Harness，不应与通用框架一并排除；但执行与持久化能力需结合 LangChain/LangGraph 阅读 |
| [Open Interpreter（当前）](https://github.com/openinterpreter/openinterpreter) | 低成本/开源模型的 Harness 模拟与 Rust 实现 | 当前官方仓库已不是经典 Python “让模型执行代码”的同一实现，不应沿用旧描述 |
| [Open Interpreter（经典版，社区维护）](https://github.com/endolith/open-interpreter) | “代码执行器作为通用工具”的极简思想和执行前确认 | 适合作为历史思想样本，维护和产品定位与当前官方仓库不同 |

## 五、暂不作为核心样本

### 5.1 通用开发框架

- LangGraph
- CrewAI
- PydanticAI
- Mastra
- OpenAI Agents SDK
- Google ADK
- Microsoft Agent Framework

这些项目主要回答“开发者如何构建 Agent/Workflow”。它们仍然是重要底座和对照资料，但不一定完整呈现一个可直接使用的 Harness 在终端、权限、Workspace、会话和产品交互上的全部决策。

这里有两个例外：

- **LangGraph** 应作为 durable state/checkpoint/interrupt 的底层参考，而不是产品级样本。
- **Deep Agents** 已经是明确的 batteries-included Harness，应保留在对照研究集，而不是因为来自框架生态就排除。

### 5.2 可视化平台

- Dify
- Flowise
- n8n

平台层、工作流引擎和 UI 占比过高，Agent 内核容易被产品架构遮蔽。它们更适合研究低代码编排、连接器和运营平台，而不是本轮 Harness 内核。

### 5.3 历史与迁移样本

- AutoGPT
- BabyAGI
- 原版 [SWE-agent](https://github.com/SWE-agent/SWE-agent)
- [AutoGen](https://github.com/microsoft/autogen)

这些项目适合理解 Agent 演化史，不建议作为当前最佳实践的主要来源。SWE-agent 官方已将默认入口转向 mini-SWE-agent；AutoGen 官方仓库已进入 maintenance mode，并建议新项目评估 Microsoft Agent Framework。

## 六、应横向提炼的 11 类 Agent 范式

最终产物不应是“每个项目一篇功能介绍”，而应围绕以下范式横向对照。

| # | 范式 | 核心问题 | 主样本 |
|---:|---|---|---|
| 1 | **极简 ReAct / Agent Loop** | state、step、continue、stop 和 budget 的最小闭环是什么？ | mini-SWE-agent、Pi |
| 2 | **Action Model** | Shell/code 与结构化工具调用各自如何组合、校验和反馈错误？ | Pi、Codex、Open Interpreter、Agent Zero |
| 3 | **Workspace 与 Runtime 隔离** | Agent、文件系统、进程和远程执行环境如何解耦？ | OpenHands、Codex、Agent Zero |
| 4 | **权限、审批与 Sandbox** | 能力在什么层被真正强制，如何做 allow/deny/ask 和 workspace trust？ | Codex、Cline、OpenCode、Gemini CLI |
| 5 | **上下文装配、压缩与外置** | system、项目指令、历史、工具输出和文件记忆如何编译进窗口？ | Pi、Codex、Letta Code、DeerFlow |
| 6 | **Durable State、Checkpoint 与恢复** | 中断、崩溃、模型错误、审批等待和进程重启后如何继续？ | OpenHands、Codex、LangGraph、Cline |
| 7 | **长期记忆与程序性技能** | 事实、经验、技能如何写入、版本化、检索、遗忘和审计？ | Letta Code、Hermes、OpenClaw、DeerFlow |
| 8 | **子 Agent 委派与上下文隔离** | 如何传任务、限制工具/预算、回传结果并避免上下文污染？ | Hermes、OpenHands、DeerFlow、OpenCode、goose |
| 9 | **Gateway、Channel、Heartbeat 与 Scheduler** | 常驻 Agent 如何接收外部事件、主动工作和定时运行？ | OpenClaw、Hermes；goose 侧重 scheduler/recipe automation |
| 10 | **可观测性、回放与评测** | 如何保存 trajectory、event、cost、artifact，并建立回归门禁？ | Codex、OpenHands、LangGraph、PydanticAI |
| 11 | **领域观察—行动接口** | 如何把领域状态表示和失败模式变成运行时一等概念？ | browser-use、Codex/Aider、Agent Zero |

相比原先的 10 类，这里把“失败、重试、中断、恢复”提升为独立范式，并补入“可观测性、回放与评测”。这两项决定一个 Agent 能否从 Demo 走向可运营系统。

## 七、推荐阅读顺序

### 第一阶段：建立最小心智模型

1. **mini-SWE-agent**：读懂最小 loop、trajectory 和 budget。
2. **Pi**：理解如何把最小循环扩展为模型适配、工具、会话和 TUI，同时记录其安全边界。

### 第二阶段：进入生产执行控制面

3. **Codex**：观察事件、命令、补丁、审批、sandbox、恢复和子 Agent 生命周期增加了哪些复杂度。
4. **OpenHands SDK**：研究 Agent、Conversation、Event、Workspace 和 Server 的解耦。

### 第三阶段：长任务、技能和记忆

5. **DeerFlow 或 Hermes Agent**：研究 planning、skills、subagents、长任务与主动运行。
6. **Letta Code**：深入研究 context compilation、MemFS、compaction、recall 和 Agent identity。

### 第四阶段：常驻与领域环境

7. **OpenClaw**：研究 Gateway、会话路由、渠道、Heartbeat、Cron 与长期运维。
8. **browser-use**：研究网页环境中的观察、动作、认证、状态和失败恢复。

### 第五阶段：同题对照

- Coding Agent：Codex vs OpenCode vs Cline vs Gemini CLI。
- Action Model：Pi typed tools vs mini-SWE-agent Bash-only vs Open Interpreter code execution。
- 长任务：DeerFlow vs OpenHands vs LangGraph-based Harness。
- 常驻运行：OpenClaw/Hermes 的 heartbeat/proactive model vs goose 的 scheduler/recipe automation。
- 记忆：Letta Code 的身份/记忆模型 vs Hermes 的经验转技能。

## 八、统一项目拆解模板

每个项目都按同一模板产出，避免最后只得到一组 README 摘要。

### 1. 定位与边界

- 它是 Agent、Harness、Runtime 还是 Product？
- 什么由项目自己实现，什么委托给模型、框架、操作系统或云服务？
- 核心开源边界、许可证和托管组件边界是什么？

### 2. 一条完整执行链

从一个真实用户请求追踪：入口 → context assembly → model call → tool dispatch → environment result → state update → stop/resume。

### 3. Loop 与控制权

- 状态对象、循环入口和停止条件。
- step/cost/time/token budget。
- final answer、tool call、handoff、agent-as-tool 的控制权差异。

### 4. Context 与 Memory

- system/project/session/tool/memory 的装配顺序。
- 压缩触发条件、保留策略、文件化外置和恢复方式。
- 长期记忆的写入策略、召回、冲突、遗忘和审计。

### 5. Tool 与 Environment

- schema、粒度、错误语义、并发、幂等和超时。
- Shell 是持久会话还是独立进程。
- Local、container、VM、remote workspace 是否保持一致语义。

### 6. Permission 与 Safety

- allow/deny/ask 在哪一层执行。
- 路径、命令、网络、密钥和浏览器认证态如何隔离。
- Prompt injection、陌生发信人和外部内容如何进入信任边界。

### 7. Durability 与 Recovery

- checkpoint 保存的是消息、业务状态还是完整 pending work。
- 取消、超时、stuck、工具失败、进程崩溃、审批等待如何恢复。
- 重试是否模型可见，是否支持 replay 和幂等执行。

### 8. Multi-Agent

- 委派触发条件与任务契约。
- 上下文、工具、workspace、预算和终止条件是否隔离。
- 子 Agent 结果如何汇总、归因、取消和处理部分失败。

### 9. 常驻与外部事件

- Channel/Gateway 如何映射身份、会话和权限。
- Heartbeat、Cron、Scheduler 和事件订阅的语义差异。
- 主动通知、重复投递、离线恢复和跨渠道一致性。

### 10. Observability 与 Eval

- 是否保留 trajectory、event、token/cost、checkpoint 和 artifact。
- 是否能回放单步决策并定位失败阶段。
- 是否有真实任务集、确定性断言、失败分类和回归门禁。

### 11. 最终结论

每个项目固定输出：

1. 一张运行时边界图。
2. 一条带关键状态的真实 trajectory。
3. 一个最小可运行实验和一组回归 eval。
4. 一份“可复用经验 / 不应照搬 / 待验证假设”清单。

## 九、后续研究建议

### 9.1 先做共同实验，而不是只读代码

选择同一类任务，在多个 Harness 上执行并记录：

- 初始 context 和每轮 context 增长。
- 工具调用序列、错误反馈和重试次数。
- 审批点、sandbox 边界和外部副作用。
- token、时延、成本、终止原因和恢复方式。
- 任务完成后留下的 memory、skill、artifact 和 checkpoint。

### 9.2 建立可复用研究台账

建议每个项目维护以下字段：

| 维度 | 最小记录 |
|---|---|
| 版本 | commit/tag、访问日期、许可证 |
| 入口 | CLI/SDK/Server、最小运行命令 |
| 核心路径 | loop、context、tool、workspace、state、permission 的源码文件 |
| 轨迹 | 输入、每步 action/observation、终止原因 |
| 可靠性 | retry、timeout、interrupt、checkpoint、resume |
| 安全 | host/container/VM、网络、secret、approval |
| 评测 | 自带 benchmark、可复跑用例、失败分类 |
| 结论 | 可复用范式、不应照搬、待验证假设 |

### 9.3 研究时的几个警戒线

- 不把 Stars、README 功能数量或项目方 benchmark 当作架构质量结论。
- 不把 MCP/ACP 接入能力等同于可靠性；状态、权限、恢复和评测仍由 Harness 负责。
- 不把 prompt 当权限系统；真正的能力限制必须发生在 tool dispatch、sandbox、network 和 secret 层。
- 不把长上下文等同于长期记忆；需要区分窗口内信息、可恢复任务状态和跨会话记忆。
- 不把角色命名等同于多 Agent；关键是上下文、工具、预算、执行和失败隔离。
- 不从大型产品仓库的 UI 开始读；先定位 loop、protocol、state、tool、workspace 和 permission。
- 不混用同名项目的不同时代实现，尤其是当前 Open Interpreter 与经典 Python 版本。

## 十、资料边界

本报告优先引用官方仓库、官方文档和源码。项目处于快速演进期，结论针对“可直接使用 + 可拆解真实 Harness 经验”这一目标，不是性能、社区规模或商业成熟度排名。

后续每次精读应固定到 commit/tag，并把推断和源码事实分开记录。当前目录中的 `AI_AGENT_HARNESS_开源项目重筛与研究路线.md` 保留为更偏 Framework/Runtime 的扩展底稿；本文件作为 Harness 优先研究的主入口。
