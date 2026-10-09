<!--
负责章节范围：
  第一章  Hindsight 是什么（3 节）
  第二章  先建立整体认知（3 节）
  第五章  Retain 链路：一条信息如何变成记忆（7 节）
源码基线：hindsight 0.10.1，MIT License；核心包 hindsight-api-slim。
所有类名/方法名/表名字段名均来自该版本源码。
-->

# 一、Hindsight 是什么

## 1.1 从问题本质看：Agent 不会自动从经验中学习

先把问题问准。一个大语言模型本身是无状态的：每一次 `chat.completions.create` 都是一次全新的前向计算，上一轮说过什么、用户三个月前改过什么偏好，模型自己一概不记得。于是过去几年给 Agent 加“记忆”的做法，本质上都在回答同一个工程问题——**如何在一次推理之外，把过去的经验变成下一次推理能用上的上下文**。

但“记住”和“学会”是两件事。README 开篇那句话把这件事讲得很硬：*“Most agent memory systems focus on recalling conversation history. Hindsight is focused on making agents that learn, not just remember.”*（大多数 Agent 记忆系统关注的是回忆对话历史，Hindsight 关注的是让 Agent 学习，而不只是记住。）这句话不是营销修辞，它直接对应到代码里的一个结构事实：Hindsight 写入侧不是“把原文存下来再向量检索回去”，而是先用一次 LLM 调用把自然语言拆成结构化的 `Fact`（`engine/retain/fact_extraction.py` 里的 `Fact` / `ExtractedFact` 模型），再把这些事实沿时间、实体、因果三种边织进一张图里，最后由后台 consolidation 把多条事实归纳成带证据数的 `observation`。

换句话说，传统做法问的是“这句话以前说过吗，找出来”，Hindsight 问的是“从这一大堆经历里，这个 Agent 现在该形成什么信念”。前者是检索问题，后者是学习问题。这一章后面所有的设计取舍，都可以回溯到这个分野上。

把这个问题再往工程上推一步。一个 Agent 如果只是“每轮对话把历史消息拼进上下文”，会立刻撞上三堵墙：上下文窗口有限，三个月前的偏好必然被截断；同一句话被说十次，就要占十次 token，没有去重；用户纠正了旧偏好（“我以前吃辣，现在不吃了”），旧文本还躺在历史里，模型会把两个矛盾信念一起看见。向量检索缓解了“找不找得到”，但没解决“旧信念被新证据推翻后该怎么办”——RAG 库里两段互相矛盾的 chunk 会被一起召回，模型只能自己猜。Hindsight 的回答是把“推翻”这件事结构化：旧事实不硬删，而是在后台 consolidation 里被新证据弱化、改写，或整体作废进 `invalidated_memory_units` 冷归档。这不是检索优化，这是把人类记忆“逐渐修正、而非全盘覆盖”的机制搬进了存储层。

## 1.2 它与 RAG、知识图谱、对话历史的边界

这是最容易混淆的地方，因为 Hindsight 同时用了 RAG 的向量、知识图谱的边、对话历史的“按用户隔离”。但三者在 Hindsight 里都只是零件，不是目标。下表把它们放在同一层坐标系里对比（其中 Hindsight 一列对照 `memory_units` / `entities` / `memory_links` / `mental_models` 等实际表结构）。

| 维度 | RAG | 知识图谱 (KG) | 对话历史 (chat history) | Hindsight |
|---|---|---|---|---|
| 基本单元 | 切分后的 chunk 原文 | 三元组 (head, rel, tail) | 一轮轮 message 数组 | `memory_units`（一条 fact，含 fact_type/embedding/event_date） |
| 写入时做了什么 | 切片 + 向量化 | 人工/规则抽三元组 | 直接 append | LLM 抽事实 + 实体归一 + 时间抽取 + 因果标注 |
| 向量 | 主索引 | 通常没有 | 没有 | 有，`embedding VECTOR(384)`，但只是四路检索之一 |
| 关系 | 无 | 边是一等公民，需人工 schema | 无 | `memory_links`：temporal/semantic/entity/causes/caused_by/enables/prevents |
| 时间 | 无 | 弱（可选时间戳） | 线性顺序，越旧越被截断 | 一等字段：`occurred_start/end`、`mentioned_at`、事件区间 |
| 冲突处理 | 整段覆盖或重复堆积 | 人工改图 | 后发覆盖先发言 | 证据驱动：新信息强化/弱化/扩展 observation，不静默替换，`proof_count` 记录证据数 |
| 学习发生在哪 | 不学习 | 不学习 | 不学习 | 后台 consolidation 把多条 fact 归纳成 observation，再刷新 mental model |
| 隔离 | 一个库一个项目 | 一个图一个域 | 通常单会话 | `banks`：一个 bank 一个“脑”，严格隔离、不跨 bank 泄漏 |
| 典型失败模式 | 召回了却答非所问、chunk 切坏 | schema 设计错了就全错、维护成本高 | 上下文塞满后旧记忆被 truncate | 抽取质量依赖 LLM、写入路径重、延迟高 |

