# 03 · Workspace 与 Runtime 隔离

> 核验日期：2026-08-30
> 主项目：OpenHands Software Agent SDK / Python
> 对照项目：Codex、Agent Zero、DeerFlow、mini-SWE-agent

---

## 1. 一句话掌握

**把 Agent 的决策循环与它实际产生副作用的执行环境解耦**：Agent 只看到一个抽象 Workspace 接口，至于命令是跑在本地进程、Docker 容器、Kubernetes Pod 还是远程主机上，由 Runtime / Executor 决定，Agent 自身不感知部署拓扑。

---

## 2. 为什么需要它

### 2.1 朴素实现的陷阱

写过第一个 Agent 的人都很熟悉这个朴素实现：

```python
import subprocess
def run_bash(cmd):
    return subprocess.check_output(cmd, shell=True, cwd="./")
```

Agent loop 直接调用 `subprocess`，工作目录就是仓库根目录。跑 Demo 没问题，走向生产会遇到一连串问题：

- **环境脏**：多次任务之间文件、端口、依赖互相污染，结果不可复现。
- **权限漏**：Agent 继承启动用户的所有权限，可以读 `.ssh/`、写系统目录、访问云凭证。
- **扩缩难**：Agent 与执行环境在同一进程里，无法调度到远端机器或容器池。
- **恢复难**：进程崩溃后，消息和 workspace 里半成品文件都丢了，无法精确恢复。
- **测试难**：Agent 代码和真实文件系统紧耦合，单测只能打桩或者真的操作磁盘。

本质问题是：**决策（Agent）和副作用（执行环境）被放在同一个信任域、同一个进程、同一个文件系统里**。Workspace 与 Runtime 隔离，就是把这两者切开，让 Agent 只拥有"发出命令并收到结构化结果"的能力，而副作用的归属、生命周期和安全边界都由 Runtime 负责。

### 2.2 四个核心理念

- **控制面 / 数据面分离（control plane / data plane split）**：源自网络与分布式系统。控制面做决策（Agent、Harness、调度器），数据面执行实际操作（Shell、文件、容器、网络）。两者之间通过明确定义的协议通信，控制面故障不会扩散到数据面。
- **能力边界（capability boundary）**：Agent 只拥有被显式授予的能力（读某目录、跑某命令、访问某网络），而不是默认拥有宿主环境的全部能力。
- **位置透明性（location transparency）**：Agent 调用 `workspace.run_command(...)`，不需要知道命令是在本机、容器还是 Kubernetes 里跑的。这既是可维护性基础，也是弹性调度的前提。
- **副作用归属（side-effect ownership）**：Workspace 有明确的生命周期——创建、使用、销毁、归档。谁创建谁负责清理，任务结束后环境可以被销毁或冻结归档，不会留下孤儿进程和文件。

### 2.3 在 Agent 四层模型中的位置

Workspace 与 Runtime 隔离横跨 **Harness** 和 **Runtime** 两层：

```text
Agent Product  (CLI / IDE / Web / API)
  └─ Agent Harness
       ├─ Control loop / policy     ← Agent
       ├─ Tools + permissions       ← tool dispatch
       └─ Workspace interface       ← 本范式的上边界
            └─ Agent Runtime
                 ├─ Executor (local/container/k8s)   ← 本范式的下边界
                 ├─ Workspace lifecycle / storage
                 └─ State / events / checkpoints
```

Agent（决策单元）通过 Workspace protocol 与 Executor（执行单元）交互。这道边界既是能力边界，也是故障边界，还是可测试性边界。

---

## 3. 最小概念模型

### 3.1 核心对象与数据流

```text
┌─────────────── Control Plane ───────────────┐
│  ┌───────┐   ┌──────────┐   ┌───────────┐   │
│  │ Agent │──▶│Conversation│──▶│ Workspace  │   │
│  │ (决策)│   │ (事件/状态)│   │ (协议层)   │   │
│  └───────┘   └──────────┘   └─────┬─────┘   │
└────────────────────────────────────┼────────┘
                                     │ Workspace protocol
                                     │ (command/file/result)
┌────────────────────────────────────┼────────┐
│              Data Plane            ▼        │
│  ┌──────────┐   ┌──────────────────────┐   │
│  │ Executor │──▶│ Sandbox/Container/Pod│   │
│  │ (执行调度)│   │ - 文件系统/进程/网络  │   │
│  └──────────┘   └──────────────────────┘   │
└─────────────────────────────────────────────┘
```

