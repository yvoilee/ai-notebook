# 06 · Durable State、Checkpoint 与恢复

> 核验日期：2026-08-30  
> 主项目：OpenHands Software Agent SDK / Python  
> 对照项目：LangGraph、OpenAI Codex、Cline

---

## 1. 一句话掌握

Durable State（持久状态）是把 Agent 的执行状态、事件日志和未完成意图在副作用发生前后持久化，使进程崩溃、人工审批等待或服务器重启后能从最近的 checkpoint 恢复，而不是从头重跑。

---

## 2. 为什么需要它

### 2.1 问题从何而来

一个真实的 Agent 执行链涉及：模型调用、工具执行、文件写入、网络请求、外部审批。每一步都可能失败或被中断：

- **进程崩溃**：容器被回收、服务重启、OOM 杀死。
- **人工等待**：审批、确认、补充信息，等待可能跨小时甚至跨天。
- **模型错误**：限流、超时、格式异常，需要重试但不能重复副作用。
- **用户中断**：暂停、修改任务后再恢复。

朴素实现把状态放在内存里，一旦进程退出，所有上下文和未完成工作全部丢失。更糟的是，恢复后重跑可能导致**重复副作用**——同一封邮件发两次、同一笔支付扣两次、同一批文件被改两次。

### 2.2 相关理论

- **Durable Execution（持久执行）**：执行状态可被持久化并在任意时刻恢复，不需要调用方维持长连接或长进程。
- **Event Sourcing（事件溯源）**：以不可变的事件日志作为状态的真相来源，当前状态可由事件重放得到。
- **Write-ahead Intent（预写意图）**：在执行副作用前先把"准备做什么"写入持久存储；失败后可据此判断是未执行还是已执行。
- **Idempotency（幂等性）**：同一操作执行多次与执行一次效果相同，是恢复安全的基础。
- **At-least-once vs exactly-once 幻觉**：分布式系统天然只能保证 at-least-once；所谓"exactly-once"往往是在特定边界内（如单个数据库事务）通过去重和原子提交实现的效果，不能无限外推到跨系统副作用。

### 2.3 在 Harness 分层中的位置

Durable State 属于 **Runtime / Control Plane** 层的核心能力。它不是 Agent 的决策逻辑，而是承载决策的底座：Harness 把 loop 的控制权交给 Runtime，由 Runtime 负责 checkpoint、调度和恢复。

---

## 3. 最小概念模型

### 3.1 核心对象与状态流

一个可恢复的 Agent 执行至少涉及四个持久化对象：

| 对象 | 作用 | 写入时机 |
|---|---|---|
| **State**（状态快照） | 当前执行位置、累计指标、配置 | 每步结束后覆盖写 |
| **Event Log**（事件日志） | 消息、动作、观察的不可变序列 | 每事件追加写 |
| **Intent**（意图记录） | 即将执行的副作用 + 幂等键 | 副作用执行前写入 |
| **Checkpoint**（检查点） | 可恢复的完整执行点快照 | 节点/步骤边界写入 |

状态流转：

```
启动 → 加载最近 checkpoint → 进入 run loop
  ├─ 产生 event → 追加到 event log
  ├─ 准备副作用 → 写入 intent（含 idempotency key）
  ├─ 执行副作用 → 写入 result / 标记 intent 完成
  ├─ 步骤结束 → 写入 checkpoint
  └─ 中断/崩溃 → 下次恢复时重放未完成步骤
```

### 3.2 语言无关伪代码：checkpointed run loop

以下伪代码展示带预写意图和幂等去重的恢复式循环：

