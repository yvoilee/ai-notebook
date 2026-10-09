# 02 · Action Model：Agent 如何表达和执行行动

> 核验日期：2026-08-30  
> 主项目：Pi Agent Harness（TypeScript）  
> 对照项目：mini-SWE-agent、OpenAI Codex、Open Interpreter、Agent Zero  

---

## 1. 一句话掌握

Action Model（行动模型）定义 Agent 能做什么（affordance）、用什么语法表达行动（action space）、行动如何被分发、验证、返回成功或错误，以及多个行动如何组合、并发和审计。

---

## 2. 为什么需要它

上一篇讨论了 Agent Loop：模型每轮输出一个决策，Harness 执行并把观察（observation）回灌给下一轮。但那个讨论刻意模糊了一个问题：**模型的输出到底长什么样？**

朴素的想法是"模型输出自然语言，我们解析它"。但这个决定会连锁影响：**可靠性**（格式漂移时谁负责重试？）、**安全性**（任意 Shell 命令等于宿主全部权限？）、**组合性**（一次能调用几个工具？能并行吗？）、**可观测性**（如何记录、回放、审计？）、**错误语义**（参数错、权限错、环境错、超时——模型怎么区分？）。

"让模型输出 Markdown 代码块，我们提取执行"是很多原型的起点。它在 Demo 中工作良好，但进入生产时会遇到：格式漂移、错误不可言说、粒度失控、审计困难、组合爆炸。Action Model 的核心价值，就是把"模型能做什么"从 prompt 里的自然语言建议，提升为 Harness 层**可校验、可审计、可限制、可组合**的一等接口。

**核心概念：**

- **Affordance（可供性）**：环境提供给行动者的行动可能性。工具 schema 就是 Agent 感知到的 affordance。
- **Action Space（行动空间）**：Agent 可选择的所有行动的集合。结构化工具把连续/无限的行动空间压缩为离散的、有类型约束的空间。
- **Typed Tool（类型化工具）**：每个工具有明确的输入 schema 和输出结构。Harness 在 dispatch 前校验参数。
- **Code-as-Action（代码即行动）**：Agent 通过生成并执行代码完成任务。极其灵活，但安全面和验证成本急剧上升。
- **Shell-as-Action（Shell 即行动）**：极端形式的 code-as-action，Agent 直接输出 Shell 命令。行动空间等同于整个操作系统的能力。

Action Model 属于 **Agent Harness** 层，是 Loop 以下、Environment 以上的关键中间层：

```text
Agent Loop → Action/ToolCall → Action Model (schema/dispatch/error/audit) → ToolResult/ErrorEnvelope → Environment
```

---

## 3. 最小概念模型

### 3.1 核心对象与数据流

Action Model 的最小概念包含五个核心对象：

1. **ToolCall**：模型请求执行的一次工具调用，包含工具名称、参数（已结构化）、调用 ID。
2. **ToolSchema**：工具的静态定义，包含名称、描述、输入参数 schema、输出格式和权限标签。
3. **Dispatcher**：根据 ToolCall 找到对应工具实现，校验参数，执行，捕获异常。
4. **ToolResult**：成功执行的返回值，包含调用 ID、结构化结果、元数据。
5. **ErrorEnvelope**：失败的返回值，包含错误类型、错误码、可读消息、是否可重试。

### 3.2 语言无关伪代码：从模型输出到 ToolResult 的完整路径

```
function execute_tool_calls(model_output, tool_registry):
    calls = parse_tool_calls(model_output)
    if calls is empty: return FINAL_ANSWER(model_output.content)
    results = []
    for call in calls:
        tool = tool_registry.get(call.name)
        if tool is None:
            results.append(ErrorEnvelope(call.id, "TOOL_NOT_FOUND",
                "Unknown tool: "+call.name, retryable=true))
            continue
        ve = validate(call.arguments, tool.input_schema)
        if ve:
            results.append(ErrorEnvelope(call.id, "INVALID_ARGUMENTS",
                ve, retryable=true))
            continue
        perm = check_permission(tool, call.arguments)
        if perm == "denied":
            results.append(ErrorEnvelope(call.id, "PERMISSION_DENIED",
                "Permission denied", retryable=false))
            continue
        if perm == "needs_approval":
            results.append(ErrorEnvelope(call.id, "APPROVAL_PENDING",
                "Waiting for user approval", retryable=true))
            continue
        try:
            raw = tool.execute(call.arguments) with timeout = tool.timeout
            results.append(ToolResult(call.id, raw, {duration_ms:...}))
        catch TimeoutError:
            results.append(ErrorEnvelope(call.id, "TIMEOUT",
                "Tool execution timed out", retryable=true))
        catch Exception e:
            results.append(ErrorEnvelope(call.id, "EXECUTION_ERROR",
                e.message, retryable=tool.is_idempotent))
    return results
```

