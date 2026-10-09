# Hindsight 技术文档大纲与写作规范

## 文档标题
《看懂 Hindsight：从仿生记忆结构到 Agent 学习闭环》

## 参考文档风格要点（必须严格遵循）
1. **问题先行**：每章开头先解释"为什么需要这个"，再展开机制
2. **边界澄清**：用比较表区分易混淆概念（如 RAG vs 记忆系统、world fact vs experience）
3. **分层叙述**：明确告诉读者哪些概念在同一层、哪些在不同层，不要混为一谈
4. **文本流程图**：用 `→` 和缩进表示流程和状态机，不用 Mermaid
5. **具体到源码**：引用真实文件名、类名、方法名、表名、字段名
6. **异常路径**：不仅讲正常流程，还要讲错误处理、并发、降级
7. **设计取舍**：区分"官方概念"和"本文归纳"，归纳处明确标注
8. **技术术语不通俗化**：保留 embedding、BM25、cross-encoder、pgvector 等术语
9. **章末小结**：每章末尾有"本章小结"
10. **编号体系**：第一/二/三/四部分 → 一/二/三...章 → 1/2/3...节

## 固定事实（已从源码确认，所有代理必须使用）
- 仓库：https://github.com/vectorize-io/hindsight，版本 0.10.1，MIT License
- 核心包：hindsight-api-slim（实际代码），hindsight-api 是元包
- 入口：`hindsight-api`（FastAPI 服务）、`hindsight-worker`（后台 worker）、`hindsight-admin`（管理 CLI）、`hindsight-local-mcp`（本地 MCP）
- 核心类：`MemoryEngine`（engine/memory_engine.py，23543 行），实现 `MemoryEngineInterface`
- 核心方法：`retain_async`、`retain_batch_async`、`recall_async`、`reflect_async`
- 数据库：PostgreSQL + pgvector（主），Oracle 23ai（功能对等），嵌入式 pg0
- 向量维度：384（VECTOR(384, FLOAT32)）
- LLM Provider：25+，支持 openai/anthropic/gemini/groq/bedrock/vertexai/minimax/deepseek/ollama/lmstudio/llamacpp/litellm 等
- 每个操作可独立配置 LLM：retain_llm_* / reflect_llm_* / consolidation_llm_*，回退到 memory_llm_*
- Embedding：可配置，支持本地（sentence-transformers/ONNX）和远程
- Reranker：cross-encoder，支持 flashrank/Google/jina-mlx 等
- 文本搜索后端：native tsvector / vchord (VectorChord BM25) / pg_search (ParadeDB) / pg_textsearch (Timescale) / pgroonga
- 生产 HTTP 强制 aiohttp 异步，禁止 httpx/requests（ruff TID251 规则）

## 核心数据表（已从 alembic oracle_baseline 迁移确认）
- **banks**: bank_id, internal_id, name, disposition(JSON: skepticism/literalism/empathy), mission, personality, config
- **documents**: id, bank_id, original_text, content_hash, metadata, retain_params, file_storage_key, tags
- **chunks**: chunk_id, document_id, bank_id, chunk_index, chunk_text, content_hash
- **memory_units**: id, bank_id, document_id, chunk_id, text, embedding(384vec), context, event_date, occurred_start/end, mentioned_at, fact_type(world/experience/observation), confidence_score, access_count, consolidated_at, proof_count, source_memory_ids, history(JSON), search_vector(BM25), tags, metadata
- **invalidated_memory_units**: memory_units 的冷归档副本 + invalidation_reason/invalidated_at/entity_ids，无 embedding 列
- **entities**: id, bank_id, canonical_name, metadata, first_seen, last_seen, mention_count
- **unit_entities**: unit_id, entity_id 多对多
- **entity_cooccurrences**: entity_id_1, entity_id_2, cooccurrence_count, last_cooccurred
- **memory_links**: from_unit_id, to_unit_id, link_type(temporal/semantic/entity/causes/caused_by/enables/prevents), entity_id, weight, source_memory_ids
- **mental_models**: id, bank_id, subtype(directive/pinned), name, description, source_query, content, embedding, observations(JSON), trigger(JSON: refresh_after_consolidation), max_tokens, history, last_refreshed_at
- **directives**: id, bank_id, name, content, priority, is_active, tags
- **async_operations**: operation_id, bank_id, operation_type, status(pending/processing/completed/failed/cancelled), worker_id, retry_count, task_payload
- **webhooks**: id, bank_id, url, secret, event_types, http_config, enabled
- **audit_log**: id, action, transport, bank_id, request/response JSON
- **observation_sources**: observation_id, source_id（观察的证据链）

