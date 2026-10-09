# Hindsight 技术文档（Part 2：存储、运行时、Recall 与 Reflect）

> 本文件负责章节范围：**第三章、第四章、第六章、第七章**。
> 对应源码版本：Hindsight 0.10.1，核心包 `hindsight-api-slim/hindsight_api/`。
> 文中凡标注「本文归纳」处，为作者基于源码结构的概括；其余概念、类名、方法名、表名、字段名均直接出自源码。

---

## 第三章 存储内核：记忆如何被组织

### 3.1 为什么不用纯向量库

一个常见误解是「记忆系统 = 一张 `id + embedding + text` 的向量表」。Hindsight 的存储层（`engine/memories/`）明确拒绝这种形态。原因在 `engine/memories/base.py` 的 `StoredMemory`、`FactRecord` 两个 dataclass 里写得很清楚：一条记忆除了向量与文本，还必须携带**四个时间字段**（`event_date`、`occurred_start`、`occurred_end`、`mentioned_at`）、**实体列表**（`entity_ids`）、**因果边**（`causal_edges`）、**证据来源**（`source_memory_ids`）与**证据强度**（`proof_count`）。

纯向量库只能回答「语义上像」，而记忆需要回答另外三类问题：这件事发生在什么时候？它和哪些人/物有关？它导致了什么、又被什么导致？这些维度靠向量相似度都拿不到，必须落成结构化列与图边。因此 Hindsight 的主存储是 **PostgreSQL + pgvector**（功能对等 Oracle 23ai），向量只是 `memory_units` 表中的一列 `embedding VECTOR(384, FLOAT32)`，而不是全部。

存储抽象层是 `MemoriesExtension`（`base.py:770`，继承 `Extension, ABC`）。它用一个 `store_owned: bool` 标志区分两类后端：默认 `False` 表示 SQL 存储（Postgres/Oracle），记忆就是表行，retain 在事务里直接写 SQL；`True` 表示存储自带的外部索引，整个 retain 作为一次原子服务端调用提交。这种设计让产品策略（预算、arm 开关）留在引擎侧，存储实现只负责「怎么存、怎么按地址读」。

### 3.2 memory_units：一条记忆的完整形态

`memory_units` 是整个系统的中心表。字段定义来自 `alembic/versions/o1a2b3c4d5e6_oracle_baseline.py`（Oracle 方言版本，PG 侧由 59 个增量迁移等价构建）。关键列如下：

| 字段 | 类型 | 含义 |
|---|---|---|
| `id` | UUID/RAW(16) | 主键，记忆全局地址 |
| `bank_id` | VARCHAR | 隔离维度，**按它做 `PARTITION BY LIST (bank_id) AUTOMATIC` 自动分区** |
| `text` | 文本/CLOB | 记忆正文（LLM 抽取后的陈述句，不是原始 chunk） |
| `embedding` | `VECTOR(384, FLOAT32)` | 向量，384 维；可空 |
| `context` | 文本 | 这句话所处的上下文/语境 |
| `event_date` | 时间戳（NOT NULL） | 事件发生日期，默认排序键 |
| `occurred_start` / `occurred_end` | 时间戳 | 事件起止区间；「2015 年」会被展开成整年区间 |
| `mentioned_at` | 时间戳 | 这句话是在何时被提到的（区别于事件本身发生时间） |
| `fact_type` | 枚举，默认 `world` | CHECK 约束仅允许 `world` / `experience` / `observation` |
| `confidence_score` | 浮点 | CHECK 约束 `[0.0, 1.0]`，可空 |
| `access_count` | 整数，默认 0 | 被召回/访问次数 |
| `consolidated_at` | 时间戳 | 何时被折叠进某个 observation；observation 的 source 才有 |
| `proof_count` | 整数，默认 1 | 这条信念被多少条原始事实佐证 |
| `source_memory_ids` | JSON/数组 | observation 由哪些原始事实 consolidation 而来 |
| `history` | JSON 数组，默认 `[]` | 这条记忆的修订历史 |
| `search_vector` | 文本向量列 | BM25 全文索引载体（后端相关） |
| `tags` / `metadata` / `observation_scopes` / `text_signals` | JSON/文本 | 标签、元数据、归属 observation 范围、拼进 BM25 文档的实体名与日期 |

三个 `fact_type` 是官方概念，也是 Hindsight 仿生分层的核心：`world`（关于人/地/事/物的客观知识）、`experience`（对话、行动、任务等亲历记忆）、`observation`（后台 consolidation 从多条事实归纳出的信念）。注意 observation 自己不直接挂文档，它通过 `source_memory_ids` 反向指回原始事实，证据链由此闭合。

表上的索引设计也能看出访问模式：`idx_mu_bank_type_date (bank_id, fact_type, event_date DESC)` 支撑按类型按时间扫描；`idx_mu_access_count (access_count DESC)` 支撑热度；向量侧则是**按 fact_type 的部分 HNSW 索引**（`retrieval.py` 注释提到 `idx_mu_emb_world / idx_mu_emb_experience / idx_mu_emb_observation`），让每个 arm 各走各的索引而不是全表顺序扫描。

