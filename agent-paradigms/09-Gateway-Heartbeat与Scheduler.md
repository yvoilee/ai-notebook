# 09 · Gateway、Heartbeat 与 Scheduler

> 核验日期：2026-08-30  
> 主项目：OpenClaw / TypeScript  
> 对照项目：Hermes Agent、goose、Letta Code

---

## 1. 一句话掌握

Gateway 管理多渠道接入与会话路由，Heartbeat 驱动主动循环与租约续期，Scheduler 负责定时任务的投递、去重与恢复——三者让 Agent 从"有人打字才动"变成"常驻运行的系统"。

---

## 2. 为什么需要它

### 问题从何而来

绝大多数 Agent Demo 的生命周期是：用户发消息 → 模型思考 → 工具执行 → 返回结果 → 结束。这是**请求—响应**模型。但真实世界的长期运行 Agent 需要：

- **多渠道接入**：同一 Agent 身份同时在 Telegram、Slack、Discord、Webhook 上可用。
- **主动行为**：每天 9 点生成日报、每小时巡检、告警时主动通知——不由用户触发。
- **会话连续性**：手机上起的头，桌面端能接着聊，上下文和权限不丢。
- **故障恢复**：进程崩溃或重启后，定时任务不丢、长任务能续上。

### 朴素实现为什么会失败

"写个 `while True` + `time.sleep(60)` 轮询" 看似简单，迅速撞上：

1. **重复投递**：多实例或重启后同一 cron 任务执行两次——双倍打扰和双倍成本。
2. **身份混乱**：不同渠道 ID 格式不同，没有统一会话身份层导致记忆和权限分裂。
3. **背压失控**：外部事件洪峰直接灌进模型循环，队列堆满或触发速率限制。
4. **无法运维**：没有 EventEnvelope 就没有审计、回放和幂等键，出问题靠日志瞎猜。
5. **安全边界模糊**：陌生渠道消息直接进主循环，等于扩大 prompt injection 攻击面。

### 在 Harness 分层中的位置

按 Agent / Harness / Runtime / Product 四层划分：

- **Gateway** 属 **Product + Runtime** 交界：渠道接入层（Product）+ 会话路由与事件分发（Runtime）。
- **Heartbeat** 属 **Runtime**：驱动主动循环、租约续期和存活检测。
- **Scheduler** 属 **Runtime**：管理定时任务的注册、触发、去重和状态持久化。

它们都在 Agent 决策循环**之外**，但决定了 Agent**什么时候被唤醒、以什么身份运行、结果送到哪里**。

---

## 3. 最小概念模型

### 核心对象与数据流

```text
                    ┌───────────────────────────────────┐
                    │            Gateway                │
                    │  ┌─────────┐  ┌───────────────┐  │
  Channels ────►    │  │ Channel │  │ Session Router│  │
 (Telegram/         │  │ Adapter │  │  + Identity   │  │
  Slack/            │  └────┬────┘  └───────┬───────┘  │
  Webhook...)       │       │               │          │
                    │       ▼               ▼          │
                    │  ┌──────────────────────────┐    │
                    │  │     Event Envelope       │    │
                    │  │ (id, sessionKey, type,   │    │
                    │  │  payload, idempotencyKey,│    │
                    │  │  timestamp, source)      │    │
                    │  └───────────┬──────────────┘    │
                    └──────────────┼───────────────────┘
                                   │
         ┌─────────────────────────┼─────────────────────┐
         ▼                         ▼                     ▼
   ┌───────────┐            ┌───────────┐          ┌───────────┐
   │  Agent    │            │ Scheduler │          │ Heartbeat │
   │  Loop     │◄───────────┤  (Cron)   │          │  (Lease)  │
   └───────────┘  trigger   └───────────┘          └───────────┘
                                      ▲                      ▲
                                      │                      │
                               durable state           durable state
                             (jobs, next_run)      (leases, claims)
```

### 关键概念区分（容易混用）

