# 08 · 子 Agent 委派与上下文隔离

> 核验日期：2026-08-30  
> 主项目：Hermes Agent / Python  
> 对照项目：OpenHands、DeerFlow、OpenCode、goose、Codex

---

## 1. 一句话掌握

子 Agent 委派是父 Agent 将可分解的子任务交给拥有独立上下文、独立工具集和独立预算的子 Agent 执行，并在完成后汇总结果的模式；核心挑战不是"多开几个 Agent"，而是在上下文隔离、预算隔离、取消传播、部分失败和结果归因之间取得平衡。

---

## 2. 为什么需要它

### 问题从何而来

单 Agent 模式下，所有子任务的工具调用、中间推理和错误重试都会塞进同一个上下文窗口。当任务涉及多条独立工作流时（例如并行调研多个模块、同时测试多个文件），上下文污染迅速加剧：

1. 子任务 A 的失败调试痕迹挤占子任务 B 的推理空间；
2. 总 step / token budget 被局部重试吃光，全局目标无法推进；
3. 不同子任务的工具副作用互相干扰（例如都在改同一临时目录）；
4. 无法对不同子任务施加不同权限等级。

朴素做法——把父上下文原样复制给子 Agent——等于没隔离；反过来——完全不传递任何上下文——又导致子 Agent 缺少必要背景。委派设计的核心就是这道边界。

### 三个容易混淆的概念

在展开之前，必须区分三种名字相近但语义完全不同的模式（统一术语，下同）：

| 模式 | 控制权 | 上下文 | 典型场景 |
|---|---|---|---|
| **agent-as-tool** | 父 Agent 每轮主动调用，子 Agent 只返回一次结果 | 父 Agent 组装单次 prompt | 子 Agent = 一个带 LLM 的工具函数 |
| **delegation（委派）** | 父 Agent 发起后等待或轮询，子 Agent 自主跑多轮 loop | 子 Agent 有独立上下文 | 把子任务整块外包 |
| **handoff（移交）** | 父 Agent 退场，子 Agent 接管原会话与用户 | 用户上下文被新 Agent 接续 | 转专业客服、转代码专家 |

本文聚焦 **delegation**，即父→子的任务委派与结果聚合。fan-out / fan-in 是委派的并发形态：父 Agent 一次扇出多个子任务，等全部（或部分）完成后扇入汇总。

### 它在 Harness 四层中的位置

子 Agent 委派横跨 Harness 和 Runtime 两层：Harness 负责定义 DelegationContract、构造子上下文、裁剪工具集；Runtime 负责并发调度、预算隔离、取消传播和状态追踪。它依赖 Context Compiler（构造子上下文）、CapabilitySet（裁剪工具权限）和 Checkpoint（子任务可恢复）三个前置能力。

---

## 3. 最小概念模型

### 核心对象

一次委派涉及六个核心对象：

1. **DelegationContract** —— 任务描述、输入参数、允许的工具集、预算上限、超时、返回格式；
2. **ChildContext** —— 子 Agent 的初始上下文，由父上下文的精选片段 + contract 组装而成；
3. **ChildAgent** —— 运行在隔离上下文中的子 Agent 实例，有独立 loop；
4. **ChildBudget** —— 子 Agent 独享的 token / step / time 预算；
5. **ResultEnvelope** —— 封装子任务结果的结构化对象，含状态、输出、消耗、错误信息；
6. **FanInAggregator** —— 父 Agent 侧的汇总器，收集多个 ResultEnvelope 并决定下一步。

### 状态机

```
           submit              start              complete
  PENDING ───────→ RUNNING ────────→ COMPLETED
     │                │                  ▲
     │ cancel      timeout│cancel        │success
     ▼                ▼                  │
  CANCELLED       TIMED_OUT  FAILED ◄────┘
                          (on error)
```