## 源码目录结构（hindsight-api-slim/hindsight_api/）
- `engine/memory_engine.py` — 核心编排类
- `engine/retain/` — retain 流水线：orchestrator.py(4491), fact_extraction.py(3627), entity_processing.py, link_creation.py, embedding_processing.py, chunk_storage.py, fact_storage.py, memory_budget.py, bank_utils.py, link_utils.py
- `engine/search/` — recall 检索：retrieval.py(940), bm25_term_selection.py, graph_retrieval.py, link_expansion_retrieval.py, fusion.py, reranking.py, temporal_extraction.py, recall_boost.py, tag_resolution.py
- `engine/reflect/` — reflect 推理：agent.py(2155), prompts.py(1648), tools.py, tools_schema.py, observations.py, retractions.py, structured_doc.py, delta_ops.py, presentation.py, models.py, tokenization.py
- `engine/consolidation/` — 后台巩固：consolidator.py(3763), prompts.py
- `engine/memories/` — 存储抽象：base.py(2256), pg/ (graph.py, reads.py, writes.py, counts.py, curation.py)
- `engine/providers/` — LLM 提供商：openai_compatible_llm.py(2250), gemini_llm.py(1526), anthropic_llm.py(960), codex_llm.py(1223), xai_oauth_llm.py, github_copilot_llm.py
- `engine/db/` — 数据库层：postgresql.py, oracle.py, ops.py, ops_postgresql.py(1967), ops_oracle.py(1630), pool_instrumentation.py
- `engine/sql/` — SQL 方言：base.py, postgresql.py, oracle.py
- `engine/embeddings.py`(2316) — 嵌入模型
- `engine/cross_encoder.py`(2349) — 重排序模型
- `engine/llm_wrapper.py`(1840) — LLM 调用封装
- `engine/entity_resolver.py`(1694) — 实体解析
- `engine/parsers/` — 文档解析
- `engine/storage/` — 文件存储（S3/GCS/Azure via obstore）
- `engine/transfer/` — 导入导出
- `engine/directives/` — 指令
- `api/http.py`(10436) — FastAPI 路由
- `worker/poller.py`(2166) — 后台任务轮询
- `admin/cli.py`(1659) — 管理 CLI
- `extensions/` — 扩展点：operation_validator.py(1022), builtin/
- `webhooks/` — Webhook 系统
- `config.py`(5447) — 配置
- `migrations.py`(1680) — 迁移管理
- `mcp_tools.py`(4574) — MCP 工具
- `metrics.py`(1351) — Prometheus 指标

## 四部分十二章大纲

### 第一部分：认识 Hindsight
**一、Hindsight 是什么**
1. 从问题本质看：Agent 不会自动从经验中学习
2. 它与 RAG、知识图谱、对话历史的边界
3. 开源范围与成熟度

**二、先建立整体认知**
1. 整体模型：retain / recall / reflect 的学习闭环
2. 最重要的三个认识（记忆不是向量堆、bank 是隔离的脑、学习发生在后台）
3. 基础概念（bank、memory type、observation、mental model、directive）