| 概念 | 触发源 | 语义 | 典型用途 |
|---|---|---|---|
| **Event-driven**（事件驱动） | 外部事件（消息、Webhook） | 事件到达即处理 | 用户消息、GitHub webhook |
| **Polling heartbeat**（轮询心跳） | 内部定时 tick | 检查状态、续租、驱动主动循环 | 存活检测、长任务进度 |
| **Cron**（定时触发） | 时间表达式匹配 | 精确时间点触发一次性任务 | 日报、定时备份 |
| **Scheduler**（调度器） | 任务队列 + 时间 | 管理任务生命周期：注册、触发、去重、重试 | 通用定时任务系统 |
| **Queue consumer**（队列消费） | 消息队列 | 按速率消费待处理任务 | 背压控制、异步处理 |

**注意**：heartbeat ≠ cron。heartbeat 是"每隔一段时间检查有没有事做"，可能什么都不做（只是续租）；cron 是"在精确时间点执行指定任务"，每次触发都有明确作业。

### 语言无关伪代码：带租约的定时任务调度

```python
def scheduler_tick(job_store, lease_store, now):
    # 1. 续租调度器租约，防止多实例同时调度
    if not lease_store.renew("scheduler-lease", ttl=120):
        return
    # 2. 找出所有到期任务
    due_jobs = job_store.find_due(now)
    for job in due_jobs:
        # 3. 幂等：用 (job_id, fire_time) 作为唯一键认领
        claim_key = f"{job.id}:{job.next_run.isoformat()}"
        if not lease_store.try_claim(claim_key, ttl=job.timeout):
            continue  # 已被其他实例认领
        try:
            # 4. 投递事件（带幂等键）
            event = EventEnvelope(
                id=generate_id(), idempotency_key=claim_key,
                session_key=job.session_key, type="scheduled_job",
                payload={"job_id": job.id, "prompt": job.prompt},
                timestamp=now, source="scheduler")
            dispatch(event)
            # 5. 计算下次运行时间，更新持久状态
            job.next_run = compute_next_run(job.schedule, now)
            job_store.update(job)
        except Exception:
            lease_store.release(claim_key)
            raise
```

核心机制：**租约（lease）** 保证单实例调度，**幂等键（idempotency key）** 保证重复投递不重复执行，**事件信封（Event Envelope）** 把业务载荷和元数据分离。

---

## 4. 关键设计决策

### 决策 1：Gateway 是可信边界还是薄转发层

**选择**：Gateway 作为**可信控制平面**，所有渠道消息必须经过身份解析、会话路由、权限校验才能进入 Agent 循环。

- **收益**：安全策略在入口统一实施；渠道适配器只管格式转换；会话状态不依赖单一渠道。
- **代价**：Gateway 成为单点，需要高可用设计；新渠道接入有适配成本。
- **失败模式**：Gateway 挂了 = 所有渠道同时不可用；路由规则写错导致串话。

OpenClaw 明确采用 "trusted gateway, untrusted execution" 模型。Hermes 的 `gateway/` 目录是整个系统的控制中枢。

### 决策 2：事件驱动 vs 轮询心跳

**选择**：两者共存，职责不同。事件驱动用于外部输入（低延迟、按需唤醒）；心跳轮询用于内部驱动（可预测、易调试）。

- **收益**：事件驱动保证响应速度，心跳保证系统有"脉搏"，无外部输入也能主动工作。
- **代价**：两套机制的状态同步需小心；心跳频率需要权衡。
- **失败模式**：心跳丢失导致租约过期、任务被错误重调度；事件和心跳同时触发同一会话需并发控制。

### 决策 3：幂等投递用什么粒度

**选择**：用 `(job_id, fire_time)` 作幂等键，粒度是"单次任务触发"。

- **收益**：最精确——同一次触发无论投递多少次都只执行一次；不同时间触发互不影响。
- **代价**：认领记录更多；TTL 需合理设置，太短长任务被重复执行，太长恢复慢。
- **失败模式**：TTL 过短 → 长任务执行中租约过期 → 另一实例也开始执行。

Hermes cron 系统用 "fire token + heartbeat" 模式实现：启动时认领 fire token，执行中定期心跳续租。

### 决策 4：会话路由用什么作为主键

**选择**：用 **session key**（不透明字符串）作为会话全局唯一标识，渠道 ID 通过映射表关联。