### 3.3 entities 与 memory_links：从事实到图谱

光有结构化列还不够，Hindsight 还把记忆连成一张轻量图。涉及四张表：

- **`entities`**：`canonical_name`（归一化名）、`first_seen` / `last_seen`、`mention_count`。有唯一索引 `(bank_id, LOWER(canonical_name))`，同名实体归并靠 `engine/entity_resolver.py` 完成。
- **`unit_entities`**：`(unit_id, entity_id)` 多对多中间表，是记忆↔实体的反向索引。
- **`entity_cooccurrences`**：`(entity_id_1, entity_id_2, cooccurrence_count, last_cooccurred)`，记录实体共现，用于图扩展。
- **`memory_links`**：记忆之间的有向边。

`memory_links.link_type` 的 CHECK 约束只允许七种取值。它们的语义对比（依据 `graph.py`、`retrieval.py` 中的使用方式）：

| link_type | 方向 | 语义 | 在 recall 图扩展中的角色 |
|---|---|---|---|
| `temporal` | 有向 | 时间相邻/先后 | temporal arm BFS 扩散时遍历 |
| `semantic` | 有向 | 语义近邻（retain 末尾 ANN pass 派生） | graph arm 扩展 |
| `entity` | — | 共享实体（**已不再物化进本表**，迁移 e9b2c7d1f3a4 后改由 `unit_entities` 派生） | graph arm 按实体种子扩展 |
| `causes` | A 导致 B | 因果：A 是因 | temporal 扩散 `causal_boost=2.0` |
| `caused_by` | A 被 B 导致 | 因果：A 是果 | temporal 扩散 `causal_boost=2.0` |
| `enables` | A 使能 B | 条件促成 | temporal 扩散 `causal_boost=1.5` |
| `prevents` | A 阻止 B | 条件抑制 | temporal 扩散 `causal_boost=1.5` |

每条边带 `weight`（CHECK 在 `[0,1]`，默认 1.0）和 `source_memory_ids`，并有唯一索引 `(from_unit_id, to_unit_id, link_type, NVL(entity_id, nil))` 防止重复边。`graph.py:graph_direct_links` 有一句关键注释：实体边不再物化进 `memory_links`，而是由调用方从 `unit_entities` 现算——这减少了一类会随实体合并而失同步的冗余边。

### 3.4 mental_models 与 directives：从记忆到知识

记忆（memory_units）是点状事实，Hindsight 再往上叠两层「总结性知识」：

- **`mental_models`**：对某主题的长期综合认识。`subtype` CHECK 只允许 `directive` / `pinned`；`content` 是正文，`embedding` 同样是 384 维向量，`observations`（JSON，默认 `{"observations":[]}`）挂它归纳出的观察列表，`max_tokens` 默认 2048。`trigger`（JSON，默认 `{"refresh_after_consolidation": false}`）声明它何时该刷新——例如 consolidation 之后自动重算。`history` 保留历次刷新版本。
- **`directives`**：`name` / `content` / `priority`（默认 0）/ `is_active`（默认 1）/ `tags`。这是人工写下的硬规则，reflect 时会作为指令注入 system prompt 的开头和结尾。

两者都挂在 `bank_id` 下，随 bank 隔离。可以把 `memory_units` 比作「神经元上的事实冲动」，`mental_models` 是「反复激活后形成的回路总结」，`directives` 则是「外部写死的行为准则」。

### 3.5 invalidated_memory_units：冷归档与可恢复删除

记忆不是被删，而是被**移动**。`engine/memories/pg/writes.py:invalidate_memory` 做的事是：先在 `unit_entities` 被外键级联删除之前快照下 `entity_ids`，再用 `snapshot_causal_links` 把因果边描述存下来（因为 temporal/semantic 边可以重算，**causal 边是 retain 时 LLM 抽取的一次性产物，重算不出来**），然后 `INSERT ... SELECT` 把整行搬进 `invalidated_memory_units`，最后删 live 行。

这张归档表是 `memory_units` 的镜像，外加三列：`invalidation_reason`、`invalidated_at`、`entity_ids`（外加 `causal_links` JSON）。**它故意没有 `embedding` 列**——baseline 注释解释得很清楚：归档是冷存储，恢复时重算 embedding，所以不存归档向量，避免换 embedding 模型后归档向量维度失配（issue #2209）。

`restore_memory` 是反向流程：把行搬回 `memory_units`，用**当前后端**重建 `search_vector`（换过全文后端也不留旧类型），把 `consolidated_at` 置空让它重新参与 consolidation，用 `restore_entity_postings` 恢复实体挂回并补回 mention 计数，用 `rematerialize_causal_links` 还原因果边，再把该 unit 排进 `graph_maintenance_queue` 让图维护重建派生边。整条路径是幂等且顺序无关的。