四层核心对象自上而下：

| 对象 | 职责 | 所在层 |
|---|---|---|
| **Agent** | 做决策：调用模型、选择工具、决定下一步 | Control Plane |
| **Conversation** | 管理事件流、状态、取消、hooks | Control Plane |
| **Workspace** | 定义执行接口：跑命令、读写文件、列目录 | 边界协议 |
| **Executor** | 实际执行：翻译成本地进程、容器或 Pod 操作 | Data Plane |

关键性质：Agent 只依赖 Workspace 接口，不依赖具体 Executor；Workspace 有生命周期（create → use → destroy / archive）；所有副作用发生在 Executor 一侧；命令结果是结构化的（exit_code、stdout、stderr、duration）。

### 3.2 语言无关伪代码

以下伪代码展示 Workspace protocol 的核心机制。它是教学简化，不是任何项目的源码逐字复制。

```text
interface Workspace:
    create(config)  → WorkspaceHandle       // 生命周期
    destroy(handle) → void
    run_command(handle, cmd, timeout) → CommandResult
    read_file(handle, path)           → FileContent
    write_file(handle, path, content) → void

struct CommandResult:
    exit_code: int     stdout: string
    stderr: string     duration_ms: int
    timed_out: bool

interface Executor:
    create_workspace(config)  → WorkspaceHandle
    execute(handle, action)   → Result
    destroy_workspace(handle) → void

function agent_loop(agent, ws_handle, executor):
    history = []
    while agent.should_continue():
        action = agent.decide(history)
        if action.type == "final_answer":
            return action.content
        if action.type == "tool_call":
            result = executor.execute(ws_handle,
                                      to_workspace_action(action))
            history.append({"role": "tool",
                "name": action.tool_name,
                "content": structured_to_message(result)})
```

关键点：Agent 不直接产生副作用；结果是结构化的；Executor 可替换；生命周期显式化。

---

## 4. 关键设计决策

### 4.1 决策一：持久 Shell vs 无状态进程

| 维度 | 持久 Shell（persistent shell） | 无状态进程（stateless subprocess） |
|---|---|---|
| 典型实现 | 一个 bash 进程常驻，命令通过 stdin 喂入 | 每次命令 fork 一个新进程 |
| 状态 | shell 里有环境变量、工作目录、后台进程 | 每次调用独立，需显式传递 cwd 和 env |
| 隔离难度 | 高（进程树复杂，退出不干净） | 低（进程退出即清理） |
| Agent 体验 | 更接近人类终端 | 需要显式管理状态 |
| 可恢复性 | 差（shell 死了一切都丢了） | 好（命令幂等或可重放） |

**OpenHands SDK** 采用可替换执行后端模式，具体 Shell 行为取决于 Executor。**mini-SWE-agent** 采用无状态 subprocess。

**适用条件**：长时间交互式（调试 REPL、起服务器）选持久 Shell；追求可复现、可审计、可恢复选无状态进程。生产系统通常两种都支持，用不同 Executor 实现。

### 4.2 决策二：文件同步 vs 挂载 vs 只读快照

Workspace 中的文件如何与外部交互，有三种策略：

1. **完全同步（full sync）**：任务开始拷进，结束拷出。实现简单但大项目慢。
2. **挂载（mount / bind）**：宿主目录直接挂进容器。快但安全边界模糊。
3. **只读快照 + 写时复制（snapshot + CoW）**：基础镜像只读，写入只在 overlay 层。安全且可复现，但实现复杂。

**OpenHands SDK** 支持本地、容器和 Kubernetes 多种 backend，文件策略随之变化。**Codex** 的 Sandbox 更偏"受控环境 + 审批"模型。

**适用条件**：个人开发用挂载；CI/评测用快照；多租户服务用容器 + overlay。