- **收益**：跨渠道会话连续；渠道可随时增删不影响状态；便于身份聚合和权限管理。
- **代价**：需维护渠道 ID → session key 映射表；新用户需身份绑定流程。
- **失败模式**：映射错误导致串话；身份聚合逻辑复杂时出现安全漏洞。

OpenClaw session 模型用 `key` 字段作主标识，配合 `idempotencyKey` 防重复创建。Hermes 通过 `profile_routing.py` 实现渠道→profile→会话分层路由。

---

## 5. 代表项目代码佐证

### OpenClaw：EventEnvelope 与会话路由（TypeScript）

OpenClaw 的 Gateway 是系统的可信控制平面，会话通过 `key` 标识，创建时支持 `idempotencyKey` 防重复，调度由 `cron` schema 定义。

以下代码是**教学等价实现**（不是源码逐字复制），展示 Gateway 核心路由逻辑：

```typescript
// 教学等价实现：OpenClaw Gateway 事件路由（TypeScript）
// 对应源码：packages/gateway-protocol/src/schema/ 下 sessions、cron、channels 定义

interface EventEnvelope<T = unknown> {
  id: string;
  idempotencyKey?: string;     // 去重键
  sessionKey: string;          // 会话主键
  type: string;                // 事件类型
  payload: T;                  // 业务载荷
  timestamp: number;
  source: "channel" | "scheduler" | "heartbeat" | "agent";
  channelInfo?: { platform: string; channelId: string; userId: string };
}

interface SessionRoute {
  sessionKey: string;
  profileId?: string;
  placement: "local" | "active" | "provisioning";
  capabilitySet: string[];
}

class SessionRouter {
  private sessions = new Map<string, SessionRoute>();
  private channelToSession = new Map<string, string>();
  private processed = new Set<string>();

  route(env: EventEnvelope): SessionRoute | null {
    // 1. 幂等检查
    if (env.idempotencyKey) {
      const k = `${env.sessionKey}:${env.idempotencyKey}`;
      if (this.processed.has(k)) return null;
      this.processed.add(k);
    }
    // 2. 渠道身份 → 会话 key 映射
    if (env.channelInfo) {
      const ck = `${env.channelInfo.platform}:${env.channelInfo.userId}`;
      const mapped = this.channelToSession.get(ck);
      if (mapped && env.sessionKey !== mapped)
        env = { ...env, sessionKey: mapped };
    }
    // 3. 查找或创建会话路由
    let route = this.sessions.get(env.sessionKey);
    if (!route) {
      route = { sessionKey: env.sessionKey, placement: "local",
                capabilitySet: ["chat", "tools"] };
      this.sessions.set(env.sessionKey, route);
    }
    return route;
  }
}
```

**关键看点：**

1. **信封与载荷分离**：`type`、`idempotencyKey`、`source` 是信封一部分，不侵入 payload。OpenClaw gateway-protocol 按领域拆分 schema 文件（sessions、cron、channels、approvals…）。
2. **幂等键是一等公民**：`sessions-create.ts` 定义了 5 分钟 idempotency retention，窗口内重复创建返回同一会话。
3. **渠道身份 ≠ 会话身份**：channel 到 session 有映射层，这是跨渠道会话连续的基础。
4. **placement 是显式状态机**：session 有 local/requested/provisioning/syncing/starting/active/draining/reconciling/reclaimed/failed 共 10 种状态（来源：`session-placement.ts`）。

**源码事实 vs 教学简化：**
- 源码事实：`SessionsCreateParamsSchema` 有 `key`、`idempotencyKey`、`agentId`、`parentSessionKey` 等字段；SessionPlacement 是 10 状态 discriminated union；cron 有独立 schema。
- 教学简化：`SessionRouter` 类是路由逻辑的等价抽象，不是 OpenClaw 中某一个具体类。

### Hermes：Cron 调度的租约机制（Python）

Hermes cron 系统是文件持久化 + 线程池 + 租约去重的典型实现。以下为**教学等价代码**（非源码逐字）：