终态有四种：COMPLETED（成功）、FAILED（子任务自身错误）、TIMED_OUT（超时）、CANCELLED（被父级或外部取消）。部分失败是 fan-out 场景下的常态——父 Agent 必须能处理"5 个子任务成功 3 个"的情况。

### 结构化并发与委派的关系

**结构化并发（structured concurrency）**是一种并发编程原则：所有并发任务都有明确的父-子生命周期边界，父任务必须等待所有子任务结束后才能结束；取消从父向子传播，错误从子向父冒泡。它保证了不会出现"启动后无人看管"的 fire-and-forget 任务，从而避免资源泄漏、孤儿任务和错误丢失。

对委派系统而言，结构化并发是天然的架构约束：
- 每个子 Agent 都是父 Agent 的结构化子任务——父 Agent loop 结束前，必须等待或显式取消所有子 Agent；
- 取消传播是双向义务：父级发出取消信号，子 Agent 协作响应（在下一个 loop iteration 边界检查）；
- fan-out/fan-in 是结构化并发的典型模式，每个子任务的结果、错误、消耗都能正确归因到父任务。

### 语言无关伪代码（Python 风格）

> 以下伪代码使用 Python 式语法表达控制流，但不依赖任何 Python 库或运行时特性，便于读者将逻辑映射到自己熟悉的语言。

```python
# 伪代码：子 Agent 委派的最小循环
function delegate(parent, contract):
    # 1. 构造子上下文（精选+组装，不传完整 history）
    child_context = ContextCompiler.build_child_context(
        system_prompt=parent.system_prompt,
        task=contract.task_description,
        selected_snippets=parent.pick_relevant(contract),
    )

    # 2. 裁剪工具集：父级 ∩ 允许工具 - blocklist
    child_tools = CapabilitySet.intersect(
        parent.tools, contract.allowed_tools, SUBAGENT_BLOCKLIST
    )

    # 3. 启动子 Agent，带独立预算
    child = ChildAgent(context=child_context, tools=child_tools,
                       budget=ChildBudget(steps=contract.max_steps,
                                          tokens=contract.max_tokens,
                                          timeout=contract.timeout_seconds))

    # 4. 运行直到终态（含错误和超时路径）
    try:
        result = child.run_with_budget()
    except TimeoutError:
        return ResultEnvelope(status="TIMED_OUT", partial=child.last_artifact)
    except BudgetExhausted:
        return ResultEnvelope(status="BUDGET_EXHAUSTED", partial=child.last_artifact)
    except CancellationError:
        return ResultEnvelope(status="CANCELLED", partial=None)
    except Exception as e:
        return ResultEnvelope(status="FAILED", error=str(e))

    # 5. 包装结果，附加消耗审计
    return ResultEnvelope(status="COMPLETED", output=result,
                          usage=child.budget.used(),
                          tool_receipts=child.tool_history_summary())
```

这段伪代码不是任何项目的源码，而是教学等价的最小实现。真实项目还需要加上：并发控制、深度限制、取消传播、结果截断、父子身份链验证和可观测性埋点。

---

## 4. 关键设计决策

以下五个决策真正决定了委派系统的性质，不能用"支持 / 不支持"二元判断。

### 决策 1：上下文构造策略——精选 vs 全量

| 策略 | 做法 | 收益 | 代价 | 失败模式 |
|---|---|---|---|---|
| **精选子集** | 只传与子任务相关的文件/片段 + 任务描述 | 子上下文干净，token 省 | 需要可靠的相关性筛选 | 漏传关键信息导致子 Agent 走偏 |
| **全量继承** | 父历史全部带入 | 子 Agent 信息充分 | 上下文迅速膨胀，父子问题同构 | 子任务中间产物回流后造成递归膨胀 |
| **仅任务描述** | 只给 task description，不带父上下文 | 隔离最彻底，最安全 | 子 Agent 重复工作 | 子任务需要的背景信息完全缺失 |