**关键教学点：失败不是异常而是数据**——所有失败路径都返回 ErrorEnvelope，Loop 只看到"结果"。错误类型决定重试策略：`TOOL_NOT_FOUND` 和 `INVALID_ARGUMENTS` 是模型侧问题；`PERMISSION_DENIED` 不可重试。权限检查嵌在 dispatch 中，不是模型说调用就一定执行。把 for 循环换成并发执行即得到并行 tool calling。

---

## 4. 关键设计决策

### 4.1 结构化工具 vs 自由代码执行

| 维度 | Typed Tool | Code-as-Action / Shell-as-Action |
|---|---|---|
| 行动空间 | 离散、有限、可枚举 | 连续、无限、图灵完备 |
| 可靠性 | 参数校验在 Harness 层完成 | 依赖模型生成正确的代码/命令 |
| 安全性 | 每个工具可独立授权和审计 | 安全边界等于执行环境的边界 |
| 灵活性 | 受限于工具集合 | 理论上可以做任何事 |
| 验证成本 | 低——每个工具单独测试 | 极高——代码的行为空间巨大 |
| 代表项目 | Pi、Codex | mini-SWE-agent、Open Interpreter 经典版、Agent Zero |

**适用条件**：任务领域可被有限工具覆盖时，typed tool 更可靠；需要开放式探索时，code-as-action 的灵活性不可替代。**失败模式**：typed tool 失败在"工具不够用"；code-as-action 失败在"不可控"。**生产收敛**：核心操作走 typed tool，开放操作走受限 code execution，共享统一错误信封和审计格式。

### 4.2 单工具串行 vs 多工具并行

- **单工具串行**：每轮一个 ToolCall。实现简单，调试方便，但效率低。
- **多工具并行**：每轮多个 ToolCall 并发执行。减少 step 数，但需处理部分失败、顺序依赖和结果合并。

Pi 和 Codex 都支持并行：全部执行完成后，每个调用的结果（成功或失败）独立返回，模型在下一轮看到完整结果集合。

### 4.3 工具粒度：原子操作 vs 复合操作

- **细粒度**：`read_file`、`write_file` 等原子操作。工具少、通用，但模型需要多步组合。
- **粗粒度**：`refactor_class`、`deploy_to_staging` 等复合操作。功能强，但工具数量爆炸，模型选择困难。

**权衡本质**：把组合复杂性放在模型那边（细粒度）还是工具实现那边（粗粒度）。**实用原则**：幂等的、安全的操作做细粒度；有副作用的、不可逆的操作做粗粒度并加审批。

### 4.4 错误语义：黑箱字符串 vs 结构化错误

- **黑箱字符串**：工具失败直接返回 stderr 或异常消息。实现简单，但错误模式不可枚举，无法自动化重试。
- **结构化错误**：ErrorEnvelope 包含 `error_type`、`message`、`retryable`、`details`。Harness 可根据错误类型决定自动重试、记录失败、触发告警。

**生产教训**：如果错误只有字符串，长期运行后无法统计"Agent 最常因为什么失败"。结构化错误是可观测性的基础。

### 4.5 工具发现：静态注册 vs 动态发现

- **静态注册**：Harness 启动时注册全部工具。简单可靠，工具集合确定。
- **动态发现**：运行时加载工具（如 MCP 服务器、插件）。灵活，但增加安全面和模型选择复杂度。

Agent Zero 的动态工具系统是后者的代表；Pi 和 mini-SWE-agent 更偏向静态注册加少量扩展点。

---

## 5. 代表项目代码佐证

> **源码事实说明**：以下 TypeScript 代码基于 Pi 的公开仓库结构与设计思路做了教学等价重写，不是源码逐字复制。Pi 使用 TypeScript，核心工具包括 read_file、write_file、edit_file、run_bash 等，工具定义采用 schema-first 方式。核验日期：2026-08-30。以官方仓库 `earendil-works/pi` 为准。

### 5.1 Tool Schema 与工具定义

Pi 风格的工具定义是 schema-first 的：每个工具同时拥有人类可读描述、类型化参数 schema 和执行函数。Schema 同时承担参数校验、模型提示生成和类型推导三重职责。