```python
# 教学等价实现：Hermes Cron 租约与去重（Python）
# 对应源码：cron/scheduler.py、cron/jobs.py
import fcntl
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

@dataclass
class ScheduledJob:
    id: str; prompt: str; schedule: dict
    session_key: str; next_run: datetime | None = None
    enabled: bool = True

class CronScheduler:
    def __init__(self, data_dir: Path):
        self.jobs_file = data_dir / "jobs.json"
        self.claims_dir = data_dir / "claims"
        self.claims_dir.mkdir(exist_ok=True)

    def try_claim(self, key: str, ttl: int) -> bool:
        """文件锁 + 修改时间实现租约，跨进程安全"""
        path = self.claims_dir / f"{key}.lock"
        try:
            f = open(path, "a+")
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            f.seek(0); c = f.read().strip()
            if c and datetime.now() - datetime.fromisoformat(c) < timedelta(seconds=ttl):
                fcntl.flock(f.fileno(), fcntl.LOCK_UN); return False
            f.seek(0); f.truncate(); f.write(datetime.now().isoformat()); f.flush()
            return True
        except (BlockingIOError, OSError): return False

    def tick(self, now: datetime):
        """由 gateway 后台线程每秒调用"""
        try:
            tl = open(self.claims_dir.parent / ".tick.lock", "a+")
            fcntl.flock(tl.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError): return
        try:
            for job in self._load_jobs():
                if not job.enabled or not job.next_run or job.next_run > now: continue
                claim = f"{job.id}:{job.next_run.isoformat()}"
                if not self.try_claim(claim, ttl=600): continue
                self._submit(job); job.next_run = self._next_after(job.schedule, now)
            self._save_jobs()
        finally: fcntl.flock(tl.fileno(), fcntl.LOCK_UN); tl.close()
```

**关键看点：**

1. **两层锁**：外层 tick 锁保证调度逻辑单实例；内层 per-job claim 锁保证单任务不重复执行。Hermes `scheduler.py` 有 `.tick.lock` 和 fire claim 机制。
2. **tick 不直接执行任务**：只负责发现和提交到线程池，避免长任务阻塞调度循环。Hermes 用通用池 + workdir 串行池两个线程池。
3. **租约 TTL + 心跳续租**：执行超 TTL 的任务需在线程中定期续租。Hermes 文档明确提到 "fire claims with heartbeats prevent double-execution"。

---

## 6. 热门项目横向对比

> **说明**：Letta Code 代表持久 Agent / heartbeat 范式，**不是完整的 Channel Gateway**；它的强项是内存持久化与主动循环，渠道接入能力较弱，纳入对比主要用于区分"常驻心跳"与"多渠道网关"两条路线。

| 维度 | OpenClaw | Hermes Agent | goose | Letta Code |
|---|---|---|---|---|
| **核心定位** | 常驻型个人 Agent，Gateway 为可信控制平面 | 自成长通用 Agent，Gateway 为多渠道消息中枢 | 桌面/CLI Agent，Recipe + Scheduler 偏自动化 | 持久内存 Agent，核心是 long-term memory + heartbeat |
| **主动循环** | Gateway 事件驱动 + cron 调度 | Gateway 后台线程每 60s tick 驱动 cron | 按需启动为主；scheduler 为补充能力 | 内置 heartbeat loop，Agent 持续存活，定期自省 |
| **定时任务** | cron schema 定义，Gateway 内调度 | 完整 cron 子系统（12+ 文件），支持 interval/once/cron | Recipe + Scheduler，cron 触发 recipe 执行 | 基于 persistence 的定时提醒与主动回访 |
| **渠道接入** | 8+ 渠道（WhatsApp/Telegram/Slack/Discord/Signal/iMessage…） | 7+ 渠道（Telegram/Discord/Slack/WhatsApp/Signal/CLI…） | 桌面端 + CLI + HTTP API，不以消息渠道为核心 | 以 API/SDK 为主，渠道接入需自行集成 |
| **会话隔离** | session key 主键，placement 状态机，profile/device 路由 | profile-based routing，按 guild/chat/thread 分层匹配 | session 级隔离，recipe 定义配置和工具集 | 按 agent_id + thread 隔离，memory 跨会话保留 |
| **通知/投递** | 渠道适配器投递，session 驱动 | DeliveryRouter，支持多目标路由，死目标检测，超限截断 | 终端输出 + 桌面通知；scheduled run 不暴露 stdio MCP | 主动消息通过集成渠道外发，无统一投递路由 |
| **恢复机制** | placement reconciling + reclaim，durable state | 文件持久化，执行账本对账，stale claim 自动释放 | session 持久化，recipe 可重入 | 核心设计：checkpoint + 完整状态恢复，崩溃后续跑 |
| **实现语言** | TypeScript / Node.js | Python | Rust | Python |
| **Gateway 形态** | 独立可信控制平面，execution 在外 | 单进程多渠道网关，与 Agent 同进程 | 无独立 Gateway，goosed 管理 session | 无 Channel Gateway，persistence runtime 是核心 |