```
function durable_run(thread_id, input):
    state = load_last_checkpoint(thread_id)
    if state is null:
        state = init_state(input)

    while not state.finished and state.step < max_steps:
        # 1. 从最近的 checkpoint 恢复，跳过已完成的副作用
        pending = load_pending_intents(thread_id)
        for intent in pending:
            if intent.status == "completed":
                continue
            # 用幂等键去重：如果外部系统已执行则直接取结果
            result = query_or_execute(intent.idempotency_key, intent.payload)
            mark_intent_completed(intent.id, result)
            state.events.append(result)

        # 恢复后立即写 checkpoint：保证已完成 intent 的结果被持久化，
        # 避免"intent 已完成但 state.events 未持久"的不一致窗口
        save_checkpoint(thread_id, state)

        # 2. 模型决策（纯计算，可重放）
        action = model_decide(state.events)

        # 3. 副作用前先写 intent
        intent_id = write_intent(thread_id, state.step, action.idempotency_key, action.payload)

        # 4. 执行副作用
        try:
            result = execute_side_effect(action)
            mark_intent_completed(intent_id, result)
            state.events.append(Observation(action.id, result))
        except SideEffectError as e:
            mark_intent_failed(intent_id, e)
            state.events.append(ErrorObservation(action.id, e))

        # 5. 每步结束写 checkpoint
        state.step += 1
        save_checkpoint(thread_id, state)

    return state
```

要点：意图在副作用**之前**写入；恢复时通过幂等键判断外部副作用是否已发生；恢复 pending intents 后立即补 checkpoint，消除"已完成意图的结果未持久"的不一致窗口；模型决策是纯计算，重放不产生新副作用。

---

## 4. 关键设计决策

### 4.1 决策一：事件溯源 vs 快照持久化

- **事件溯源（Event Sourcing）**：所有状态变更以事件形式追加写入，当前状态由事件重放得到。代表：OpenHands SDK 的 EventLog。
  - 收益：完整审计、可回放任意时点、天然支持订阅。
  - 代价：重放成本随事件数增长，需要快照或冷凝（condensation）。
- **快照持久化（Snapshot Persistence）**：定期或每步写入完整状态快照。代表：LangGraph checkpointer。
  - 收益：恢复只需加载最近快照，速度稳定。
  - 代价：写放大、历史粒度取决于快照频率。

**失败模式**：纯事件溯源在事件量极大时恢复超时；纯快照在频繁写入时 IO 压力过大。生产系统通常两者结合——事件日志保留细节，快照加速恢复。

### 4.2 决策二：检查点粒度

- **每工具调用一个 checkpoint**：最细粒度，恢复最快，但写入频次最高。
- **每模型轮次（step）一个 checkpoint**：在 LLM 返回后、工具执行完成后各写一次。平衡粒度和开销。
- **每 N 步 / 每节点一个 checkpoint**：粗粒度，写入少，但恢复时重复执行的部分多。

**适用条件**：副作用越昂贵（如外部 API、文件系统写入），检查点粒度应越细；纯计算步骤可以合并。

### 4.3 决策三：中断语义

- **节点边界中断**：只能在节点/步骤之间暂停，恢复时从下一个节点开始。代表：LangGraph interrupt。
  - 实现简单、语义清晰。
  - 长节点内的状态会丢失，需要重跑整个节点。
- **函数内部中断**：在任意 `interrupt()` 调用处暂停，恢复时从该点继续。代表：LangGraph Functional API。
  - 表达力强，但恢复时节点函数会**从头重跑**，靠 checkpoint 跳过已完成的 task。
  - 易产生"我以为在该行继续，实际函数从头执行"的误解。

### 4.4 决策四：幂等键的归属

- **Harness 自动生成**：基于 run_id + step_id + tool_call_id 哈希，对 Agent 透明。
  - 收益：开箱即用，Agent 无需关心。
  - 代价：无法跨会话去重，同一逻辑操作在不同会话中会重复执行。
- **业务层提供**：由工具或 Agent 明确指定业务幂等键（如订单号、文件路径）。
  - 收益：跨会话、跨系统去重。
  - 代价：需要业务方正确设计键，否则失效。

**方法论推断**：两种方式应分层——Harness 提供运行时幂等键保证运行时不重复，关键副作用由工具层补充业务幂等键保证跨会话安全。

---

## 5. 代表项目代码佐证

### 5.1 OpenHands SDK：事件日志 + 自动持久化

**项目**：OpenHands Software Agent SDK（Python）  
**源码路径**：`openhands-sdk/openhands/sdk/` 下的 `conversation.py`、`event.py`、`state.py`  
**在执行链中的位置**：Conversation 层负责状态管理和事件日志，持久化服务以观察者方式消费事件流。

