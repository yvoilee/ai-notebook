# 第四部分：理解设计取舍

## 八、Consolidation 与后台链路：记忆如何学习和进化

![Consolidation 后台链路](https://feishu.cn/file/FQi4bsY3todCecxPhgtcCUoTn0c)

### 8.1 为什么需要后台巩固：retain 只负责写入，学习发生在 consolidation

读到第七章，读者可能已经有一个疑问：retain 把文档切成 chunks、抽成事实（fact）、写进 `memory_units`，recall 四臂并行把它们捞回来——这一套已经能"记住"了，为什么还需要一个后台进程？

答案是：**retain 是"编码"，consolidation 才是"学习"**。retain 阶段做的事是被动的信息登记——一段文本进来，抽出其中提到的实体、时间、关系，逐字落库。它不判断"这件事之前是不是已经知道了"，也不把"用户上周说喜欢徒步"和"昨天说要去优胜美地"合并成一句更稳定的信念。如果没有 consolidation，`memory_units` 表里会随着对话线性膨胀：同一个事实被说十遍，就有十条几乎重复的记忆，recall 时还会互相打架。

Consolidation 就是把这些零散事实（`fact_type='experience'` 与 `fact_type='world'`）在后台反复比较、合并、归纳，沉淀成 **observation**——一种 `fact_type='observation'` 的 memory_unit。它在 `engine/consolidation/consolidator.py`（3763 行）中实现，入口是 `run_consolidation_job()`（第 1542 行）。它由 retain 操作间接触发（retain 完成后在 `async_operations` 表里写一条 `consolidation` 类型任务），不阻塞用户请求。

这就解释了第二章提到的"三个最重要的认识"之一：**学习发生在后台**。用户调 `retain()` 立刻返回，Agent 下次对话时感知到的记忆质量，取决于后台那一轮 consolidation 跑完没有。

### 8.2 Observation 生成：从多条事实中归纳信念

consolidation 的核心是一次带状态的 LLM 批处理。流程如下：

```
retain 写入 N 条未巩固事实 (consolidated_at IS NULL, fact_type ∈ {experience, world})
        │
        ▼
_count_unconsolidated_rows()  ── 统计待处理量，写 operation 进度 (0/N → N/N)
        │
        ▼
按 tag scope 分组 (_consolidation_batch_key)，每批 consolidation_batch_size 条
        │
        ▼
为每批新事实做一次召回 (_find_related_observations)
   ├─ 向量召回已有的相关 observation
   └─ 拼成 "new facts + existing observations" 两个文本块
        │
        ▼
_consolidate_batch_with_llm() 调用 consolidation_llm
   system prompt = 缓存前缀 (build_consolidation_system_prompt，bank 无关)
   user  message = MISSION + 本批 INPUT (+ capacity 约束)
        │
        ▼
LLM 返回 JSON：{"creates": [...], "updates": [...], "deletes": [...]}，每项带 reason
        │
        ▼
校验 + 去重 (_dedupe_updates，同一 observation_id 只允许一条 update)
        │
        ▼
_apply_create_action / _apply_update_action / _execute_delete_action 落库
        │
        ▼
_trigger_mental_model_refreshes()  ── 触发受影响的 mental model 刷新
```

LLM 要做一个明确的三选一决策，写在 `consolidation/prompts.py` 的 `_PROCESSING_RULES` 和 `_DECISION_GUIDE` 里：

- **CREATE**：新事实描述的是一个此前没有任何 observation 覆盖的独立 facet（"Alice 每周工作到凌晨"），就新建一条 observation；
- **UPDATE**：新事实在讲同一个 canonical 事件/决定/主张（"Donald 再次强调 Athena 的自主权"），就把它作为证据追加到已有 observation 上，而不是新建一个兄弟节点；
- **DELETE**：旧 observation 被新事实彻底推翻（"beta 候补名单已关闭，改为开放注册"），才删除，并同时 create 替代项。

几条容易被忽视但很关键的硬规则（prompts.py 原文）：

1. **PREFER UPDATE OVER CREATE**："One canonical observation with many source facts is always better than many siblings with one source fact each." 但 CREATE 仍是默认——规则只防重复，不拒绝记录新知识。
2. **ONE OBSERVATION PER DISTINCT FACET**：一条 observation 只追踪一个 facet——一个计数、一个实体属性、一个关系、一个决定。绝不把不同 facet 揉进一条。
3. **MATCH BY ENTITY/FACET, NOT TOPIC**：不能因为话题相近就合并，必须命中同一个具体实体或 facet。
4. **NO COMPUTATION**：consolidator 明确被禁止做算术。用户先说"我有 2 只狗"再说"我有只叫 Rex 的狗"，它**不会**自作主张改成 3——因为它不知道 Rex 是不是那两只之一。计数只在用户明确给新值时才更新。
5. **PRESERVE HISTORY**：sold/died/moved 这类有历史意义的 observation 永不删除，只做 UPDATE 保留时间线。

输出格式强制要求每条 create/update/delete 都带 `reason`，并且这条 reason 会被审计（"This is audited to catch duplicate creates"）——这是工程上防止 LLM 无脑新建兄弟 observation 的关键闸门。

### 8.3 Observation 的证据链与 proof_count

observation 不是改写过的事实，而是一条**指向多条源事实的指针**。它在 `memory_units` 表里就是普通一行，但多了两个字段：

- `source_memory_ids: uuid[]`——这条 observation 合并了哪些原始 fact 的 id；
- `proof_count: int`——这些源事实去重后的数量。

看 consolidator.py 第 413-414 行（UPDATE 分支）的 SQL 写法，就能理解证据链是怎么维护的：

```sql
source_memory_ids = (
    SELECT array_agg(DISTINCT e) FROM unnest(source_memory_ids || $2::uuid[]) e
),
proof_count = (
    SELECT count(DISTINCT e) FROM unnest(source_memory_ids || $2::uuid[]) e
)
```

每次 UPDATE，新证据的 id 被 `||` 拼进旧数组，再 `DISTINCT` 去重；`proof_count` 永远是数组里去重后的真实基数，而不是简单累加 1。第 1404-1417 行的 `_reconcile_merge_via_store` 做的是同一件事：`merged_sources = list(dict.fromkeys([...]))`，再把 `proof_count=len(merged_sources)` 写回。

这带来一个重要性质：**observation 的"可信度"是可计算的**。`proof_count=1` 意味着这只是某人一句话的孤证；`proof_count=5` 意味着五条独立来源在说同一件事。这正是下一章要讲的"证据驱动"设计在数据结构上的落点。

还有一个反向保护：`_filter_live_source_memories()`（第 731 行）会检查 observation 引用的源 fact 是否还活着。如果一条 observation 的全部源记忆后来都被失效归档了（`_any_live_source_memory` 返回空），这次 UPDATE 会被跳过——不会让一条失去全部证据的"幽灵信念"继续留在库里。库表层面另有 `observation_sources(observation_id, source_id)` 这张关联表（见 spec 固定事实），把证据链独立成可索引的多对多关系。

### 8.4 Mental Model 刷新：trigger 机制与定时任务

observation 是"信念"，mental model 是"对某类信念的总结陈述"。consolidation 跑完后，并非所有 mental model 都需要重算——那样太贵。Hindsight 用了两级触发：

**第一级：consolidation 后增量触发。**`_trigger_mental_model_refreshes()`（第 2265 行）只挑两类候选：

1. `mental_models.trigger->>'refresh_after_consolidation' = true` 的模型；
2. 且其 tag 作用域真的被这轮 consolidation 碰到了（SQL 里用 `tags && $2::varchar[]` 做粗过滤，再调 `compute_mental_model_is_stale()` 精确认定"自上次刷新后确实有新记忆进来"）。

命中后调 `submit_async_refresh_mental_model(..., skip_if_in_flight=True)`。`skip_if_in_flight` 很关键：一条 consolidation 链每一轮都会触发刷新，而多个 consolidation 可能在同一 bank 上并发跑，正在 pending/processing 的模型不能被重复入队（源码注释指向 issue #3411）。

**第二级：cron 定时触发。** 在 `engine/maintenance.py`（第 470 行）里，一个维护例程用 `croniter` 计算 `trigger.refresh_cron` 是否到期：

```python
cron = row["refresh_cron"]
prev_fire = croniter(cron, now).get_prev(datetime)   # 上一个该触发的时刻
if prev_fire > last_refreshed_at:   # 且距上次刷新还没触发过
    # 提交一次 refresh
```

也就是说，mental model 有两种自动刷新策略：跟着新记忆走（`refresh_after_consolidation`），或按时刻表走（`refresh_cron`，如"每天早上重算一次用户画像"）。两者都落到同一个 `refresh_mental_model` 异步任务上。

### 8.5 Worker 与 async_operations：分布式后台处理

后台任务不是进程内线程池，而是一张数据库表驱动的分布式队列——`async_operations`。字段（见 spec）：`operation_id, bank_id, operation_type, status(pending/processing/completed/failed/cancelled), worker_id, retry_count, task_payload`。

`worker/poller.py`（2166 行）里的 `WorkerPoller` 类（第 290 行）就是这个队列的消费者：

```
poller 循环
  claim_batch()  ── SELECT ... WHERE status='pending' AND next_retry_at <= now()
                     按 slot 预留容量挑任务，拿到 worker_id 标记为 processing
        │
        ▼
  按 operation_type 分配槽位（slot_reservations，默认 {"consolidation": 2}，
  即保证 consolidation 至少占 2 个并发槽，retain 最多挤占其余）
        │
        ▼
  self._executor(task.task_dict)   # 注入的是 MemoryEngine.execute_task
        │
        ├─ 正常返回 → _mark_all_completed
        ├─ 抛 RetryTaskAt → _schedule_retry_all（status 回 pending，next_retry_at 推迟，retry_count+1）
        ├─ 抛 DeferOperation → _defer_all（背压，不算失败）
        ├─ _WallTimeoutExceeded → _mark_all_failed（任务卡死超时被取消）
        └─ 其他异常 → _mark_all_failed，写 error_message
```

几个设计细节值得单独说：

- **按任务类型区分墙钟超时**。`_WALL_TIMEOUTS` 字典（第 83-92 行）里，retain 是"绝对总时长上限"（一个 retain 就该一口气跑完），而 consolidation 是"无进展时长上限"（idle ceiling——只要还在打 heartbeat 更新 stage，跑多久都行，但一旦卡住不动就判超时），`refresh_mental_model` 复用 reflect 的超时。这避免了长 consolidation 被误杀。
- **背压与重试分离**。存储层主动拒绝写入时抛 `is_store_backpressure`，poller 把它当成"推迟"而非"失败"（`_backpressure_defer_seconds`），不消耗 retry 预算——否则积压时一批长 ingest 会在重试次数耗尽时丢文档。
- **retain 折叠（fold）**。第 735 行 `_fold_retain_peers` 会把排在同一 serialization_key 后面的多个 retain 折叠进一次执行，减少 LLM 开销。
- **子任务状态聚合**。`batch_retain` 会拆成多个子 operation，`_maybe_update_parent_operation` 在所有兄弟完成后才把父任务标终态。

### 8.6 Webhook：生命周期事件通知

后台链路需要对外部系统可观测，Hindsight 用 webhook 做事件外发。`webhooks/models.py` 定义了三类事件：

```python
class WebhookEventType(StrEnum):
    CONSOLIDATION_COMPLETED = "consolidation.completed"
    RETAIN_COMPLETED        = "retain.completed"
    MEMORY_DEFENSE_TRIGGERED = "memory_defense.triggered"
```

每个事件是一个统一信封 `WebhookEvent`：`event / bank_id / operation_id / status / timestamp / data`，`data` 按事件类型分别是 `ConsolidationEventData`（observations_created/updated/deleted 计数）、`RetainEventData`（document_id、memory_unit_count）、`MemoryDefenseEventData`（action=redact/block、matched_types）。

投递由 `webhooks/manager.py`（244 行）负责；`webhooks/url_guard.py`（337 行）做目的地安全——默认阻止向私网地址投递（`DEFAULT_WEBHOOK_ALLOWED_HOSTS=[]` 即只允许公网目的地，见 config.py 第 2077 行），这是防 SSRF 的关键配置。

### 8.7 本章小结

- retain 只负责把信息编码入库；**真正的"学习"——去重、合并、归纳成带证据的信念——发生在后台 consolidation**。
- consolidation 是一个带状态的 LLM 批处理：召回相关 observation → 让模型在 CREATE/UPDATE/DELETE 间三选一 → 校验去重后落库。规则明确禁止模型做算术、鼓励合并、极度保守地删除。
- observation 的可信度落在两个字段上：`source_memory_ids`（证据指针数组）与 `proof_count`（去重后的证据数），且会清理掉全部源记忆失效的"幽灵信念"。
- mental model 有两条刷新路径：`refresh_after_consolidation` 增量触发、`refresh_cron` 用 croniter 定时触发，二者都进异步队列且防重复入队。
- 后台任务用 `async_operations` 表做分布式队列，WorkerPoller 按任务类型分配槽位、区分绝对/空闲超时、把背压当推迟而非失败。
- webhook 把 retain / consolidation / memory_defense 三类生命周期事件外发给外部系统，并有 URL 守卫防止 SSRF。

---

## 九、Hindsight 的关键设计思想（本文归纳）

> **本章标注：本文归纳。** 以下六条不是 README 逐条列出的"官方特性清单"，而是作者在通读 `engine/` 各模块后从源码行为中提炼出来的设计取舍。每一条都附了源码依据，便于读者回到代码验证。

### 9.1 仿生记忆结构：world / experience / observation 的分层

**设计思想**：Hindsight 不把所有文本一视同仁地塞进一个向量池，而是按"记忆的人类形态"分三层——`fact_type` 字段就是这条分界线：

| fact_type | 语义 | 类比人类记忆 |
|-|-|-|
| `world` | 关于外部世界的客观事实（"巴黎是法国首都"） | 语义记忆 |
| `experience` | 用户/Agent 亲身经历过的事件（"用户周一开了个会"） | 情景记忆 |
| `observation` | 从多条 experience/world 里归纳出的稳定信念 | 被巩固的长期记忆 |

**源码依据**：`memory_units.fact_type` 枚举正是 `world / experience / observation`（spec 固定事实）；consolidation 的输入筛选条件写死为 `["experience", "world"]`（consolidator.py 第 1644、1669 行 `_count_unconsolidated_rows(..., ["experience","world"], ...)`）——observation 不再参与下一轮归纳，否则会递归膨胀。这说明三层是流水线刻意设计的，不是巧合。

### 9.2 证据驱动而非覆盖：新信息强化/弱化/扩展，不静默替换

**设计思想**：传统知识库遇到矛盾文本时通常"覆盖"——新值直接写掉旧值。Hindsight 选择**证据累积**：新事实要么给旧 observation 追加证据（UPDATE + source_fact_ids），要么新建并列 observation，要么在被彻底推翻时才 DELETE。它从不静默地把旧文本改成新文本。

**源码依据**：prompts.py `_PROCESSING_RULES` 第 1 条 "PREFER UPDATE OVER CREATE … attach the new facts as evidence"；第 7 条 "PRESERVE HISTORY … never DELETE them"；proof_count 用 `array_agg(DISTINCT ...)` 只增不减（consolidator.py 第 413 行）；`history` JSON 列保留每次改写快照（`_append_observation_history` 第 2806 行）。结论：**事实会过时，但证据和历史不会被悄悄擦掉**。

### 9.3 Bank 严格隔离：一个 bank 一个脑

**设计思想**：bank 不是"命名空间前缀"，而是**完全隔离的记忆边界**——跨 bank 不共享 memory_units、entities、mental models，连 consolidation 的 LLM 配置和 disposition 都按 bank 解析。

**源码依据**：几乎每条 SQL 都带 `WHERE bank_id = $1`；`run_consolidation_job` 第一行就是 `resolve_full_config(bank_id, ...)`（第 1571 行）做 bank 级配置覆盖；mental model 刷新时特意注释 "preventing unnecessary refreshes across security boundaries"（第 2276 行）；`banks.disposition`（skepticism/literalism/empathy JSON）也是 per-bank。设计意图很清楚：多租户/多用户/多产品必须物理隔离，不能互相"串味"。

### 9.4 多语言默认：输入语言端到端保留

**设计思想**：Hindsight 默认不把用户内容翻译成英文再存——**输入语言是什么，observation 就用什么语言写**，且按 observation 粒度（不是按批次）决定语言。

**源码依据**：consolidation prompts.py `_DEFAULT_LANGUAGE_RULE` 原文："Write every observation in the language of its own source facts — never translate them. Per observation, not per batch… Proper nouns, identifiers, and units stay verbatim." 更绝的是它禁止"旧英文 observation 被新中文事实更新后，在原文上嫁接中文"——要求直接用新事实的语言重写（"Discard the old phrasing and compose … from scratch"）。config.py 第 2944 行有个开关 `llm_output_language`：不设置就保持源语言，设置了才强制统一。embedding 默认还带多语种模型 `intfloat/multilingual-e5-small`（config.py 第 1212 行）。

### 9.5 Memory Defense：写入前的 PII / 密钥扫描

**设计思想**：记忆系统最大的反噬风险是"把密钥和隐私存进去了"。Hindsight 在 retain 写入前加一道**可配置的 per-bank 防线**，而不是事后清洗。

**源码依据**：`extensions/memory_defense.py` 定义三态 `DefenseAction.ALLOW / REDACT / BLOCK`；`extensions/builtin/memory_defense_regex.py` 是默认实现——纯正则、无 LLM 调用、对卡号候选还带 Luhn 校验。它内置**四十余种**模式（`anthropic_key / openai_key / google_api_key / aws_access_key / github_token 全家桶 / slack_token / stripe_secret / private_key_pem / 带口令的 db_url …`）。命中后二选一：就地 redact 或整条 block；命中事件通过 `memory_defense.triggered` webhook 外发，且 webhook 里只放指纹化预览（`ghp_AAAA...BBBB`），**原始密钥绝不离开本机**（models.py 第 43 行注释）。

### 9.6 每操作独立 LLM：retain / reflect / consolidation 可用不同模型

**设计思想**：三个阶段对模型能力的需求差别极大——retain 抽事实要快、便宜；reflect 要推理强；consolidation 要稳定、能长上下文。Hindsight 不让用户被迫用一个模型扛全部。

**源码依据**：consolidator.py 第 1575 行 `self._consolidation_llm_config.with_config(config, bank_id=bank_id, operation="consolidation")`；spec 固定事实写明每个操作可独立配 `retain_llm_* / reflect_llm_* / consolidation_llm_*`，未配置时回退到 `memory_llm_*`。配合 25+ provider 抽象（`engine/providers/`），实际部署里常见组合是"retain/consolidation 用便宜模型，reflect 用旗舰模型"。

### 9.7 本章小结

这六条归纳起来是同一种价值观：**把"记忆"当成有证据、有历史、有边界、有语言、有安全边界的活体组织，而不是一堆可随意覆盖的向量**。仿生分层是骨架，证据累积是肌肉，bank 隔离是皮肤，多语言和 memory defense 是对外的感受器官，每操作独立 LLM 则是这套昂贵系统在成本上的调节阀。

---

## 十、它适合什么，不适合什么

### 10.1 适合的场景

基于源码能力（后台 consolidation、per-bank 隔离、observation 证据链、编码 agent 集成）反推，Hindsight 的甜区是"需要跨会话长期学习"的 Agent：

- **长期个性化对话 Agent**：用户的偏好、事实、状态会被反复合并成 observation，且 `proof_count` 让"用户反复强调的偏好"自然权重更高。
- **编码 Agent 的项目记忆**：官方 `@vectorize-io/hindsight-coding-agents` 直接按 git 历史和过往会话自动建 per-repo bank，把架构、约定、在途工作注入 agent 上下文。
- **AI 员工 / 长期运行的工作流**：需要"记得上次做到哪、上次为什么这么决定"，且多人/多任务之间要严格隔离 bank。

### 10.2 不一定适合的场景

| 场景 | 为什么不是甜区 |
|-|-|
| **一次性问答 / 简单 RAG** | Hindsight 要跑 retain→consolidation 两条 LLM 链路、写 pgvector、起 worker，单文档问答用它是杀鸡用牛刀；直接 RAG 更快更便宜。 |
| **无状态、不重复访问的工作流** | 记忆系统的价值在"第二次还能用"。如果数据写进去再读一次就扔，consolidation 的后台成本收不回来。 |
| **超低延迟、纯缓存场景** | recall 要四臂并行检索 + RRF 融合 + cross-encoder 重排，p99 延迟和成本都高于 KV 缓存。 |
| **需要强一致事务的业务数据库** | 它是"记忆"不是 OLTP——记忆本来就允许近似、允许后台最终一致，不要拿它当主数据仓库。 |
| **完全离线、零 LLM 预算** | retain/consolidation/reflect 都依赖 LLM，没有 LLM 它退化成一个带图的向量库，优势发挥不出来。 |

一句话边界：**它优化的是"跨时间、跨会话地把经验沉淀成可靠信念"，不是"把文档毫秒级捞出来"。**

### 10.3 二次开发最值得复用的部分

如果想借鉴或二开，源码里有几块质量很高、可独立拆用：

1. **`engine/consolidation/prompts.py` 的合并决策范式**（240 行）：CREATE/UPDATE/DELETE 三选一 + 强制 reason + 禁算术 + 保历史，这套 prompt 设计可以直接搬到任何"去重归纳"任务上。
2. **`extensions/memory_defense.py` 的正则密钥/PII 扫描**（44 个模式 + Luhn 校验 + 指纹化预览）：与主流程解耦，可单独抽出来给任何写库前的清洗用。
3. **`worker/poller.py` 的数据库表队列模型**：slot 预留、绝对/空闲双超时、背压 deferral、retry 退避，是一份很干净的分布式任务队列参考实现。
4. **`engine/search/` 的四臂检索 + RRF + cross-encoder 重排**（fusion.py 176 行、reranking.py 475 行）：语义/BM25/图/时间四路融合，是检索质量的样板。
5. **多后端 SQL 方言层**（`engine/sql/` postgresql.py / oracle.py）：同一份逻辑跑 PG+pgvector 和 Oracle 23ai，是做多数据库适配的范例。

---

## 十一、源码阅读地图

> 路径：`hindsight-api-slim/hindsight_api/`。按"从入门到深入"分五趟，括号内为行数。

**第一趟：先跑起来、看清骨架（1 个下午）**

| 顺序 | 文件 | 行数 | 职责 |
|-|-|-|-|
| 1 | `config.py` | 5447 | 全部环境变量与默认值；先扫一眼结构，不必逐行 |
| 2 | `server.py` / `main.py` | — | FastAPI 进程入口、装配 |
| 3 | `engine/interface.py` | 734 | `MemoryEngineInterface`：对外承诺了哪几个方法 |
| 4 | `engine/memory_engine.py` | 23543 | 编排核心，**先只读 `retain_async/recall_async/reflect_async/execute_task` 四个入口**，其余当字典查 |

**第二趟：三条同步链路（retain → recall → reflect）**

| 顺序 | 文件 | 行数 | 职责 |
|-|-|-|-|
| 5 | `engine/retain/orchestrator.py` | 4491 | retain 流水线总编排 |
| 6 | `engine/retain/fact_extraction.py` | 3627 | LLM 抽事实/实体/时间/关系 |
| 7 | `engine/entity_resolver.py` | 1694 | 实体归一化 |
| 8 | `engine/retain/link_utils.py` | 1148 | temporal/semantic/causal 链接 |
| 9 | `engine/search/retrieval.py` | 940 | recall 四臂检索主循环 |
| 10 | `engine/search/fusion.py` | 176 | RRF 融合 |
| 11 | `engine/search/reranking.py` | 475 | cross-encoder 重排 |
| 12 | `engine/reflect/agent.py` | 2155 | reflect 多步推理 Agent |
| 13 | `engine/reflect/prompts.py` | 1648 | reflect 的 system prompt |

**第三趟：后台学习链路（本章重点）**

| 顺序 | 文件 | 行数 | 职责 |
|-|-|-|-|
| 14 | `engine/consolidation/prompts.py` | 240 | **最易读、最值得先读**：合并决策规则 |
| 15 | `engine/consolidation/consolidator.py` | 3763 | observation 生成/合并/删除主逻辑 |
| 16 | `worker/poller.py` | 2166 | async_operations 队列消费者 |
| 17 | `worker/main.py` | 453 | worker 进程启动 |
| 18 | `engine/maintenance.py` | 594 | cron 定时刷新 mental model |
| 19 | `webhooks/manager.py` | 244 | 事件外发 |
| 20 | `webhooks/url_guard.py` | 337 | webhook SSRF 防护 |

**第四趟：存储与数据模型**

| 顺序 | 文件 | 行数 | 职责 |
|-|-|-|-|
| 21 | `engine/memories/base.py` | 2256 | 存储后端抽象接口 |
| 22 | `engine/memories/pg/writes.py` | 623 | 写 memory_units/links/entities |
| 23 | `engine/memories/pg/reads.py` | 835 | 读路径 |
| 24 | `engine/memories/pg/graph.py` | 1016 | 图查询（entity 共现、链接扩展） |
| 25 | `engine/db/ops_postgresql.py` | 1967 | PG 方言 SQL 落地 |
| 26 | `engine/embeddings.py` | 2316 | embedding 模型封装 |
| 27 | `engine/cross_encoder.py` | 2349 | reranker 封装 |

**第五趟：横切关注点**

| 顺序 | 文件 | 行数 | 职责 |
|-|-|-|-|
| 28 | `engine/llm_wrapper.py` | 1840 | LLM 调用统一封装 |
| 29 | `engine/providers/openai_compatible_llm.py` | 2250 | 25+ provider 的基类 |
| 30 | `extensions/memory_defense.py` | 356 | PII/密钥扫描 |
| 31 | `extensions/builtin/memory_defense_regex.py` | 57 | 默认正则实现 |
| 32 | `extensions/operation_validator.py` | 1022 | 操作校验扩展点 |
| 33 | `admin/cli.py` | 1659 | 迁移/修复/卡任务排查 |
| 34 | `api/http.py` | 10436 | FastAPI 路由（按需查） |

> 建议：`memory_engine.py` 两万多行不要从头读，它是"总机"，按上面四趟里遇到的调用点跳读即可。

---

## 十二、Hindsight 上手

### 12.1 启动方式：Docker / pip / Helm / Embedded

以下命令均来自仓库 README 的 Quick Start，未做改写。

**Docker（官方推荐）**，自带嵌入式 pg0，一条命令起服务：

```bash
export OPENAI_API_KEY=sk-xxx

docker run -it --pull always --name hindsight --restart unless-stopped -p 8888:8888 -p 9999:9999 \
  -e HINDSIGHT_API_LLM_API_KEY=$OPENAI_API_KEY \
  -v hindsight-data:/home/hindsight/.pg0 \
  ghcr.io/vectorize-io/hindsight:latest
```

起好后：API 在 `http://localhost:8888`，UI 在 `http://localhost:9999`。换 LLM provider 用 `HINDSIGHT_API_LLM_PROVIDER`（openai / anthropic / gemini / groq / bedrock / vertexai / deepseek / ollama / litellm … 25+）。

**Docker + 外部 PostgreSQL**（`docker/docker-compose/docker-compose.yml`）：

```bash
export OPENAI_API_KEY=sk-xxx
export HINDSIGHT_DB_PASSWORD=choose-a-password
cd docker/docker-compose
docker compose up
```

**裸机 pip**：

```bash
pip install hindsight-api
export HINDSIGHT_API_LLM_API_KEY=sk-xxx
hindsight-api          # 同时起 API 与 worker
```

**Kubernetes Helm**：

```bash
helm install hindsight oci://ghcr.io/vectorize-io/charts/hindsight \
  --set api.llm.provider=openai \
  --set api.llm.apiKey=sk-xxx \
  --set postgresql.enabled=true
```

**Embedded（无需独立服务进程，进程内嵌入）**：

```bash
pip install hindsight-all -U        # Intel Mac 用 hindsight-all-slim
```

### 12.2 三行代码接入：Python SDK

```python
from hindsight_client import Hindsight

client = Hindsight(base_url="http://localhost:8888")

client.retain(bank_id="my-bank",  content="Alice works at Google as a software engineer")  # 记
client.recall(bank_id="my-bank",  query="What does Alice do?")                             # 搜
client.reflect(bank_id="my-bank", query="Tell me about Alice")                             # 深度推理
```

Node / Go / CLI / REST 均有等价客户端（`@vectorize-io/hindsight-client` 等）。

### 12.3 LLM Wrapper：两行代码给现有 Agent 加记忆

不想改业务代码，就把 LLM client 包一层：

```bash
pip install hindsight-litellm
```

```python
from openai import OpenAI
from hindsight_litellm import wrap_openai

client = wrap_openai(
    OpenAI(),
    bank_id="user-123",
    hindsight_api_url="http://localhost:8888",   # 不传则默认连 Hindsight Cloud
)

response = client.chat.completions.create(
    model="gpt-5-mini",
    messages=[{"role": "user", "content": "What do you know about me?"}],
)
```

每次调用前自动 recall 相关记忆，调用后自动 retain 对话；Anthropic SDK 对应 `wrap_anthropic()`。底层走 LiteLLM，覆盖 100+ 模型。

### 12.4 编码 Agent 集成

一条命令给 CLI 编码 agent 接上 per-repo 长期记忆（自动从 git 历史和过往会话建 bank）：

```bash
npx @vectorize-io/hindsight-coding-agents install all           # 探测到的全部 agent
npx @vectorize-io/hindsight-coding-agents install claude-code   # 只接某一个
```

支持 Claude Code、Codex CLI、Cursor CLI、GitHub Copilot CLI、opencode、Cline、Aider 等。

### 12.5 生产部署要点

- **存储**：生产用 PostgreSQL + pgvector（Oracle 23ai 功能对等）；嵌入式 pg0 适合单机/开发，不要拿来扛多副本。
- **进程分离**：API（`hindsight-api`）与后台 worker（`hindsight-worker`）建议分开部署——consolidation 是 LLM 密集型长任务，别和在线 API 抢 CPU。Worker 的并发槽位可按 `slot_reservations` 调（默认保证 consolidation 2 槽）。
- **配置层级**：全局环境变量 → per-tenant → per-bank 逐级覆盖；per-operation LLM 在生产里建议把 consolidate/retain 配便宜模型、reflect 配旗舰模型。
- **安全**：开 Memory Defense（per-bank 配 `memory_defense.rules`，`sensitive_data` 命中时 redact 或 block）；webhook 默认阻止私网目的地，需要内网回调时显式配 `WEBHOOK_ALLOWED_HOSTS`。
- **可观测**：Prometheus 指标在 `metrics.py`，重点看 `hindsight_async_operations{status="failed"}` 这个 gauge（权威失败数）；卡任务用 `hindsight-admin` CLI 排查。
- **事件**：retain / consolidation / memory_defense 生命周期事件走 webhook 外发，接你自己的审计/通知。

---

## 结语：Hindsight 真正控制的是"学习秩序"

写到这里，十二章串起来其实只在讲一件事。

表面上，Hindsight 是一个"Agent 记忆系统"——能存、能搜、能答。但如果你顺着 retain → recall → reflect → consolidation 一路读下来，会发现它花最多工程力气的地方，根本不是"怎么存得快"或"怎么搜得准"，而是**怎么让新进来的经验，有序地、可追溯地、不互相污染地，变成 Agent 下次还能用的信念**。

它规定了：一条事实从文档里出来时叫 experience，必须被打上时间、挂上实体、连上图谱（第五章）；被问到时，要四路并行捞、融合、重排，只在预算内给模型最相关的（第六章）；要深思时，模型必须拿着证据链说话，不能凭空发挥（第七章）；而过了这一切之后，后台还要把零散事实合并成 observation——合并时不许做算术、不许静默覆盖、必须留历史、必须数清证据（第八章）。再往下，每一个 bank 是一个隔离的脑，每种语言是它自己的语言，每一次写入要先过密钥安检，每一类思考可以用不同价格的模型（第九章）。

这就是"学习秩序"：**它不替 Agent 变聪明，它约束经验沉淀成记忆的那条路径不发生混乱**。RAG 关心"这一次把相关文档找出来"，而 Hindsight 关心"一百次之后，这个 Agent 关于同一个人、同一件事、同一个项目，有没有形成一个前后一致、可被证伪、还带着证据的认识"。

开源世界里不缺能存向量的库，缺的是对"记忆该如何随时间生长"这件事有一整套明确、可执行、可审计主张的系统。Hindsight 把这套主张写进了 23000 行的 `memory_engine`、3763 行的 consolidator 和那些近乎苛刻的 prompt 规则里。读懂它，你读懂的不只是一个产品，而是一种"怎么让 AI 慢慢变聪明而不是慢慢变糊涂"的工程回答。