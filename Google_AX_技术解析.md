# 看懂 Google AX：从声明式资源到可恢复的 Agent 沙箱

> **一句话定位：**AX 是运行 Agent 工作负载的声明式集群编排层。用户用 `Task`、`Workspace` 和 `Model` 描述任务意图，AX 负责把它转换为 Agent Substrate 上的隔离 Actor，并管理工作区准备、状态观察、暂停、恢复和调试。

本文基于官方仓库 [google/ax](https://github.com/google/ax) 的提交 `ac2332829f22360ff97b0ba34d94dd0dd782f17e`。AX 仍处于快速开发期，本文区分“当前源码已经实现的行为”和 Roadmap 中的计划，后续版本可能改变接口与语义。

---

# 先认识 AX

## AX 管的是 Agent 工作负载，不是 Agent Loop

大模型只能生成下一段输出。Agent 框架在进程内补上 Prompt、Tool、Memory 和 Loop；但把成千上万个 Agent 放进集群之后，还会遇到另一组问题：每个任务放在哪里运行，怎样隔离代码和文件，如何准备仓库与工具，谁记录任务状态，空闲任务怎样暂停，恢复时哪些状态能够延续，以及工程人员如何进入沙箱排查问题。

AX 处理的是这层平台问题。它把 Agent 看作一种有状态、可能长时间存活、会访问外部模型与工具、需要严格隔离的工作负载。用户提交声明式资源，AX 控制面负责资源状态和生命周期，Agent Substrate 负责真正的 Actor、Worker、沙箱和快照，任务容器里的 Runner 再把声明变成工作目录与运行进程。

## 它与 Kubernetes、Agent Harness、工作流系统的边界

| 形态 | 主要解决什么 | AX 与它的关系 |
|---|---|---|
| 模型 SDK | 请求模型、流式输出、错误类型 | AX 不替代模型 SDK；`Model` 只统一保存供应商、模型名、参数和凭据引用 |
| Agent Harness | Agent Loop、Tool、Message、上下文、会话 | Harness 运行在 `Task` 容器里；AX 不规定内部 Loop |
| 工作流编排 | DAG、步骤依赖、确定性任务流 | AX 提供可组合的隔离 `Task`，不直接建模业务 DAG |
| Kubernetes | 容器调度、资源、网络与控制器生态 | AX 借用声明式操作习惯，但没有把海量短任务保存为 Kubernetes CRD |
| Agent Substrate | Actor、Worker、沙箱、快照、任务路由 | AX 的执行底座；AX 把 `Task` 映射为 Substrate Actor |
| AX | Agent 任务的声明、环境装配、生命周期、观察与调试 | 位于 Agent 框架和底层 Actor 基础设施之间 |

AX 的 CLI 有意做成 `kubectl` 的形状：`apply`、`get`、`describe`、`watch`、`delete`，再增加 `suspend`、`resume` 和 `ssh`。相似的是操作方式，不是存储实现。AX 把资源状态放在 Redis，由自己的 gRPC Server 直接与 Agent Substrate 调和。

## 三个资源原语建立了平台契约

### Task 是最小的隔离执行单元

`Task` 声明镜像、命令、环境变量、CPU/内存请求与限制、绑定的 Workspace，以及是否开放调试接口。AX 不试图把一个 Agent 的计划、委派、重试和任务树全部塞进单个资源；它只提供便宜、可隔离、可暂停、可丢弃的节点。一个任务可以完成全部工作，也可以由 Agent 在上层组合成任务树。

### Workspace 把环境准备从命令里拆出来

`Workspace` 描述 Agent 开工前需要放进文件系统和工具环境的内容：Git 仓库、内联文件、MCP Server/Registry、Skill Registry 与 Skill 路径。`Task.spec.workspaces` 可以绑定多个 Workspace，并为每个绑定指定路径和自然语言 `goal`。第一个 Workspace 是任务命令的工作目录。

Workspace 的价值在于把“准备工作台”声明为可复用资源。它当前并不是预先构建一次、供所有任务共享的镜像缓存；Runner 仍会在每个任务的持久目录中执行首次准备，只是准备方式有统一声明，暂停恢复时不会重复覆盖已有状态。

### Model 把平台模型配置集中管理

`Model` 保存 Provider、模型标识、Provider 专属参数和 Kubernetes Secret 引用。它让平台组件能够复用同一份模型配置，例如目标驱动的 Workspace 环境规划；同时避免把 API Key 明文复制进每个任务清单。

### Atespace 是三种资源的共同作用域

每个 AX 资源都属于一个 `atespace`，默认值是 `default`。Task 名称会直接成为 Substrate Actor 名称，资源名和 atespace 都必须符合小写 RFC 1123 标签：最多 63 个字符，只能包含小写字母、数字和 `-`，并以字母或数字开头、结尾。

## 当前成熟度要按开发中项目看待

仓库采用 Apache License 2.0，但 README 明确提示 AX 及多项功能仍在重度开发，核心概念、协议和规格在稳定版本前可能出现破坏性变化。当前适合源码学习、平台原型和受控试点；进入生产前至少要锁定提交或镜像 digest，补齐集成测试、安全策略、凭据治理、预算护栏和升级兼容层。

---

# 系统架构围绕两次翻译展开

AX 的工作可以拆成两次翻译。控制面先把 YAML 资源翻译为 Substrate 的 ActorTemplate 与 Actor；Runner 再把 Task/Workspace 规格翻译为沙箱里的目录、进程和观测接口。

## 分层看清组件职责

| 层次 | 核心组件 | 职责 |
|---|---|---|
| 访问与声明层 | `ax` CLI、YAML Manifest、gRPC Client | 解析清单、连接集群、提交资源、查看状态、进入任务 |
| AX 控制面 | `ax-server`、Redis Store、Redis Locker、TaskReconciler | 校验、持久化、加锁、发布状态、驱动 Substrate 生命周期 |
| Agent Substrate | Atespace、ActorTemplate、Actor、Worker、atenet router | 分配运行位置、提供 gVisor 沙箱、持久目录、暂停快照与请求路由 |
| 任务沙箱 | `ax-task-runner`、Workspace Setup、Metadata/Guest Server、Agent 命令 | 准备工作区、监督命令、暴露就绪与调试能力 |

## `ax apply` 先在客户端把 YAML 变成类型化 RPC

`ax apply -f task.yaml` 不会把原始 YAML 发给服务端。CLI 使用 `yaml.v3` 逐段解析多文档清单，先读取 `kind`，再解码成 `Task`、`Workspace` 或 `Model` 的 Protobuf 类型，最后调用对应的 RPC：

- `Task` 调用 `CreateTask`；
- `Workspace` 调用 `UpdateWorkspace`；
- `Model` 调用 `UpdateModel`。

这种设计让 Server 只处理类型化对象，未知字段和拼错字段会在严格解码或校验阶段尽早失败。它也带来一个重要差异：当前 `Task` 一旦创建就是不可变资源，重复 apply 同名 Task 会得到失败；Workspace 和 Model 才支持更新。

## Server 用资源锁保护一次生命周期变更

`ax-server` 在同一端口提供 gRPC 与 `GET /healthz`。资源写操作按 `kind / atespace / name` 获取独占锁。生产入口使用 Redis Locker：先执行带 TTL 的 `SET NX`，锁释放时通过 Lua 校验 token、删除锁并发布通知；竞争者订阅 Pub/Sub，同时保留定时重试，避免漏通知后永久等待。

加锁解决的是同一资源上的并发变更，不是分布式事务。以 Task 创建为例，Server 会按顺序保存初始记录、调用 Reconciler、更新状态；中途失败时把 Task 标成 `Failed`，不会把已经发生的外部动作伪装成没有发生。

## Redis 同时承担资源存储、列表索引和状态推送

Task、Workspace、Model 以 Protobuf JSON 保存在 Redis。不同 atespace 有各自的有序索引，Task 状态更新会同时发布到专属 Pub/Sub Channel。`WatchTask` 先发送当前快照，随后把 Pub/Sub 更新转成 Server Streaming gRPC；达到 `Failed` 或 `Completed` 后结束流。

这也是 AX 不使用 CRD 的核心取舍。官方设计文档认为，把数百万个短生命周期任务存为 CRD 会把 etcd 推到不擅长的容量和写入频率区间。AX 选择 Redis 保存状态，再在细粒度分布式锁下直接与 Agent Substrate 调和。

## Reconciler 把 Task 映射为 Actor

TaskReconciler 当前按下面的顺序工作：

1. 确保目标 Atespace 已存在；
2. 使用 Task 名称作为 Actor 名称；
3. 收集 Task 环境变量、Task YAML、绑定的 Workspace YAML 和可用凭据；
4. 根据镜像与环境内容计算摘要，创建或复用任务专属 ActorTemplate；
5. 确保 Actor 存在；
6. 按 Task 期望状态调用 `SuspendActor` 或 `ResumeActor`；
7. 恢复后轮询 Runner 的 `/readyz?check=workspace`；
8. 更新 `WorkspaceReady` 与 `Ready` 条件。

ActorTemplate 默认使用 gVisor 沙箱，挂载 `/workspace` DurableDir，并把 `/usr/local/bin/ax-task-runner` 作为容器固定入口。Task 的 `spec.command` 不直接成为容器入口，而是通过 `AX_TASK_YAML` 交给 Runner 再启动。

## Runner 是控制面和 Agent 进程之间的协议适配器

Runner 在每个 Task 容器中作为 PID 1 运行。它承担四项稳定职责：

- 在 80 端口提供 `/healthz`、`/readyz` 和元数据接口；
- 依次准备绑定的 Workspace；
- 把 `spec.command` 作为独立进程组启动并监督；
- 收到停止信号时向整个进程组转发 `SIGTERM`，等待 10 秒后再强制结束。

命令退出后，Runner 不退出。这样元数据接口仍然可用，开启 `spec.debug` 时也仍能通过 `ax ssh` 检查沙箱。当前控制面不会把任务命令退出码回写为 Task 的终态；退出码只由 Runner 记录，或交给自定义 Runner 的 `OnCommandExit` 回调处理。

## Runner Contract 允许替换执行框架

自定义镜像仍需在 `/usr/local/bin/ax-task-runner` 提供可执行入口，并遵守 Runner Contract：读取 `AX_TASK_YAML` 和 `AX_WORKSPACES_YAML`，在 80 端口提供健康与就绪接口，准备 Workspace，启动并监管命令，处理 SIGTERM；需要 `ax ssh` 时还要在 `debug=true` 下提供 Guest gRPC 服务。

定制可以分三层：

1. 只扩展默认镜像，保留原 Runner；
2. 在自有 Go 二进制中嵌入 `runner.Run`；
3. 按协议从头实现 Runner。

最浅的一层通常最稳。只有当默认工作区布局、进程监管或元数据协议不满足需求时，才值得接管完整 Runner 生命周期。

---

# 核心执行链路从 Task 创建开始

## 创建与运行是两个动作

当前源码里，`CreateTask` 会把初始 `status.phase` 设为 `Suspended`，保存记录后立刻执行一次 Reconcile。由于期望状态是 Suspended，Reconciler 会创建必要的 Actor/Template，再把 Actor 暂停。只有显式执行 `ax resume task <name>`，Task 才进入 Running，并开始 Worker 分配、Runner 启动和 Workspace 准备。

这与 README 的快速上手示例存在需要留意的语义差异：清单可以成功创建，任务却不会自动开始执行。自动化脚本应把 `resume` 作为独立步骤，并在之后等待 `Ready=True`。

```bash
ax apply -f task.yaml
ax resume task test
ax watch task test
```

## Workspace 首次准备按绑定顺序执行

Runner 将 Task 的 WorkspaceRef 与控制面传来的 Workspace 资源按名称匹配，计算每个挂载路径，然后按声明顺序执行 `SetupWorkspace`。没有指定路径时落在 `/workspace/<name>`；第一个路径成为任务命令的工作目录。没有绑定 Workspace 时，Runner 仍提供空的 `/workspace`。

一次 Maiden Run 会进行以下操作：

1. 创建目标目录和 `/ax` 状态目录；
2. 写入 `Workspace.spec.files` 声明的内联文件；
3. 为每个 Git Repo 执行 `git init`、设置 remote、fetch 指定分支并 checkout；
4. 创建 Skill 路径；
5. 如果绑定提供 `goal`，尝试调用 Antigravity Agent 准备工具链和依赖；
6. Git 全部成功后，在 `/ax` 写入与 Workspace 路径对应的初始化标记。

Git 拉取失败会最多重试五次并记录诊断日志，但 Setup 不因此返回错误；标记会被省略，以便下次启动重试。目标驱动的 Antigravity bootstrap 缺脚本、缺 API Key、超时或执行失败时也只写日志并继续。它默认有 10 分钟超时，并通过 workspace-only 文件策略限制文件工具的路径，但允许其他能力，包括命令执行。

因此，`WorkspaceReady=True` 的准确含义是“Runner 已走完 Setup 调用并开放就绪接口”，不能直接解释为“所有仓库、依赖和目标准备都通过验收”。高要求场景应在 Task 命令开头增加确定性的环境检查，或使用自定义 Runner 把检查结果纳入 readiness。

## Task 命令运行在独立进程组中

工作区准备完成后，Runner 设置 `AX_METADATA_URL` 和 `spec.env`，以第一个 Workspace 为工作目录，启动 `spec.command`。独立进程组保证暂停或删除时可以连同 Agent 派生的子进程一起收敛。

Runner 的等待逻辑有两个分支：

- 命令先退出：记录退出信息，Runner 继续存活，直到容器被停止；
- 控制上下文先取消：向进程组发 `SIGTERM`，等待 10 秒，必要时发 `SIGKILL`。

这种设计优先保证沙箱可检查性。代价是 Task 的控制面状态与用户命令的业务完成状态并不等价。若需要自动判断任务成功、上传产物或通知上游，应在自定义 Runner 的退出回调或任务协议中明确实现。

## Phase 与 Conditions 要一起读

`status.phase` 是粗粒度摘要，当前代码中会出现 `Suspended`、`Running`、`Failed` 和 `Terminating` 等值。Conditions 提供能否工作的细节：

- `WorkspaceReady=True`：Runner 的 Workspace 准备阶段已经结束；
- `Ready=True`：Task 处于 Running，并且 WorkspaceReady=True；
- 暂停时 Ready=False，reason 为 `TaskSuspended`；
- Workspace 仍在准备时，Ready=False，reason 为 `WorkspaceInitializing`。

`ax watch` 适合观察条件变化，但目前它只在 Redis 中的 Task 状态变化时收到推送。诊断“为什么环境不可用”时，还应结合 `ax describe`、Runner 日志、`/metadata` 和工作区内容。

## `ax ssh` 通过 Guest Services 进入沙箱

只有 `spec.debug: true` 的 Task 才开放 Guest Services。Runner 在同一 80 端口用 h2c 同时承载 HTTP 与 gRPC，提供进程执行和文件访问。CLI 会先尝试直接连接 Worker IP；不可达时，自动端口转发到 `atenet-router`，并在 gRPC Metadata 中设置 `ate-target-actor: <atespace>/<task>`。

`debug` 默认关闭是有意的：Guest Services 允许在沙箱内执行任意命令并访问文件。它适合开发、验证和故障排查，不应在不必要的生产任务上长期开放。

## 普通网络请求也走 atenet router

Task 不会各自创建 Kubernetes Service 或 Ingress。集群内外的请求都可以发给 Substrate 的 atenet router，并通过 `ate-target-actor` 选择目标 Actor。Router 会解析 Actor 当前在哪个 Worker，必要时先恢复已暂停的 Actor，再把请求转发过去。`Host` 与 `:authority` 保留给应用自身使用。

这一层把任务寻址与 Worker 地址解耦，但也意味着业务入口、认证、访问控制和流量策略需要围绕 Router 设计，而不是依赖每个 Task 的 Service 对象。

## Suspend 与 Resume 延续文件，不延续原进程内存

暂停时，Runner 收到 SIGTERM，先尝试让命令进程组清理退出；Substrate 对 DurableDir 建立数据快照。恢复时，Substrate 启动新的容器和进程树，把快照恢复到 `/workspace`。Runner 再次启动后，看到 `/ax` 下的初始化标记，会跳过 Maiden Run，直接使用恢复后的文件启动任务命令。

所以当前恢复语义要分两层理解：

- **能够延续：**Workspace 文件、仓库改动，以及 Agent 主动写入持久目录的检查点；
- **不会自动延续：**进程内堆栈、未落盘会话、内存队列、临时网络连接和外部系统中未确认的副作用。

如果希望“从上一步继续”，Agent 本身必须把可恢复状态写进持久目录，并让启动命令能够识别检查点。AX 提供的是恢复载体和生命周期，不会替 Agent 框架补上业务级 checkpoint 协议。

## 删除要同时清理 Actor、模板和资源记录

`ax delete task` 先把 Phase 标成 `Terminating`，随后删除同名 Actor，再按命名模式清理这个 Task 历次规格产生的 ActorTemplate；最后才删除 Redis 记录。Substrate 的 Actor 删除可能异步收敛，客户端会轮询到资源不存在，Task 删除命令因此比删除 Workspace 或 Model 使用更长的超时。

---

# 设计取舍决定了使用边界

## 不用 CRD 换来规模空间，也引入独立控制面

Redis 避开了 etcd 对海量短任务的存储与写入压力，也便于用 Pub/Sub 支持 watch。但 AX 因此需要自己维护 API Server、资源校验、分布式锁、索引、状态推送和调和逻辑。它获得了针对 Agent 工作负载的规模和语义自由，同时放弃了 Kubernetes 原生 CRD 自动拥有的生态能力。

## 声明式 Workspace 中嵌入了非确定性准备

Git、内联文件、固定路径等准备动作可复现；自然语言 `goal` 交给 Agent 后，环境准备会受模型、网络、软件源和当前仓库状态影响。当前 Runner 对 bootstrap 失败采取“记录后继续”，更适合提高启动容错性，却不适合作为严格验收。

生产落地时，建议把稳定、关键的依赖固化进镜像或确定性脚本，把 `goal` 留给探索性准备和低风险补充。若 goal 是任务成功的前提，应另加机器可判定的验证门。

## 控制面状态与工作负载状态刻意分离

Runner 命令退出后仍保持沙箱运行，方便调试；控制面目前不接收退出码。这意味着 `Running` 描述 Actor 与 Runner，而不代表业务命令仍在运行；`Ready` 描述环境可用，也不代表目标任务已经完成。

平台接入方应另外定义业务完成协议，例如写入完成文件、上报回调、记录产物清单，或由自定义 Runner 把退出状态传给外部系统。

## 安全由多层接线共同决定

当前默认 ActorTemplate 使用 gVisor，并通过 DurableDir 保存工作区。`debug=true` 会额外开放任意进程执行和文件访问。Workspace goal 的 Antigravity Agent 使用 workspace-only 文件策略，但 `run_command` 被允许；模型凭据可被注入任务环境。是否安全不能只看“用了沙箱”四个字，还要检查以下完整链路：

- Actor 的 SandboxClass 与安全配置；
- Task 镜像和 Runner 是否可信；
- Workspace 与运行阶段能拿到哪些凭据；
- egress、MCP Server 和 Registry 的访问范围；
- debug 是否关闭；
- Agent 写入持久目录和访问外部系统的权限。

Roadmap 计划把 Workspace Setup 与 Task Runtime 拆成不同 Actor，并分别执行最小权限策略。这说明当前版本仍在收紧初始化阶段和运行阶段的权限边界。

## Roadmap 不能当作已实现能力

官方 Roadmap 列出了尚在演进的方向：稳定 `v1alpha1` 规格，增加 `Sandbox / SandboxConfig`，迁移新 Actor API，拆分 Setup Actor，空闲检测与自动暂停，带状态分支的 Task Fork，动态环境策展，SPIFFE 身份，治理与预算护栏，以及 Runner 层的 OpenTelemetry 和轨迹采集。

评估当前 AX 时，应以源码和实际接口为准。例如 TaskStatus 已有 `pending_approval` 与 token usage 字段，Roadmap 也提到审批和预算，但当前控制面还没有完整的审批 RPC 与治理闭环。类型存在不等于功能已经可用。

## 适合与不适合的场景

### 更适合

- 需要在集群中批量运行隔离的编码、评测、数据处理或办公 Agent；
- 多种 Agent Framework 需要共用统一的 Task、Workspace 与生命周期；
- 工作负载需要暂停释放计算资源，并从持久工作区恢复；
- 需要用声明式资源预装仓库、工具、MCP 和 Skill；
- 平台团队愿意运营 Redis、AX Server、Substrate 与 Runner 镜像供应链。

### 暂不适合直接采用

- 只调用一次模型、没有隔离与恢复要求的简单服务；
- 主要问题是确定性 DAG 编排，而不是 Agent 运行环境；
- 需要稳定 API、成熟多租户治理和完整审计，但无法接受 `v1alpha1` 的快速变化；
- 期望暂停后原进程内存、会话与连接原样续跑；
- 需要以 Task 控制面状态直接判断业务成功，却不准备补充完成协议。

## 最值得复用的设计

即使不整体采用 AX，仍有几项设计值得借鉴：

- 用少量资源原语分开描述“执行单元”“工作环境”和“模型配置”；
- 把 Runner 设计成稳定协议，让 Agent Framework 与底层调度解耦；
- 把文件持久状态与进程短暂状态分开，明确恢复承诺；
- Phase 只给摘要，Conditions 解释可用性与原因；
- 调试能力默认关闭，并作为显式权限面处理；
- 面向海量短任务时，重新评估把所有对象塞进 CRD/etcd 的成本。

---

# 源码阅读地图

| 阅读目标 | 建议入口 | 重点关注 |
|---|---|---|
| 建立项目定位 | [`README.md`](https://github.com/google/ax/blob/ac2332829f22360ff97b0ba34d94dd0dd782f17e/README.md) | 三个原语、快速上手、CLI 语义 |
| 理解总体架构 | [`DESIGN.md`](https://github.com/google/ax/blob/ac2332829f22360ff97b0ba34d94dd0dd782f17e/DESIGN.md) | Redis 取代 CRD、组件和 RPC |
| 看资源 Schema | [`pkg/apis/v1alpha1/ax.proto`](https://github.com/google/ax/blob/ac2332829f22360ff97b0ba34d94dd0dd782f17e/pkg/apis/v1alpha1/ax.proto) | Task、Workspace、Model、Status、Conditions |
| 看 Manifest 校验 | [`pkg/apis/v1alpha1/types.go`](https://github.com/google/ax/blob/ac2332829f22360ff97b0ba34d94dd0dd782f17e/pkg/apis/v1alpha1/types.go) | 严格 YAML 解码、RFC 1123、Workspace 路径约束 |
| 理解 CLI | [`cmd/ax/main.go`](https://github.com/google/ax/blob/ac2332829f22360ff97b0ba34d94dd0dd782f17e/cmd/ax/main.go) | apply、watch、ssh、tunnel |
| 理解 API Server | [`internal/server/server.go`](https://github.com/google/ax/blob/ac2332829f22360ff97b0ba34d94dd0dd782f17e/internal/server/server.go) | Task 不可变、直接调和、状态更新 |
| 理解 Task 到 Actor | [`internal/controller/reconciler.go`](https://github.com/google/ax/blob/ac2332829f22360ff97b0ba34d94dd0dd782f17e/internal/controller/reconciler.go) | Template 摘要、resume、readiness、Conditions |
| 理解 Runner | [`runner/runner.go`](https://github.com/google/ax/blob/ac2332829f22360ff97b0ba34d94dd0dd782f17e/runner/runner.go) | Workspace 顺序、进程组、退出与停止 |
| 理解工作区准备 | [`internal/workspace/setup.go`](https://github.com/google/ax/blob/ac2332829f22360ff97b0ba34d94dd0dd782f17e/internal/workspace/setup.go) | Maiden Run、Git 重试、Marker、bootstrap |
| 理解 Substrate 接缝 | [`internal/substrate/client.go`](https://github.com/google/ax/blob/ac2332829f22360ff97b0ba34d94dd0dd782f17e/internal/substrate/client.go) | ActorTemplate、gVisor、DurableDir、快照 |
| 理解状态与 Watch | [`internal/store/redis/store.go`](https://github.com/google/ax/blob/ac2332829f22360ff97b0ba34d94dd0dd782f17e/internal/store/redis/store.go) | Redis Key、Index、Pub/Sub |
| 理解竞争控制 | [`internal/lock/lock.go`](https://github.com/google/ax/blob/ac2332829f22360ff97b0ba34d94dd0dd782f17e/internal/lock/lock.go) | SET NX、token 校验、释放通知 |
| 看未来方向 | [`docs/roadmap.md`](https://github.com/google/ax/blob/ac2332829f22360ff97b0ba34d94dd0dd782f17e/docs/roadmap.md) | Setup Actor、Fork、SPIFFE、治理、Telemetry |

# 快速上手

运行 AX 需要 Kubernetes 集群和已经部署的 Agent Substrate。随后安装 CLI，部署 Redis 与 AX Server：

```bash
go install github.com/google/ax/cmd/ax@latest
make deploy AX_IMAGE_REPO=<your-registry>
```

一个最小清单可以同时放 Workspace、Model 和 Task。下面只展示 Task 与 Workspace 的核心关系：

```yaml
apiVersion: ax.io/v1alpha1
kind: Workspace
metadata:
  name: golang
spec:
  git:
    - repo: https://github.com/golang/go.git
      branch: master
---
apiVersion: ax.io/v1alpha1
kind: Task
metadata:
  name: test
spec:
  command: ["bash", "-lc", "go test ./..."]
  workspaces:
    - name: golang
      path: /workspace/go
      goal: "Ensure that Go tool chain is available and built from source"
  debug: true
```

按当前源码语义，创建后再显式恢复：

```bash
ax apply -f task.yaml
ax resume task test
ax watch task test
ax describe task test
ax ssh test -- ls -la /workspace/go
ax suspend task test
ax resume task test
```

用于生产或重复实验时，应把镜像固定到 digest，减少 `goal` 承担的关键准备，关闭不必要的 `debug`，并为业务完成状态、产物上传和恢复检查点建立明确协议。

# 结语：AX 控制的是 Agent 的运行边界

AX 最有价值的地方不在于替 Agent 写了多少智能逻辑，而在于把运行边界变成平台契约：任务怎样声明，环境怎样装配，进程在哪里运行，哪些文件能在暂停后留下，怎样观察就绪，何时允许进入沙箱，以及删除时需要清理哪些外部资源。

它也把一条边界划得很清楚：控制面可以恢复工作目录和运行条件，Agent 自己仍要负责业务状态、幂等、副作用确认和任务完成协议。理解这条边界，才能判断 AX 应该成为平台底座，还是只借鉴其中的资源与 Runner 设计。
