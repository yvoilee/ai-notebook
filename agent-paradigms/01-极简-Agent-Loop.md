# 01 · 极简 Agent Loop

> 核验日期：2026-08-30  
> 主项目：[mini-SWE-agent](https://github.com/SWE-agent/mini-swe-agent)（Python）  
> 对照项目：Pi、Codex、OpenHands SDK

---

## 1. 一句话掌握

**极简 Agent Loop 是一个"观察—决策—行动"的闭环控制过程：Agent 反复调用模型、解析行动、在环境中执行、把结果追加回历史，直到预算耗尽或任务被判定完成。**

它是所有更复杂 Agent 范式的基底——Action Model、Context、Durability、Subagent 都是往这个最小循环上叠加状态和控制面。

---

## 2. 为什么需要它

### 2.1 问题从何而来

把 LLM 变成能做事的 Agent，最朴素的想法是"让模型输出一段代码/命令，然后执行"。但这种一次性调用有三个根本缺陷：

1. **没有反馈回路**：模型不知道自己的行动是否成功，无法纠错。
2. **没有进度感**：模型无法判断任务做到了哪一步，也不会主动停止。
3. **没有资源边界**：模型可以无限输出、无限调用，成本和时延不可控。

Agent Loop 的本质是把单次模型调用包装成一个**受控的闭环控制系统**：模型是控制器，环境是被控对象，观察结果是反馈信号，预算是安全闸。

### 2.2 相关理论

- **ReAct 范式**（Yao et al., 2022）：Reasoning + Acting 交替进行，每一步先思考再行动，再根据观察继续思考。
- **闭环控制（Closed-loop Control）**：系统根据输出的反馈不断调整输入，区别于开环的一次性指令。
- **马尔可夫决策过程（MDP）**：Agent 在每一步（state）选择行动（action），环境返回新状态和奖励（reward），目标是最大化累积奖励。
- **轨迹（Trajectory）**：一次运行中所有 `thought → action → observation` 三元组的有序序列，是分析、回放和评测的基础数据。

### 2.3 在 Agent 四层体系中的位置

按本系列统一术语，极简 Loop 位于 **Harness 层**的最内核：

```text
Agent Product（CLI / IDE / UI）
  └─ Agent Harness
       ├─ ⭐ control loop ← 本章主题
       ├─ context / memory
       ├─ tools / workspace / permissions
       └─ delegation / interaction
            └─ Agent Runtime
                 ├─ state / events / checkpoints
                 └─ ...
```

一个极简 Loop 本身不负责持久化、并发、多 Agent 或复杂权限——它只回答一个问题：**一轮一轮怎么走，什么时候停。**

---

## 3. 最小概念模型

### 3.1 核心对象

最小 Agent Loop 只有五个核心概念：

| 概念 | 含义 |
|---|---|
| **Policy** | 决策函数，输入当前上下文，输出下一步行动。通常就是一次 LLM 调用。 |
| **Action** | 模型决定要做的事。可以是 Bash 命令、工具调用、或最终回答。 |
| **Environment** | 行动的执行场所。返回观察结果（成功输出或错误信息）。 |
| **Trajectory / History** | 所有轮次的 `{role, content}` 消息序列，是上下文的原始材料。 |
| **Budget** | 循环的终止约束：步数、时间、成本、Token 等。 |

### 3.2 状态机视图

```text
        ┌──────────┐
        │  START   │
        └────┬─────┘
             │ 初始化 messages / budget
             ▼
        ┌──────────┐
        │  MODEL   │ 调用模型，生成 action
        │  CALL    │
        └────┬─────┘
             │
        ┌────▼─────┐
   ┌────┤  PARSE   │ 解析 action 类型
   │    └────┬─────┘
   │         │
   │    ┌────▼─────┐
   │    │ EXECUTE  │ 在环境中执行 action
   │    └────┬─────┘
   │         │
   │    ┌────▼─────┐
   │    │ APPEND   │ 把 observation 追加到 history
   │    └────┬─────┘
   │         │
   │    ┌────▼─────┐
   └────┤  CHECK   │ 检查 budget / stop condition
  继续  └────┬─────┘
             │ 停止
             ▼
        ┌──────────┐
        │   END    │
        └──────────┘
```

### 3.3 最小状态

一个运行中的 Agent Loop，其完整状态可以用以下结构表示：

```text
RunState = {
  messages:   list[Message],   # 完整消息轨迹（system + user + assistant + tool）
  step_count: int,             # 已执行步数
  cost:       float,           # 累计成本（USD）
  deadline:   timestamp,       # 截止时间
  status:     enum,            # running | done | budget_exceeded | timeout | error
}
```

注意：`messages` 既是**历史记录**（用于调试和回放），也是**上下文输入**（下一轮模型调用的依据）。在极简 Loop 中，两者是同一个东西——这是它简单的根源，也是它遇到长任务时第一个要突破的限制。

### 3.4 语言无关伪代码

以下伪代码展示了一个 ReAct 风格的极简 Agent Loop，覆盖了模型调用、行动解析、环境执行、观察追加和预算检查五个核心环节：

```text
# 语言无关伪代码
function run_agent(task, budget):
    # 1. 初始化状态
    messages = [
        {role: "system", content: SYSTEM_PROMPT},
        {role: "user",   content: task}
    ]
    step = 0
    status = "running"

    # 2. 主循环
    while status == "running":
        # 2a. 预算检查（前置检查）
        if step >= budget.max_steps:
            status = "budget_exceeded"; break
        if now() >= budget.deadline:
            status = "timeout"; break

        # 2b. 调用模型（决策）
        try:
            response = model.call(messages)
        except ModelError as e:
            messages.append({role: "user", content: f"Model error: {e}"})
            step += 1
            continue

        # 2c. 解析行动
        action = parse_action(response)

        # 2d. 终止条件判断
        if action.type == "final_answer":
            messages.append({role: "assistant", content: response})
            status = "done"
            break

        # 2e. 执行行动（环境交互）
        try:
            observation = environment.execute(action)
        except EnvError as e:
            observation = f"Error: {e}"

        # 2f. 追加到历史
        messages.append({role: "assistant", content: response})
        messages.append({role: "user",      content: observation})

        # 2g. 更新计数与成本
        step += 1
        cost += response.token_cost

        # 2h. 成本预算检查（后置检查）
        if cost >= budget.max_cost:
            status = "budget_exceeded"

    return {messages, step, cost, status}
```

注意几个关键设计细节：
- **预算检查有两处**：进入循环时检查步数和时间（前置），执行完后检查成本（后置）。
- **错误也是观察**：模型错误和环境错误都被转化为消息写回历史，让模型自己决定如何处理。
- **状态在循环内单调增长**：`messages` 只追加不修改，`step` 和 `cost` 只增不减。

---

## 4. 关键设计决策

### 4.1 决策一：线性消息轨迹 vs. 结构化状态

**选择**：用一个扁平的消息列表作为唯一状态载体。  
**收益**：极其简单，调试时直接打印 messages 就能看到完整推理过程；模型天然理解聊天格式。  
**代价**：状态不可控——历史越长，上下文越满，成本越高，模型越容易被早期错误带偏。  
**失败模式**：长任务中上下文溢出，或早期错误在历史中反复出现导致恶性循环。

什么时候该打破线性轨迹？当你需要**选择性保留、压缩、或外置历史**时——那就是第 05 篇"上下文装配"的主题。

### 4.2 决策二：单一 Bash 工具 vs. 多工具 Schema

**选择**（mini-SWE-agent）：只给模型一个 Bash Shell，让它用命令行完成所有操作。  
**收益**：Action Model 极简——不需要定义工具 Schema、不需要参数校验、不需要分派逻辑。模型的输出就是一串 Shell 命令。  
**代价**：安全风险极高（继承宿主所有权限）、反馈格式不统一（命令输出是自由文本）、错误语义模糊（`exit code 1` 可能代表任何问题）。  
**失败模式**：误删文件、泄露凭证、死循环命令占用资源。

这是一个典型的**教学/研究友好、生产危险**的设计。生产系统必须引入权限控制和 Sandbox（见第 04 篇）。

### 4.3 决策三：预算硬限制 vs. 模型自判断

**选择**：同时使用。硬预算（步数、时间、成本）做强制兜底，模型通过输出 `finish`/`answer` 行动来自主停止。  
**收益**：既防止模型无限循环，又允许模型在完成任务时优雅退出。  
**代价**：需要模型学会识别"完成"——这本身可能需要 prompt engineering 或特定的 fine-tuning。  
**失败模式**：模型在预算耗尽前反复重试同一个错误操作；或者过早宣布完成但任务实际上没做完。

三类预算的分工：
| 预算类型 | 作用 | 特点 |
|---|---|---|
| **Step budget** | 限制最大行动次数 | 最容易实现，与成本大致正相关 |
| **Cost budget** | 限制累计 Token 成本 | 更精细，但需要实时统计 |
| **Time budget** | 限制总运行时长 | 防止环境卡死或模型慢响应 |

### 4.4 决策四：同步阻塞循环 vs. 事件驱动执行

**选择**（极简 Loop）：同步阻塞的 `while` 循环。每一步顺序执行：等模型 → 等环境 → 下一步。  
**收益**：心智模型简单，调用栈清晰，错误容易追踪。  
**代价**：无法并发执行多个工具；无法处理异步事件（如用户中断、审批回复、外部通知）；进程崩溃后无法恢复。  
**失败模式**：长命令执行期间用户无法中断；进程退出后所有状态丢失。

当你需要并发、中断和恢复时，就需要从同步循环升级为**事件驱动 Runtime**——这是第 06 篇"Durable State"和第 09 篇"Gateway/Scheduler"的主题。

---

## 5. 代表项目代码佐证

### 5.1 mini-SWE-agent 的默认 Agent Loop

**项目**：[mini-SWE-agent](https://github.com/SWE-agent/mini-swe-agent)  
**源码路径**：`src/minisweagent/agents/default.py`  
**在完整执行链中的位置**：CLI 入口 → Agent.run() ← 本章解读 → Bash 环境执行 → 输出结果

mini-SWE-agent 是 SWE-agent 项目的"极简版"，核心 Agent 实现非常短，正好用于展示一个最朴素的 ReAct Loop。它的设计哲学是：**用最少的代码跑通一个能解决真实 SWE 任务的 Agent**，所有高级特性（多工具、GUI、评测框架）都被剥离。

以下是根据官方仓库结构和设计意图重写的**教学等价代码**，不是源码逐字复制。它保留了核心逻辑：线性消息历史、单 Bash 工具、三类预算、模型驱动的停止判断。

**源码事实**：默认 Agent 使用线性消息列表 + Bash 执行 + step/cost/time 三类预算。  
**教学简化**：省略了模型适配层、交互式审批、文件观察工具封装和错误分类；`_parse_response` 的正则解析器做了大幅简化。

```python
# 教学等价代码（基于 mini-SWE-agent 设计，非源码逐字复制）
import time
from dataclasses import dataclass, field

@dataclass
class Budget:
    max_steps: int = 30
    max_cost: float = 2.0
    max_seconds: float = 600

@dataclass
class RunState:
    messages: list[dict] = field(default_factory=list)
    step_count: int = 0
    total_cost: float = 0.0
    start_time: float = field(default_factory=time.time)
    status: str = "running"  # running|done|budget_exceeded|timeout|error

class MinimalSWEAgent:
    def __init__(self, model, bash_env, system_prompt, budget):
        self.model, self.bash_env = model, bash_env
        self.system_prompt, self.budget = system_prompt, budget

    def run(self, task):
        state = RunState()
        state.messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": task},
        ]
        while state.status == "running":
            if state.step_count >= self.budget.max_steps:
                state.status = "budget_exceeded"; break
            if time.time() - state.start_time >= self.budget.max_seconds:
                state.status = "timeout"; break
            try:
                response = self.model.chat(state.messages)
            except Exception as e:
                state.messages.append({"role": "user",
                    "content": f"[Model call failed: {e}]"})
                state.step_count += 1; continue
            state.total_cost += getattr(response, "cost", 0.0)
            action, is_final = self._parse_response(response.content)
            if is_final:
                state.messages.append({"role": "assistant", "content": response.content})
                state.status = "done"; break
            try:
                obs = self.bash_env.run(action)
                obs_text = f"```bash\n$ {action}\n{obs.stdout}\n{obs.stderr}\n(exit: {obs.returncode})\n```"
            except Exception as e:
                obs_text = f"[Execution error: {e}]"
            state.messages.append({"role": "assistant", "content": response.content})
            state.messages.append({"role": "user", "content": obs_text})
            state.step_count += 1
            if state.total_cost >= self.budget.max_cost:
                state.status = "budget_exceeded"
        return state
```

行动解析逻辑（`_parse_response`）使用正则从自由文本中提取 Bash 命令或识别 finish 信号——这是极简 Loop 的典型脆弱点。教学等价实现如下：

```python
import re

def _parse_response(self, text):
    """提取 Bash 命令或判断是否完成。教学简化版。"""
    if re.search(r"\b(finish|I have completed|The answer is)", text, re.I):
        return "", True
    m = re.search(r"```bash\n(.*?)\n```", text, re.DOTALL)
    if m:
        return m.group(1).strip(), False
    return "echo 'Please wrap bash commands in ```bash ... ``` or finish.'", False
```

**需要关注的关键点**：

1. **状态完全由 `messages` 列表承载**：每一轮结束后，assistant 消息和 observation（作为 user 消息）被追加进去。下一轮的模型输入就是这个完整列表。这是"线性轨迹"设计的直接体现。

2. **错误也是反馈**：模型调用失败和环境执行失败都不会终止循环，而是被封装成消息写回历史。模型在下一轮看到错误信息后自行决定如何处理。这种"把一切都交给模型"的策略是极简 Loop 的标志。

3. **三类预算分别检查**：步数和时间在循环开头检查（前置），成本在执行后检查（后置）。三类预算对应三种失败模式：重复无效操作、环境挂起、长上下文成本爆炸。

4. **`_parse_response` 是脆弱点**：用正则从自由文本中提取行动格式——模型一旦不按预期格式输出，解析就会失败。这就是为什么更成熟的系统转向结构化工具调用（tool use / function calling），把行动解析从"正则匹配"升级为"模型输出结构化 JSON + Schema 校验"。

---

## 6. 热门项目横向对比

以下对比聚焦于 **Loop 表示、状态载体、停止条件、错误反馈、可恢复性** 五个维度——这些是 Agent Loop 范式的核心问题，而非泛泛的功能对比。

| 项目 | Loop 表示 | 状态载体 | 停止条件 | 错误反馈方式 | 可恢复性 |
|---|---|---|---|---|---|
| **mini-SWE-agent** | 同步 `while` 循环，单文件实现 | 线性 `messages` 列表 | 模型输出 finish + step/cost/time 硬预算 | 错误文本直接追加为 user message | 无，进程退出即丢失 |
| **Pi** | Agent Core 循环，模块化 Tool/Memory/TUI 层 | `SessionState`（消息 + 工具元数据 + 会话配置） | 模型 final response + 可配置 step budget | ToolResult 结构化对象（成功/错误/中断） | 会话可序列化保存，重启后可加载 |
| **OpenAI Codex** | 事件驱动 Runtime，命令/事件/状态分离 | 命令队列 + 事件日志 + 会话快照 | 任务完成判定 + 审批中断 + 超时 | 结构化错误码 + 分类处理（可重试/致命/需审批） | 完整 checkpoint 与恢复，支持中断后续跑 |
| **OpenHands SDK** | Agent Server 事件循环，Event 驱动 | Conversation + Events + ToolState 分层 | Step limit + agent 主动 finish + 用户中断 | Event 流中的 ErrorEvent，附带元数据 | 完整 durable state，支持从任意事件恢复 |

### 6.1 共同收敛的设计

1. **都有硬预算兜底**：无论系统多复杂，step limit / timeout 是必选项。这说明"模型会卡住"是所有 Agent 系统的共识风险。
2. **都区分"模型自停止"和"系统强制停止"**：前者是正常完成，后者是异常终止——两者的状态和后续处理完全不同。
3. **错误都回注给模型**：没有哪个系统在工具出错时直接 crash——都把错误信息作为下一轮的输入，让模型决定重试还是换路。

### 6.2 仍有分歧的设计

1. **状态粒度不同**：mini-SWE-agent 只有消息列表；Codex 和 OpenHands 把状态拆成命令、事件、会话快照多层。这反映了从"教学简单"到"生产可运维"的演进。
2. **行动格式不同**：从自由文本 + 正则（mini-SWE-agent）→ 结构化 Tool Call（Pi、OpenHands）→ 命令 + 事件双通道（Codex）。行动格式的演进是 Harness 复杂度增长的主线之一。
3. **错误处理策略不同**：极简系统"把错误全丢给模型"；成熟系统会先分类错误（可重试/需要审批/致命），再决定是否让模型介入。前者简单但浪费 token，后者高效但需要更多工程。

### 6.3 项目特有但不可盲目迁移的设计

- **mini-SWE-agent 的单 Bash 工具**：在 SWE 基准测试（代码仓库任务）中效率很高，因为 Shell 本身就是万能工具。但不能推广到需要精确权限控制的生产环境。
- **Codex 的事件驱动 Runtime**：为桌面端 Coding Agent 设计，支持异步审批、后台执行和 UI 更新。对于 CLI 场景的简单 Agent 来说过重。
- **OpenHands 的 Workspace 解耦**：为远程/容器化执行环境设计，本地开发时增加了不必要的抽象层。

---

## 7. 方法论抽象

### 7.1 设计原则

1. **先证明最小闭环，再增加状态和控制面**：永远从一个能跑通的 while 循环开始，而不是从架构图开始。只有闭环跑通了，你才知道瓶颈在哪、哪里需要加复杂度。
2. **预算是第一公民**：没有预算的 Agent Loop 就是无限循环。把 step/cost/time 三类预算放进版本 0.1，比任何"智能"特性都重要。
3. **错误也是一等公民**：每个行动都有三种结果——成功输出、业务错误、系统错误。后两种必须能被模型看见和处理。
4. **状态单调增长**：在极简 Loop 中，messages 只追加不修改。这让调试和回放变得简单。任何"修改历史"的操作都需要额外的理由和审计机制。

### 7.2 决策顺序

从零构建一个 Agent Harness，Loop 层的决策应按以下顺序进行：

```text
第 1 步：确定行动格式（自由文本？结构化 Tool Call？命令事件？）
   ↓
第 2 步：确定状态载体（线性消息？分层状态？事件溯源？）
   ↓
第 3 步：确定预算机制（step / cost / time，谁来检查，检查频率）
   ↓
第 4 步：确定停止条件（模型自停止的信号格式 + 硬停止的触发点）
   ↓
第 5 步：确定错误语义（哪些错误让模型重试，哪些直接终止）
```

顺序很重要——**行动格式决定了状态结构，状态结构决定了恢复和可观测性的上限**。如果第 1 步选了自由文本 + 正则，后面的所有控制都会受限。

### 7.3 可观察的不变量

一个健康的 Agent Loop 应该满足以下不变量（invariant）：

| 不变量 | 含义 | 违反时的症状 |
|---|---|---|
| step 数 ≤ max_steps | 总步数不超过预算 | 无限循环、成本爆炸 |
| cost ≤ max_cost | 累计成本不超过预算 | 账单失控 |
| 每轮 messages 长度严格递增 | 每轮至少追加 assistant + observation 两条 | 静默失败、状态丢失 |
| 最终 status ∈ {done, budget_exceeded, timeout, error} | 循环一定以某种确定状态终止 | 悬挂进程、资源泄漏 |

### 7.4 从最小实现到生产实现的演化路径

```text
阶段 0：同步 while 循环 + 消息列表 + 单工具   ← mini-SWE-agent
  → 阶段 1：结构化 Tool Call + 参数校验 + 工具分派   ← Pi
  → 阶段 2：会话状态序列化 + 可中断 + 可恢复   ← Pi/Cline（部分）
  → 阶段 3：事件驱动 Runtime + 命令/事件/状态分离   ← Codex、OpenHands
  → 阶段 4：Durable State + Checkpoint + 并发 + 观测
  → 阶段 5：多 Agent + 委派 + 子任务隔离   ← Hermes、OpenHands multi-agent
```

每个阶段都只解决一个核心问题，并且前一阶段的问题必须已经被解决。跳阶段实现（比如还没有可靠的单 Agent Loop 就直接做多 Agent）几乎一定会在可靠性上付出代价。

---

## 8. 实践练习

### 练习：用 Python 写一个 60 行的极简 Agent Loop

**预计时间**：30–45 分钟  
**目标**：亲手实现一个能跑通"模型调用 → 行动解析 → 环境执行 → 预算检查"全流程的最小 Agent，理解每一步的状态变化。

**步骤**：

1. **准备环境**：使用任何支持 chat completion 的模型 API（或用 mock 函数代替，方便离线测试）。环境模拟用 Python 的 `subprocess` 执行 Bash 命令即可。

2. **实现 `run_agent` 函数**，要求：
   - 接收 `task: str` 和 `budget: dict` 两个参数
   - 维护 `messages`、`step`、`cost` 三个状态变量
   - 循环中依次完成：预算检查 → 模型调用 → 解析 Bash 命令 → 执行 → 追加观察
   - 模型输出包含 `FINISHED` 时停止
   - step 超过 `budget["max_steps"]` 或 cost 超过 `budget["max_cost"]` 时停止

3. **测试用例**：
   - 正常完成：让 Agent 执行 `echo hello world` 并说 FINISHED（验证正常路径）
   - 超步数：设置 `max_steps=2`，让模型反复 `echo` 不停止（验证 budget 路径）
   - 错误恢复：故意让第一步执行 `nonexistent_command`，观察模型是否能从错误中调整（验证错误反馈路径）

4. **进阶挑战**（可选）：
   - 添加 time budget（用 `time.time()` 做 deadline 检查）
   - 添加一个 `max_context_tokens` 限制，在上下文过长时截断早期历史
   - 想想截断早期历史会丢失什么？这暴露了极简 Loop 的什么局限？

**验收标准**：
- 三个测试用例都能跑出预期的最终 `status`
- 打印完整 `messages` 列表能清晰看到每一轮的 action 和 observation
- 代码不超过 60 行（不含 import 和测试代码）

---

## 9. 掌握检查

### 9.1 自测问题

1. **为什么说"错误也是观察"？** 如果在工具执行失败时直接终止 Agent，而不是把错误信息写回历史，会丢失什么能力？

2. **极简 Loop 中，`messages` 同时承担了"历史记录"和"上下文输入"两个角色。这种设计的优点和局限各是什么？当任务变长时，第一个会出问题的方面是什么？**

3. **三类预算（step / cost / time）分别防止什么类型的故障？请各举一个场景例子。为什么不能只用其中一类？**

4. **mini-SWE-agent 使用正则从自由文本中提取 Bash 命令；Pi 使用结构化 Tool Call。这两种 Action Model 对 Loop 的错误处理有什么影响？**

### 9.2 生产落地检查清单

在把一个极简 Loop 推向生产之前，逐项确认：

- [ ] 三类预算（step / cost / time）都已实现，且有合理的默认值
- [ ] 模型输出格式有兜底解析，格式错误时会反馈给模型而不是 crash
- [ ] 环境执行有超时保护，防止单个命令无限挂起
- [ ] 最终状态明确（done / budget_exceeded / timeout / error），不会出现模糊状态
- [ ] 完整 trajectory 可导出，用于调试和评测
- [ ] 工具执行有权限边界（至少不能默认继承宿主全部权限）
- [ ] 用户可以在执行过程中中断

### 9.3 常见误区

1. **误区："模型足够聪明就不需要预算"**  
   错。模型会陷入重复、会被错误信息引导、会忘记自己已经试过什么。预算是工程兜底，不依赖模型能力。

2. **误区："把 history 做长就是长期记忆"**  
   错。线性追加的 history 只是窗口内的原始数据。长期记忆需要写入、检索、遗忘和审计机制——那是第 07 篇的主题。

3. **误区："自由文本行动格式不够优雅，所以直接上最复杂的结构化工具系统"**  
   错。行动格式的复杂度应该和任务需求匹配。对于某些场景（如纯代码仓库操作），单 Bash 工具可能比十个结构化工具更高效。

4. **误区："错误处理越精细越好"**  
   不一定。每多一层错误分类就多一分复杂度。极简 Loop 的"把所有错误都扔给模型"策略虽然浪费 token，但实现成本为零。在早期阶段，简单策略往往更有价值。

---

## 10. 边界与延伸阅读

### 10.1 本文的边界

- 只讨论**单 Agent、单线程、同步阻塞**的极简 Loop。并发、异步、事件驱动 Runtime 不在本篇范围。
- 行动格式只做了概念层面的对比，不深入 Tool Schema 设计、参数校验和工具分派——那是第 02 篇"Action Model"的主题。
- Workspace 隔离、Sandbox 和远程执行环境的问题在第 03、04 篇讨论。
- 上下文压缩、外置和记忆系统在第 05、07 篇讨论。

### 10.2 官方来源

| 来源 | 链接 | 用途 |
|---|---|---|
| mini-SWE-agent 官方仓库 | https://github.com/SWE-agent/mini-swe-agent | 主项目源码与 README |
| mini-SWE-agent 默认 Agent 实现 | `src/minisweagent/agents/default.py`（仓库内） | Agent Loop 核心实现 |
| Pi Agent Harness | https://github.com/earendil-works/pi | 对照项目：模块化 Harness 设计 |
| OpenAI Codex | https://github.com/openai/codex | 对照项目：事件驱动生产 Runtime |
| OpenHands Software Agent SDK | https://github.com/OpenHands/software-agent-sdk | 对照项目：Agent Server 与 Workspace 解耦 |
| ReAct 论文 | https://arxiv.org/abs/2210.03629 | Reasoning + Acting 范式原始文献 |

> 注：mini-SWE-agent 的 `src/minisweagent/agents/default.py` 路径基于项目结构惯例，核验日期为 2026-08-30。项目快速演进中，建议以仓库最新 main 分支为准。

### 10.3 下一步阅读

- 想知道行动格式如何从自由文本演进到结构化工具调用 → 第 02 篇《Action Model》
- 想理解 Agent 的执行环境如何与宿主隔离 → 第 03 篇《Workspace 与 Runtime 隔离》
- 想知道长任务中上下文不够了怎么办 → 第 05 篇《上下文装配、压缩与外置》