OpenHands SDK 的持久化设计有三个核心特征：

1. **Append-only EventLog**：所有消息、动作、观察都作为不可变事件追加到日志，是状态的最终来源。
2. **自动持久化**：`ConversationState` 通过自定义 `__setattr__` 在字段变更时自动序列化，无需手动 save。
3. **两层存储**：`base_state.json`（核心状态快照，覆盖写）+ `events/` 目录（逐事件 JSON 文件，追加写）。

以下是**教学等价代码**（不是源码逐字复制，用于展示核心机制）。先看状态模型和自动持久化：

```python
# 教学等价代码：OpenHands 风格的状态自动持久化
import json, os, threading
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import List

@dataclass
class Event:
    id: str
    source: str        # user / agent / environment
    event_type: str    # message / action / observation / error
    payload: dict

@dataclass
class ConversationState:
    conversation_id: str
    step: int = 0
    status: str = "idle"   # idle / running / paused / error
    event_count: int = 0
    _persistence_dir: Path = field(default=None, repr=False)

    def __setattr__(self, name, value):
        object.__setattr__(self, name, value)
        # 公共字段变更时自动持久化 base_state
        if not name.startswith("_") and name != "conversation_id":
            if hasattr(self, "_persistence_dir") and self._persistence_dir:
                self._save_base()

    def _save_base(self):
        # 仅持久化公共字段（排除 _ 开头的内部字段）
        data = {k: v for k, v in asdict(self).items() if not k.startswith("_")}
        path = self._persistence_dir / "base_state.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False))
        tmp.replace(path)   # 原子替换，避免半写损坏
```

再看 `DurableConversation` 的懒加载恢复与事件追加写入：

```python
# 教学等价代码：DurableConversation 的恢复与事件追加
class DurableConversation:
    def __init__(self, conversation_id: str, persistence_dir: str):
        self._dir = Path(persistence_dir) / conversation_id
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.events: List[Event] = []
        self.state = ConversationState(
            conversation_id=conversation_id,
            _persistence_dir=self._dir,
        )
        self._load()

    def _load(self):
        base = self._dir / "base_state.json"
        if base.exists():
            data = json.loads(base.read_text())
            for k, v in data.items():
                if k != "conversation_id":
                    object.__setattr__(self.state, k, v)
        # 懒加载：只计数事件文件，不一次性读入内存
        event_dir = self._dir / "events"
        if event_dir.exists():
            self.state.event_count = len(list(event_dir.iterdir()))

    def append_event(self, event: Event):
        with self._lock:
            event_dir = self._dir / "events"
            event_dir.mkdir(exist_ok=True)
            idx = self.state.event_count
            path = event_dir / f"event-{idx:06d}-{event.id}.json"
            path.write_text(json.dumps(asdict(event), ensure_ascii=False))
            # event_count 变更触发 __setattr__ → 自动保存 base_state
            self.state.event_count = idx + 1
```

**关注点**：
1. `__setattr__` 钩子使状态变更自动持久化，崩溃时损失最小。
2. 事件采用独立文件追加写，避免大文件的部分写入损坏。
3. `base_state.json` 用临时文件 + rename 实现原子写入，保证恢复时总能读到合法快照。
4. 事件目录懒加载：启动时只计数，不一次性加载所有事件，适合长会话。

> 说明：以上为教学等价实现，简化了事件类型系统、LLM 转换层、stuck detection 和 workspace 集成。源码事实请参见 OpenHands SDK 官方仓库的 `openhands/sdk/state.py` 和 `openhands/sdk/event/` 模块。

### 5.2 LangGraph：checkpointer + interrupt

LangGraph 采用另一条路径：以 **checkpointer** 为核心持久化抽象，在每个 super-step（节点执行批次）边界写入状态快照。中断通过 `interrupt()` 函数在节点内触发，恢复时节点函数会重新执行，但已完成的子任务（task）结果从 checkpoint 恢复而非重新计算。