### 3.6 多后端文本搜索：BM25 的五种实现

BM25 不是一个固定实现，而是一个可插拔的 arm。`engine/sql/postgresql.py:build_bm25_arm` 按 `text_search_extension` 分发到五种后端，每种的打分算子和过滤谓词都不同：

| 后端 | 打分表达式 | 匹配谓词 | 备注 |
|---|---|---|---|
| `native`（默认 tsvector） | `ts_rank_cd(search_vector, to_tsquery(lang, $))` | `search_vector @@ to_tsquery(...)` | token 用 ` \| ` 做 OR 连接；无 IDF，靠 `bm25_term_selection` 选高区分度词 |
| `vchord`（VectorChord） | `-(search_vector <&> to_bm25query(idx, tokenize(q,'llmlingua2')))` | 算子给所有文档打分，需 `> 0` 门控 | `<&>` 返回负分，取负；必须门控零分噪声 |
| `pg_search`（ParadeDB） | `paradedb.score(id)` | `id @@@ paradedb.boolean(should=>...)` | 跨 `text`/`text_signals` 字段 fan-out |
| `pg_textsearch`（Timescale） | `-(text <@> to_bm25query(q, idx))` | 无独立谓词，按距离 ASC | 距离即分数，升序让索引驱动排序 |
| `pgroonga` | `pgroonga_score(tableoid, ctid)` | `(text||' '||context||' '||text_signals) &@~ expr` | TokenBigram + NormalizerNFKC150，词间 OR |

关键工程取舍：各后端算子的分数尺度完全不同（`ts_rank_cd`、负距离、`paradedb.score`），所以 Hindsight 不在 SQL 里比分数，而是统一在下游按**排名**做 RRF 融合（见第六章）。`bm25_term_selection.py` 还解释了 native 后端的一个痛点：`ts_rank_cd` 没有 IDF 且不在索引里，长查询会扫全库再排序，于是它从 `pg_stats.most_common_elems` 里挑文档频率最低（最具区分度）的前 N 个词，绝不盲目截断前 N 个 token。

### 3.7 本章小结

Hindsight 的存储内核不是向量库，而是一张按 bank 自动分区的事实表 `memory_units`，外加实体表、七类边的轻量图、总结层 `mental_models`、规则层 `directives`，以及一张无向量列的冷归档表 `invalidated_memory_units`。向量只是其中一列；时间、实体、因果、证据链才是记忆区别于 RAG chunk 的地方。文本搜索通过 SQL 方言抽象支持五种 BM25 后端，分数不可比，统一交给下游融合。

---

## 第四章 运行时核心模块

### 4.1 MemoryEngine：23000 行的编排核心

`MemoryEngine`（`engine/memory_engine.py:2360`，实现 `MemoryEngineInterface`，全文件 23543 行）是整个系统的门面与编排器。它自己不做具体检索/抽取，而是把请求拆成「鉴权 → 配置解析 → 调用存储/LLM/检索 → 收尾钩子」。`__init__`（2371 行）的参数列表本身就是运行时拓扑：`db_url`、三套独立的 LLM（`retain_llm_*` / `reflect_llm_*` / `consolidation_llm_*`，各自回退到 `memory_llm_*`）、`embeddings`、`cross_encoder`、`query_analyzer`、连接池参数、`task_backend`、`operation_validator`、`tenant_extension`。

`initialize()`（5257 行）按顺序启动：内嵌 pg0 → 初始化 embeddings → cross-encoder → query_analyzer（默认 `DateparserQueryAnalyzer`）→ memories 扩展 → 校验 LLM 连通性。这种「构造轻、initialize 重」的两阶段是为了让 FastAPI lifespan 能精确控制启动顺序与失败上报。`run_migrations` 默认 True，服务首次启动会自己把 schema 推到 head；provider 为 `none` 时自动跳过连通性探测，便于离线与测试。

核心对外方法四个：`retain_async`、`retain_batch_async`、`recall_async`、`reflect_async`。它们都长一个样：先 `_authenticate_tenant`、跑 `operation_validator` 前置钩子、解析 bank 配置，再干活，最后跑后置钩子。这种一致的骨架是 Hindsight 能在每个操作前后插入审计、限流、多租户校验的原因。值得强调的是 `MemoryEngine` 自己不内嵌产品策略——`FullRecallRequest`（base.py）注释明确写「这是引擎解析后的值，不是调用方的原始请求」：预算、arm 开关、reranker 模式都在引擎侧算好再下发，存储实现无需读 config，换 bank 配置不必发版。连接池还做了读写分离：`read_database_url` 单独配一个读池，`_get_read_backend()` 把 recall 这类读密集流量从写主库卸下来。

### 4.2 API 层与 Worker：同步路径与异步路径的分离