### 共同收敛的设计

- **事件信封抽象**：四个项目都区分"消息元数据"和"业务载荷"——id、时间戳、来源、目标字段都是标配。
- **幂等键是标配**：OpenClaw 的 `idempotencyKey`、Hermes 的 fire claim、goose 的 session 去重、Letta 的 message id 去重——都解决"重复投递不重复执行"。
- **会话与渠道解耦**：渠道 ID 不直接等于会话 ID，中间有映射或持久化层。这是支持多渠道或长生命周期的前提。

### 仍有分歧的设计

- **Gateway 形态**：OpenClaw 做成独立可信层，execution 在外；Hermes 的 Gateway 和 Agent 同进程，靠 profile 逻辑隔离；goose 和 Letta 都没有独立 Gateway 概念——goose 偏 recipe 触发，Letta 偏持久内存。
- **主动循环的地位**：OpenClaw、Hermes 和 Letta 的心跳/持久化是核心功能，是"常驻"的基础；goose 的 scheduler 更像 recipe 触发器，Agent 按需运行。
- **调度的表达力**：Hermes cron 支持自然语言任务、脚本任务、监控检测，还有 incident 聚合和 streak nudge；goose 只管"到点跑 recipe"；Letta 用 memory + heartbeat 实现主动行为，不是传统 cron。

### 项目特有但不可盲目迁移的设计

- **OpenClaw 的 10 状态 placement 状态机**：为 cloud workers、device workers、多 profile 等复杂部署设计，简单单实例场景不需要这么多状态。
- **Hermes 的 lifecycle_guard**：阻止 cron job 包含 `hermes gateway restart` 等自毁命令。前提是 Agent 能自己创建 cron job——如果不允许，不需要这层。
- **goose 的 Recipe 模型**：把工具集、prompt、参数打包成可分享模板，是"可复用工作流"思路，和"常驻 Agent 主动循环"是两条路线。
- **Letta Code 的持久化 memory + checkpoint**：把 Agent 状态（包括 memory、工具调用栈）完整持久化，适合超长生命周期场景；如果只是定时任务，过度设计。

---

## 7. 方法论抽象

### 设计原则

1. **信封和载荷分离**：所有跨边界消息都要有信封（id、时间戳、来源、幂等键、会话键），载荷只管业务。这是可观测、可回放、可审计的基础。
2. **路由在信任边界外做，决策在信任边界内做**：Gateway 负责"属于谁、能不能进"，Agent 负责"怎么处理"。不要让渠道适配器直接调用模型。
3. **一切外部触发都要幂等**：用户消息可能网络重发、cron 可能多实例重复触发、webhook 可能被重放——都要有去重机制。
4. **心跳 ≠ 调度 ≠ 事件**：三者解决不同问题，不要混成一个"定时循环"。heartbeat 管存活和续租，scheduler 管时间触发任务，event-driven 管外部输入。
5. **状态要能重建**：Gateway 或 Scheduler 重启后，必须能从持久化状态重建所有会话路由和定时任务，不能靠内存。

### 决策顺序

从零构建带 Gateway/Scheduler 的系统，按此顺序决策：

1. **会话身份模型**：用什么标识会话？决定路由表主键。
2. **渠道接入模式**：Gateway 是可信中间层还是薄转发？直接影响安全模型。
3. **事件模型**：EventEnvelope 有哪些字段？幂等键的粒度？
4. **主动循环机制**：需要 heartbeat 吗？cron 精度要求？单实例还是分布式？
5. **持久化策略**：jobs、claims、sessions、delivery ledger 存在哪里？一致性要求多高？

### 可复用的核心数据模型