Hermes 默认走"仅任务描述 + 自包含任务描述"路线：子 Agent 拿到 fresh conversation，不传父历史，所有背景信息必须由任务描述本身携带。DeerFlow 则走"精选子集"路线，会在 initial state 中带一部分 skill index。

### 决策 2：递归深度——扁平 vs 树形

子 Agent 能否再委派孙 Agent？这决定了委派拓扑是扁平的 fan-out 还是可扩展的任务树。

- **扁平（默认深度 1）**：Hermes 默认 `max_spawn_depth = 1`，最安全，调试最容易；
- **树形（可配置深度 N）**：DeerFlow 和 goose 的 orchestration 支持多层，适合复杂任务分解，但需要更强的预算控制和深度感知（每层都要扣预算）。

关键不变量：**无论深度多少，每一层的预算必须从父层分配，不能凭空新增**。否则总预算不可控。

### 决策 3：工具权限继承策略

子 Agent 的工具权限从哪来？三个典型选项：

1. **父级子集**：子 Agent ≤ 父 Agent 权限，再叠加 blocklist（Hermes、DeerFlow）；
2. **独立配置**：每个子 Agent 类型有固定权限模板（OpenCode 的 general / explore / scout）；
3. **随任务声明**：父 Agent 在委派时声明需要哪些工具，由审批层决定（goose 的 recipe 方式）。

共同收敛的设计：**至少要禁用递归委派工具和直接与用户交互的工具**。否则会出现无限递归或"子 Agent 替父 Agent 回答用户"的控制权混乱。

### 决策 4：失败语义——部分失败 vs 全有或全无

fan-out 场景下，3 个子任务成功、2 个失败，父 Agent 怎么处理？

- **全有或全无**：任一失败 → 整体失败 → 触发重试或降级。简单但浪费已完成的工作。
- **部分结果可用**：返回所有成功的 ResultEnvelope + 失败清单，由父 Agent 决定是否重试。更灵活，但父 Agent 必须能处理不完整结果。
- **带降级阈值**：成功比例超过阈值则继续，否则整体失败。介于两者之间。

DeerFlow 和 goose 都采用"部分结果可用"模式，把判断权交给父 Agent。这也是更符合 Agent 范式的选择——决策是 Agent 的职责，不是 Runtime 的职责。

### 决策 5：取消传播——协作式 vs 强制式

父 Agent 取消时，子 Agent 怎么停下？

- **协作式中断**：在下一个 loop iteration 边界检查取消标志，正在执行的工具请求优雅取消（Hermes 的 `stop` action）。对工具友好，但停止可能不及时。
- **强制式终止**：直接杀掉子进程 / 线程。立即停止，但可能留下半成品文件或不一致状态。
- **混合**：先发协作取消，超时后强制终止。goose 和 DeerFlow 都倾向这种。

---

## 5. 代表项目代码佐证

主项目：**Hermes Agent**（Python），重点看 `tools/delegate_tool.py`。
来源：`https://github.com/NousResearch/hermes-agent/blob/main/tools/delegate_tool.py`，核验日期 2026-08-30。

以下代码是基于 Hermes 源码结构的**教学等价重写**，不是逐字复制。它保留了核心设计：子上下文隔离、工具 blocklist、线程池并发、深度限制和结果包装，同时简化了与其他模块的耦合。

### 数据模型与全局控制（约 25 行）

```python
from dataclasses import dataclass
from enum import Enum
from typing import Optional

class SubagentStatus(str, Enum):
    PENDING = "pending"; RUNNING = "running"
    COMPLETED = "completed"; FAILED = "failed"
    CANCELLED = "cancelled"; TIMED_OUT = "timed_out"

@dataclass
class DelegationContract:
    task_description: str
    max_steps: int = 30
    timeout_seconds: int = 300
    allowed_tools: Optional[set] = None

@dataclass
class ResultEnvelope:
    status: SubagentStatus
    output: Optional[str] = None
    error: Optional[str] = None
    steps_used: int = 0

# 源码事实：模块级注册表 + 默认扁平拓扑
_active: dict[str, dict] = {}
MAX_SPAWN_DEPTH = 1
BLOCKLIST = {"delegate_task", "clarify", "memory",
             "send_message", "cronjob"}
```