LangGraph 的幂等保证建立在两个基础上：
- **原子 checkpoint 提交**：状态快照 + frontier queue + 已记录 I/O + 幂等键在一个数据库事务中提交。
- **task 级结果缓存**：Functional API 中每个 task 的输出被 checkpoint 化，重放时直接返回缓存结果。

需要注意：如果一个 task 开始执行但未在 checkpoint 提交前崩溃，恢复时该 task 会**重新运行**。这就是为什么 LangGraph 文档强调"副作用操作必须幂等"——框架只能保证框架内部状态的 exactly-once，跨系统副作用的 exactly-once 需要业务层配合。

---

## 6. 热门项目横向对比

| 维度 | OpenHands SDK | LangGraph | OpenAI Codex (Rust) | Cline |
|---|---|---|---|---|
| **持久化模型** | 事件溯源 + 状态快照 | Checkpoint 快照（super-step 边界） | JSONL 会话转录 + WorldState 快照 + 增量 Patch | 影子 Git 仓库 + 任务历史 |
| **保存粒度** | 每事件 + 每字段自动持久化 | 每节点/每 super-step | 每 turn + WorldState section patch | 每工具调用后 |
| **中断语义** | pause() 暂停循环，run() 恢复；可在暂停时发新消息 | interrupt() 函数级中断；resume 从节点重跑，已完成 task 从 checkpoint 恢复 | 进程级会话持久化；退出后重进从会话文件恢复 | IDE 扩展级；关闭标签页后从历史 + 影子 Git 恢复 |
| **副作用恢复** | 事件日志可重放；工具错误作为 AgentErrorEvent 让模型自行恢复 | task 级 checkpoint 缓存 + 幂等键；未完成 task 重跑 | 文件系统状态通过 WorldState 快照 + RFC 7386 patch 精确恢复 | 通过影子 Git 回滚文件；对话历史回退到 checkpoint |
| **人工审批等待** | 通过 pause/resume + 事件机制实现；confirmation mode 产生 UserRejectObservation 事件 | interrupt() 原生支持；等待时长无限制，状态持久化在 checkpointer | 审批命令在 turn 边界等待；session 持久化支持跨进程 | 每步审批（Plan/Act 模式）；checkpoint 天然支持回退和继续 |
| **进程重启后恢复** | 同 conversation_id + persistence_dir 自动恢复 | 同 thread_id + checkpointer 从最近 checkpoint 继续 | 从 sessions 目录加载 JSONL + WorldState 快照重建 | 从扩展存储 + 影子 Git 恢复任务和文件状态 |
| **幂等保证层级** | 事件级去重；副作用幂等依赖工具实现 | task 级缓存 + 原子提交；副作用幂等需业务设计 | 文件系统级（WorldState 基线比对）；外部副作用不保证 | 文件级（Git 回滚）；外部副作用不保证 |

### 6.1 共同收敛的设计

1. **快照 + 增量的双层结构**：OpenHands 的 base_state + events、Codex 的 WorldState 快照 + JSON merge patch、Cline 的 Git 快照 + commit 序列，本质都是"基线 + 增量"模式。
2. **原子写入**：成熟实现都用临时文件 + rename 或数据库事务保证 checkpoint 不损坏。
3. **错误分层**：工具级错误（可恢复）和会话级错误（终止 run loop）被明确区分。

### 6.2 仍有分歧的设计

1. **事件溯源 vs 快照优先**：OpenHands 以事件为真相来源，LangGraph 以状态快照为真相来源。
2. **中断粒度**：LangGraph 支持节点内任意点中断（函数级），OpenHands 和 Codex 在 step/turn 边界中断。
3. **文件状态处理**：Codex 把文件系统纳入 WorldState 做精确基线管理；Cline 用影子 Git 做文件回滚；OpenHands 把 workspace 视为外部环境，文件状态不由 checkpoint 直接管理。

### 6.3 项目特有但不可盲目迁移的设计

- **Cline 的影子 Git**：只适用于代码编辑场景，对非文件副作用（网络调用、API 请求）无法回滚。
- **LangGraph 的 task 级 checkpoint**：依赖 Functional API 的 task 抽象，普通 Graph API 只能到节点粒度。
- **Codex 的 WorldState section**：为 coding agent 深度定制的状态分区模型，推广到通用 Agent 需要重新设计 section 类型。