### 4.3 决策三：本地嵌入 vs 远程 Server

Workspace 是在 Agent 进程内部实现，还是作为独立服务？

- **本地嵌入**：简单、低延迟、调试方便。但 Agent 和执行环境在同一信任域。
- **远程 Server（Agent Server）**：通过 HTTP/gRPC 调用 Workspace API。支持多租户、资源池、弹性伸缩。增加网络复杂度和延迟。

**OpenHands SDK** 的 `openhands-agent-server/` 目录就是把 Conversation + Workspace 提升为服务的实现。一旦 Workspace 有了明确协议，"本地"和"远程"只是两种不同的 Executor 实现，Agent 代码完全不需要知道——这就是位置透明性的价值。

### 4.4 决策四：能力在协议层还是执行层

Agent 的能力限制应该在哪一层强制？

- **协议层（Workspace 接口）**：dispatch 前拦截。所有 Executor 共享同一份策略，但协议变厚。
- **执行层（Sandbox）**：在容器里强制（cgroup、seccomp、网络策略）。强制力最强，但每种 backend 都要配。

成熟系统通常**两层都做**：协议层做快速拒绝和友好提示，执行层做不可绕过的安全强制（defense in depth）。

> 本范式讨论 Workspace/Runtime 的隔离架构，具体权限与 Sandbox 机制见第 4 篇《权限、审批与 Sandbox》。

---

## 5. 代表项目代码佐证

主项目：**OpenHands Software Agent SDK**（Python）

### 5.1 源码路径与定位

根据 OpenHands 官方仓库（`github.com/OpenHands/software-agent-sdk`）的公开结构，核心模块分布如下：

| 模块 | 路径 | 职责 |
|---|---|---|
| Agent | `openhands-sdk/openhands/sdk/agent/` | Agent 定义、step/astep、状态转换 |
| Conversation | `openhands-sdk/openhands/sdk/conversation/impl/local_conversation.py` | run loop、取消、hooks |
| Event | `openhands-sdk/openhands/sdk/event/` | 消息、工具、状态变化统一为事件 |
| Workspace | `openhands-sdk/openhands/sdk/workspace/` | Workspace 接口与本地实现 |
| Agent Server | `openhands-agent-server/` | 把 Conversation 提升为远程服务 |

> 说明：以上路径来自项目公开仓库结构与官方 README，是源码事实。以下代码为教学等价实现，用于阐明核心设计，不是源码逐字复制。原项目代码量较大且处于快速迭代中，建议以官方仓库最新版本为准。核验日期：2026-08-30。

### 5.2 Workspace 协议与本地实现（教学等价代码）

OpenHands SDK 的核心设计理念，是把 Workspace 抽象成协议，Agent 通过协议与执行环境交互。下面分两段展示：协议定义和一个最小化的本地实现。

**第一段：Workspace 协议定义**

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional
import uuid

@dataclass
class CommandResult:
    """命令执行的结构化返回。Agent 看到的就是这个，不直接接触进程。"""
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False
    command_id: str = field(default_factory=lambda: str(uuid.uuid4()))

@dataclass
class WorkspaceHandle:
    """Workspace 标识符。Agent 只持有 handle，不持有环境本身。"""
    workspace_id: str
    working_dir: str

class Workspace(ABC):
    """Workspace protocol：Agent 看到的全部能力接口。
    具体是本地、容器还是 Kubernetes，由实现类决定。"""
    @abstractmethod
    def create(self) -> WorkspaceHandle: ...
    @abstractmethod
    def destroy(self, handle: WorkspaceHandle) -> None: ...
    @abstractmethod
    def run_command(self, handle: WorkspaceHandle,
                    command: str, timeout: int = 30) -> CommandResult: ...
    @abstractmethod
    def read_file(self, handle: WorkspaceHandle, path: str) -> str: ...
```

**第二段：本地 Executor 的 run_command 与路径安全**

```python
import subprocess, os, time, shutil