HTTP 层是 `api/http.py`（10436 行），一个 FastAPI app，所有业务路由挂在 `/v1/default/banks/{bank_id}/` 下：`POST .../memories/recall`、`POST .../reflect`、`POST .../documents`（retain 入口）、`/mental-models/...`、`/directives`、`/observations`、`/operations`、`/webhooks` 等。`/health`、`/health/ready`、`/metrics` 是运维面。app 在 `lifespan`（4887 行）里随事件循环启停，并用专门的 exception handler 把 `AuthenticationError`、`StoreWriteUnavailable` 翻译成对应 HTTP 状态。

关键设计是**同步 vs 异步分离**：

- **同步路径**：recall、reflect 这类要立刻拿结果的，在 HTTP 请求里直接 `await`，前面套 `@audited("recall")`、precheck/admit 依赖、query 长度上限（`recall_max_query_tokens`）。
- **异步路径**：retain、consolidation、mental model 刷新、bank 导入导出、webhook 投递，统一落成 `async_operations` 表的一行（`status` 在 `pending/processing/completed/failed/cancelled` 间流转），HTTP 立即返回 `operation_id`。

后台由 `worker/poller.py:WorkerPoller` 驱动：`claim_batch` 用 `FOR UPDATE SKIP LOCKED` 抢任务，`execute_task` 分发到 `MemoryEngine.execute_task`（3901 行起有 `_handle_batch_retain`、`_handle_consolidation`、`_handle_graph_maintenance`、`_handle_refresh_mental_model`、`_handle_webhook_delivery`、`_handle_import/export_bank` 等处理器）。失败按 `next_retry_at` 退避重试；worker 重启时 `recover_own_tasks` / `release_own_tasks` 回收自己挂掉的 processing 任务，`_reconcile_orphaned_parents` 处理父子操作。wall-clock 超时由 `_WallCeiling` 监控，到点回调 `on_task_wall_timeout` 而不是硬杀。这套表 + 轮询的本质是把「慢 LLM 任务」从 Web 请求里彻底摘出去，Web 只负责接单和查状态。

### 4.3 LLM Provider 抽象：25+ 提供商的统一接口

`engine/providers/` 把不同厂商藏在统一接口后。`openai_compatible_llm.py` 一个文件就覆盖了 OpenAI、Groq、Ollama、LMStudio、MiniMax、DeepSeek、Opencode Go——因为它们都是 OpenAI 协议。其余专门文件：`gemini_llm.py`、`anthropic_llm.py`、`codex_llm.py`、`xai_oauth_llm.py`、`github_copilot_llm.py`、`litellm_llm.py`、`fireworks_llm.py`、`llamacpp_llm.py`，外加 `mock_llm` / `none_llm` 用于测试与无 LLM 模式。

工程上有两条硬约束值得注意：一是**生产 HTTP 强制 aiohttp 异步**（ruff TID251 禁 httpx/requests），openai_compatible 里用 `LoopLocalSession` 管连接；二是**每个操作可独立配模型**，`__init__` 里的 `_op_defaults` 把 `HINDSIGHT_API_RETAIN_LLM_TIMEOUT` 这类按操作覆盖一路传进 provider，而不是只记在 config 里（issue #2452 修的就是这个「配了不生效」的 bug）。回退顺序是显式的：某操作没配，才落到 `memory_llm_*`。

### 4.4 Embedding 与 Cross-Encoder：检索质量的两层保障

`engine/embeddings.py` 定义 `Embeddings` ABC，实现分本地与远程：`LocalSTEmbeddings`（sentence-transformers）、`OnnxEmbeddings`（ONNX 运行时）、`RemoteTEIEmbeddings`（Text-Embeddings-Inference 服务）、`OpenAIEmbeddings`、`CohereEmbeddings`、`GeminiEmbeddings`、`LiteLLMEmbeddings`。`create_embeddings_from_env()` 按环境变量选一个。维度被钉死在 384，与 `memory_units.embedding VECTOR(384)` 对应——这也是为什么归档表不存向量：换 embedding 模型意味着维度变，存量向量必须重算。

`engine/cross_encoder.py` 是第二层：粗排召回几十个候选后，用 cross-encoder 做 query-document 对的精排。`CrossEncoderModel` ABC 下，本地默认 `cross-encoder/ms-marco-MiniLM-L-6-v2`（`LocalSTCrossEncoder`），远程/托管有 `CohereCrossEncoder`、`JinaMLXCrossEncoder`、`GoogleCrossEncoder`、`FlashRankCrossEncoder`、`SiliconFlowCrossEncoder`，`MultiCrossEncoder` 把多个成员串成故障转移链（一个挂了自动切下一个）。`RRFPassthroughCrossEncoder` 是给 slim 部署的降级实现——它不真打分，直接把 RRF 排名当分数传下去。两个模型都在 `initialize()` 里懒加载，本地模型的首次加载放在线程池里跑以免阻塞事件循环。

### 4.5 扩展机制：Tenant、OperationValidator、Storage