---

## 7. 方法论抽象

### 7.1 设计原则

1. **预写意图原则**：任何副作用发生之前，必须先把意图（含幂等键）写入持久存储。
2. **不可变事件原则**：已发生的事实（消息、动作结果、错误）以追加方式记录，永不修改。
3. **原子边界原则**：checkpoint 必须在一个原子操作中完成——要么完整写入，要么完全不写。
4. **幂等降级原则**：框架只能保证自身状态的 exactly-once 效果，跨系统副作用的幂等由工具/业务层保障。
5. **恢复即常态原则**：恢复路径和正常路径是同一条代码路径，不应有"正常模式"和"恢复模式"的分支。

### 7.2 决策顺序

1. 先确定**检查点粒度**：根据副作用代价选择每工具、每 step 还是每节点。
2. 再确定**持久化模型**：事件溯源适合审计和重放，快照适合快速恢复，两者可结合。
3. 然后定义**中断语义**：节点边界还是函数级，影响 Agent 编写方式。
4. 最后设计**幂等策略**：Harness 层的运行时幂等键 + 工具层的业务幂等键。

### 7.3 可观察的不变量

- 每个 checkpoint 都有唯一且单调递增的版本号。
- 从事件日志重放得到的状态，与快照状态一致（除了被冷凝/遗忘的部分）。
- 同一个幂等键的副作用，在持久化记录中最多有一个"已完成"结果。
- 恢复后的第一个模型调用，其上下文与中断前完全一致。

### 7.4 从最小实现到生产实现的路径

1. **最小版**：JSON 文件保存消息历史，重启后重新喂给模型（不保证副作用不重复）。
2. **基础版**：每步写状态快照 + 事件日志，崩溃后从最近 step 恢复。
3. **增强版**：引入预写意图和幂等键，保证工具调用的 at-least-once + 去重。
4. **生产版**：数据库 checkpointer + 原子事务提交 + 多级快照 + 事件冷凝 + 可观测性集成。

---

## 8. 实践练习

### 练习：实现一个带预写意图的 checkpointed run loop（约 45 分钟）

**目标**：用 Python 实现约 150 行的可恢复 Agent loop，验证崩溃后恢复不会重复发送邮件（模拟副作用）。

**步骤**：

1. 定义 `Checkpointer` 类，用 SQLite 保存 state、intents 和 events（三张表）。
2. 实现 `durable_step(thread_id, step_fn)`：在执行 step_fn 前写入 intent，执行后更新为 completed。
3. 模拟一个"发邮件"副作用，用 `email_id` 作为幂等键——如果 intent 已标记 completed 则不重复发送。
4. 在第 3 步后人为抛出异常模拟崩溃。
5. 重新运行程序，用同一个 thread_id 恢复，验证：第 3 步的邮件没有重发，第 4 步及以后正常继续。
6. 增加一个中断点：在第 5 步调用 `interrupt("need_approval")`，下次恢复时传入审批结果继续。

**验收标准**：
- 同一 thread_id 恢复后，已完成的副作用不重复执行（可以用计数变量验证）。
- 中断后恢复，模型接收到的上下文与中断前一致。
- SQLite 数据库中的 intent 表有明确的 pending / completed / failed 状态。

---

## 9. 掌握检查

### 9.1 自测问题

1. **为什么"副作用前先写 intent"很重要？如果反过来（先执行再记录）会出什么问题？**  

2. **LangGraph 的 interrupt() 是"在行号处恢复"吗？实际行为是什么？**  

3. **"Exactly-once 幻觉"指的是什么？在 Agent 系统中哪些层面可以做到 exactly-once，哪些不能？**  

4. **事件溯源和快照持久化各自适合什么场景？**  

### 9.2 生产落地检查清单