### 子 Agent 构造与委派入口（约 35 行）

```python
from concurrent.futures import ThreadPoolExecutor

def _build_child(parent, contract: DelegationContract, depth: int):
    if depth >= MAX_SPAWN_DEPTH:
        raise RuntimeError("Subagent spawn depth exceeded")

    # 裁剪工具：父级 ∩ 允许工具 - blocklist
    child_tools = {n: t for n, t in parent.tools.items()
                   if n not in BLOCKLIST and (
                       contract.allowed_tools is None
                       or n in contract.allowed_tools)}

    # 源码事实：fresh conversation，不传父历史
    child_ctx = [
        {"role": "system", "content": parent.base_system_prompt},
        {"role": "user", "content":
         f"Subagent task:\n{contract.task_description}\n"
         "Do not interact with the user. Summarize concisely."},
    ]

    child = parent.__class__(tools=child_tools, context=child_ctx)
    child.max_steps = contract.max_steps
    return child

def delegate_task(parent, contract: DelegationContract) -> ResultEnvelope:
    child = _build_child(parent, contract, depth=1)
    _active[id(child)] = {"agent": child, "status": SubagentStatus.RUNNING}
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(child.run_until_complete)
            try:
                result = fut.result(timeout=contract.timeout_seconds)
                return ResultEnvelope(
                    SubagentStatus.COMPLETED, output=result,
                    steps_used=child.steps_used)
            except TimeoutError:
                # 教学简化：Python future.cancel() 仅能取消未启动任务；
                # 真实 Hermes 通过子 Agent loop 的 stop action 检查
                # 实现协作式中断，这里仅示意超时后的状态包装。
                fut.cancel()
                return ResultEnvelope(
                    SubagentStatus.TIMED_OUT, error="timeout",
                    steps_used=child.steps_used)
    except Exception as e:
        return ResultEnvelope(SubagentStatus.FAILED, error=str(e))
    finally:
        _active.pop(id(child), None)
```

### fan-out 并行委派与部分失败汇总（约 20 行）

```python
import asyncio

async def delegate_parallel(parent, contracts: list) -> list:
    """fan-out/fan-in：并行委派，部分失败不影响其他子任务。"""
    sem = asyncio.Semaphore(5)  # 全局并发上限

    async def _one(c):
        async with sem:
            return await asyncio.to_thread(delegate_task, parent, c)

    # gather(return_exceptions=True) 确保部分失败时仍返回全部结果
    results = await asyncio.gather(
        *[_one(c) for c in contracts], return_exceptions=True)

    envelopes = []
    for r in results:
        if isinstance(r, Exception):
            envelopes.append(ResultEnvelope(
                SubagentStatus.FAILED, error=str(r)))
        else:
            envelopes.append(r)
    # 父 Agent 据此决定：重试失败项 / 用部分结果继续 / 整体放弃
    return envelopes
```

### 执行链与关键点

Hermes 的委派调用链大致是：

```
父 Agent loop
  → tool_call: delegate_task(goal="...", ...)
    → delegate_tool.py: delegate_task()
      → _build_child()  [构造隔离上下文 + 裁剪工具]
      → ThreadPoolExecutor     [独立线程运行]
      → 子 Agent 独立 loop     [自己的 step/budget/context]
      → ResultEnvelope         [包装结果回传]
  → 父 Agent 收到 tool_result（只包含摘要，不含子 Agent 中间步骤）
```

四个关注点：(1) 上下文隔离是硬约束，子 Agent 拿到 fresh conversation；(2) 工具 blocklist 是安全底线，至少禁用委派本身、用户交互、记忆写入和持久调度；(3) 审批回调的线程安全（源码用 `initializer=_set_subagent_approval_cb` 替换工作线程回调，避免子线程调 `input()` 死锁）；(4) 深度和并发都有默认上限，生产环境不建议随便调大。