`extensions/base.py:Extension` 是所有扩展的基类，靠 `set_context` 拿到运行时上下文，子类用类级 `name` 自报家门。几个最常用的扩展点：

- **`TenantExtension`**（`extensions/tenant.py`）：`authenticate()` 校验 API key、解析租户，`provision_bank_tables` 给租户建表，`get_allowed_config_fields` 限制租户能改哪些配置。多租户时所有 bank 级操作都要 `RequestContext`。
- **`OperationValidatorExtension`**（`extensions/operation_validator.py`）：把操作分成 `PrecheckOperation`，提供 `validate_retain / validate_recall / validate_reflect` 前置钩子和 `on_*_complete` 后置钩子，可拒绝（`ValidationResult.reject`，403）或改写 tags；`RecallContext`、`ReflectContext` 等是钩子拿到的上下文。
- **`MemoryDefenseExtension`**（`extensions/memory_defense.py`）：retain 写入前 `screen()` 扫描内容，用正则把 AWS 密钥、Stripe key、US 手机号/邮箱等替换成 `[REDACTED:type]`，原文绝不进 `hits`。
- 存储扩展即 `MemoriesExtension`（见 3.1），按 `MEMORIES` 前缀加载；`bank_tables.py` 则给多租户 bank 挂额外表。


这里还有一个常被忽略的点：扩展是**按名字发现、按生命周期挂载**的。`extensions/builtin/` 目录里是产品自带的扩展实现（如内置 tenant、webhook、bank_tables），第三方扩展通过入口点注册后由引擎加载。`set_context` 把 db 连接、配置、logger 注入扩展，所以扩展不直接持有全局状态，而是在每次被回调时从上下文拿连接——这与 Web/Worker 共享进程、却不互相污染的连接管理一致。

### 4.6 本章小结

运行时是一个「瘦门面 + 胖后台」结构：`MemoryEngine` 在同步请求里编排 recall/reflect，在异步任务表里驱动 retain/consolidation；LLM、embedding、cross-encoder、存储都抽成接口，靠环境变量与扩展点替换；多租户与安全靠 Extension 钩子横切，不污染主路径。Web 与 Worker 共享同一张 `async_operations` 表，靠 `SKIP LOCKED` 抢占与退避重试做到水平扩展。

---

## 第六章 Recall 链路：一次查询如何召回记忆

### 6.1 四臂并行检索：semantic / keyword(BM25) / graph / temporal

Recall 的入口是 `MemoryEngine.recall_async`（`engine/memory_engine.py:8223`）。它的 docstring 把自己写成「N×4 路并行检索」：N 个 `fact_type`（world/experience/observation）× 4 个检索臂。

进入 `recall_async` 后，先做一系列 ingress 卫生：`sanitize_text` 清掉孤立 UTF-16 代理符（issue #1875）、`_truncate_query_to_token_limit` 截断超长查询（consolidation 曾拿整段事实当查询，造出 54k 词的 OR tsquery 把 PG 栈打崩，issue #3134）、校验 fact_type、跑 validator、`_require_bank_exists`（不存在直接 404，而不是返回空 200）、解析模糊 tag。然后按 bank 配置决定四个开关：`enable_text_search`、`enable_temporal_retrieval`、`enable_graph_retrieval`、`reranking` 模式——一个 bank 可以关掉用不上的臂，用召回广度换延迟。

真正的四路在 `engine/search/retrieval.py`。文本流程图如下：

```
用户 query
  → [CPU] temporal_extraction：从 query 抽时间窗口（off event loop，~秒级）
  → get_memories().recall_unified(...)  ── 一次调用拿回所有臂 ──┐
                                                              ▼
        ┌──────────────┬──────────────┬──────────────┬──────────────┐
        ▼              ▼              ▼              ▼              ▼
   semantic 臂     bm25 臂        graph 臂       temporal 臂
   向量 <=> 余弦   tsvector/BM25   实体+链接扩散   时间窗+链接扩散
   (每 fact_type   (有词才跑;       (种子=语义top   (窗口内ANN取60→
    部分HNSW)      无词则整条省略)   20, 沿memory_  覆盖8桶取10入口→
                                    links扩展)     BFS≤5层因果/时间边)
        └──────────────┴──────────────┴──────────────┴──────────────┘
                              ▼
                    per_source_cap 截断每臂
                              ▼
                    RRF 融合（k=60）
                              ▼
              cross-encoder 精排 + 乘性加分
                              ▼
                 token budget 截断 → 返回
```

四个臂的职责（本文归纳）：**semantic** 找语义近邻；**bm25** 补向量召不回的精确关键词；**graph** 从高相似种子沿实体/链接跳到相关记忆；**temporal** 在指定时间窗内按时间邻近度扩散。`retrieve_semantic_bm25_combined_sql` 把 semantic 和 bm25 两类子查询用 `UNION ALL` 拼成一条 SQL，每个 fact_type 一个子查询、各自 `ORDER BY ... LIMIT`，从而命中按 fact_type 的部分 HNSW 索引。BM25 臂是条件性的：查询没有词字符或 `enable_text_search=False` 时整条省略，而不是跑了再丢。