```typescript
// Pi 风格 Tool 定义（教学等价代码，非源码逐字复制）
import { z } from "zod";

interface Tool<I = unknown, O = unknown> {
  name: string;
  description: string;
  inputSchema: z.ZodSchema<I>;
  permissionTags: string[];
  timeoutMs: number;
  isIdempotent: boolean;
  execute: (input: I, ctx: ToolContext) => Promise<O>;
}
interface ToolContext { workspace: string; sessionId: string; }

const ReadFileInput = z.object({
  path: z.string().describe("File path relative to workspace"),
  offset: z.number().int().min(0).optional(),
  limit: z.number().int().min(1).max(500).optional(),
});

const readFileTool: Tool<z.infer<typeof ReadFileInput>, string> = {
  name: "read_file",
  description: "Read file contents from workspace",
  inputSchema: ReadFileInput,
  permissionTags: ["fs:read"],
  timeoutMs: 5000,
  isIdempotent: true,
  execute: async (input, ctx) => {
    const p = resolvePath(ctx.workspace, input.path);
    assertWithinWorkspace(p, ctx.workspace); // 路径沙箱
    let c = await fs.promises.readFile(p, "utf-8");
    if (input.limit) c = c.split("\n")
      .slice(input.offset ?? 0, input.offset! + input.limit).join("\n");
    return c;
  },
};
```

**设计要点**：权限标签而非直接权限判断（工具定义与权限策略解耦）；路径沙箱在工具内部完成（Harness 层安全闸门，不依赖模型自律）；幂等性声明让调度器自动决定重试策略。

### 5.2 Dispatcher 核心流程

Dispatcher 是 Action Model 的心脏：从 ToolCall 到 ToolResult/ErrorEnvelope 的完整转换，所有失败路径都返回结构化错误，从不抛出异常给 loop。

```typescript
// 核心 dispatch 流程（教学等价代码，非源码逐字复制）
interface ToolCall { id: string; name: string; arguments: unknown; }
interface ToolResult { callId: string; ok: true; output: unknown; }
interface ErrorEnvelope {
  callId: string; ok: false;
  errorType: "TOOL_NOT_FOUND"|"INVALID_ARGUMENTS"|"PERMISSION_DENIED"|"TIMEOUT"|"EXECUTION_ERROR";
  message: string; retryable: boolean;
}
type ToolOutcome = ToolResult | ErrorEnvelope;

async function dispatch(call: ToolCall, tool: Tool, ctx: ToolContext): Promise<ToolOutcome> {
  // 1. 参数校验
  const parsed = tool.inputSchema.safeParse(call.arguments);
  if (!parsed.success) return {
    callId: call.id, ok: false, errorType: "INVALID_ARGUMENTS",
    message: parsed.error.issues.map(i => `${i.path.join(".")}: ${i.message}`).join("; "),
    retryable: true,
  };
  // 2. 权限检查
  const perm = checkPermission(tool, parsed.data, ctx);
  if (perm === "denied") return {
    callId: call.id, ok: false, errorType: "PERMISSION_DENIED",
    message: `Permission denied for ${call.name}`, retryable: false,
  };
  // 3. 执行 + 异常封装
  try {
    const output = await withTimeout(tool.execute(parsed.data, ctx), tool.timeoutMs);
    return { callId: call.id, ok: true, output };
  } catch (err) {
    return {
      callId: call.id, ok: false,
      errorType: err instanceof TimeoutError ? "TIMEOUT" : "EXECUTION_ERROR",
      message: err instanceof Error ? err.message : String(err),
      retryable: tool.isIdempotent,
    };
  }
}
```

**设计要点**：ErrorEnvelope 是一等公民，所有失败路径都返回结构化错误；权限检查嵌在 dispatch 中间，是执行前的闸门；调用 ID 全程关联，支持审计和回放。

### 5.3 Outcome 到 Observation 的转换

Dispatcher 返回的 ToolOutcome 不会直接喂给模型，而是经过格式化变成 observation——这决定了模型"看到"什么样的反馈。

```typescript
// outcome → observation 转换（教学等价代码，非源码逐字复制）
function formatOutcomesForModel(outcomes: ToolOutcome[]): string {
  return outcomes.map(o => {
    if (o.ok) return `[Tool ${o.callId}] success\n${truncate(String(o.output), 10000)}`;
    return `[Tool ${o.callId}] ERROR (${o.errorType}, retryable=${o.retryable})\nMessage: ${o.message}`;
  }).join("\n\n");
}
```