几个容易踩的边界点需要单独讲清楚。

**它不是 RAG。** RAG 存的是“原文片段”，检索回来直接拼进 prompt；Hindsight 存的是抽好的事实，原文（`documents.original_text`、`chunks.chunk_text`）默认只作为溯源和 delta 比对用，甚至可以通过 `store_document_text=false` 不存。检索时四路并行（semantic / BM25 keyword / graph / temporal，见 `engine/search/`），向量只是其中一路，还要经过 reciprocal rank fusion 和 cross-encoder rerank。

**它不是从零画的知识图谱。** KG 要求预先定义 schema 和关系类型，而 Hindsight 的实体（`entities.canonical_name`）是写入时由 LLM 抽名字、再经 `EntityResolver` 用 trigram 相似度对齐到既有 canonical 节点的，不需要人先画 ontology。边的类型是系统固定的那 7 种，不是开放 schema。

**它不是把对话历史塞进上下文窗口。** 对话历史是无差别保留每一轮文本，窗口满了就丢最早的；Hindsight 把每一轮对话转成 `world` / `experience` 两类 fact（`fact_type` 字段），丢掉“语气词”和“寒暄”，保留“用户说过他喜欢意餐”这种可被未来调用的事实。

## 1.3 开源范围与成熟度

仓库地址 `github.com/vectorize-io/hindsight`，当前基线 0.10.1，许可证 MIT。需要先纠正一个包名误解：`pip install hindsight-api` 装的是元包，真正的代码在 `hindsight-api-slim/hindsight_api/` 下。它不是一个库，而是一组进程：

- `hindsight-api`：FastAPI 服务（`api/http.py`，10436 行），对外是 REST + 每 bank 一个 MCP 端点 `/mcp/{bank_id}/`；
- `hindsight-worker`：后台 worker（`worker/poller.py`），轮询 `async_operations` 表里 pending/processing 的任务；
- `hindsight-admin`：管理 CLI，跑迁移、bank 修复、卡单处理；
- `hindsight-local-mcp`：本地 MCP 桥。

存储后端是 PostgreSQL + pgvector（向量维度 384，`VECTOR(384, FLOAT32)`），Oracle 23ai 是功能对等的企业选项，本地开发有嵌入式 pg0。LLM Provider 抽象了 25+ 家（openai/anthropic/gemini/groq/bedrock/vertexai/minimax/deepseek/ollama/lmstudio 等），而且 retain、reflect、consolidation 三个阶段可以各自配不同模型（`retain_llm_*` / `reflect_llm_*` / `consolidation_llm_*`，回退到 `memory_llm_*`）。文本搜索后端可在 native tsvector / vchord (BM25) / pg_search (ParadeDB) / pg_textsearch / pgroonga 之间选。

成熟度上要诚实地讲两点。第一，代码体量已经不是玩具：核心编排类 `MemoryEngine` 在 `engine/memory_engine.py`，23543 行；单 retain orchestrator 就有 4491 行，里面塞满了 issue 编号注释（#1888、#3294、#3387、#3756、#4068、#4251……），说明这是一个在生产事故里反复打磨过的系统，而不是 demo。第二，它依然是 0.x 版本，API 和内部表结构在快速演进——比如 `fact_type` 字面量在抽取层叫 `world`/`assistant`，落库后统一成 `world`/`experience`/`observation`，这种映射在源码里要靠上下文才能看出来。读它的时候要做好“按版本对号入座”的准备，不要把博客文章里的旧描述直接套到这份代码上。