---

## 6. 热门项目横向对比

下表对比六个项目在子 Agent 委派与上下文隔离范式上的设计差异。维度均为本范式特有，不做泛化功能对比。

| 维度 | Hermes | OpenHands SDK | DeerFlow | OpenCode | goose | Codex |
|---|---|---|---|---|---|---|
| **触发方式** | `delegate_task` 工具调用，由 Agent 自主决定 | 未明确暴露原生子 Agent 接口，需通过 Server 层自行编排 | `task()` 内置工具，Lead Agent 调用 | 内置 subagent（general/explore/scout），Agent 自主委派 + 用户 @ 提及 | 自然语言触发 + recipe 配置，自主或显式 | 未在开源仓库中明确暴露子 Agent 委派接口 |
| **上下文隔离边界** | 完全独立 conversation，不传父历史 | 每个 Agent 实例独立 Conversation 对象 | 独立 event loop + 独立 ThreadState，父 RunJournal 被剥离 | 独立 child session，父子会话可导航 | 独立 goose 实例，独立 context window | 未公开明确的委派机制 |
| **并发模型** | ThreadPoolExecutor，默认最多 10 并发 | 未提供原生并发委派 | 后台线程池，每轮最多 3 子 Agent，有全局 capacity 控制 | 单任务委派为主，未见原生并发 | 支持 parallel 模式，多实例并行 | 未明确 |
| **预算隔离** | 子 Agent 独立 step budget，超时独立 | 每个 Agent 有独立 budget 配置 | 子 Agent 独立 token/step budget，middleware 管控 | 未明确公开 | 25 turns + 5 分钟超时，可自然语言调整 | 未明确 |
| **工具权限策略** | 父级子集 + blocklist（5 个禁用工具） | 每个 Agent 独立 Tool 配置 | 继承 + allow/deny 列表 + 身份授权 | 每个子 Agent 类型有固定权限模板 | 继承父扩展，可声明式限制 | 未明确 |
| **结果汇总方式** | 父 Agent 只看到摘要，不含子中间步骤 | Tool result 形式返回 | `SubagentResult` 结构化对象，含状态和 tool receipts | 子会话结果回父会话，用户可见完整子会话 | full details / summary only 两种模式 | 未明确 |
| **失败处理** | 失败向上抛，父 Agent 决定是否重试 | 依赖 Runtime 事件系统 | 6 种终态，原子状态转换 | 未明确公开 | 部分失败：只返回成功子 Agent 结果，失败的无输出 | 未明确 |
| **递归委派** | 默认深度 1，可配置开启 | 未明确 | 支持多层（lead → subagent） | 未明确支持 | 子 Agent 不能再 spawn 子 Agent | 未明确 |

### 共同收敛的设计

1. **子 Agent 默认不拥有父 Agent 的全部历史**——所有有明确实现的项目都做了上下文隔离，区别只在隔离程度。
2. **递归委派默认被禁止或深度受限**——Hermes 深度 1、goose 子 Agent 不能再 spawn，都是为了防止预算爆炸。
3. **工具权限是子集而非超集**——子 Agent 权限不会超过父 Agent，这是安全不变量。
4. **结果以结构化 envelope 返回**——不论叫 ResultEnvelope、SubagentResult 还是 summary JSON，都包含状态、结果和消耗信息。

### 仍有分歧的设计

1. **并发是一等公民还是事后加的**：DeerFlow 和 goose 原生支持并行，Hermes 支持但偏后台管理，OpenCode 更偏单任务委派。
2. **委派触发是工具调用还是自然语言隐式**：Hermes / DeerFlow / OpenCode 都是显式工具调用；goose 可以自然语言隐式触发（由模型判断何时 spawn）。
3. **子 Agent 是动态创建的还是预定义类型**：Hermes / DeerFlow / goose 都是动态创建（任务描述驱动）；OpenCode 有固定子 Agent 类型（general/explore/scout）。

