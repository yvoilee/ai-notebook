# 第三部分：追踪核心执行链路

## 五、Retain 链路：一条信息如何变成记忆

这一章追踪一次 `retain` 调用从 HTTP 进来到落库的全过程。它是整个系统最重、事故注释最多的一条链路，值得拆开看。

![Retain 流水线](https://feishu.cn/file/Y309bwcDko4LtCxPXsPc7f4unXg)

### 5.1 入口：从 HTTP 请求到 orchestrator

入口路由在 `api/http.py:9772`：

```
POST /v1/default/banks/{bank_id}/memories
```

处理函数 `api_retain`（`http.py:9798`）做的第一件事不是存数据，而是把多模态 item 规范化成纯文本：`canonicalize_item_content` 把图片换成占位符 `[attachment:short_id]`，图片字节本身在 ingress 阶段就写进内容寻址存储，下游永远只碰文本。然后它按 `strategy` 把 items 分组，每条组装成 `RetainContentDict`（`types.py:112`，字段 `content/context/event_date/metadata/document_id/entities/tags/update_mode/observation_scopes` 等）。

接下来分两路：

- `async=true` → `MemoryEngine.submit_async_retain`：写一行 `async_operations` 表（status=pending），立刻把 `operation_id` 还给调用方，真正的活儿由 `hindsight-worker` 轮询捞起；
- `async=false` → 直接 `await MemoryEngine.retain_batch_async(...)`。注意 `config.retain_batch_enabled=true` 时同步路径会被拒（400），因为大批次 retain 可能跑几分钟到几小时，HTTP 扛不住。

`MemoryEngine.retain_async`（`memory_engine.py:5918`）只是 `retain_batch_async`（`:5966`）的单条包装。`retain_batch_async` 依次做：租户鉴权（`_authenticate_tenant`）、operation validator 扩展点、`_ensure_bank_exists`、**全字段 sanitize**（去掉 UTF-16 孤代理和 NUL，否则会崩 embedder 或 INSERT，issue #1875/#3729）、按 document_id 分组，最后调到 `engine/retain/orchestrator.py` 里的模块级函数 `retain_batch()`（`orchestrator.py:1352`）。

到这里，HTTP 层和 MemoryEngine 层的活就干完了。真正的流水线在 orchestrator 里。

### 5.2 第一阶段：文档切分与事实抽取（LLM 抽取 entities / temporal / relationships）

`retain_batch()` 在动 LLM 之前先过三道闸门：

1. **Memory Defense 筛查**（`orchestrator.py:1543`）：如果配了 PII/密钥扫描扩展，逐 item 调 `screen()`，命中就 `REDACT`（把 `[REDACTED:github_token]` 写回正文）或 `BLOCK`。整批全 BLOCK 抛 `MemoryDefenseAllBlockedError` → HTTP 422；部分 BLOCK 就把被挡的槽位从列表里删掉，用 `_align_result` 把返回结果填回原位置（`orchestrator.py:1616`）。
2. **document_id 决议**：没有显式 document_id 就 `uuid4()` 生成；异步重试时从 `async_operations.result_metadata.document_ids[0]` 恢复（`:1631`）。
3. **delta retain 探测**：`attempts_delta_retain()` 为真就先走 `_try_delta_retain()`——它对已有 document 按 chunk 的 `content_hash` diff，只重抽改动过的 chunk，没改动的 chunk 连事实都不重抽。命中就直接返回，不再走全量路径。

通过后才进入切分：`fact_extraction.iter_chunks(content, retain_chunk_size, structured_chunk_size, max_attachments_per_chunk)` 把正文切成 chunk 流（`orchestrator.py:1924`）。切分器能识别 JSONL、对话 turn、结构化文档，还会把图片占位符当作不可切分的原子段。

真正的事实抽取在 `_extract_and_embed()`（`orchestrator.py:1212`）里，调用 `fact_extraction.extract_facts_from_contents`。它对每个 chunk 发一次结构化输出 LLM 调用，system prompt 是 `CONCISE_FACT_EXTRACTION_PROMPT`（默认模式），输出由 Pydantic 模型 `ExtractedFact`（`fact_extraction.py:255`）约束：

```
what        核心事实，1-2 句
when/where/who/why   四个维度，缺失填 "N/A"
fact_kind   "event" | "conversation"   ← 决定要不要写 occurred_start
fact_type   "world" | "assistant"
entities    ["Alice", "Kubernetes", ...]
occurred_start / occurred_end   ISO-8601
causal_relations  [{target_index: <本 fact 之前的某个下标>, relation_type: "caused_by"}]
from_attachments  0-based 附件下标
```

几个设计点值得单拎出来：

- **因果边只允许指向本 chunk 里排在自己前面的 fact**（`FactCausalRelation.target_index` 描述：“MUST be less than this fact's position”）。这是为了让 LLM 没法瞎编一个不存在的下标。落库时 `causal_relations` 只存 `caused_by` 一种方向（`link_creation.py:81`）。
- **粗日期要写区间**。prompt 明确要求“in 2015”要展开成 `occurred_start=2015-01-01` / `occurred_end=2015-12-31`，而不是坍缩到 1 月 1 日——因为后者等于让记忆声称了一个它没说过的日子。
- **抽取失败会自动切 chunk 重试**：输出超长时 `_split_chunk_for_output_retry` 把 chunk 对半切，但有 500 字符下限防止无限递归（`fact_extraction.py:310`）。

抽取出来的 `ExtractedFact` 经 `ProcessedFact.from_extracted_fact`（`types.py:450`）过滤掉退化文本（`"..."`、`"—"`、纯标点这种 LLM 幻觉产物），再把因果下标在过滤后重新映射（`_remap_causal_relations`，`orchestrator.py:1271`）——被删的 fact 的出边和入边一起消失，而不是错指到下一条幸存 fact。

### 5.3 第二阶段：实体解析与归一化（entity_resolver）

抽出来的 `entities` 是 LLM 自由文本猜的名字：“Alice”“阿丽斯”“Alice Zhang”可能指同一个人，也可能不是。这一步由 `engine/entity_resolver.py` 的 `EntityResolver` 完成。

它被刻意放在**写事务之外**跑（`_pre_resolve_phase1`，`orchestrator.py:558`），用一条单独连接，因为它要做 trigram GIN 扫描 + co-occurrence 打分，是 read-heavy 的慢操作，不能占着行锁。算法骨架是：

```
对每个新提到的名字 mention:
  1. pg_trgm GIN 索引捞出相似度候选（默认上限 200 个，避免 event-loop 阻塞）
  2. 在 Python 里算 trigram 集合相似度 + token 兼容 + 数字匹配（_tokens_are_compatible）
  3. 叠加 entity_cooccurrences 共现权重（两个人常一起出现，更可能是同一群人）
  4. 超过 merge_min_similarity(0.3) 就归到既有 canonical entity，否则新建
  5. 同一批 retain 内部再做一次 intrabatch 聚类（intrabatch_merge_similarity=0.5），
     把 "Alice" 和 "Alice Zhang" 在本批内合并
```

结果是 `EntityResolutionResult`：resolved_entities（canonical id 列表）、entity_to_unit（每个占位 unit 挂哪些实体）、unit_to_entity_ids。这里有个关键工程细节：**Phase 1 用 `str(i)` 当占位 unit id**（因为真实 UUID 要等 INSERT 才生成），等 Phase 2 INSERT 完拿到真 id，再用 `_remap_phase1_results`（`orchestrator.py:640`）把所有占位 id 翻译成真 UUID。

另外，调用方自己传的 `entities` 和 LLM 抽的 entities 会合并（`entity_processing.py:33`）：LLM 抽的一律 `resolve=True`（必须对齐到 canonical），调用方传的默认也 resolve，但可以 `resolve_entities=False` 要求“按字面量我就是要这个名字”，两者撞名时用户意图优先（`entity_processing.py:77`）。

实体的 `mention_count` 和 `last_seen`**不在写事务里更新**，而是先攒在 `EntityResolver._pending_stats` 里，事务提交后再 `flush_pending_stats()`（`entity_resolver.py:565`）——而且按 `asyncio.current_task()` 隔离 key，避免并发 retain 互相 flush 对方未提交的 id。

### 5.4 第三阶段：链接创建（temporal / semantic / causal）

真正的写事务在 `_insert_facts_and_links()`（`orchestrator.py:691`）里，一个事务内完成：

```
INSERT memory_units (拿到真 unit UUID)
  → reassert_entities_batch（在本事务里重新锁定刚解析出的实体父节点，#2662）
  → INSERT unit_entities 多对多
  → create_temporal_links_batch
  → create_semantic_links_batch（streaming 模式下跳过，推迟到 Phase 3）
  → create_causal_links_batch
```

三类边的生成逻辑：

- **temporal**（`link_utils.py:486`）：默认 24 小时时间窗。用 `(bank_id, fact_type, event_date)` B-tree 索引做双向 LATERAL 扫描，每个新 unit 向前后各取 K 个邻居，`weight = max(0.3, 1 - time_diff_hours/24)`，每 unit 上限 `MAX_TEMPORAL_LINKS_PER_UNIT = 20`。不用全窗排序，是为了在 16 万条 memory 时把 74ms 的扫描压到 0.6ms。
- **semantic**：cosine 相似度超过 `semantic_link_min_similarity` 就连边。但 streaming retain **在批次内故意不做**——它会让后续批次越来越慢（O(bank_size) 的 ANN 探测），所以推迟到全部批次提交后由 `_run_final_semantic_ann()`（`orchestrator.py:1995`）统一跑一遍：按 1000 个 seed 切块、4 路并发、top_k=20。
- **causal**：直接消费 LLM 在抽取时标的 `caused_by` 关系（`link_creation.py:81`）。数据库和检索路径还认识 `enables`/`prevents` 等历史类型，但 retain 只写 canonical 的 `caused_by`。

注意一件事：**entity 类型的 `memory_links` 不在 retain 里写**。注释明确说（`orchestrator.py:770`）——实体之间的关系边是 `/graph` 端点按需从 `unit_entities` 自连接推出来的，写它只会增加写放大，不服务检索。

### 5.5 第四阶段：嵌入与索引写入

事实文本本身不直接进向量模型。`embedding_processing.augment_texts_with_dates()`（`embedding_processing.py:15`）会先把待嵌入文本改写成：

```
Alice got promoted (happened in 2025-06-15) [Alice, Google]
```

也就是把 `occurred_start`（或 `mentioned_at`）自然语言化追加到句尾、再把实体名用方括号拼上。**存进数据库的 `text` 列仍然是原始事实文本**，被增强的这串只用于算 embedding——这样做是为了让“六月份去露营”这种查询能命中六月发生的事，同时不污染可展示的原文。

嵌入向量是 384 维 float32，在内存里用 `array("f")` 紧凑打包（`PackedEmbedding`，`types.py:34`，比 `list[float]` 省 7.6 倍内存），写库时用 `embedding_to_pgvector` 渲染成 `'[%.9g,...]'` 字面量——9 位有效数字是 float32 的最短往返精度，避免二次 rounding。

除了 pgvector 向量列，`memory_units.search_vector`（BM25 全文向量）也在写入时构建。也就是说每条 fact 一落库就同时具备：稠密向量（语义）、稀疏 BM25（关键词）、时间字段（temporal）、实体挂载（graph）。recall 阶段能四路并行，是因为 retain 在写入时就把四路的索引都建好了。

### 5.6 异常路径：并发、预算超限、LLM 失败

这条链路的注释密度说明异常路径是一等公民，挑最重要的几类讲。

**并发同文档写入。** 每个批次写事务第一步是 `pool.ops.lock_document_for_write()` 对 `documents` 行 `SELECT ... FOR UPDATE`（`orchestrator.py:3164`）。抢到锁后核对 `content_hash`：如果跟本请求的 hash 对不上，说明另一个 retain 已经 cascade 删旧写新把文档“接管”了，replace 模式下就 `pipeline_aborted = True` 丢弃剩余批次；append 模式下直接抛 `ConcurrentAppendConflict` 让调用方在新文档上重做——因为 append 携带的是别人没见过的新内容，丢了就是真丢数据。

**崩溃恢复。** 重试同一个 operation 时，orchestrator 先读 `documents.content_hash` 和已有 chunk 的 hash 集合（`orchestrator.py:2488`），命中就把已提交 chunk 跳过；`async_operations.result_metadata.facts_committed_document_ids` 作为更粗的断点。这就是为什么 worker 任务可以安全重跑——它是幂等的。

**内存预算。** 旧版只按 chunk 数量限流，但一个“100 chunk”的批次可能是几百 KB 也可能是几百 MB（取决于 LLM 抽了多少 fact）。`RetainMemoryBudget`（`memory_budget.py`）改成按字节预算：生产者在把 chunk 入队前用 `estimate_chunk_bytes`（512 字节/fact 开销 + 字符串长度 + 384 维向量）预留，消费者提交后释放；单个 chunk 比整个预算还大时，只要当前管道是空的就放它进来，否则会死锁。

**LLM 失败。** 生产者任务 `asyncio.gather(..., return_exceptions=True)` 收集异常到 `producer_error`，所有 chunk 抽完后统一抛。消费者失败（死锁受害者、锁超时）时，生产者不能跟着泄漏——`finally` 块显式 cancel 所有 extraction 任务和 `CoalescingEmbedder`，否则它们会永久堵在 `chunk_queue.put()` 上继续烧 token（issue #3002）。

**Memory Defense 全挡。** 整批被策略 BLOCK 时抛 `MemoryDefenseAllBlockedError`，HTTP 层转成 422，body 里带回每个违规 item 的 detector 和 message。

### 5.7 本章小结

把整条链路压成一张文本流程图（本文归纳，节点名对齐源码函数）：

```
POST /v1/default/banks/{bank_id}/memories  (api/http.py: api_retain)
  → canonicalize_item_content（图片→占位符）
  → MemoryEngine.retain_batch_async (memory_engine.py:5966)
      鉴权 / sanitize / ensure bank
  → retain_batch() (retain/orchestrator.py:1352)
      ├─ Memory Defense screen（REDACT/BLOCK → 422）
      ├─ resolve document_id（生成/从 operation 恢复）
      ├─ stale-request check / append CAS
      ├─ delta retain 尝试（chunk hash diff，未变则跳过）
      └─ iter_chunks 切分
          ↓ producer (LLM，并发限流)
          _extract_and_embed
            fact_extraction LLM 抽 ExtractedFact(what/when/where/who/why, world|assistant,
                                                entities, occurred_start/end, caused_by)
            → 退化文本过滤
            → augment_texts_with_dates（时间+实体拼进待嵌入串）
            → embed 384 维
            → RetainMemoryBudget.reserve(bytes) → queue
          ↓ consumer (DB，按 chunk_batch_size 或字节预算 flush)
          _process_db_batch
            Phase 1  _pre_resolve_phase1（独立连接，无事务）
                       EntityResolver: pg_trgm GIN → co-occurrence → 归一 canonical
            Phase 2  写事务
                       lock_document_for_write (SELECT FOR UPDATE)
                       handle_document_tracking / store_chunks_batch
                       insert_facts_batch → 真 UUID
                       _remap_phase1_results（占位→真 id）
                       unit_entities / temporal links / causal links
            Phase 3  提交后 fire-and-forget
                       flush_pending_stats（mention_count/cooccurrence）
                       _run_final_semantic_ann（全 bank 语义边，top_k=20）
          ↓
      写入 memory_units / chunks / entities / unit_entities / memory_links / entity_cooccurrences
```

Retain 的核心设计取舍是：**把所有“贵”的操作（LLM 抽取、实体 trigram 扫描、ANN 语义边）尽量推到事务外、推到提交后，把所有“检索正确性依赖”的写（fact、unit_entities、temporal/causal 边）压进一个事务**。它不是一条“存文本”的链路，而是一条把非结构化输入转成带时间、实体、因果、双路向量索引的结构化记忆的 ETL——正因为它在写入时把活干得足够细，后台 consolidation 才能低成本地把这些事实归纳成 Agent 真正能用的信念。

## 六、Recall 链路：一次查询如何召回记忆

![Recall 四臂检索融合](https://feishu.cn/file/GZNubqDuiojScTxIpgQcOLmCnEc)

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
- **bank 不存在**：`_require_bank_exists` 返回 404，而不是跑完一整套扇出后空返 200。
- **标签/更新窗口**：`created_after/before` 名义上按创建，实际过滤 `updated_at`——「这段时间里变动过的记忆」，编辑过的事实会重新进入窗口。
- **多语言**：native tsvector 的语言由 `text_search_extension_native_language` 配置；pgroonga 用 TokenBigram 天然支持 CJK；vchord 用 llmlingua2 分词。
- **长查询兜底**：native 后端靠 `bm25_term_selection` 从 `pg_stats` 选高区分度词，失败时退回保留前 N 词，绝不阻塞 recall。

### 6.6 本章小结

Recall 是一个「四臂粗排 → 排名融合 → cross-encoder 精排 → token 截断」的漏斗。它的关键洞见是：不同臂的分数不可比，所以融合只信名次（RRF）；精排只对融合后的小池子做，成本可控；时间、热度、证据强度作为乘性微调而不是硬规则叠加在 CE 主分上。异常路径覆盖了空查询、断连、未同步索引、不存在的 bank 和超长查询。

---

## 七、Reflect 链路：Agent 如何深度思考

![Reflect Agent 循环](https://feishu.cn/file/Wd5mbK6uHoV8EOx9s7wc8bnZnpb)

### 7.1 Reflect 不是增强版 Recall：它是一个多步 Agent

最容易犯的错是把 reflect 当成「一次更强的 recall」。`reflect_async`（`engine/memory_engine.py:15501`）的 docstring 第一句就划清界限：它是一个 **read-only 的 agentic loop**，用一组只读工具迭代检索与推理，**自己不写入任何记忆**。对比 recall「一次查询、一次漏斗、立刻返回」，reflect 是「空上下文开始 → 自己决定查什么 → 再查 → 再推理 → 直到自己回答 done」。

它的工具有五个（`engine/reflect/tools.py`、`tools_schema.py`）：

| 工具 | 作用 | 数据层 |
|-|-|-|
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

reflect 还有一条**降级路径**：当 cross-encoder 不可用、或工具全被禁用时，agent 仍能在不访问数据库的情况下给出一个「基于已知 bank 配置」的回答，但会显式标注证据为空；结构化抽取失败也不会让整个请求失败，而是退回纯文本答案并带上错误标记。这种「能力可降级但不静默失败」的取向贯穿 reflect 全程。

### 7.6 本章小结

Reflect 是一个只读、tool-calling 的多步 Agent：它从空上下文出发，按「mental model → observation → raw fact → chunk」的分层顺序自己决定查什么，用带 evidence 集合校验的 done 工具收尾，保证每个引用都真实来自被检索过的记忆。bank 的 disposition 通过自然语言描述调节推理风格，结构化输出与 mental model 的 delta 编辑让它既能给人答案，也能增量地改写长期知识。它和 recall 的本质区别在于：recall 是系统替你选好再排好，reflect 是模型自己规划取证路径。

---

*本部分完。*