**本章小结：** Hindsight 解决的不是“怎么把历史文本找回来”，而是“Agent 怎么从经历里形成可被未来调用的信念”。它复用了向量检索、图边、按用户隔离这些成熟零件，但写入侧强制走一次 LLM 事实抽取 + 实体归一 + 时间/因果标注，并把“学习”推迟到后台 consolidation。它是 MIT 开源的一组服务（API + worker + admin），跑在 PostgreSQL/pgvector 上，0.10.1 阶段已经有生产级的事故打磨痕迹，但仍在快速演进。

---

# 二、先建立整体认知

## 2.1 整体模型：retain / recall / reflect 的学习闭环

Hindsight 对外只暴露三个动词，对应 `MemoryEngine` 上的三个核心方法：`retain_async` / `recall_async` / `reflect_async`。README 把它们叫“The Three Operations”，这是官方概念，不是本文归纳。理解这三个动词之间的箭头，就理解了整个系统。

```
                    ┌─────────────────────────────────────────────┐
                    │              bank（一个脑，严格隔离）        │
                    └─────────────────────────────────────────────┘
                                        ▲
   写入：新经历进来                       │              读取：把记忆用回去
   retain(content)                       │
        │                                │
        ▼                                ▼
  LLM 抽 fact ──► entities/时间/因果边   recall(query)   reflect(query)
        │            ┌──────────┐         │                │
        │            │ memory_  │   四路并行检索          多步 Agent 推理
        │            │ units /  │   → RRF 融合            recall→reason→tool
        │            │ entities /│   → cross-encoder      →再 recall
        │            │ links     │   rerank→token 预算    │
        │            └────┬─────┘                        ▼
        │                 │                      带证据的结论 /
        │                 ▼                      刷新 mental_model
        │        后台 consolidation（不在请求路径上）
        │                 │
        └────────►  多条 fact 归纳成 observation（带 proof_count）
                            │
                            └────────► 刷新 mental_model（定时/触发）
```

三条边要分清：

- **retain → recall**：retain 负责把一条输入变成结构化、可检索的 fact 集合；recall 负责在你下次提问时把相关 fact 取回来。这是最基础的“写入—读取”闭环。
- **retain →（后台）→ observation**：retain 本身不做归纳。多条同类 fact 要等 worker 在后台跑 consolidation，才会被合并成一条带证据链的 `observation`（`observation_sources` 表记录证据来源）。
- **recall / reflect → 写入 mental_model**：reflect 不是只读，它可以把“想清楚的结论”落成 `mental_models` 行（`subtype=directive/pinned`），下次读这条就是一次数据库读，不再走检索和 LLM。

关键认识是：**retain 这一步并不“学习”，它只是忠实地把经历结构化地存下来**。真正的学习发生在两条不在请求热路径上的地方——后台 consolidation（fact → observation）和 mental model 刷新（observation → 长期知识）。这个分工直接决定了第五章要讲的 retain 流水线为什么那么重：它把脏活累活都在写入时干完，是为了让后续的学习可以异步、批量、低成本地跑。

顺带把 recall 和 reflect 的分工也点清楚，免得后面混淆。**recall 是“查”**：它把四路检索结果融合、重排、按 token 预算裁剪后原样返回给调用方，自己不做推理，适合“上次那个会议定了什么”这种有明确答案的问题。**reflect 是“想”**：它是一个多步 Agent（`engine/reflect/agent.py`，2155 行），在内部循环里反复 recall → reason → 调工具 → 再 recall，每个结论都要引用源记忆做证据 grounding，适合“这个用户身上有什么风险”这种需要跨多条记忆综合判断的问题。README 举的例子是 AI 项目经理反思项目风险、销售 Agent 反思哪类外联话术有回应——这些都不是一次向量检索能答的。一句话：recall 给你材料，reflect 替你读完材料写结论。

## 2.2 最重要的三个认识

在钻进任何一张表之前，先把三个反直觉的事实立住。它们都直接来自源码，不是比喻。

**认识一：记忆不是一堆向量。** 刚接触的人以为 Hindsight = “向量库存用户偏好”。打开 `memory_units` 表结构就会发现，向量只是其中一列（`embedding`，384 维），同行还躺着 `fact_type`（world/experience/observation）、`event_date`、`occurred_start/end`、`mentioned_at`、`confidence_score`、`access_count`、`proof_count`、`source_memory_ids`、`search_vector`（BM25 全文向量）、`history`（JSON）。一条记忆是一个带时间戳、带类型、带证据数、带全文索引的结构化对象，向量只负责“语义像不像”这一个维度。recall 之所以要四路并行，就是因为单靠向量回答不了“六月份发生了什么”（时间）或“Alice 还牵过谁”（图）。