### 项目特有但不可盲目迁移的设计

- **Hermes 的 steer / stop 控制平面**：父 Agent 可以 `steer` 正在运行的子 Agent（注入纠正文本）或 `stop` 它。这套细粒度控制很强大，但要求子 Agent 实现协作式中断，不是所有项目都能直接照搬。
- **DeerFlow 的 capacity 全局容量控制**：进程级的 `SubagentExecutionCapacity` admission controller，适合多租户或资源受限的 server 部署，单机 CLI 不需要。
- **goose 的 ACP 外部 Agent 集成**：把 Claude Code、Codex 等外部 Agent 通过 ACP/MCP 纳入统一委派框架，这是协议层创新，需要外部 Agent 实现对应协议。

> 不确定项：OpenHands SDK 和 Codex 的子 Agent 委派机制。OpenHands SDK 自述支持"多 Agent 大任务"但未在开源仓库中暴露明确的委派接口；Codex 仓库未公开子 Agent 相关源码或文档。两者的实际实现可能在商业版本或未开源模块中。以上判断基于 2026-08-30 可访问的开源内容。

---

## 7. 方法论抽象

把上面的项目实现提炼为可迁移的设计规则。

### 设计原则

1. **隔离优先，共享需显式声明**。默认子 Agent 看不到父历史、用不了父工具、花不到父预算。任何共享都必须经过显式筛选和授权。
2. **预算是委派的硬约束，不是建议**。每个子 Agent 必须有独立的 step / token / time 预算，且预算从父级扣除（或从父级分配的额度中扣除）。
3. **失败是常态，不是异常**。委派系统必须能优雅处理超时、取消、预算耗尽和运行时错误，并把不完整结果交给父 Agent 决策。
4. **深度 < 广度优先**。在相同总预算下，扁平 fan-out 比深层任务树更可靠、更可观测。深度委派是高级特性，默认关闭。

### 决策顺序

实现子 Agent 委派时，按以下顺序做决策，每一步都影响后续：

1. 先定**上下文边界**：子 Agent 能看到什么？——决定隔离强度；
2. 再定**工具权限**：子 Agent 能做什么？——决定安全边界；
3. 再定**预算模型**：子 Agent 能花多少？——决定成本可控性；
4. 再定**并发拓扑**：扁平还是树形？串行还是并行？——决定复杂度；
5. 最后定**结果格式**：ResultEnvelope 里装什么？——决定父 Agent 能否有效汇总。

不要反过来——不要先写 fan-out 逻辑再回头想"哦对了还得加个超时"。

### 可复用接口

```python
# 可复用委派接口（方法论抽象，不绑定任何项目）
@dataclass
class DelegationContract:
    task_description: str
    input_data: dict = field(default_factory=dict)
    allowed_tools: Optional[set[str]] = None
    max_steps: int = 30
    timeout_seconds: int = 300
    expected_output_schema: Optional[dict] = None
    return_mode: str = "summary"

@dataclass
class ResultEnvelope:
    subagent_id: str
    status: str  # COMPLETED | FAILED | TIMED_OUT | CANCELLED | BUDGET_EXHAUSTED
    output: Optional[Any] = None
    error: Optional[str] = None
    usage: dict = field(default_factory=dict)
    tool_receipts: list[dict] = field(default_factory=list)
    partial_artifact: Optional[Any] = None

class SubagentDelegator:
    def delegate(self, contract) -> ResultEnvelope: ...
    def delegate_parallel(self, contracts: list) -> list[ResultEnvelope]: ...
    def cancel(self, subagent_id: str) -> bool: ...
```

### 从最小实现到生产实现的路径