> **mini-SWE-agent 对照**（方法论推断）：mini-SWE-agent 采用 bash-only 设计——整个 action model 就是一个 `run_bash` 函数，没有 schema、没有结构化错误、没有权限标签。安全完全依赖外部 sandbox（容器）。这就是 shell-as-action 的本质：用一个图灵完备的工具代替所有 typed tools，代价是安全、验证和可观测性全部下放到环境层。

---

## 6. 热门项目横向对比

### 6.1 对比表

| 维度 | Pi (TypeScript) | mini-SWE-agent (Python) | OpenAI Codex (Rust) | Open Interpreter 经典版 (Python) | Agent Zero (Python) |
|---|---|---|---|---|---|
| **行动表达范式** | Typed tools | Bash-only（单 Shell 工具） | Typed commands + code execution | Code-as-action（Python 执行） | Dynamic tool + shell + code ⁽¹⁾ |
| **工具数量与粒度** | 约 10–20 个内置工具，细粒度 | 1 个工具，粒度 = 操作系统 | 数十个命令对象，中等粒度 | 1 个执行器，粒度 = 编程语言 | 动态注册，几十到上百个，粒度不均 |
| **Schema 约束强度** | 强——Zod 校验参数，失败返回结构化错误 | 无——命令是自由文本 | 强——Rust enum 定义命令变体，类型安全 | 弱——只有解释器做语法检查 | 中——每个工具有 schema，但可动态增减 |
| **错误语义** | 结构化 ErrorEnvelope（6+ 错误类型，含 retryable） | 字符串（exit code + stdout/stderr） | 结构化 Result 类型（Rust Result + 错误码） | 原始 Python 异常 traceback | 结构化错误 + 原始异常混合 |
| **并发/组合能力** | 支持并行 tool calling | 不支持——每轮一个命令 | 支持并行命令执行 | 不支持——代码顺序执行 | 支持多工具并行调用 |
| **可审计性** | 高——ID、时间戳、权限标签、结构化结果 | 低——只有命令字符串和输出文本 | 高——命令对象、事件日志、审计轨迹完整 | 低——只有代码和执行输出 | 中——有调用记录，但动态工具增加审计复杂度 |
| **安全边界** | 工具级权限标签 + 路径沙箱 | 全部依赖外部 sandbox | Sandboxed execution + 多级审批 + workspace trust | 几乎无（默认继承宿主权限） | Docker 容器隔离 + 层级子 Agent 权限隔离 |

⁽¹⁾ Agent Zero 的动态工具系统仍在快速演进中，具体实现可能已有更新（核验日期：2026-08-30）。

### 6.2 收敛、分歧与不可迁移

**共同收敛**：①统一的 ToolCall/ToolResult 抽象——可观测性和回放的基础；②输出截断——避免上下文窗口爆炸；③超时机制——超时是预期内的失败结果；④错误反馈回模型——失败也是信息，模型需要知道才能修正。

**仍有分歧**：①行动空间开放程度——从几十个 typed tools 到一个 bash 到动态工具集，没有统一答案，取决于任务领域和安全要求；②结构化错误粒度——越细自动化能力越强，但实现成本越高；③并行调用是否原生——不仅是性能差异，也影响模型推理模式（并行要求模型在一轮中规划多个独立行动）。

**不可盲目迁移**：①Agent Zero 的动态工具发现——大多数生产系统不需要这种灵活性，反而引入信任和版本管理问题；②mini-SWE-agent 的纯 bash 设计——在封闭评估环境中高效，但生产环境等于把安全全部外包给基础设施；③Codex 的命令对象系统——Rust enum 类型安全性高，但新增工具需改核心定义、重新编译，适合稳定产品而非快速迭代。

---

## 7. 方法论抽象

### 7.1 五条设计原则

1. **Schema 优先**：工具定义是数据不是注释。Schema 同时用于模型提示、参数校验、文档生成、权限审计和测试生成。
2. **错误即数据**：任何失败都返回结构化错误信封，不抛异常。Loop 不应该有 try/catch 包裹工具调用。
3. **分层安全**：安全不只在 prompt 层说"不要做坏事"。至少三层：工具定义层（声明权限）、dispatch 层（检查权限、校验参数）、执行环境层（sandbox、容器、网络隔离）。
4. **幂等性优先**：设计工具时优先让它幂等。幂等工具可以安全重试、checkpoint 恢复后重放、并行调度中更自由。
5. **输出可预测**：工具输出的格式和长度必须可控。可能返回大量数据的工具需要内置分页或截断机制。