### 6.2 融合：Reciprocal Rank Fusion

四个臂的分数尺度天差地别（余弦相似度、`ts_rank_cd`、距离、temporal_proximity），不能直接相加。`engine/search/fusion.py:reciprocal_rank_fusion` 用标准 RRF：

```
# fusion.py，k 默认 60
score(d) = Σ_over_lists   1 / (k + rank_l(d))
# 每个臂独立排名次，同一文档在多个臂出现就累加；
# source_names 固定为 ["semantic", "bm25", "graph", "temporal"]
```

伪代码：

```python
def reciprocal_rank_fusion(result_lists, k=60):
    rrf, arms = {}, {}
    for arm_name, ranked in zip(["semantic","bm25","graph","temporal"], result_lists):
        for rank, doc in enumerate(ranked, start=1):
            rrf[doc.id] += 1.0 / (k + rank)          # 仅靠名次融合，跨尺度可比
            arms[doc.id].record(arm_name, doc.score) # 保留原始分用于 trace
    return sorted(rrf, key=lambda d: rrf[d], reverse=True)   # → MergedCandidate
```

融合前先 `cap_per_source` 把每个臂截到 top-N（`per_source_cap`），防止某个臂过度膨胀把其它臂挤出后续的 reranker 候选预算。`fusion.py` 还提供一个 `interleave_fusion` 作为替代：轮询取各臂第 1 名、第 2 名……它专门给 consolidation 去重用——RRF 会把「语义第 1 但和孪生观察没有图边、词面也不重叠」的候选压到预算线以下，导致 LLM 看不到而重复建观察，轮询融合保证每臂头部必占一席。

### 6.3 重排序：Cross-Encoder 的精确排序

RRF 之后仍有几十到几百候选，`reranking.py:CrossEncoderReranker.rerank` 把它们做成 `[query, doc_text]` 对交给 cross-encoder。doc_text 被加工成 `"[Date: June 5, 2022 (2022-06-05)] context: text"`——日期以两种格式拼在前面，让模型对时间敏感。

分数归一化分两种：外部 API reranker（Cohere/Jina 等）返回的分数本就在 `[0,1]`，原样透传以保留绝对置信；本地 sentence-transformer 返回 logit，用 sigmoid 压到 `(0,1)`。NaN 一律归 0。若后端自带相关性判断（`prunes_candidates`），打 0 分的候选直接被丢弃。

最后 `apply_combined_scoring` 把 CE 主分和三类乘性加分相乘：

```
combined = CE_norm × recency_boost × temporal_boost × proof_count_boost
recency_boost     = 1 + 0.2 × (recency     - 0.5)   # ±10%
temporal_boost    = 1 + 0.2 × (temporal    - 0.5)   # ±10%
proof_count_boost = 1 + 0.1 × (proof_norm  - 0.5)   # ±5%，对数归一
```

recency 曲线可选 `linear`（365 天线性衰减到 0.1 底）、`exponential`（半衰期 90 天）或 `none`。粗日期（「2015 年」存成整年区间）从区间末尾计分并封顶在中性 0.5，避免把未来区间误当新鲜记忆（issue #3893）。当 reranker 是 `RRFPassthrough` 时，所有 CE 分相同，代码改用 RRF 排名填一个有意义的基底分，否则加分项会退化成纯按时间排序。`recall_boost.py` 还提供 `HINDSIGHT_API_RECALL_STRATEGY_BOOSTS`：把某个臂（如 `graph:high`）在融合前按「排名压缩」抬高，让它的候选在硬候选预算里不被挤掉。

### 6.4 预算控制：token budget 与事实选择

召回不是越多越好。最终结果按 `max_tokens`（默认 4096，只数 `text` 字段，BPE 词表 `o200k_base`）逐条累加，**遇到会超预算的那条就停**，不硬塞。中间还有 `truncate_to`：在花 token 预算前先把候选截到一个上限。

`thinking_budget` 是图遍历预算（`Budget.LOW=100 / MID=300 / HIGH=1000` 量级，adaptive 模式按 `max_tokens` 推导并 clamp 到 `[recall_budget_min, recall_budget_max]`）；`reranker_max_candidates` 控制送进 cross-encoder 的候选数。temporal arm 内部还有自己的硬预算：入口池 `_TEMPORAL_POOL_SIZE=60`、入口点 `_TEMPORAL_ENTRY_POINTS=10`、时间桶 `_TEMPORAL_COVERAGE_BUCKETS=8`、扩散 `max_iterations=5`、`batch_size=20`、`per_source_limit=10`。这些数字共同保证一次 recall 不会在大图上无限扩散。

### 6.5 异常路径：空结果、连接失败、标签与多语言

源码里埋了大量异常分支，这里归纳几条主要的：