1. **最小可用**：单线程 + 同步委派 + 独立上下文 + 基本 blocklist；
2. **并发委派**：加入线程/进程池、并发上限、fan-out/fan-in；
3. **预算管控**：独立 step/token/time 预算、预算耗尽优雅终止；
4. **健壮失败**：超时、取消、部分失败、重试机制；
5. **可观测性**：子 Agent trajectory 追踪、归因、成本聚合；
6. **深度委派**：树形拓扑 + 每级预算分配 + 深度限制；
7. **动态权限**：基于任务声明的细粒度工具授权 + 审批。

大多数项目停留在第 3-4 级。第 6-7 级需要与 Runtime 的 checkpoint、事件系统和权限系统深度集成。

---

## 8. 实践练习

### 练习：用 Python 实现一个带预算和超时的并行委派器

**目标**：30–45 分钟内，实现一个支持并行委派、预算隔离、超时取消和部分失败汇总的子 Agent 委派器。

**前提**：假设你已有一个简单的 `SimpleAgent` 类，它有 `run(max_steps)` 方法，跑自己的 loop，返回字符串结果。不需要接入真实 LLM——可以用一个模拟 Agent 来代替（比如根据输入返回固定格式的模拟结果 + 随机 sleep）。

**要求**：

1. 定义 `DelegationContract`（task、max_steps、timeout_seconds）和 `ResultEnvelope`（status、output、error、steps_used）；
2. 实现 `SubagentDelegator.delegate_parallel(contracts)`，用 `asyncio.gather` 或 `ThreadPoolExecutor` 并发执行；
3. 每个子 Agent 有独立 step 预算和超时时间；
4. 支持部分失败——某些子任务超时/报错不影响其他子任务的结果；
5. 实现工具 blocklist（至少包含 `delegate` 本身，防止递归）；
6. 写一个测试用例：3 个子任务，其中 1 个故意超时，验证另外 2 个正常返回、超时的返回 TIMED_OUT 状态。

**进阶挑战**（+15 分钟）：加入全局并发上限（如最多同时跑 2 个子 Agent），用信号量或 bounded executor 实现。

**检验标准**：运行测试，确认总耗时 ≈ max(成功任务时间)（不是累加），确认超时任务在超时时间点附近返回，确认 blocklist 生效。

---

## 9. 掌握检查

### 自测问题

1. **delegation、handoff 和 agent-as-tool 三者的核心区别是什么？请从控制权和上下文两个维度回答。**
   - 提示：谁在驱动 loop？谁拥有完整上下文？

2. **为什么子 Agent 的工具权限必须是父 Agent 的子集，而不能是超集？如果打破这个不变量会出什么问题？**
   - 提示：从安全模型和权限升级的角度想。

3. **fan-out 场景下，"部分失败"模式比"全有或全无"模式更适合 Agent 范式，为什么？**
   - 提示：决策权应该在谁手里？Runtime 还是 Agent？

4. **结构化并发（structured concurrency）在子 Agent 委派中为什么重要？如果子 Agent 是"启动后就不管"的 fire-and-forget 模式，会有哪些问题？**
   - 提示：从资源泄漏、取消传播、错误归因三个角度说。

### 生产落地检查清单

在你的系统中加入子 Agent 委派之前，逐项确认：

- [ ] 子 Agent 有独立的 step / token / time 预算，且预算从父级分配
- [ ] 默认禁用递归委派（深度上限 = 1），更深层级需要显式配置
- [ ] 工具权限是父级子集，且 blocklist 至少包含：委派工具本身、用户交互工具、持久调度工具
- [ ] 子 Agent 上下文不是父上下文的完整复制，而是精选子集 + 任务描述
- [ ] ResultEnvelope 包含明确的状态枚举（成功 / 失败 / 超时 / 取消 / 预算耗尽）
- [ ] 并发委派有全局上限，不会因任务分解爆炸
- [ ] 取消信号能传播到子 Agent（至少是协作式的 iteration 边界检查）
- [ ] 子 Agent 的 trajectory 和消耗可观测、可归因到父任务
- [ ] 部分失败场景有明确定义的父级处理逻辑
- [ ] 子 Agent 不能直接访问共享记忆 / 共享凭证，只能通过受控接口交互