### 7.2 决策顺序

从零设计 Action Model，按以下顺序决策：
1. 确定任务领域的行动空间（封闭 vs 开放？工具数量？是否动态？）
2. 选择行动表达范式（typed tools / code-as-action / 混合）
3. 设计 Tool Schema 和 ErrorEnvelope（参数描述方式？错误类型？重试策略？）
4. 设计 Dispatch 流程（串行/并行？超时？权限检查插入点？）
5. 设计 Observation 格式（成功/错误如何呈现？截断策略？）
6. 设计审计与可观测性（记录哪些字段？如何关联 ToolCall 和 ToolResult？）

### 7.3 不变量与通用数据模型

设计良好的 Action Model 满足以下不变量：
1. 每个 ToolCall 有且仅有一个 ToolOutcome，绝不会"消失"或"重复"。
2. Dispatcher 从不抛出异常给调用者。所有内部错误都被包装为 ErrorEnvelope。
3. 工具执行的副作用只发生在 dispatch 之后。参数校验和权限检查不产生任何副作用。
4. 输出长度有上界。任何工具的返回值经过格式化后不超过预设阈值。
5. 调用 ID 在整个会话中唯一。支持按 ID 查询、审计和回放。

**通用数据模型**（方法论推断，可在任何语言中实现）：

```
ToolDefinition: name, description, input_schema, permission_tags, timeout_ms, is_idempotent
ToolCall: id, name, arguments
ToolResult: call_id, ok=true, output, metadata
ErrorEnvelope: call_id, ok=false, error_type(enum), message, retryable, details?
ToolOutcome = ToolResult | ErrorEnvelope
```

### 7.4 演化路径

```
阶段1：单工具 Shell 执行（≈50行）—— 原型验证、Demo、封闭沙箱
阶段2：多工具 + Schema 校验（≈300行）—— 内部工具、明确工具集合场景
阶段3：权限 + 审批 + 审计（≈500行新增）—— 面向用户的产品、生产环境
阶段4：并行 + 流式 + 动态发现（≈500行新增）—— 复杂多步任务、Agent 平台
```

---

## 8. 实践练习

### 练习：实现 Typed Tool Action Model（30–60 分钟）

**目标**：实现一个带 schema 校验、结构化错误、权限标签和超时机制的 typed tool 系统，包含 `read_file`、`write_file`、`list_dir`、`run_bash` 四个工具。

**步骤**：

1. **定义数据结构**（10 分钟）：`Tool` 接口、`ToolCall`、`ToolResult`、`ErrorEnvelope`。错误类型至少包含 `TOOL_NOT_FOUND`、`INVALID_ARGUMENTS`、`PERMISSION_DENIED`、`TIMEOUT`、`EXECUTION_ERROR`。
2. **实现四个工具**（15 分钟）：每个工具声明权限标签（`fs:read`、`fs:write`、`shell:exec`）。文件操作限制在 workspace 目录内（路径沙箱）。
3. **实现 Dispatcher**（15 分钟）：工具注册、参数校验、权限检查（`fs:read` 默认允许，`fs:write` 和 `shell:exec` 需审批）、超时执行、异常捕获和结构化错误封装。
4. **测试验证**（10 分钟）：正常调用成功；调用不存在工具 → TOOL_NOT_FOUND；参数缺失 → INVALID_ARGUMENTS；run_bash → APPROVAL_PENDING；超时命令 → TIMEOUT。

**验收标准**：五个测试用例全部通过；dispatcher 的 `dispatch` 方法永不抛出异常（总是返回 ToolOutcome）；每个 outcome 都有 `callId`，与输入 ToolCall 关联。

**进阶挑战**（可选，+30 分钟）：实现 `dispatchAll` 支持并行调用；添加输出截断；实现简单审计日志。

---

## 9. 掌握检查

### 9.1 自测问题

1. **概念辨析**：typed tool 和 code-as-action 各自的核心优势和代价是什么？在什么情况下选择其中一种？什么时候混合使用更合理？
2. **错误语义设计**：为什么 ErrorEnvelope 中需要 `retryable` 字段？如果没有这个字段，系统会损失什么能力？举出三种 `retryable=true` 和两种 `retryable=false` 的错误场景。
3. **安全分层**："Prompt 里告诉模型'不要删除文件'"为什么不是足够的安全措施？Action Model 层至少需要哪些安全机制？分别在哪个执行点生效？
4. **粒度权衡**：设计一个数据库操作 Agent，你会用单工具 `execute_sql` 还是数十个粗粒度工具？理由是什么？对可靠性和安全性的影响如何？
5. **并发与一致性**：如果 Agent 同时调用同一文件的 `write_file` 和 `read_file`，Dispatcher 应如何处理？串行化？报错？还是让竞态发生？设计理由是什么？