class LocalWorkspace(Workspace):
    """本地进程实现：subprocess + 独立目录。适合开发测试。"""
    def __init__(self, root: str = "/tmp/workspaces"):
        self._root = root
        self._active: dict[str, WorkspaceHandle] = {}

    def create(self) -> WorkspaceHandle:
        ws_id = str(uuid.uuid4())[:8]
        ws_dir = os.path.join(self._root, ws_id)
        os.makedirs(ws_dir, exist_ok=True)
        handle = WorkspaceHandle(workspace_id=ws_id, working_dir=ws_dir)
        self._active[ws_id] = handle
        return handle

    def destroy(self, handle: WorkspaceHandle) -> None:
        if handle.workspace_id in self._active:
            shutil.rmtree(handle.working_dir, ignore_errors=True)
            del self._active[handle.workspace_id]

    def run_command(self, handle, command, timeout=30) -> CommandResult:
        start = time.time()
        try:
            proc = subprocess.run(command, shell=True,
                cwd=handle.working_dir, capture_output=True,
                text=True, timeout=timeout)
            return CommandResult(proc.returncode, proc.stdout,
                proc.stderr, int((time.time()-start)*1000))
        except subprocess.TimeoutExpired as e:
            return CommandResult(-1, e.stdout or "",
                f"Timed out after {timeout}s",
                int((time.time()-start)*1000), timed_out=True)

    def read_file(self, handle, path) -> str:
        full = os.path.realpath(os.path.join(handle.working_dir, path))
        # 路径穿越检查：确保解析后的路径仍在 workspace 内
        if not full.startswith(os.path.realpath(handle.working_dir)):
            raise PermissionError(f"Path traversal blocked: {path}")
        with open(full, "r") as f:
            return f.read()