- [ ] 每个持久化写入操作都是原子的（临时文件 + rename 或数据库事务）。
- [ ] 所有副作用在执行前有预写意图记录，且包含幂等键。
- [ ] 恢复路径与正常执行路径是同一段代码，无特殊分支。
- [ ] 工具级错误与会话级错误被明确区分，错误可被模型感知和恢复。
- [ ] checkpoint 有版本号或时间戳，支持回滚到历史检查点。
- [ ] 长会话有冷凝/压缩机制，避免事件日志无限增长。
- [ ] 持久化存储本身有备份和故障转移方案。
- [ ] 有故障注入测试验证：进程被杀、数据库中断、网络分区后的恢复正确性。

### 9.3 常见误区

1. **"有了 checkpoint 就不会重复执行"**：错。Checkpoint 只保存状态快照，如果副作用发生在 checkpoint 之前但状态未写入，恢复时仍会重跑。必须配合预写意图和幂等键。
2. **"把消息历史存下来就是 durable state"**：错。消息历史只是历史记录，durable state 还包括执行位置、未完成工作、工具执行状态和工作空间状态。
3. **"LangGraph 的 checkpointer 能保证我的 API 调用不重复"**：错。Checkpointer 保证框架内部状态的一致性，但外部 API 调用的幂等性需要 API 本身和业务层共同保障。
4. **"中断恢复就是从断点那行继续执行"**：错。大多数实现是从最近的 checkpoint 边界重放，中间的计算会重复执行。只有纯计算或已 checkpoint 的结果不会重复。
5. **"事件溯源天然可靠"**：错。事件日志的追加写可靠不代表重放可靠——重放过程中如果有副作用，同样会重复。事件重放必须是纯计算，或者配合幂等键去重。

---

## 10. 边界与延伸阅读

### 10.1 适用边界

Durable State 范式主要解决**执行可靠性**问题，它不直接解决：
- **长期记忆**：跨会话的知识沉淀和技能积累（见第 7 篇）。
- **上下文管理**：窗口内信息的装配、压缩和外置（见第 5 篇）。
- **权限审批**：审批的策略引擎和安全边界（见第 4 篇）。
- **可观测性**：指标、追踪和评测（见第 10 篇）。

### 10.2 官方来源

- **OpenHands Software Agent SDK**
  - Conversation 架构：https://docs.openhands.dev/sdk/arch/conversation
  - Event 架构：https://docs.openhands.dev/sdk/arch/events
  - Conversation Persistence：https://docs.openhands.dev/sdk/guides/convo-persistence
  - Pause and Resume：https://docs.openhands.dev/sdk/guides/convo-pause-and-resume
  - 源码仓库：https://github.com/OpenHands/software-agent-sdk

- **LangGraph**
  - Checkpointers 概念：https://docs.langchain.com/oss/python/langgraph/checkpointers
  - Interrupts 概念：https://docs.langchain.com/oss/python/langgraph/interrupts
  - Functional API / Determinism / Idempotency：https://docs.langchain.com/oss/python/langgraph/functional-api
  - Durable Execution：https://docs.langchain.com/oss/python/langgraph/durable-execution.md
  - Checkpoint 库源码：https://github.com/langchain-ai/langgraph/blob/main/libs/checkpoint/README.md

- **OpenAI Codex (Rust)**
  - 仓库：https://github.com/openai/codex
  - World State Persistence（会话恢复、Fork、Rollback）：Release v0.145.0 及 PR #29833/#29835/#29837
  - Session 存储：`~/.codex/sessions/` 下的 JSONL 转录文件

- **Cline (Roo Code)**
  - Checkpoints 文档：https://docs.cline.bot/core-workflows/checkpoints
  - 仓库：https://github.com/cline/cline

### 10.3 不确定项

- OpenHands SDK 的 agent-server 模式下持久化的具体实现（文档以本地 SDK 为主），服务器端是否复用同一套持久化层需阅读源码确认。
- LangGraph 原子 checkpoint 提交的具体事务隔离级别和并发控制策略，不同 checkpointer 实现（Sqlite vs Postgres）可能有差异。
- Codex 的 WorldState patch 机制在多大程度上能覆盖非文件系统的环境状态（如环境变量、进程状态），需进一步核验源码。