### 9.2 生产落地检查清单

- [ ] 所有工具都有明确的输入 schema，schema 同时用于校验和模型提示生成
- [ ] 所有工具失败返回结构化 ErrorEnvelope（错误类型 + 消息 + 可重试标志）
- [ ] 所有工具调用经过同一个 dispatcher，统一处理校验、权限、超时和异常
- [ ] 每个 ToolCall 有唯一 ID，ToolResult/ErrorEnvelope 携带相同 ID
- [ ] 工具声明权限标签，权限策略与工具定义解耦
- [ ] 所有可能挂起的工具有超时配置，超时被建模为错误结果
- [ ] 工具输出有长度限制，防止上下文窗口爆炸
- [ ] 工具明确声明是否幂等，调度器据此决定重试策略
- [ ] 所有工具调用（成功和失败）都有结构化日志记录
- [ ] 文件系统、Shell、网络操作有明确的边界限制

### 9.3 常见误区

1. **"工具越多越好"**：工具数量增加会让模型的选择成本指数上升。工具应该做"有用且必要"的最小集合。
2. **"错误信息越详细越好"**：过于详细的错误信息（如完整栈追踪）浪费上下文窗口，还可能泄露内部信息。错误只需包含模型修正行动所需的最小必要信息。
3. **"用大模型做参数校验就够了"**：模型生成的参数必须在 Harness 层用 schema 做确定性校验。格式/类型/边界值错误是确定性校验可以 100% 捕获的。
4. **"Shell 工具等于通用能力，不需要其他工具"**：shell-as-action 灵活但在可靠性、安全性和可观测性上都有代价。实用原则：只读操作做 typed tool，写操作和探索操作走受限的 shell/code execution。
5. **"并行调用只是性能优化"**：并行 tool calling 不只是更快，它还改变了模型的推理模式——需要在一轮中识别多个独立子任务并同时发起，这是一种能力跃迁。

---

## 10. 边界与延伸阅读

### 10.1 边界

- 本文聚焦于 Action Model 本身——工具定义、分发、错误和审计。工具执行的**环境隔离**（容器、VM、workspace）将在第 3 篇《Workspace 与 Runtime 隔离》中深入讨论。
- 权限标签和审批是 Action Model 与权限系统的接口，完整的权限模型将在第 4 篇《权限、审批与 Sandbox》中展开。
- 工具的动态发现和协议互操作（如 MCP、ACP）属于工具生态层面，不在本文范围。

### 10.2 官方来源

- **Pi Agent Harness**：https://github.com/earendil-works/pi — 关注 `packages/core/` 下的 tool 定义与 dispatch 模块
- **mini-SWE-agent**：https://github.com/SWE-agent/mini-swe-agent — 核心文件 `agent.py`
- **OpenAI Codex**：https://github.com/openai/codex — Rust 命令对象系统和事件驱动执行模型
- **Open Interpreter**：https://github.com/openinterpreter/openinterpreter — 当前版；经典版参考 https://github.com/endolith/open-interpreter
- **Agent Zero**：https://github.com/agent0ai/agent-zero — 动态工具注册表和层级子 Agent 工具委派
- **JSON Schema**：https://json-schema.org/ — 工具参数 schema 事实标准
- **MCP**：https://modelcontextprotocol.io/ — 工具动态发现协议
- **OpenAI Tool Calling**：https://platform.openai.com/docs/guides/function-calling — 业界主流工具调用格式

### 10.3 不确定项

- Pi 仓库的具体文件组织和类名可能随版本变化。本文 TypeScript 代码基于公开设计理念做教学等价实现，不当作源码引用。
- Open Interpreter 当前版本与经典版本差异较大，code-as-action 讨论主要基于经典版设计思想。
- Agent Zero 的工具系统仍在快速演进中，动态工具发现的具体实现可能已有更新。

---

*本文是 Agent 范式精华技术文档系列的第 2 篇。上接第 1 篇《极简 Agent Loop》，下启第 3 篇《Workspace 与 Runtime 隔离》。*