**认识二：bank 是隔离的脑，不是分租户的文件夹。** `banks` 表带 `disposition` 字段（skepticism / literalism / empathy 三个性格维度的 JSON）、`mission`、`personality`。这意味着每个 bank 不只是数据隔离，它还携带影响 reflect 推理“性格”的背景。README 原话是 “one brain for one user, agent, or project. Isolation is strict: no cross-bank leakage”。retain 入口第一行就 `await get_memories().assert_writable(bank_id)`（`orchestrator.py:1413`），实体解析、co-occurrence、向量索引全部按 `bank_id` 分区。你不能把 bank 当成 namespace，它是一个有自己性格的独立认知主体。

**认识三：学习发生在后台，不在 retain 请求里。** retain 是同步或异步排队写入，但“从一堆 fact 里归纳出 observation”这件事是 worker 在 `async_operations` 表里挑任务跑的（`engine/consolidation/consolidator.py`，3763 行）。mental model 的刷新靠 `trigger.refresh_after_consolidation` 之类的机制和定时任务。这解释了一个产品行为：你 retain 完立刻 reflect，拿到的是“从原始 fact 现查现推”的答案；过一段时间再来，结论会因为后台 consolidation 而变化——因为 bank 真的“想过一遍”了。

## 2.3 基础概念（官方术语表）

下面这些是 README 和源码里反复出现的官方概念，先统一口径，后面章节不再解释。

- **bank**：隔离的记忆存储，一个“脑”。对应 `banks` 表。带 disposition 性格和 mission。
- **world fact / experience**：retain 抽取时标注的两类（抽取 schema 里叫 `fact_type: world | assistant`，落库后 `assistant` 对应 `experience`）。world 是“关于世界的客观事实、用户偏好、规则、纠正”；experience 是“Agent 自己实际做过的动作、经历”。这个区分来自 `ExtractedFact.fact_type` 的字段描述。
- **observation**：后台 consolidation 从多条 fact 归纳出的、带证据数的信念。`fact_type=observation`，有 `proof_count` 和 `source_memory_ids`，证据被删时会被作废（`invalidated_memory_units` 冷归档）。
- **mental model**：对一个固定问题的常驻答案（“这个用户的偏好是什么”），读它是一次数据库读，不查 LLM。对应 `mental_models` 表，`subtype` 为 `directive` 或 `pinned`。
- **directive**：一条可执行指令，对应 `directives` 表，带 `priority`、`is_active`，比 mental model 更“硬”。
- **entity**：被 LLM 抽出来、再由 `EntityResolver` 归一到 canonical 名字的人/组织/地点/概念。对应 `entities` 表，`unit_entities` 是多对多。
- **memory link**：fact 之间的边，`memory_links.link_type` 取 temporal / semantic / entity / causes / caused_by / enables / prevents。

本文在这些词之外做的归纳（比如“学习闭环”“三阶段”）都会显式标注“本文归纳”。

还有两个默认开启的行为值得在术语表里提前登记，否则后面读代码会困惑。一是**多语言默认**：输入语言被端到端保留，事实按原文存、实体保留原生写法——`张伟` 不会被规范化成 `Zhang Wei`，BM25 分词语言和 LLM 输出语言是两件独立配置的事。二是 **Memory Defense**：一个按 bank 开关的策略，对每一次 retain 扫 45 类密钥/PII 模式，命中就按策略 redact 成 `[REDACTED:github_token]` 或直接 block，是写入侧的前置闸门，第五章 5.2 会再见到它。

**本章小结：** Hindsight 的对外语义只有 retain / recall / reflect 三个动词，但学习本身不在 retain 里，而在后台 consolidation 和 mental model 刷新里。recall 是查、reflect 是想；记忆是带时间、类型、证据数、全文索引的结构化对象，不是向量堆；bank 是有性格的隔离脑；理解了这三点，再去看第五章的重写入流水线就不会觉得它过度设计。

---

# 五、Retain 链路：一条信息如何变成记忆

这一章追踪一次 `retain` 调用从 HTTP 进来到落库的全过程。它是整个系统最重、事故注释最多的一条链路，值得拆开看。