### 常见误区

1. **误区：把"多个角色 prompt"当子 Agent**。同一个上下文窗口里切换 system prompt 不是子 Agent——没有上下文隔离、没有预算隔离、没有独立 loop。关键不是角色名字，而是隔离边界。
2. **误区：子 Agent 上下文越全越好**。全量继承父历史等于没隔离，还会导致上下文膨胀随委派深度指数增长。精选子集 + 好的任务描述 > 全量历史。
3. **误区：委派一定比单 Agent 快**。并行委派对 CPU 密集 / IO 密集的独立子任务有加速效果，但对强依赖的任务（如"先写 A 再基于 A 写 B"）没有帮助，反而增加开销。错误的并行拆分反而更慢。
4. **误区：用委派代替更好的工具设计**。如果一个子任务只是查个 API 或做个计算，应该用工具调用，不是委派一个子 Agent。委派的开销远大于工具调用，只有当子任务本身需要多轮推理和工具使用时才划算。

---

## 10. 边界与延伸阅读

### 不适用边界

- 任务无法分解为独立子任务时（强顺序依赖、共享状态密集），委派的收益很低；
- 子任务极其简单（单轮工具调用搞定），用工具调用比委派高效得多；
- 延迟敏感的交互场景（用户等在屏幕前），并行委派的协调开销可能抵消收益；
- 安全要求极高的场景——多一层 Agent 就多一层攻击面，prompt injection 可以从子任务传播回父任务。

### 相关范式

- **上下文装配**（范式 #5）：子上下文的构造依赖 Context Compiler；
- **Durable State 与恢复**（范式 #6）：长生命周期的子 Agent 需要 checkpoint 和 resume；
- **权限与 Sandbox**（范式 #4）：工具权限裁剪和执行环境隔离是委派安全的基础；
- **Gateway 与 Scheduler**（范式 #9）：后台委派任务的调度和跨渠道通知。

### 官方来源

- Hermes Agent 委派工具源码：[`tools/delegate_tool.py`](https://github.com/NousResearch/hermes-agent/blob/main/tools/delegate_tool.py)（核验日期 2026-08-30）
- Hermes Agent 架构文档：[hermes-agent.nousresearch.com/docs/developer-guide/architecture](https://hermes-agent.nousresearch.com/docs/developer-guide/architecture)
- DeerFlow 子 Agent 执行器：[`backend/packages/harness/deerflow/subagents/executor.py`](https://github.com/bytedance/deer-flow/blob/main/backend/packages/harness/deerflow/subagents/executor.py)（核验日期 2026-08-30）
- DeerFlow 子 Agent 注册表：[`backend/packages/harness/deerflow/subagents/registry.py`](https://github.com/bytedance/deer-flow/blob/main/backend/packages/harness/deerflow/subagents/registry.py)
- OpenCode Agent 文档：[opencode.ai/docs/agents](https://opencode.ai/docs/agents)（核验日期 2026-08-30）
- goose Subagents 文档：[goose-docs.ai/docs/guides/context-engineering/subagents](https://goose-docs.ai/docs/guides/context-engineering/subagents/)（核验日期 2026-08-30）
- goose Orchestration 博客：[goose-docs.ai/blog/2026/05/05/goose-as-conductor](https://goose-docs.ai/blog/2026/05/05/goose-as-conductor/)
- goose 仓库：[github.com/aaif-goose/goose](https://github.com/aaif-goose/goose)（`goose-docs.ai` 是同一项目的官方文档站）
- OpenHands Software Agent SDK：[github.com/OpenHands/software-agent-sdk](https://github.com/OpenHands/software-agent-sdk)（子 Agent 委派接口未在开源仓库明确暴露）
- OpenAI Codex：[github.com/openai/codex](https://github.com/openai/codex)（子 Agent 委派实现未在开源仓库公开）
