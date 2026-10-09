# Orca 如何管理并行编程 Agent

Orca 把多个编程 Agent 放进可管理的开发环境：为任务安排工作目录，启动或连接 Agent，呈现执行状态，并让用户在桌面、手机和远程主机之间继续工作。理解它的关键，是分清**工作区、进程、会话记录和界面**。这些对象可以一起出现，却有不同的生命周期；窗口重开、网络恢复、历史记录恢复，也分别需要不同的机制。

本文面向有工程经验、尚未接触 Orca 的开发者，重点分析工作区创建、结构化消息投递、状态归属和终端恢复。编辑器、浏览器操作、账号管理等功能只在涉及架构边界时说明。

| 版本依据 | 本文采用的值 |
| --- | --- |
| 仓库 | [stablyai/orca](https://github.com/stablyai/orca) |
| 实际读取分支 | `main` |
| 完整 commit | `3dd7d294559309cc95b0143f6cece7404b2245c1` |
| `package.json` 版本 | `1.4.214`，仅代表该源码快照的包版本 |
| 资料读取日期 | 2026-09-28，Asia/Shanghai |
| 版本入口 | [固定源码树](https://github.com/stablyai/orca/tree/3dd7d294559309cc95b0143f6cece7404b2245c1)，[package.json](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/package.json#L1-L12) |

下文无特别标注的实现描述均来自这一 commit。标为“官方说明”的内容是仓库作者的描述；“本文归纳”是对代码关系的解释；示例和预期结果均不代表实际业务运行结果。本次未提供额外参考文档。

## 从多开终端到管理执行环境

只运行一个 Agent 时，终端加 Git 往往够用。并行工作后，问题变成了：两个 Agent 是否改同一个目录？哪一个仍在运行，哪一个只是没收到输出？桌面重启后，应当连接旧进程，还是重新启动？用户在手机上重试一次创建请求，会不会多出一个工作区？

Orca 把这些问题放进同一个产品。Git worktree 提供工作目录隔离，runtime 接收和组织操作，终端 daemon 持有 PTY，结构化会话 host 管理聊天记录与 Provider 子进程。外部 Agent 继续负责模型调用及其自身的工具执行策略。Orca 也有实验性的多 Agent 编排层，但不能据此把整个项目描述成一个统一的模型推理循环。

开源范围包括桌面代码、CLI、SSH relay、移动端，以及 `cloud/` 下的手机连接中继。根目录许可为 MIT，版权声明是 Lovecast Inc.；`cloud/README.md` 明确其代码沿用根许可。MIT 许可不提供外部模型服务的使用权，也不意味着所有 Agent 已安装或已登录。[许可](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/LICENSE)、[云端中继说明](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/cloud/README.md#L1-L18)。

成熟度应落实到可核对的机制。该版本已有跨平台构建脚本、单元测试和 Electron 端到端测试；与此同时，编排文档仍标记为 Experimental，状态统一工作也明确保留过渡路径。这些事实说明项目覆盖面较广、内部边界仍在演进，不能推出某种生产可用性或稳定性等级。本次没有测量性能，也没有核验所有平台的发布产物。[项目脚本](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/package.json)、[编排入口说明](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/docs/site/content/docs/cli/orchestration.mdx#L1-L35)。

## 先区分对象，再看模块

以下模型是**本文按职责归纳**，不是官方分层命名。

| 对象 | 负责表达什么 | 不能从它推出什么 |
| --- | --- | --- |
| Repository / Workspace | 仓库注册信息、工作目录和执行主机；工作区也可以是普通文件夹 | 有工作区不代表已有 Agent 进程 |
| Git worktree | 独立检出的目录、分支与 Git 状态 | 不提供容器级权限或网络隔离 |
| Terminal / PTY Session | Shell 和 CLI Agent 所在的终端进程，以及输出和终端模式 | 有滚屏历史不代表进程仍活着 |
| Structured Agent Session | 原生聊天的稳定身份、journal、操作记录及 Provider 关联 | 打开聊天不必立即启动 Provider 子进程 |
| Agent Status | 对执行证据的汇总，供侧栏、CLI 等读取 | `working` 不是操作系统级的永久存活证明 |
| Run / Task / Dispatch | 编排命名空间、工作项及某次执行尝试 | Run 本身不替协调者决定下一步派谁做什么 |

工作区可为文件夹这一点直接影响创建链路：`createManagedWorktree` 遇到 folder repo 会转入注册流程，不执行 Git worktree 创建。结构化会话则把 conversation 和 Provider child 分开，`StructuredAgentSessionHost` 通过会话访问器打开记录，只在需要执行时启动 Agent。[工作区路由](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/runtime/orca-runtime-create-managed-worktree.ts#L85-L139)、[结构化会话 host](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/native-chat/agent-session-wire/structured-agent-session-host.ts#L4-L7)。

贯穿全文使用一个**说明性示例**：项目 `demo-api` 需要修复“空输入导致异常”，同时补回归测试。开发者创建两个 worktree，分别试验实现和测试，并在一个原生聊天中发送“修复空输入”。这些名称、消息和过程都为解释机制而设，未在本次环境执行。

![Orca 控制入口与执行归属](assets/architecture.png)

图中区分两类执行路径。PTY 路径运行终端程序，结构化路径经 Provider adapter 交换消息与事件。当前结构化 adapter router 明确路由 `claude` 和 `codex`，还要检查执行位置是否受支持。因此 README 所说“可以运行任意 CLI Agent”应理解为终端兼容面，不能扩展为所有 Agent 都支持相同的原生聊天协议。[Adapter Router](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/native-chat/agent-session-wire/structured-agent-session-adapter-router.ts#L8-L26)。

另一个容易混淆的名称是 relay。`src/relay/` 是 SSH 执行侧代理；`cloud/` 的 relay 是连接手机和桌面 host 的服务。前者处理远端 PTY 等执行操作，后者转发连接帧。阅读源码时不能只凭“relay”一词把它们当成同一组件。

## 入口如何抵达真正的实现

桌面入口 `src/main/index.ts` 主要组织启动、窗口与退出流程。业务调用继续进入 runtime、IPC handler 和具体服务。CLI 的 `worktree create` 则明确调用 `RuntimeClient.call('worktree.create', …)`，RPC 方法解析参数后进入 `createManagedWorktree`。因此，分析工作区创建应沿调用向下读，不能停在 CLI 参数声明或 UI 按钮。[桌面入口](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/index.ts#L1-L15)、[CLI 创建 handler](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/cli/handlers/worktree.ts#L185-L254)、[RPC 方法](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/runtime/rpc/methods/worktree.ts#L78-L120)。

`OrcaRuntimeService` 的实现拆在多个 `orca-runtime-*` 文件中，通过继承链组织。文件里有些类名只是机械拆分形成的承接层，不宜据此画出几十层“架构”。更有解释力的边界是：谁接受请求，谁选择执行主机，谁写持久状态，谁持有真实进程。

远端独立 runtime 还有 `src/main/orcad/orcad-entry.ts` 入口。它装配自己的 profile store、hook server 和 runtime 服务，不能假定所有请求都必须经过桌面 renderer。反过来，直接 SSH 的控制面仍可能留在桌面端；二者的离线行为将在后文比较。[orcad 装配入口](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/orcad/orcad-entry.ts)。

## 创建 worktree 是分阶段的操作

### 从请求到可用目录

在示例中，创建 `fix-empty-input` 的输入包括仓库选择器、名称、base ref，以及可选的 startup Agent 和 prompt。沿 CLI/RPC 路径，核心顺序如下。

1. **识别请求与执行主机。** RPC 调用 `dedupeWorktreeCreate`；`createManagedWorktree` 解析 repo，检查所选 Agent 是否被禁用，并构造启动计划。`resolveWorktreeCreateRoute` 决定本地、SSH 或其他 runtime 归属。不能把一个远端路径直接交给本机 Git。
2. **确定 base 与候选名称。** `createRuntimeLocalManagedWorktree` 同时启动用户名和 base 的只读查询，再解析分支和目标路径。没有可用默认 base 时，明确要求调用者指定 `--base`。
3. **落实 Git checkout。** `createRuntimeLocalGitWorktree` 处理 remote-tracking ref 和刷新结果，然后尝试消费预备 worktree。未命中时走普通 `addWorktree`，稀疏模式则走 `addSparseWorktree`。
4. **记录元数据并准备目录内容。** `materializeRuntimeLocalWorktree` 写入 `instanceId`、base、展示名称、关联任务等信息，然后处理配置的链接目录、共享目录和包含文件复制。
5. **准备 setup 和启动终端。** 上层运行 setup 准备逻辑、刷新相关缓存并发出 worktree 变更通知，再启动终端。返回值可以包含工作区、warning、setup receipt 和 startup terminal handle。

源码入口分别为：[创建总流程](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/runtime/orca-runtime-create-managed-worktree.ts#L17-L310)、[本地创建阶段](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/runtime/runtime-local-worktree-create.ts#L50-L146)、[Git 创建与预备 checkout](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/runtime/runtime-local-git-worktree-create.ts#L69-L195)、[目录与元数据处理](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/runtime/runtime-local-worktree-materialization.ts#L65-L160)。

这里有一个具体的加速设计：预备 checkout 可以提前完成一部分工作，创建请求命中后消费它；补充预备资源的 `rearm.fire()` 放在最外层 `finally`。这样后续复制文件或终端启动失败时，也不会永远漏掉补充动作。代码还刻意把补充动作推迟到前台创建流程之后，避免立即重建预备资源与当前启动争用资源。它的代价是多了一套预备资源的有效性判断和失败收尾，不能把每次创建都简化为一条 `git worktree add`。[预备资源消费](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/runtime/runtime-local-git-worktree-create.ts#L140-L184)、[finally 收尾](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/runtime/orca-runtime-create-managed-worktree.ts#L17-L31)。

### “创建成功”并不等于“Agent 做完了”

Git checkout、元数据保存和终端启动不是一个跨资源事务。元数据是在目录链接和文件复制之前写入 store 的；`setWorktreeMeta` 更新内存状态并调用 `scheduleSave`，所以名为 `onMetadataPersisted` 的回调也不能被直接解释为磁盘已经完成强制同步。后续失败时，应分别检查 Git 目录、Orca 元数据和终端状态，不应凭一个错误返回就断言“没有创建任何东西”。[元数据写入顺序](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/runtime/runtime-local-worktree-materialization.ts#L74-L156)、[store 保存调度](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/persistence/loading-store/metadata-lineage-operations.ts#L111-L127)。

返回的 `setupReceipt.state` 可能是 `running`、`skipped`、`not_configured` 或 `spawn_failed`。即使 `startupTerminal.spawned` 为真，也只是启动阶段的结果，并没有证明提示词已经完成，更没有证明代码已经通过测试。工作区变更通知还可以先于终端启动完成到达订阅者。[结果构造](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/runtime/orca-runtime-create-managed-worktree.ts#L218-L325)。

默认 base 的刷新也有条件：如果已有 remote-tracking ref，刷新失败不一定阻止创建；缺少该 ref 且刷新失败则报错。前一种情况允许继续工作，也意味着基线未必是服务器上的最新提交。对需要严格复现的任务，应使用明确的 commit/ref，而不是把“点了创建”当成“已同步最新代码”。[base 刷新分支](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/runtime/runtime-local-git-worktree-create.ts#L69-L109)。

### 重复请求只在有限窗口内合并

`dedupeWorktreeCreate` 的 key 是 `repoSelector + '\0' + clientMutationId`。同一 key 的并发调用共享 Promise，成功结果保留 60 秒，失败立即移除；没有 key 就直接执行。缓存存在于当前 runtime 的内存中。

因此，手机因连接切换丢失响应后，在窗口内携同一 ID 重试，可以拿回原来的创建结果。它不提供跨重启、无限期的 exactly-once 语义；同名分支冲突也不是这套机制处理的同一种问题。调用者应保存返回的工作区身份，而非不断生成新请求 ID 重试。[实现](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/runtime/orca-runtime-terminal-create-deduplication.ts#L174-L203)、[60 秒常量](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/runtime/orca-runtime-core.ts#L72)、[去重测试](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/runtime/orca-runtime-tests/dedupe-worktree-create.spec.ts)。

## 原生聊天如何可靠地接收一条消息

这是 Orca 比“把字符串写进终端”更深的一层。示例中的“修复空输入”进入结构化会话后，系统要分别回答：消息是否已记录、是否已交给 Provider、Provider 是否完成本轮工作。

![结构化消息时序](assets/send-sequence.png)

图示的是一次正常路径及异常分支。接收响应与后台投递的具体到达顺序可能交错；有严格顺序要求的是：**先提交接收记录，再进行投递；先记录 pending，再调用 adapter**。Provider 事件也可能先于投递调用的最终返回到达。

### 同一个消息 ID 不重复投递

`sendStructuredAgentSessionTurn` 在会话的串行队列里调用统一 mutation admission。`sendPlan` 将 `clientOperationId` 用作 `clientMessageId`，使用全局 operation ID 作用域，并对 body 计算、核验请求身份相关信息。`performSend` 查找已有 submission：同一 ID 但 payload fingerprint 不同会拒绝，同一消息则重放已存记录。

首次接收调用 `journal.appendSubmission`。写入失败时返回“未记录、未发送”；写入成功返回 submission，并唤醒 delivery loop。返回的 mutation 结果还带 `replayed`、`fence` 和 journal `cursor`，调用方可以把乐观显示的消息与 host 记录对齐。[发送入口](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/native-chat/agent-session-wire/structured-agent-session-host-mutations.ts#L79-L145)、[发送计划](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/native-chat/agent-session-wire/structured-agent-session-mutation-plans.ts#L42-L96)、[接收实现](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/native-chat/agent-session-wire/structured-agent-session-turns.ts#L97-L139)、[admission 与返回值](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/native-chat/agent-session-wire/structured-agent-session-mutation-admission.ts#L105-L164)。

这里的 `fence` 是写入代际边界，journal 不接受落后于当前有效边界的写入。它约束旧执行者继续写入的风险。它与客户端消息去重解决不同问题：前者处理“谁还有资格写”，后者处理“这次操作是否已经记录”。[Journal 写入检查](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/native-chat/agent-session-journal/journal-row-writer.ts#L20-L38)。

### Journal 的提交早于外部动作

当前 journal 使用 SQLite。数据库开启 WAL、5 秒 busy timeout 和 `synchronous = FULL`。每条 row 的插入与 session 投影更新位于同一个 `BEGIN IMMEDIATE` 事务，`COMMIT` 后才采纳为内存中的新序号。作者在代码中明确说明，FULL 用于让发送前的记录获得比 WAL/NORMAL 更强的断电持久性。[数据库配置](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/native-chat/agent-session-journal/journal-database.ts#L23-L79)、[事务写入](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/native-chat/agent-session-journal/journal-row-writer.ts#L17-L41)。

这个设计避免“消息已经交给 Provider，本地却连发送记录都没有”的常见窗口，但没有把数据库和外部 Provider 变成同一个事务。实际介质与文件系统的持久性仍属于运行环境条件；本文未做断电实验。

数据库版本也有保护：先检查 `user_version`，发现比当前实现更新的 schema 时，改以只读方式打开，不先修改 WAL 配置或表结构。版本降级至少不会因这条打开路径擅自写坏新格式。[新 schema 只读分支](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/native-chat/agent-session-journal/journal-database.ts#L23-L39)。

### 投递循环允许停止操作插入

`StructuredAgentSessionDeliveryLoop` 每个 session 只运行一个 loop。它读取最早的 queued submission，启动或复用 Provider child，再调用 `handOverSubmission`。等待 Provider 初始化完成的 `awaitStarted` 放在会话串行队列之外；随后回到队列重新核对 child 的 generation/fence 和消息状态，才交付内容。

这样，用户在启动过程中按 Stop，停止请求仍能进入队列：先撤销排队消息，必要时停止尚在 starting 的 child，而会话记录保留。循环把准备与交付拆为多个串行步骤，也避免了“开始等待时成立的状态，在真正发送时已过期”。[投递循环](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/native-chat/agent-session-wire/structured-agent-session-delivery-loop.ts#L75-L202)、[停止流程](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/native-chat/agent-session-wire/structured-agent-session-host-mutations.ts#L147-L205)。

交付前，`handOverSubmission` 先写 `dispatchState = pending`，再执行 `adapter.dispatch`。得到接受或拒绝结果后更新 journal；如果 adapter 只报告 `admitted`，暂时保持 pending，等待后续确认。这几个状态都不能直接替代“本轮执行成功”。[交付代码](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/native-chat/agent-session-wire/structured-agent-session-turns.ts#L146-L198)。

### 超时留下不确定性，而非自动重试

当已经启动的 adapter 抛出异常，host 无法仅凭异常分辨“Provider 没收到”与“收到后响应丢失”，因此记录为 `unknown`。同一个消息 ID 再来仍只重放记录，不自动发第二遍；兼容字段 `retryUnknown` 也不改变这个约束。如果 child 尚未证明启动成功，代码才可以把无法接收的投递判为 rejected。[异常分类](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/native-chat/agent-session-wire/structured-agent-session-turns.ts#L59-L82)、[不重复投递约束](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/native-chat/agent-session-wire/structured-agent-session-mutation-plans.ts#L48-L60)。

这获得的是“有记录的同一发送不会因盲重试重复下发”，代价是某些消息需要保留不确定结果，不能保证每条消息最终自动送达。用户重新发起一条新消息应使用新 ID，但在此之前要判断旧请求是否已经执行，尤其当它会修改文件或运行命令时。

重启也不是无条件续跑队列。delivery loop 会拒绝在当前 journal handle 打开之前遗留的 queued submission，注明 host 已重启；已经可能交付的 pending/unknown 则不能当作“肯定没发过”。该选择优先避免重复执行，牺牲了部分自动继续能力。[重启遗留处理](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/native-chat/agent-session-wire/structured-agent-session-delivery-loop.ts#L125-L153)。

## 状态汇总为何必须记录归属

示例中的 Agent 已经结束主回复，但它启动的后台任务仍在运行，此时侧栏应该显示什么？如果桌面、手机和 CLI 各自从文字或缓存推测，就容易得出不同结论。

Orca 的设计原则是执行主机拥有状态，读者订阅状态。不过，**当前版本仍处于迁移阶段**。参考文档开头明确标记为 PR 2A 边界：结构化会话进入完整作用域的 canonical store，未绑定的 PTY/relay 证据仍走隔离的 legacy adapter，renderer bridge 也尚未全部删除。不能把同一文档后面描述的目标状态全当成已完成实现。[当前边界说明](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/docs/reference/agent-status-store.md#L1-L18)。

### 状态身份不能只有 paneKey

`AgentStatusSubject` 包含执行主机、WSL distro、workspace ID、workspace kind，再加上 PTY run、PTY pane 或 structured session 身份。序列化 key 把这些部分一起保存。相同 pane 名或相同路径出现在另一台机器时，不应自动指向同一条执行记录。[身份类型与序列化](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/shared/agent-status-subject.ts#L13-L39)、[key 构造](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/shared/agent-status-subject.ts#L169-L211)。

`ingestStructuredStatus` 会核对 subject 与 summary 的 session/workspace 是否一致；如果结构化地址与 legacy evidence 冲突，直接报错。写入结果同时保留整体 `state` 和主 Agent 自身的 `mainAgent`。整体状态可以把未完成后台任务折算进去，主 Agent 的完成结果仍单独存在。这样“主回复已完成，但后台任务仍在工作”不会被压扁成一个无法解释的布尔值。[结构化状态归入](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/agent-hooks/server/server-ingest-structured.ts#L25-L113)。

### 副本需要连续的版本，而非最后一次到达优先

`createAgentStatusStore` 支持 authority 和 replica 两种模式。只有 authority 接受本地 `applyMutation`；replica 需要先接受 snapshot，后续 mutation 的 epoch、previousRevision 和 revision 必须与本地连续匹配。乱序、重复或跨 epoch 的增量返回 false；调用层需要据此处理同步失败，不能把拒绝增量自动描述为“底层已完成重新同步”。[状态存储实现](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/shared/agent-status-store.ts#L60-L185)。

这是有明确条件的复制协议：epoch 区分一代状态，revision 表达本代内的顺序。它不是多主写入合并，也不是允许任意客户端修改远端事实的 CRDT。

### 持久状态不自动成为活状态

PTY hook 状态文件采用 250 毫秒 debounce，写临时文件后 rename。恢复时丢弃超过七天的条目，并把恢复记录标成 `restoredUnconfirmed`。结构化行不写进这份 `last-status.json`，它们从 journal 重新发布，避免形成两份互相竞争的持久来源。[持久化实现](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/agent-hooks/server/server-persistence.ts#L17-L138)、[时间常量](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/agent-hooks/server/server-constants.ts#L3-L23)、[恢复标记](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/agent-hooks/server/server-hydration.ts#L73-L110)。

因此，重启后能显示上次 Agent 的信息，和系统已经确认它仍在执行，是两件事。该状态文件的临时写入与 rename，也不能套用前一节 SQLite FULL 的持久性结论。

## 终端恢复要同时处理进程和画面

### 活进程重连

本地 daemon 持有 `TerminalHost`，后者持有 Session 和真实 PTY。`createOrAttach` 按 session ID 管理正在创建的 Promise，同一个 ID 的并发创建先等前一个操作结束，避免异步 spawn 重复启动进程；等待支持取消。不同 ID 不需要因这张表而串行。[同 ID 创建约束](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/daemon/terminal-host.ts#L77-L120)、[并发测试](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/daemon/terminal-host-concurrent-create.test.ts)。

已有 session 活着且未终止时，`createOrAttachTerminalSession` 同步取 snapshot，分离旧 client 并附加新 client，返回 `isNew: false`、PID 和 incarnation。`attachOnly` 的含义也很重要：它要求连接既有 session，不能在找不到时悄悄当作新建。[连接既有 session](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/daemon/terminal-host-session-create.ts#L32-L98)。

快照包含 ANSI 画面、normal-buffer scrollback、模式恢复序列、尺寸、cwd 和可选的 output sequence。完整终端恢复不能只把最后一段纯文本塞回界面：TUI 可能使用 alternate screen、光标控制、括号粘贴等模式。仓库中的 reattach 测试把快照灌入新的 headless emulator，再加入重绘输出检查结果；这正对应“旧进程继续跑，新界面恢复画面”的场景。[快照结构](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/daemon/terminal-snapshot.ts)、[重连画面测试](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/daemon/reattach-snapshot.test.ts#L38-L75)。

### 历史恢复

若活进程已经不存在，磁盘历史仍可能帮助恢复可读画面。`buildDurableCheckpointSnapshot` 以 live snapshot 为当前内容权威，只让磁盘历史补充已从 live normal buffer 淘汰的较早行。不能用旧快照覆盖当前活画面，也不能把冷恢复出来的文本解释为“旧进程从原 CPU 状态继续执行”。[历史合成](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/daemon/daemon-durable-history-snapshot.ts#L18-L90)。

对于 Agent，继续先前语义上下文还依赖 Provider 的会话身份和 resume 能力。滚屏、Orca 会话记录和 Provider 内部上下文具有不同用途，保存其中一种不等于另外两种也已保存。

### 升级后连接哪一代 daemon

该版本 daemon 协议号是 36，同时列出 1 至 35 的旧协议版本。`DaemonPtyRouter` 为 session 保存所属 adapter，既有 session 可以路由到保留的旧 daemon，新 session 默认使用当前 daemon。这让“应用升级”和“终端进程必须结束”不再强制绑定，但增加了协议能力判断和多代进程路由的成本。[协议版本](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/daemon/daemon-protocol-version.ts)、[路由实现](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/daemon/daemon-pty-router.ts#L17-L90)。

这并不保证任意退出动作都保活。显式终止、操作系统进程回收、服务管理器清理整个 cgroup，都可能结束 PTY。对特定版本、平台和退出方式的保活承诺，需要单独运行相应测试。

## 远端失联时为何不能自动重开

直接 SSH 路径中，远端 relay 拥有 PTY，但远端 `orca` shim 的控制请求仍代理回客户端 runtime。连接断开时，PTY 可能继续跑，shim 却会因没有 owning client 而失败。若任务必须在桌面离线期间继续使用 Orca 控制能力，应该选择在远端拥有独立控制面的 runtime 模型。[执行边界说明](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/docs/reference/ssh-execution-boundary.md)、[shim 请求无主拒绝](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/relay/dispatcher-rpc-routing.ts#L25-L58)。

这解释了为什么远端状态采用三种进程判定。

| 判定 | 所需证据 | 不能替代它的现象 |
| --- | --- | --- |
| `live` | 执行主机确认当前身份的进程仍在 | 本地还有一行缓存 |
| `unverifiable` | 无法得到足够主机证据 | 不能因此重标为 exited |
| `exited` | 执行主机给出与当前身份对应的退出证据 | 超时、断网、本地集合里没找到 ID |

源码中甚至区分两种相似的 not-found：relay 的 session map 没这个 ID，只返回普通 `PTY "…" not found`；真正经过存活探测确认进程已退出，才附带 `process exited` marker。旧 relay 不带 marker，也不能被当成退出证明。本次直接调用该识别函数，核对了普通缺失、身份不符和已证实退出三种输入。[attach 判定](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/relay/pty-handler.ts#L2093-L2129)、[证据识别函数](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/shared/pty-attach-absence-evidence.ts)。

直接 SSH 的恢复还有两个限制。

首先，relay 配有 `100 * 1024` 的近期输出 buffer，按 JavaScript 字符串 code unit 计量。它不是无限完整日志；超出保留范围的输出不能仅靠这一 buffer 找回。不过当前 attach 已有 source recovery/checkpoint 分支，不能把旧文档中的 tail replay 描述当成所有协商路径的完整模型。本次只确认有限 buffer 和 attach 分支，未实测不同客户端组合的完整恢复范围。[buffer 常量](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/relay/pty-handler.ts#L351)、[source recovery 分支](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/relay/pty-handler.ts#L2140-L2195)。

其次，直接 SSH relay 的安装目录包含 bundle 内容版本，握手要求版本相同。应用更新改变 bundle 后，新客户端可能连接到新安装的 relay，而旧 relay 仍持有活进程。官方边界文档明确记录了这种“进程可能继续运行，但新客户端失去原连接”的问题。代码中的目录模型和严格握手与此一致；这不是前一节本地 daemon 多代协议路由的同一种保证。[安装目录计算](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/ssh/ssh-relay-versioned-install.ts#L72-L95)、[严格版本握手](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/relay/relay-handshake.ts#L111-L140)。

对示例里的远端修复任务，连接失败后应先恢复与 owning host 的联系、检查对应工作区与执行身份，再决定是否重新发起任务。否则，同一个目录中可能同时存在失联的旧执行和新启动的执行。

## 编排层如何约束任务完成

并行打开两个 Agent，不等于已经建立任务依赖、完成确认和消息消费语义。Orca 的实验性 orchestration 层进一步引入 Run、Task、Dispatch、worker 和 decision gate。官方文档明确：Run 是持久命名空间和协调者 inbox，本身不负责放置 worker；Task 描述工作与依赖，Dispatch 表示一次执行尝试。[编排模型](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/docs/site/content/docs/cli/orchestration.mdx#L19-L35)。

套到说明性示例中，可以把“修复实现”和“补回归测试”作为 Task，分别交给某个 Dispatch。某个 Agent 的侧栏变成 done，与协调任务被正确结算仍是两种事件；worker 的完成消息要携带 task/dispatch 身份和明确 outcome。协调者消费 Delivery 后需要 ack，未确认的 Delivery 会重放，不能把“消息显示过”当成“工作已完成且通知已消费”。这些是官方协议约定，调用方也必须遵守。[监督执行与消费流程](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/docs/site/content/docs/cli/orchestration.mdx#L37-L78)、[消息语义](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/docs/site/content/docs/cli/orchestration.mdx#L111-L150)。

代码对任务状态也做了实际约束。`updateTaskStatus` 先取得生命周期写事务，再检查 active Dispatch 和 supervised worker；没有 active Dispatch 就不能直接设成 dispatched，仍有活跃 supervised worker 时也不能任意把任务结算或重新打开。合法完成后才提升依赖任务的 ready 状态。这让数据库状态不至于脱离仍在执行的 worker，但不能替协调者判断代码是否正确。[任务状态事务](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/runtime/orchestration/db/tasks/task-status-transition.ts#L14-L120)。

该层并未在本文中做端到端验证。它适合在理解工作区、会话和执行主机边界以后继续研究，不宜作为首次体验 Orca 的最小路径。

## 能力来自哪些取舍

| 具体机制 | 获得的能力 | 成本或限制 |
| --- | --- | --- |
| Git worktree 加 Orca 元数据 | 多个分支各有工作目录，任务与目录可关联 | 仍共享主机资源；链接目录还可能有意共享文件；不是安全沙箱 |
| 终端执行与结构化 adapter 并存 | 保留 CLI 兼容面，同时提供可追踪的消息与事件 | 两条路径的恢复、状态和 Provider 支持范围不同 |
| 接收记录先提交，再异步投递 | 响应丢失后可对齐同一消息，减少重复下发 | 出现 unknown 时无法靠简单自动重试解决 |
| 会话串行队列与 generation/fence | 控制同一会话的并发写入，拒绝过期执行者 | 需处理启动、取消、退出和记录恢复之间的边界 |
| 执行主机拥有事实，读者保留呈现策略 | 减少各端独立推导状态造成的冲突 | 当前仍有 legacy adapter 和 renderer bridge，不能假设迁移已经完成 |
| daemon 独立于界面且保留旧代路由 | 界面重建或部分升级时可重连活终端 | 多协议、快照及进程代际的组合更复杂 |
| 直接 SSH 与独立 runtime 两种部署模型 | 同时覆盖轻量远端执行和远端独立控制 | 离线行为不同，同一主机重复登记会造成身份和管理混乱 |

由这些机制可以判断适用场景，而不必从功能数量推测。

**适合优先尝试的场景**是已有 CLI Agent、经常并行修改多个分支、需要随时回到执行现场的开发工作。收益主要来自目录、终端和会话的连续管理。若还要从手机继续查看或操作，则需要进一步验证自己采用的连接和执行模型。

**需要额外工程建设的场景**包括长期无人值守、远程故障恢复和严格审计。应明确配置 runtime 的服务管理方式、独立产物保存、执行超时、业务级去重及访问控制；不能仅凭终端历史或侧栏状态承担这些责任。

**不应直接把它当作的系统**包括多租户不可信代码沙箱、带业务 exactly-once 承诺的通用工作流引擎，以及对所有 Agent 提供同等结构化能力的统一模型 SDK。这些判断限于本文核对的路径：worktree 只隔离目录，外部动作不在 journal 事务内，adapter router 的支持范围也有明确限制。

## 按问题阅读源码

下面给出一条学习顺序。每一步以一个问题收束，避免从顶层目录一路漫游。

| 顺序与问题 | 文件和关键符号 | 阅读时应核对的结果 |
| --- | --- | --- |
| 1．一个操作怎样进入 host？ | [CLI worktree handler](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/cli/handlers/worktree.ts)、[RPC worktree 方法](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/runtime/rpc/methods/worktree.ts) | 识别参数解析、RPC 边界与 runtime 调用，不把 handler 当作 Git 实现 |
| 2．目录究竟何时创建？ | [createManagedWorktree](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/runtime/orca-runtime-create-managed-worktree.ts)、[本地 Git 创建](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/runtime/runtime-local-git-worktree-create.ts) | 画出 base、预备 checkout、Git、元数据、setup、终端的顺序 |
| 3．重复创建怎么合并？ | [dedupeWorktreeCreate](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/runtime/orca-runtime-terminal-create-deduplication.ts#L174-L203) | 找到 key、成功窗口、失败清理和无 key 行为 |
| 4．消息什么时候真的发送？ | [sendPlan](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/native-chat/agent-session-wire/structured-agent-session-mutation-plans.ts)、[performSend / handOverSubmission](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/native-chat/agent-session-wire/structured-agent-session-turns.ts) | 区分接收、pending、adapter 调用和后续事件 |
| 5．记录如何抵抗中断？ | [JournalRowWriter](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/native-chat/agent-session-journal/journal-row-writer.ts)、[DeliveryLoop](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/native-chat/agent-session-wire/structured-agent-session-delivery-loop.ts) | 核对 COMMIT、fence、队列外等待、重启遗留和 unknown |
| 6．谁有资格改变状态？ | [AgentStatusSubject](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/shared/agent-status-subject.ts)、[createAgentStatusStore](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/shared/agent-status-store.ts)、[ingestStructuredStatus](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/agent-hooks/server/server-ingest-structured.ts) | 分开作用域、复制顺序、主 Agent 与后台任务 |
| 7．旧终端如何回来？ | [TerminalHost](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/daemon/terminal-host.ts)、[createOrAttachTerminalSession](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/daemon/terminal-host-session-create.ts)、[DaemonPtyRouter](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/daemon/daemon-pty-router.ts) | 判断取快照、连活进程、冷恢复和新建进程各自的条件 |
| 8．远端没回应意味着什么？ | [SSH 边界文档](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/docs/reference/ssh-execution-boundary.md)、[relay attach](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/relay/pty-handler.ts#L2093-L2195) | 分辨失联与已证实退出，再追版本和身份检查 |

看实现后读对应测试，重点包括：

- [创建去重测试](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/runtime/orca-runtime-tests/dedupe-worktree-create.spec.ts)：并发共享、成功重放、失败重试、仓库作用域。
- [发送去重测试](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/native-chat/agent-session-wire/structured-agent-session-send-idempotency.test.ts)：跨 caller ledger 重用同一个发送 ID 不重复 dispatch。
- [journal 事务测试](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/native-chat/agent-session-journal/journal-row-writer.test.ts)：插入失败如何回滚。
- [状态存储测试](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/shared/agent-status-store.test.ts)：authority/replica、snapshot 和增量约束。
- [terminal 并发创建测试](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/daemon/terminal-host-concurrent-create.test.ts)、[重连画面测试](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/main/daemon/reattach-snapshot.test.ts)：身份复用和快照语义。
- [relay attach 测试](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/src/relay/pty-handler-attach-replay.test.ts)：不存在与已证实退出的区别。

这些是已阅读的测试证据，不代表本次执行了整套测试。

## 最小上手与验证

推荐先验证本地 worktree 和普通终端，再加入 Agent。这样不依赖付费模型调用，也不会把登录、网络和 Provider 差异混进第一轮检查。

### 前置条件与固定版本

该 commit 的 `package.json` 要求 Node.js 24，固定 `packageManager` 为 pnpm 12.0.0。还需 Git；原生依赖的构建环境随操作系统而异。官方贡献说明的本地路径是 `pnpm install` 后 `pnpm dev`，普通安装只覆盖当前 OS/CPU。[版本要求](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/package.json)、[本地开发说明](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/.github/CONTRIBUTING.md#L17-L28)。

以下命令**依据官方说明和固定源码整理，未在本次环境完整运行**。clone 和版本核对已在研究环境执行；依赖安装与应用启动未执行。请使用单独研究目录。

```bash
git clone https://github.com/stablyai/orca.git
cd orca
git checkout 3dd7d294559309cc95b0143f6cece7404b2245c1
git rev-parse HEAD
node --version
pnpm --version
pnpm install --frozen-lockfile
pnpm dev
```

手工体验时，启动桌面程序后添加一个可丢弃的测试仓库，创建一个不附带 Agent 的 worktree，并在普通终端执行只读命令 `git rev-parse --show-toplevel` 和 `git branch --show-current`。预期是目录对应新 worktree、分支对应创建结果；只看到侧栏项目不能代替这个检查。不要用生产仓库的 setup 脚本做第一次实验。

随后关闭并重新打开终端视图，观察历史和进程是否分别恢复。可以先在 shell 中运行 `echo $$` 记录 PID；相同 PID 只能作为辅助证据，还应结合 Orca 的 session/incarnation 与主机情况。若测试应用重启，必须记录退出方式；不能把视图重开结果推广成整机重启后仍保留进程。

这一步不需要启动 Agent。要验证结构化聊天，再安装、登录受支持的 Provider，并明确其费用和工作目录权限；本次未执行该步骤，也未调用 Agent Provider API。

### 先跑有针对性的测试

安装依赖后，可用仓库原有 Vitest 路径检验本文的主要不变量。下面命令同样**未在本次环境运行**。

```bash
ORCA_BACKGROUND_LAUNCH=1 pnpm test \
  src/shared/agent-status-store.test.ts \
  src/main/native-chat/agent-session-wire/structured-agent-session-send-idempotency.test.ts \
  src/main/native-chat/agent-session-journal/journal-row-writer.test.ts \
  src/main/daemon/terminal-host-concurrent-create.test.ts \
  src/main/daemon/reattach-snapshot.test.ts \
  src/relay/pty-handler-attach-replay.test.ts
```

`pnpm test` 会先执行原生运行时准备脚本，并不是只解释几个 TypeScript 文件。Agent 自动运行测试或应用时应遵守仓库规定，使用 `ORCA_BACKGROUND_LAUNCH=1`，避免测试窗口夺取焦点。[测试脚本](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/package.json)、[仓库测试约束](https://github.com/stablyai/orca/blob/3dd7d294559309cc95b0143f6cece7404b2245c1/AGENTS.md#L5-L12)。

### 本次实际验证及其边界

本次已下载固定 commit，阅读上述实现和测试，核对包版本及许可，检查文档引用目标和行范围，并将两张确定性 SVG 图渲染为 PNG 后逐张检查。

代码执行验证采用本机 Node.js `v22.23.1`，只直接导入无需第三方依赖的源码函数和常量：普通 PTY 缺失不算已退出、身份不符不算已退出、带明确 marker 才算已退出；daemon 当前版本为 36、旧版本列表为 1 至 35；startup ingress 能力在版本 24/25 的边界符合实现。**7 项断言通过**。这不是项目要求的 Node 24 全量测试环境，也不能证明真实 SSH 或 Electron 流程通过。

曾尝试直接加载完整状态存储进行独立 smoke 检查，但先遇到 TypeScript 参数属性转换限制，调整后又因未安装 `zod` 停止。未安装整套依赖，因此没有得到该项运行结论；状态复制部分依据实现和仓库测试阅读确认。完整构建、原生模块、断电恢复、手机连接、SSH 重连与付费 Provider 行为均未实测。对部署决策有影响的部分，应在目标平台补做验证。

## 结语

Orca 最值得理解的工程选择，是让工作区、活进程和可恢复记录各自保有身份，再明确规定它们怎样连接。这样，用户可以并行推进任务，也有机会在界面或连接变化后回到同一份工作。

相应的判断原则也很具体：worktree 隔离不等于安全隔离，消息接收不等于执行完成，历史可读不等于进程存活，远端失联不等于可以安全重跑。接受这些边界后，才能正确使用它的恢复机制，并判断哪些可靠性责任还需要自己的工程系统承担。