- **空查询/无词**：查询 tokenize 后为空 → BM25 臂整条省略，只跑向量臂；fact_type 过滤掉已废弃的 `opinion`；全部类型为空直接返回空 `RecallResultModel`。
- **连接错误重试**：`recall_async` 外套信号量 `_search_semaphore` 背压，再对 `TooManyConnectionsError` 等做 3 次指数退避（0.5/1/2s）；`OperationCancelledError`（客户端断开）不重试，直接向上抛成 499。
- **Oracle Text 未同步**：`retrieve_semantic_bm25_combined_sql` 捕获 `DRG-10599 / ORA-30600`，用不带 BM25 参数布局的纯向量查询重跑，保证有结果。
- **bank 不存在**：`_require_bank_exists` 返回 404，而不是付完整套扇出后空返 200。
- **标签/更新窗口**：`created_after/before` 名义上按创建，实际过滤 `updated_at`——「这段时间里变动过的记忆」，编辑过的事实会重新进入窗口。
- **多语言**：native tsvector 的语言由 `text_search_extension_native_language` 配置；pgroonga 用 TokenBigram 天然支持 CJK；vchord 用 llmlingua2 分词。
- **长查询兜底**：native 后端靠 `bm25_term_selection` 从 `pg_stats` 选高区分度词，失败时退回保留前 N 词，绝不阻塞 recall。

### 6.6 本章小结

Recall 是一个「四臂粗排 → 排名融合 → cross-encoder 精排 → token 截断」的漏斗。它的关键洞见是：不同臂的分数不可比，所以融合只信名次（RRF）；精排只对融合后的小池子做，成本可控；时间、热度、证据强度作为乘性微调而不是硬规则叠加在 CE 主分上。异常路径覆盖了空查询、断连、未同步索引、不存在的 bank 和超长查询。

---

## 第七章 Reflect 链路：Agent 如何深度思考

### 7.1 Reflect 不是增强版 Recall：它是一个多步 Agent

最容易犯的错是把 reflect 当成「一次更强的 recall」。`reflect_async`（`engine/memory_engine.py:15501`）的 docstring 第一句就划清界限：它是一个 **read-only 的 agentic loop**，用一组只读工具迭代检索与推理，**自己不写入任何记忆**。对比 recall「一次查询、一次漏斗、立刻返回」，reflect 是「空上下文开始 → 自己决定查什么 → 再查 → 再推理 → 直到自己回答 done」。

它的工具有五个（`engine/reflect/tools.py`、`tools_schema.py`）：

| 工具 | 作用 | 数据层 |
|---|---|---|
| `search_mental_models` | 先查用户沉淀的总结（质量最高） | `mental_models` 向量检索 |
| `search_observations` | 查 consolidation 归纳出的带新鲜度的信念 | 内部走一次 recall（observation 类型） |
| `recall` | 查原始事实作为 ground truth（仅 world/experience） | 调用 `recall_async` |
| `expand` | 按 memory id 回读 chunk/文档原文 | 仅当 bank 开了文档文本存储才启用 |
| `done` | 提交最终答案 | 结构化工具调用 |

这是一种**分层检索**：先试总结（便宜、现成），再试观察（中等），最后才翻原始事实（最贵）。agent 自己决定下一层够不够。入口处还有硬校验：空 query 直接 `ValueError`；reflect provider 配成 `none` 直接抛 `LLMNotAvailableError`。

### 7.2 Agent 循环：recall → reason → tool call → 再 recall

核心循环在 `engine/reflect/agent.py:_run_reflect_agent_inner`。流程：

```
构造 system prompt（bank_profile + directives + disposition）
  → user prompt（原始 query）
  → LLM（带 tools）
        │
        ├─ 没有任何 tool call
        │     └─ 从没成功过 tool call → ReflectToolCallError（要求 tool-calling 模型）
        │        已有过 tool call      → 视为主动停 → 走 _finish 综合答案
        │
        ├─ 调了 done
        │     └─ 还没收集到任何证据（available_*_ids 全空）且没到最后一轮？
        │           → 回一条 tool 错误「先搜索再回答」，continue
        │           否则 → _process_done_tool → 校验引用 → 输出
        │
        └─ 调了其它工具（可并行多个）
              ├─ 剔除幻觉工具（不在 enabled_tools 集合里）
              ├─ 并行执行 tool（内部各 acquire 自己的 DB 连接，不占着连接等 LLM）
              ├─ 把结果按原始 tool_calls 顺序回填进 messages
              └─ 下一轮（rolling cache 把上一轮缓存起来）
        循环直到 done 或达到 max_iterations → _forced_final_synthesis 强制收尾
```

`max_iterations` 不是固定值：`reflect_max_iterations` 乘预算系数（low 0.5× / mid 1.0× / high 2.0×），默认 `DEFAULT_MAX_ITERATIONS=10`。工具调用可并行，但结果按原始顺序回填（Anthropic 要求一一对应）。两个工程细节：一是 DB 连接只在工具真正访问数据库时才 acquire，漫长的 LLM 调用期间不占连接；二是滚动 prompt cache 在每轮后台预建，把上一轮完整输入缓存起来，下一轮只发增量。