### 第二部分：拆解系统架构
**三、存储内核：记忆如何被组织**
1. 为什么不用纯向量库：记忆需要时间、实体和因果
2. memory_units：一条记忆的完整形态
3. entities 与 memory_links：从事实到图谱
4. mental_models 与 directives：从记忆到知识
5. invalidated_memory_units：冷归档与可恢复删除
6. 多后端文本搜索：BM25 的五种实现
7. 本章小结

**四、运行时核心模块**
1. MemoryEngine：23000 行的编排核心
2. API 层与 Worker：同步路径与异步路径的分离
3. LLM Provider 抽象：25+ 提供商的统一接口
4. Embedding 与 Cross-Encoder：检索质量的两层保障
5. 扩展机制：Tenant、OperationValidator、Storage
6. 本章小结

### 第三部分：追踪核心执行链路
**五、Retain 链路：一条信息如何变成记忆**
1. 入口：从 HTTP 请求到 orchestrator
2. 第一阶段：文档切分与事实抽取（LLM 抽取 entities/temporal/relationships）
3. 第二阶段：实体解析与归一化（entity_resolver）
4. 第三阶段：链接创建（temporal/semantic/entity/causal）
5. 第四阶段：嵌入与索引写入
6. 异常路径：并发、预算超限、LLM 失败
7. 本章小结

**六、Recall 链路：一次查询如何召回记忆**
1. 四臂并行检索：semantic / keyword(BM25) / graph / temporal
2. 融合：Reciprocal Rank Fusion
3. 重排序：Cross-Encoder 的精确排序
4. 预算控制：token budget 与事实选择
5. 异常路径：空结果、多语言、标签过滤
6. 本章小结

**七、Reflect 链路：Agent 如何深度思考**
1. Reflect 不是增强版 Recall：它是一个多步 Agent
2. Agent 循环：recall → reason → tool call → 再 recall
3. Disposition：bank 性格如何影响推理
4. 证据 grounding：每个结论必须引用源记忆
5. 结构化输出与 mental model 写入
6. 本章小结

**八、Consolidation 与后台链路：记忆如何学习和进化**
1. 为什么需要后台巩固：retain 只负责写入，学习发生在 consolidation
2. Observation 生成：从多条事实中归纳信念
3. Observation 的证据链与 proof_count
4. Mental Model 刷新：trigger 机制与定时任务
5. Worker 与 async_operations：分布式后台处理
6. Webhook：生命周期事件通知
7. 本章小结

### 第四部分：理解设计取舍
**九、Hindsight 的关键设计思想（本文归纳）**
1. 仿生记忆结构：world/experience/observation 的分层
2. 证据驱动而非覆盖：新信息强化/弱化/扩展，不静默替换
3. Bank 严格隔离：一个 bank 一个脑
4. 多语言默认：输入语言端到端保留
5. Memory Defense：写入前的 PII/密钥扫描
6. 每操作独立 LLM：retain/reflect/consolidation 可用不同模型

**十、它适合什么，不适合什么**
1. 适合的场景（长期个性化 Agent、编码 Agent 项目记忆、AI 员工）
2. 不一定适合的场景（简单 RAG 问答、无状态工作流、超低延迟纯缓存）
3. 二次开发最值得复用的部分

**十一、源码阅读地图**
- 按学习路径推荐阅读顺序，标注每个文件的职责和行数

**十二、Hindsight 上手**
1. 启动方式：Docker / pip / Helm / Embedded
2. 三行代码接入：Python SDK 基本用法
3. LLM Wrapper：两行代码给现有 Agent 加记忆
4. 编码 Agent 集成
5. 生产部署要点

### 结语：Hindsight 真正控制的是"学习秩序"

## 输出要求
- 每章 1500-3000 字，深度与参考文档相称
- 使用 markdown 格式
- 包含比较表、文本流程图、伪代码块
- 所有技术事实必须有源码依据，不编造
- 区分官方概念和本文归纳
- 不使用 Mermaid/ASCII 图替代最终图（文本流程图 `→` 形式可以）