```typescript
// 可复用核心数据模型（与具体项目无关）
interface EventEnvelope<T> {
  id: string;
  idempotencyKey?: string;
  sessionKey: string;
  type: string;
  payload: T;
  timestamp: number;
  source: string;
  traceId?: string;
}

interface ScheduledJob {
  id: string;
  sessionKey: string;
  schedule: { kind: "cron" | "interval" | "once"; expr: string };
  payload: Record<string, unknown>;
  enabled: boolean;
  lastRunAt?: number;
  nextRunAt?: number;
}

interface SessionRoute {
  sessionKey: string;
  identity: string;
  capabilitySet: string[];
  state: "idle" | "active" | "suspended";
  channelBindings: Array<{ platform: string; channelId: string }>;
}
```

### 从最小到生产的演进路径

1. **最小可用**：单进程 + 内存数组 + setInterval + Set 去重。能跑，重启丢状态。
2. **持久化**：jobs 存文件/DB + 文件锁/行锁幂等。单实例可靠。
3. **Gateway 接入**：渠道适配器 + 会话路由表 + EventEnvelope。支持多渠道。
4. **背压与队列**：事件入队列 + worker 消费 + 速率限制。抗洪峰。
5. **分布式调度**：Redis/etcd 分布式租约 + 多实例。高可用。
6. **可观测**：delivery ledger + 事件追踪 + 失败指标 + 告警。可运营。

---

## 8. 实践练习

### 30–60 分钟练习：实现带租约的极简 Scheduler

**目标**：用 TypeScript 实现文件持久化的 cron 调度器，支持幂等认领和重复投递处理。

**步骤**：

1. **定义数据模型**（10 min）：`ScheduledJob`、`EventEnvelope` 接口，job 含 id、cron 表达式、sessionKey、prompt、lastRun、nextRun。
2. **文件持久化**（10 min）：jobs 存 JSON 文件，实现 load/save/add/list。
3. **tick 循环**（10 min）：每秒检查到期任务，用 `node-cron` 或手动计算 nextRun，到期构造 EventEnvelope 打印输出。
4. **租约去重**（15 min）：用 `proper-lockfile` 或自写文件锁实现 `tryClaim(jobId, fireTime, ttl)`。启动两个进程验证同一任务不重复执行。
5. **边界测试**（5 min）：构造任务执行时间 > TTL 的场景，观察是否重复调度（应该会，说明 TTL 要匹配任务时长）。

**验收标准**：两个 Node 进程同跑，同一 cron 每分钟只触发一次；杀一个另一个接管；重启 jobs 不丢。

---

## 9. 掌握检查

### 自测问题

1. heartbeat 和 cron 的区别是什么？为什么不能只用其中一个？
2. 幂等键为什么用 `(job_id, fire_time)` 而不是 `job_id`？用 `job_id` 会出什么问题？
3. Gateway 为什么要做"渠道身份 → 会话身份"映射？直接用渠道用户 ID 当会话键有什么坏处？
4. 背压（backpressure）在 Gateway 层应该怎么处理？直接丢弃还是排队？各自适用场景？
5. 如果 Agent 自己能创建 cron job（像 Hermes 那样），会引入什么安全风险？至少两个。

### 生产落地检查清单

- [ ] 所有外部输入（渠道消息、webhook、cron 触发）经过 Gateway 身份校验
- [ ] EventEnvelope 包含 id、timestamp、source、sessionKey、idempotencyKey
- [ ] 幂等去重有持久化存储，不依赖内存
- [ ] 调度器使用租约机制，多实例不重复调度
- [ ] 长任务有心跳续租，不因 TTL 短而重复执行
- [ ] 渠道 ID 和会话 ID 分离，有映射表
- [ ] 有死信队列或失败日志，投递失败不静默丢失
- [ ] 有背压机制（队列长度限制、速率限制、拒绝策略）
- [ ] Gateway 有健康检查和监控
- [ ] 定时任务的 CRUD 有审计日志

### 常见误区