### 7.3 Disposition：bank 性格如何影响推理

每个 bank 在 `banks.disposition`（JSON，默认 `{"skepticism":3,"literalism":3,"empathy":3}`）里存三个 1–5 的性格分量。`engine/search/think_utils.py:build_disposition_description` 把数字翻译成 prompt 里的自然语言，再由 `prompts.py:bank_disposition_line` 注入 system prompt。三者的行为方向：

- **skepticism（怀疑度）**：1 = 轻信表面信息；3 = 平衡；5 = 高度怀疑，逐条审查准确性与隐藏动机。
- **literalism（字面度）**：1 = 爱读言外之意；3 = 平衡；5 = 严格按字面和承诺解释。
- **empathy（共情度）**：1 = 只看事实数据；3 = 平衡；5 = 形成记忆时充分考虑他人情绪与处境。

注意全 3 的中性 bank 不注入这行——注释说「单独把 `skepticism=5` 这种数字塞进 prompt，弱模型会把它当元数据忽略」，所以必须翻译成行为描述。这是「性格」影响推理风格而非检索结果的典型例子。

### 7.4 证据 grounding：每个结论必须引用源记忆

reflect 最硬的约束是**不能编造引用**。agent 维护三个集合：`available_memory_ids`、`available_mental_model_ids`、`available_observation_ids`，每成功跑一个工具就把返回结果里的 id 加进去。

当模型调 `done` 并附上 `memory_ids` / `mental_model_ids` / `observation_ids` 时，`_process_done_tool`（1719 行）做一次集合过滤：

```python
used_memory_ids      = [m for m in args.get("memory_ids")      or [] if m in available_memory_ids]
used_mental_model_ids= [m for m in args.get("mental_model_ids") or [] if m in available_mental_model_ids]
used_observation_ids= [o for o in args.get("observation_ids") or [] if o in available_observation_ids]
```

任何模型「幻觉」出来的、从没被工具返回过的 id，直接被丢弃——返回的 `used_*_ids` 才是这次答案真正站在其上的证据链。再加上 done 前置护栏：一个 evidence 集合都还空着就想 done，会被回怼「先搜索」。这两条合起来保证了 reflect 的输出是 grounded 的，而不是模型自由发挥。若 `done` 的 `answer` 为空（常因输出被 completion cap 截断），会抛 `ReflectNoAnswerError` 而不是塞占位答案。

### 7.5 结构化输出与 mental model 写入

reflect 默认返回一段自然语言答案，但支持两种结构化形态：

- **`response_schema`**：调用方传一个 JSON Schema，`_generate_structured_output` 在答案出来后再做一次抽取式 LLM 调用，把答案解析成 `structured_output` 字段；解析失败不致命，记 `structured_output_error`。
- **文档模式（`answer_as_document`）**：模型在 `done.document` 里直接返回分节结构，`structured_doc.py` 的 `StructuredDocument` / `Section` / `Block` 模型把它渲染成 markdown，不再让代码去「读」模型写的散文反推结构。

mental model 的**刷新**走的是另一套 delta 操作（`engine/reflect/delta_ops.py`）：LLM 不重写整篇，而是吐出一组结构化编辑指令——`AppendBlockOp` / `InsertBlockOp` / `ReplaceBlockOp` / `RemoveBlockOp` / `AddSectionOp` / `RemoveSectionOp` / `ReplaceSectionBlocksOp` / `RenameSectionOp`——每条带 block/section id。任何一条不合 schema，整批拒绝并要求重发；两次都失败就记 `delta_ops_failed` 并拒绝写入。这种「最小 diff」而不是「整篇覆盖」的写法，正是证据驱动、不静默替换的落地。directives 则作为硬规则在 system prompt 首尾两端注入。


值得一提的是 reflect 的**降级路径**：当 cross-encoder 不可用、或工具全被禁用时，agent 仍能在不访问数据库的情况下给出一个「基于已知 bank 配置」的回答，但会显式标注证据为空；结构化抽取失败也不会让整个请求失败，而是退回纯文本答案并带上错误标记。这种「能力可降级但不静默失败」的取向贯穿 reflect 全程。

### 7.6 本章小结

Reflect 是一个只读、tool-calling 的多步 Agent：它从空上下文出发，按「mental model → observation → raw fact → chunk」的分层顺序自己决定查什么，用带 evidence 集合校验的 done 工具收尾，保证每个引用都真实来自被检索过的记忆。bank 的 disposition 通过自然语言描述调节推理风格，结构化输出与 mental model 的 delta 编辑让它既能给人答案，也能增量地改写长期知识。它和 recall 的本质区别在于：recall 是系统替你选好再排好，reflect 是模型自己规划取证路径。

---

*本部分完。*