```

### 5.3 代码佐证关键点

1. **Workspace 是协议，不是实现**：`Workspace` 抽象基类定义了 Agent 能看到的全部能力。`LocalWorkspace` 只是其中一个实现，换成 `RemoteWorkspace`（对应 `openhands-agent-server/` / Kubernetes backend）Agent 代码不变——这就是位置透明性。

2. **结构化结果携带错误语义**：`CommandResult` 包含 `exit_code`、`timed_out` 等字段，Agent 用逻辑判断而非字符串匹配处理错误。对比朴素实现里 `subprocess.check_output` 把所有错误都抛成异常，结构化结果给了 Agent 更细的决策粒度。

3. **显式生命周期 + 资源安全**：`create` / `destroy` 对应明确的资源获取和释放，配合 `try/finally` 可确保不泄漏。真实项目里这个生命周期绑定到 Conversation 事件（对话结束 → workspace 销毁或归档）。

4. **路径安全是 Executor 的责任**：`read_file` 中的 `realpath` + `startswith` 检查，演示了文件操作的错误处理方式。真实实现还会处理文件不存在、权限不足、符号链接攻击等更多边界情况。

---

## 6. 热门项目横向对比

### 6.1 对比表

| 维度 | OpenHands SDK | Codex | Agent Zero | DeerFlow | mini-SWE-agent |
|---|---|---|---|---|---|
| **Workspace 抽象层** | 独立 Workspace protocol，Agent 通过接口调用 | Sandbox 作为执行层，与 core 分层 | 系统级 workspace（完整 Linux 环境） | 偏高层 artifact 管理，底层依赖框架 runtime | 无显式 Workspace 抽象，直接 subprocess |
| **容器隔离** | Docker / Kubernetes backend，一等支持 | Sandbox（受控执行环境），Rust 实现 | Docker 隔离是推荐部署方式 | 可配合容器部署 | 需外部 sandbox（官方明确说明） |
| **Kubernetes 支持** | 原生支持 K8s Pod 作为 workspace | 未作为主要场景 | 不直接支持，需自行编排 | 可通过底层 runtime 支持 | 不支持 |
| **进程模型** | 可配置（subprocess / 容器 exec） | 命令执行 + 文件编辑，结构化事件 | 持久 shell + 桌面进程 | 取决于工具实现 | 无状态 subprocess |
| **生命周期管理** | Conversation 驱动 create/destroy/archive | 会话绑定，可恢复 | Docker 容器生命周期 | 任务级生命周期 | 无显式生命周期 |
| **位置透明性** | 高（同接口支持 local/container/k8s） | 中（主要面向本地 + sandbox） | 低（系统级环境假设较强） | 中（高层抽象但 runtime 依赖外部） | 无（硬编码本地执行） |
| **结构化结果** | 事件系统统一封装 | 结构化 protocol（命令、diff、事件） | 偏原始输出（系统命令返回） | 结构化 tool result | 字符串 stdout/stderr |
| **主语言** | Python | Rust | Python | Python | Python |

> 数据来源：项目公开仓库、官方 README 与源码目录结构。核验日期：2026-08-30。部分项目（DeerFlow、Agent Zero）的细粒度实现细节需进一步下钻源码确认，见 §10.4 不确定项。

### 6.2 收敛、分歧与特有设计

**共同收敛的设计**：
1. 执行环境与决策逻辑分离，即使最轻量的 mini-SWE-agent 也把 `environment` 作为独立模块。
2. 成熟项目用结构化类型传递执行结果（exit_code、stdout、stderr、timed_out），而非裸字符串。
3. 生产级项目都有显式或隐式的 workspace 生命周期概念。

**仍有分歧的设计**：
1. **Workspace 粒度**：OpenHands 是"每个 Conversation 一个 workspace"的细粒度；Agent Zero 是"整个系统作为 workspace"的粗粒度；Codex 介于两者之间。
2. **进程模型**：持久 Shell vs 无状态 subprocess 没有统一答案，取决于任务类型。
3. **隔离强度**：从本地目录到容器到 K8s Pod 到 VM，不同项目针对不同安全场景。没有"越严越好"。

**项目特有但不可盲目迁移的设计**：
- OpenHands 的 Agent Server 适合云端多租户；本地 CLI 工具引入 Server 只会增加复杂度。
- Agent Zero 的完整系统环境（桌面、浏览器）是特色，但攻击面和复杂度极高。
- Codex 的 Sandbox + 审批深度整合与其终端用户 coding agent 定位强相关，纯 SDK 不需要。

---

## 7. 方法论抽象

### 7.1 五条设计原则

1. **协议先行原则**：先定义 Workspace protocol（接口 + 数据结构），再写具体实现。Agent 永远依赖协议，不依赖具体类。
2. **副作用归边原则**：所有真实副作用（文件写入、进程创建、网络访问）只能发生在 Executor（Data Plane）一侧。Control Plane 只能通过 Workspace 协议间接产生副作用。
3. **结构化结果原则**：Workspace 返回的必须是结构化数据（带 exit_code、timed_out、error_type 等），不能是裸字符串。
4. **显式生命周期原则**：Workspace 必须有 create/destroy/archive，资源创建和释放是一等操作，需要被追踪、审计、可回滚。
5. **位置透明原则**：Agent 代码不应能区分它在和本地还是远程 workspace 交互。写了 `if isinstance(ws, RemoteWorkspace)` 说明抽象泄漏了。

### 7.2 决策顺序与不变量

从零实现 Workspace 隔离，建议按以下顺序决策：

1. 先确定安全等级（单用户 / 内部服务 / 多租户 SaaS）→ 决定隔离强度下限。
2. 再选进程模型（无状态 subprocess vs 持久 shell）→ 取决于任务类型。
3. 再定义 Workspace 协议 → 基于上面两点，定义 Agent 需要的最小接口集。
4. 最后选执行后端 → 本地 / Docker / K8s / VM，按需要实现多个 Executor。

常见反模式是上来就选 Kubernetes，然后倒推 Workspace 接口——结果接口被 K8s API 污染，Agent 被迫感知 Pod、Namespace 等运维概念。

**设计良好的 Workspace 隔离系统，以下不变量应始终成立**：
- Agent 不可绕过 Workspace 接口直接访问文件系统或进程。
- 同一个命令在不同 Executor 上运行，返回的 `CommandResult` 结构和语义一致。
- 所有被创建的 workspace 最终都会被销毁或归档，不存在"孤儿 workspace"。
- 一个 workspace 里的文件、进程、环境变量，不会出现在另一个里。
- 命令超时、OOM、磁盘满等执行层错误，被捕获并转换成结构化结果返回。

### 7.3 从 Demo 到生产的演化路径

| 阶段 | Workspace 实现 | 适用场景 |
|---|---|---|
| L0 无隔离 | 直接 subprocess + 当前目录 | 个人 Demo、学习 |
| L1 接口抽象 | Workspace ABC + 本地实现 | 单用户工具、可测试性 |
| L2 进程隔离 | subprocess + 独立目录 + 路径检查 | 内部工具、低风险任务 |
| L3 容器隔离 | Docker 容器 + volume | 多用户服务、不可信代码 |
| L4 编排隔离 | K8s Pod + 网络策略 + 资源配额 | 多租户 SaaS、弹性伸缩 |
| L5 深度防御 | VM / Firecracker + 多层策略 + 审计 | 高安全场景、合规 |

不需要一步到位，大多数团队在 L2 或 L3 就足够了。关键是接口一旦定义好，升级隔离级别不需要改 Agent 代码。

---

## 8. 实践练习

### 8.1 练习：实现 Workspace Protocol（约 45 分钟）

**目标**：亲手写一个最小 Workspace 协议和两个实现（本地 + 内存 mock），体会位置透明性和结构化结果。

**步骤**：

1. **定义协议**（10 分钟）：写 `Workspace` 抽象基类，包含 `run_command`、`read_file`、`write_file`、`list_dir` 四个方法；定义 `CommandResult` 数据类。
2. **实现本地版本**（10 分钟）：用 `subprocess.run` 和 `os` 模块实现四个方法，每个 workspace 有独立临时目录，`run_command` 处理超时。
3. **实现内存 mock**（10 分钟）：用 Python dict 模拟文件系统，`run_command` 只支持有限命令，其余返回 exit_code=127。
4. **写通用 Agent 函数**（10 分钟）：写 `run_task(ws: Workspace, description: str) -> str`，依次执行写文件 → 运行命令 → 读结果 → 返回汇总。演示同一个函数可传入两种不同实现。
5. **验证错误路径**（5 分钟）：故意运行失败命令和超时命令，确认 Agent 拿到结构化失败结果而非异常。

**验收标准**：同一个 `run_task` 函数，传入两种不同 Workspace 实现得到语义一致的结果；命令失败和超时不会让 Agent 进程崩溃；每个 workspace 有独立文件空间，互不干扰。

---

## 9. 掌握检查

### 9.1 自测问题

1. **位置透明性的代价是什么？** 提示：考虑序列化、延迟、调试难度、错误诊断。
2. **为什么 Workspace 协议返回结构化结果（CommandResult）而不是直接抛出异常？** 提示：从 Agent 决策角度思考。
3. **持久 Shell 和无状态 subprocess 各适用于什么场景？** 分别举一个适合和不适合的例子。
4. **"副作用归边原则"的含义是什么？Control Plane 直接写本地文件会有什么问题？**
5. **Workspace 生命周期为什么要显式化（create/destroy），而不是用隐式的工作目录？**

### 9.2 生产落地检查清单

- [ ] **接口隔离**：Agent 是否只依赖 Workspace 接口，不引用具体 Executor 类？
- [ ] **生命周期**：每个 workspace 是否有明确的创建和销毁时机？是否有自动清理（TTL、GC）防止泄漏？
- [ ] **资源配额**：是否限制了每个 workspace 的 CPU、内存、磁盘、网络带宽？
- [ ] **错误处理**：命令超时、OOM、磁盘满是否都被捕获并转换成结构化结果？
- [ ] **路径安全**：文件操作是否做了路径穿越检查（path traversal）？
- [ ] **网络隔离**：workspace 是否有独立的网络命名空间或网络策略？
- [ ] **凭证安全**：宿主的 `.ssh`、`.aws`、环境变量是否不会泄漏到 workspace？
- [ ] **可观测性**：每个 workspace 的创建、销毁、命令执行是否有日志和审计记录？
- [ ] **并发安全**：多个 Agent 同时操作 workspace 是否有竞态条件？
- [ ] **恢复能力**：Agent 进程崩溃后，workspace 状态能否被重新挂载或清理？

### 9.3 常见误区

1. **"用了 Docker 就安全了"**：Docker 默认配置下容器仍有相当权限。还需考虑网络策略、seccomp、capabilities、卷挂载范围等。Workspace 隔离是多层的。
2. **"Agent 能感知部署拓扑也没关系"**：一旦 Agent 代码出现 `if kubernetes:`，未来加新 Executor 就要改 Agent 代码。位置透明性是可维护性的基础。
3. **"越隔离越好"**：极致隔离有性能和可用性代价。根据实际威胁模型选级别，不要过度设计。
4. **"把 Shell 输出当结果就行"**：纯字符串输出需用正则或模型推理判断成功，既慢又不可靠。结构化结果让错误处理变成确定性逻辑。
5. **"Workspace 就是文件系统"**：除了文件，还包括进程树、环境变量、网络栈、临时端口、挂载点……生命周期管理要覆盖所有资源。

---

## 10. 边界与延伸阅读

### 10.1 与其他范式的关系

- 本篇是**第 2 篇 Action Model** 的下游：Action Model 定义了工具调用协议，Workspace 隔离定义了工具执行时的环境边界。
- 本篇是**第 4 篇 权限、审批与 Sandbox** 的上游：Sandbox 在 Workspace 隔离基础上增加更细的能力控制和审批流程。
- 本篇是**第 6 篇 Durable State 与恢复** 的基础：Workspace 状态是恢复时需要考虑的重要部分——只恢复消息不恢复文件，任务无法继续。
- 本篇与**第 11 篇 领域观察—行动接口** 互补：Workspace 是通用执行环境，领域接口（如浏览器）是特定领域的专用执行环境。

### 10.2 不适用边界

- 如果 Agent 没有任何外部副作用（纯对话、纯数据查询），Workspace 隔离不是必需的。
- 如果 Agent 就是一个本地脚本工具，只有自己用，引入完整 Workspace 抽象可能过度设计。
- Workspace 隔离不能代替权限审批和 Sandbox——它只是把执行环境和决策逻辑分开，具体哪些操作被允许需要权限系统来管。

### 10.3 官方来源

| 项目 | 官方来源 | 关注点 |
|---|---|---|
| OpenHands Software Agent SDK | [github.com/OpenHands/software-agent-sdk](https://github.com/OpenHands/software-agent-sdk) | `openhands-sdk/openhands/sdk/workspace/`、`conversation/impl/local_conversation.py`、`openhands-agent-server/`（细路径随版本演进，以仓库当前结构为准） |
| OpenAI Codex | [github.com/openai/codex](https://github.com/openai/codex) | `codex-rs/core/`、`protocol/`、`exec/`、sandbox 模块 |
| Agent Zero | [github.com/agent0ai/agent-zero](https://github.com/agent0ai/agent-zero) | Docker 配置、系统工具、workspace 目录结构 |
| DeerFlow | [github.com/bytedance/deer-flow](https://github.com/bytedance/deer-flow) | runtime 层、artifact 管理、长任务编排 |
| mini-SWE-agent | [github.com/SWE-agent/mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent) | `src/minisweagent/environments/`、subprocess 执行模型 |

> 核验日期：2026-08-30。项目处于快速迭代期，具体实现可能已变化，请以官方仓库最新版本为准。

### 10.4 不确定项

1. **DeerFlow 的 Workspace 具体实现**：其高层描述强调 planning、skills、subagents，但 workspace / runtime 层的具体实现深度和自研比例，需要下钻源码确认。
2. **Agent Zero 的远程执行能力**：以 Docker 隔离和桌面控制为特色，但是否支持 Kubernetes 等编排后端，需进一步确认。
3. **Codex Sandbox 的技术细节**：Sandbox 是在 Rust core 内实现还是依赖外部组件，以及与 OpenHands K8s backend 在隔离强度上的差异，需要更细的源码对照。
4. **OpenHands SDK 的 K8s workspace 细节**：Kubernetes backend 中 Pod 生命周期管理和文件同步机制的具体实现，需阅读 `openhands-agent-server/` 目录下的 K8s 相关代码确认。