1. **"cron 就是 setInterval"**——差远了。生产 cron 需要持久化、去重、容错、并发控制、失败重试、执行审计。
2. **"heartbeat 频率越高越好"**——太密浪费资源还加速触发限流。按需要选：秒级巡检 1s，长任务续租用任务时长的 1/3。
3. **"渠道越多越好"**——每个新渠道增加安全面和运维成本。先把一个渠道做扎实。
4. **"幂等 = 不重复执行"**——幂等是"执行多次和一次效果相同"，不是"不会被执行多次"。业务逻辑本身也要幂等。
5. **"Gateway 就是消息转发器"**——如果只做转发就毫无价值。真正的价值是身份路由、权限校验、幂等去重、背压控制、协议转换。
6. **混淆 goose recipe scheduler 和常驻 Agent heartbeat**——goose 的 scheduler 是"到点跑 recipe，跑完就结束"；OpenClaw/Hermes/Letta 的 heartbeat 是"Agent 持续活着，定期检查有没有事"。前者是任务自动化，后者是常驻运行。不要混为一谈。

---

## 10. 边界与延伸阅读

### 适用边界

适用于：跨多渠道接入的 Agent、需定时主动执行任务的 Agent、需 24/7 常驻运行的 Agent。

不适用或需大幅裁剪：纯交互式 CLI/IDE 插件、单次运行的 batch job、完全由工作流引擎驱动的 Agent。

### 不确定项

- OpenClaw cron 的具体执行细节（触发机制、持久化方式）未能从公开源码完全确认——`cron.ts` 只定义了 schema，执行逻辑在 gateway 内部模块。以上分析基于 gateway-protocol 类型定义和项目自述推断。
- goose scheduler 在 Rust 源码中的具体实现路径（哪个 crate、哪些文件）未能从源码目录直接确认，以上分析基于项目文档和 issue 描述。
- Letta Code 的渠道接入与 Gateway 能力基于其官方文档与架构描述推断（核验日期：2026-08-30），具体实现细节可能随版本变化。

### 官方来源

**OpenClaw**
- 仓库：[github.com/openclaw/openclaw](https://github.com/openclaw/openclaw)
- Sessions Create Schema：[packages/gateway-protocol/src/schema/sessions-create.ts](https://github.com/openclaw/openclaw/blob/main/packages/gateway-protocol/src/schema/sessions-create.ts)
- Session Placement 状态机：[packages/gateway-protocol/src/schema/session-placement.ts](https://github.com/openclaw/openclaw/blob/main/packages/gateway-protocol/src/schema/session-placement.ts)
- Cron Schema：[packages/gateway-protocol/src/schema/cron.ts](https://github.com/openclaw/openclaw/blob/main/packages/gateway-protocol/src/schema/cron.ts)
- Channels Schema：[packages/gateway-protocol/src/schema/channels.ts](https://github.com/openclaw/openclaw/blob/main/packages/gateway-protocol/src/schema/channels.ts)

**Hermes Agent**
- 仓库：[github.com/NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent)
- Cron Scheduler：[cron/scheduler.py](https://github.com/NousResearch/hermes-agent/blob/main/cron/scheduler.py)
- Cron Jobs 管理：[cron/jobs.py](https://github.com/NousResearch/hermes-agent/blob/main/cron/jobs.py)
- 消息投递路由：[gateway/delivery.py](https://github.com/NousResearch/hermes-agent/blob/main/gateway/delivery.py)
- Profile 路由：[gateway/profile_routing.py](https://github.com/NousResearch/hermes-agent/blob/main/gateway/profile_routing.py)
- 渠道目录：[gateway/channel_directory.py](https://github.com/NousResearch/hermes-agent/blob/main/gateway/channel_directory.py)

**goose**
- 仓库：[github.com/aaif-goose/goose](https://github.com/aaif-goose/goose)
- Recipes 文档：[documentation/docs/guides/recipes/](https://github.com/aaif-goose/goose/tree/main/documentation/docs/guides/recipes)
- Scheduler 相关 Issue：[#4387 Unify Agent Execution](https://github.com/aaif-goose/goose/issues/4387)
- Scheduled recipe 限制：[#11408 stdio MCP in scheduled runs](https://github.com/aaif-goose/goose/issues/11408)

**Letta Code**
- 仓库：[github.com/letta-ai/letta-code](https://github.com/letta-ai/letta-code)
- 平台文档：[letta.ai/docs](https://letta.ai/docs)（Letta Code 是 Letta 平台生态中的具体 Agent 项目）