## 5.1 入口：从 HTTP 请求到 orchestrator

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

## 5.2 第一阶段：文档切分与事实抽取（LLM 抽取 entities / temporal / relationships）

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

## 5.3 第二阶段：实体解析与归一化（entity_resolver）

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

实体的 `mention_count` 和 `last_seen` **不在写事务里更新**，而是先攒在 `EntityResolver._pending_stats` 里，事务提交后再 `flush_pending_stats()`（`entity_resolver.py:565`）——而且按 `asyncio.current_task()` 隔离 key，避免并发 retain 互相 flush 对方未提交的 id。

## 5.4 第三阶段：链接创建（temporal / semantic / causal）

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

## 5.5 第四阶段：嵌入与索引写入

事实文本本身不直接进向量模型。`embedding_processing.augment_texts_with_dates()`（`embedding_processing.py:15`）会先把待嵌入文本改写成：

```
Alice got promoted (happened in 2025-06-15) [Alice, Google]
```

也就是把 `occurred_start`（或 `mentioned_at`）自然语言化追加到句尾、再把实体名用方括号拼上。**存进数据库的 `text` 列仍然是原始事实文本**，被增强的这串只用于算 embedding——这样做是为了让“六月份去露营”这种查询能命中六月发生的事，同时不污染可展示的原文。

嵌入向量是 384 维 float32，在内存里用 `array("f")` 紧凑打包（`PackedEmbedding`，`types.py:34`，比 `list[float]` 省 7.6 倍内存），写库时用 `embedding_to_pgvector` 渲染成 `'[%.9g,...]'` 字面量——9 位有效数字是 float32 的最短往返精度，避免二次 rounding。

除了 pgvector 向量列，`memory_units.search_vector`（BM25 全文向量）也在写入时构建。也就是说每条 fact 一落库就同时具备：稠密向量（语义）、稀疏 BM25（关键词）、时间字段（temporal）、实体挂载（graph）。recall 阶段能四路并行，是因为 retain 在写入时就把四路的索引都建好了。

## 5.6 异常路径：并发、预算超限、LLM 失败

这条链路的注释密度说明异常路径是一等公民，挑最重要的几类讲。

**并发同文档写入。** 每个批次写事务第一步是 `pool.ops.lock_document_for_write()` 对 `documents` 行 `SELECT ... FOR UPDATE`（`orchestrator.py:3164`）。抢到锁后核对 `content_hash`：如果跟本请求的 hash 对不上，说明另一个 retain 已经 cascade 删旧写新把文档“接管”了，replace 模式下就 `pipeline_aborted = True` 丢弃剩余批次；append 模式下直接抛 `ConcurrentAppendConflict` 让调用方在新文档上重做——因为 append 携带的是别人没见过的新内容，丢了就是真丢数据。

**崩溃恢复。** 重试同一个 operation 时，orchestrator 先读 `documents.content_hash` 和已有 chunk 的 hash 集合（`orchestrator.py:2488`），命中就把已提交 chunk 跳过；`async_operations.result_metadata.facts_committed_document_ids` 作为更粗的断点。这就是为什么 worker 任务可以安全重跑——它是幂等的。

**内存预算。** 旧版只按 chunk 数量限流，但一个“100 chunk”的批次可能是几百 KB 也可能是几百 MB（取决于 LLM 抽了多少 fact）。`RetainMemoryBudget`（`memory_budget.py`）改成按字节预算：生产者在把 chunk 入队前用 `estimate_chunk_bytes`（512 字节/fact 开销 + 字符串长度 + 384 维向量）预留，消费者提交后释放；单个 chunk 比整个预算还大时，只要当前管道是空的就放它进来，否则会死锁。

**LLM 失败。** 生产者任务 `asyncio.gather(..., return_exceptions=True)` 收集异常到 `producer_error`，所有 chunk 抽完后统一抛。消费者失败（死锁受害者、锁超时）时，生产者不能跟着泄漏——`finally` 块显式 cancel 所有 extraction 任务和 `CoalescingEmbedder`，否则它们会永久堵在 `chunk_queue.put()` 上继续烧 token（issue #3002）。

**Memory Defense 全挡。** 整批被策略 BLOCK 时抛 `MemoryDefenseAllBlockedError`，HTTP 层转成 422，body 里带回每个违规 item 的 detector 和 message。

## 5.7 本章小结

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
