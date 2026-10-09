<title>看懂 Hindsight：从仿生记忆结构到 Agent 学习闭环</title>

> 参考文档：[看懂 DeepSeek Harness：从插件内核到 Agent 执行闭环](https://bytedance.larkoffice.com/wiki/BGCuwF19YiEuzDk3Rgnc3bbtnLh)  
> 源码基线：Hindsight v0.10.1 · MIT License · [github.com/vectorize-io/hindsight](https://github.com/vectorize-io/hindsight)

# 第一部分：认识 Hindsight

## 一、Hindsight 是什么

### 1.1 从问题本质看：Agent 不会自动从经验中学习

先把问题问准。一个大语言模型本身是无状态的：每一次 `chat.completions.create` 都是一次全新的前向计算，上一轮说过什么、用户三个月前改过什么偏好，模型自己一概不记得。于是过去几年给 Agent 加“记忆”的做法，本质上都在回答同一个工程问题——**如何在一次推理之外，把过去的经验变成下一次推理能用上的上下文**。

但“记住”和“学会”是两件事。README 开篇那句话把这件事讲得很硬：*“Most agent memory systems focus on recalling conversation history. Hindsight is focused on making agents that learn, not just remember.”*（大多数 Agent 记忆系统关注的是回忆对话历史，Hindsight 关注的是让 Agent 学习，而不只是记住。）这句话不是营销话术，它直接对应到代码里的一个结构事实：Hindsight 写入侧不是“把原文存下来再向量检索回去”，而是先用一次 LLM 调用把自然语言拆成结构化的 `Fact`（`engine/retain/fact_extraction.py` 里的 `Fact` / `ExtractedFact` 模型），再把这些事实沿时间、实体、因果三种边织进一张图里，最后由后台 consolidation 把多条事实归纳成带证据数的 `observation`。

换句话说，传统做法问的是“这句话以前说过吗，找出来”，Hindsight 问的是“从这一大堆经历里，这个 Agent 现在该形成什么信念”。前者是检索问题，后者是学习问题。这一章后面所有的设计取舍，都可以回溯到这个分野上。

把这个问题再往工程上推一步。一个 Agent 如果只是“每轮对话把历史消息拼进上下文”，会立刻撞上三堵墙：上下文窗口有限，三个月前的偏好必然被截断；同一句话被说十次，就要占十次 token，没有去重；用户纠正了旧偏好（“我以前吃辣，现在不吃了”），旧文本还躺在历史里，模型会把两个矛盾信念一起看见。向量检索缓解了“找不找得到”，但没解决“旧信念被新证据推翻后该怎么办”——RAG 库里两段互相矛盾的 chunk 会被一起召回，模型只能自己猜。Hindsight 的回答是把“推翻”这件事结构化：旧事实不硬删，而是在后台 consolidation 里被新证据弱化、改写，或整体作废进 `invalidated_memory_units` 冷归档。这不是检索优化，这是把人类记忆“逐渐修正、而非全盘覆盖”的机制搬进了存储层。

### 1.2 它与 RAG、知识图谱、对话历史的边界

这是最容易混淆的地方，因为 Hindsight 同时用了 RAG 的向量、知识图谱的边、对话历史的“按用户隔离”。但三者在 Hindsight 里都只是零件，不是目标。下表把它们放在同一层坐标系里对比（其中 Hindsight 一列对照 `memory_units` / `entities` / `memory_links` / `mental_models` 等实际表结构）。

| 维度 | RAG | 知识图谱 (KG) | 对话历史 (chat history) | Hindsight |
|-|-|-|-|-|
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

### 1.3 开源范围与成熟度

仓库地址 `github.com/vectorize-io/hindsight`，当前基线 0.10.1，许可证 MIT。需要先纠正一个包名误解：`pip install hindsight-api` 装的是元包，真正的代码在 `hindsight-api-slim/hindsight_api/` 下。它不是一个库，而是一组进程：

- `hindsight-api`：FastAPI 服务（`api/http.py`，10436 行），对外是 REST + 每 bank 一个 MCP 端点 `/mcp/{bank_id}/`；
- `hindsight-worker`：后台 worker（`worker/poller.py`），轮询 `async_operations` 表里 pending/processing 的任务；
- `hindsight-admin`：管理 CLI，跑迁移、bank 修复、卡单处理；
- `hindsight-local-mcp`：本地 MCP 桥。

存储后端是 PostgreSQL + pgvector（向量维度 384，`VECTOR(384, FLOAT32)`），Oracle 23ai 是功能对等的企业选项，本地开发有嵌入式 pg0。LLM Provider 抽象了 25+ 家（openai/anthropic/gemini/groq/bedrock/vertexai/minimax/deepseek/ollama/lmstudio 等），而且 retain、reflect、consolidation 三个阶段可以各自配不同模型（`retain_llm_*` / `reflect_llm_*` / `consolidation_llm_*`，回退到 `memory_llm_*`）。文本搜索后端可在 native tsvector / vchord (BM25) / pg_search (ParadeDB) / pg_textsearch / pgroonga 之间选。

成熟度上要诚实地讲两点。第一，代码体量已经不是玩具：核心编排类 `MemoryEngine` 在 `engine/memory_engine.py`，23543 行；单 retain orchestrator 就有 4491 行，里面塞满了 issue 编号注释（#1888、#3294、#3387、#3756、#4068、#4251……），说明这是一个在生产事故里反复打磨过的系统，而不是 demo。第二，它依然是 0.x 版本，API 和内部表结构在快速演进——比如 `fact_type` 字面量在抽取层叫 `world`/`assistant`，落库后统一成 `world`/`experience`/`observation`，这种映射在源码里要靠上下文才能看出来。读它的时候要做好“按版本对号入座”的准备，不要把博客文章里的旧描述直接套到这份代码上。

**本章小结：** Hindsight 解决的不是“怎么把历史文本找回来”，而是“Agent 怎么从经历里形成可被未来调用的信念”。它复用了向量检索、图边、按用户隔离这些成熟零件，但写入侧强制走一次 LLM 事实抽取 + 实体归一 + 时间/因果标注，并把“学习”推迟到后台 consolidation。它是 MIT 开源的一组服务（API + worker + admin），跑在 PostgreSQL/pgvector 上，0.10.1 阶段已经有生产级的事故打磨痕迹，但仍在快速演进。

---

## 二、先建立整体认知

### 2.1 整体模型：retain / recall / reflect 的学习闭环

![Hindsight 学习闭环](https://feishu.cn/file/QgK7bgKdaoVUayxzhGVcvVmQnTb)

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

顺带把 recall 和 reflect 的分工也点清楚，免得后面混淆。**recall 是“查”：它把四路检索结果融合、重排、按 token 预算裁剪后原样返回给调用方，自己不做推理，适合“上次那个会议定了什么”这种有明确答案的问题。reflect 是“想”**：它是一个多步 Agent（`engine/reflect/agent.py`，2155 行），在内部循环里反复 recall → reason → 调工具 → 再 recall，每个结论都要引用源记忆做证据 grounding，适合“这个用户身上有什么风险”这种需要跨多条记忆综合判断的问题。README 举的例子是 AI 项目经理反思项目风险、销售 Agent 反思哪类外联话术有回应——这些都不是一次向量检索能答的。一句话：recall 给你材料，reflect 替你读完材料写结论。

### 2.2 最重要的三个认识

在钻进任何一张表之前，先把三个反直觉的事实立住。它们都直接来自源码，不是比喻。

**认识一：记忆不是一堆向量。** 刚接触的人以为 Hindsight = “向量库存用户偏好”。打开 `memory_units` 表结构就会发现，向量只是其中一列（`embedding`，384 维），同行还躺着 `fact_type`（world/experience/observation）、`event_date`、`occurred_start/end`、`mentioned_at`、`confidence_score`、`access_count`、`proof_count`、`source_memory_ids`、`search_vector`（BM25 全文向量）、`history`（JSON）。一条记忆是一个带时间戳、带类型、带证据数、带全文索引的结构化对象，向量只负责“语义像不像”这一个维度。recall 之所以要四路并行，就是因为单靠向量回答不了“六月份发生了什么”（时间）或“Alice 还牵过谁”（图）。

**认识二：bank 是隔离的脑，不是分租户的文件夹。**`banks` 表带 `disposition` 字段（skepticism / literalism / empathy 三个性格维度的 JSON）、`mission`、`personality`。这意味着每个 bank 不只是数据隔离，它还携带影响 reflect 推理“性格”的背景。README 原话是 “one brain for one user, agent, or project. Isolation is strict: no cross-bank leakage”。retain 入口第一行就 `await get_memories().assert_writable(bank_id)`（`orchestrator.py:1413`），实体解析、co-occurrence、向量索引全部按 `bank_id` 分区。你不能把 bank 当成 namespace，它是一个有自己性格的独立认知主体。

**认识三：学习发生在后台，不在 retain 请求里。** retain 是同步或异步排队写入，但“从一堆 fact 里归纳出 observation”这件事是 worker 在 `async_operations` 表里挑任务跑的（`engine/consolidation/consolidator.py`，3763 行）。mental model 的刷新靠 `trigger.refresh_after_consolidation` 之类的机制和定时任务。这解释了一个产品行为：你 retain 完立刻 reflect，拿到的是“从原始 fact 现查现推”的答案；过一段时间再来，结论会因为后台 consolidation 而变化——因为 bank 真的“想过一遍”了。

### 2.3 基础概念（官方术语表）

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

# 第二部分：拆解系统架构

## 三、存储内核：记忆如何被组织

![Hindsight 核心数据模型](https://feishu.cn/file/Mj1BbmnP2ofWqcxws6kcxbMknzf)

### 3.1 为什么不用纯向量库

一个常见误解是「记忆系统 = 一张 `id + embedding + text` 的向量表」。Hindsight 的存储层（`engine/memories/`）明确拒绝这种形态。原因在 `engine/memories/base.py` 的 `StoredMemory`、`FactRecord` 两个 dataclass 里写得很清楚：一条记忆除了向量与文本，还必须携带**四个时间字段**（`event_date`、`occurred_start`、`occurred_end`、`mentioned_at`）、**实体列表**（`entity_ids`）、**因果边**（`causal_edges`）、**证据来源**（`source_memory_ids`）与**证据强度**（`proof_count`）。

纯向量库只能回答「语义上像」，而记忆需要回答另外三类问题：这件事发生在什么时候？它和哪些人/物有关？它导致了什么、又被什么导致？这些维度靠向量相似度都拿不到，必须落成结构化列与图边。因此 Hindsight 的主存储是 **PostgreSQL + pgvector**（功能对等 Oracle 23ai），向量只是 `memory_units` 表中的一列 `embedding VECTOR(384, FLOAT32)`，而不是全部。

存储抽象层是 `MemoriesExtension`（`base.py:770`，继承 `Extension, ABC`）。它用一个 `store_owned: bool` 标志区分两类后端：默认 `False` 表示 SQL 存储（Postgres/Oracle），记忆就是表行，retain 在事务里直接写 SQL；`True` 表示存储自带的外部索引，整个 retain 作为一次原子服务端调用提交。这种设计让产品策略（预算、arm 开关）留在引擎侧，存储实现只负责「怎么存、怎么按地址读」。

### 3.2 memory_units：一条记忆的完整形态

`memory_units` 是整个系统的中心表。字段定义来自 `alembic/versions/o1a2b3c4d5e6_oracle_baseline.py`（Oracle 方言版本，PG 侧由 59 个增量迁移等价构建）。关键列如下：

| 字段 | 类型 | 含义 |
|-|-|-|
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
|-|-|-|-|
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
|-|-|-|-|
| `native`（默认 tsvector） | `ts_rank_cd(search_vector, to_tsquery(lang, $))` | `search_vector @@ to_tsquery(...)` | token 用 `\|` 做 OR 连接；无 IDF，靠 `bm25_term_selection` 选高区分度词 |
| `vchord`（VectorChord） | `-(search_vector <&> to_bm25query(idx, tokenize(q,'llmlingua2')))` | 算子给所有文档打分，需 `> 0` 门控 | `<&>` 返回负分，取负；必须门控零分噪声 |
| `pg_search`（ParadeDB） | `paradedb.score(id)` | `id @@@ paradedb.boolean(should=>...)` | 跨 `text`/`text_signals` 字段 fan-out |
| `pg_textsearch`（Timescale） | `-(text <@> to_bm25query(q, idx))` | 无独立谓词，按距离 ASC | 距离即分数，升序让索引驱动排序 |
| `pgroonga` | `pgroonga_score(tableoid, ctid)` | \`(text |  |

关键工程取舍：各后端算子的分数尺度完全不同（`ts_rank_cd`、负距离、`paradedb.score`），所以 Hindsight 不在 SQL 里比分数，而是统一在下游按**排名**做 RRF 融合（见第六章）。`bm25_term_selection.py` 还解释了 native 后端的一个痛点：`ts_rank_cd` 没有 IDF 且不在索引里，长查询会扫全库再排序，于是它从 `pg_stats.most_common_elems` 里挑文档频率最低（最具区分度）的前 N 个词，绝不盲目截断前 N 个 token。

### 3.7 本章小结

Hindsight 的存储内核不是向量库，而是一张按 bank 自动分区的事实表 `memory_units`，外加实体表、七类边的轻量图、总结层 `mental_models`、规则层 `directives`，以及一张无向量列的冷归档表 `invalidated_memory_units`。向量只是其中一列；时间、实体、因果、证据链才是记忆区别于 RAG chunk 的地方。文本搜索通过 SQL 方言抽象支持五种 BM25 后端，分数不可比，统一交给下游融合。

---

## 四、运行时核心模块

![Hindsight 系统架构总览](https://feishu.cn/file/XzwcbsuKJoMYBoxdBsAcjYLgnsf)

### 4.1 MemoryEngine：23000 行的编排核心

`MemoryEngine`（`engine/memory_engine.py:2360`，实现 `MemoryEngineInterface`，全文件 23543 行）是整个系统的门面与编排器。它自己不做具体检索/抽取，而是把请求拆成「鉴权 → 配置解析 → 调用存储/LLM/检索 → 收尾钩子」。`__init__`（2371 行）的参数列表本身就是运行时拓扑：`db_url`、三套独立的 LLM（`retain_llm_*` / `reflect_llm_*` / `consolidation_llm_*`，各自回退到 `memory_llm_*`）、`embeddings`、`cross_encoder`、`query_analyzer`、连接池参数、`task_backend`、`operation_validator`、`tenant_extension`。

`initialize()`（5257 行）按顺序启动：内嵌 pg0 → 初始化 embeddings → cross-encoder → query_analyzer（默认 `DateparserQueryAnalyzer`）→ memories 扩展 → 校验 LLM 连通性。这种「构造轻、initialize 重」的两阶段是为了让 FastAPI lifespan 能精确控制启动顺序与失败上报。`run_migrations` 默认 True，服务首次启动会自己把 schema 推到 head；provider 为 `none` 时自动跳过连通性探测，便于离线与测试。

核心对外方法四个：`retain_async`、`retain_batch_async`、`recall_async`、`reflect_async`。它们都长一个样：先 `_authenticate_tenant`、跑 `operation_validator` 前置钩子、解析 bank 配置，再干活，最后跑后置钩子。这种一致的骨架是 Hindsight 能在每个操作前后插入审计、限流、多租户校验的原因。`MemoryEngine` 自己不内嵌产品策略——`FullRecallRequest`（base.py）注释明确写「这是引擎解析后的值，不是调用方的原始请求」：预算、arm 开关、reranker 模式都在引擎侧算好再下发，存储实现无需读 config，换 bank 配置不必发版。连接池还做了读写分离：`read_database_url` 单独配一个读池，`_get_read_backend()` 把 recall 这类读密集流量从写主库卸下来。

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

# 第四部分：理解设计取舍

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

> 建议：`memory_engine.py` 两万多行不要从头读，它是"总机"，按上面五趟里遇到的调用点跳读即可。

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

# 结语：Hindsight 真正控制的是"学习秩序"

写到这里，十二章串起来其实只在讲一件事。

表面上，Hindsight 是一个"Agent 记忆系统"——能存、能搜、能答。但如果你顺着 retain → recall → reflect → consolidation 一路读下来，会发现它花最多工程力气的地方，根本不是"怎么存得快"或"怎么搜得准"，而是**怎么让新进来的经验，有序地、可追溯地、不互相污染地，变成 Agent 下次还能用的信念**。

它规定了：一条事实从文档里出来时叫 experience，必须被打上时间、挂上实体、连上图谱（第五章）；被问到时，要四路并行捞、融合、重排，只在预算内给模型最相关的（第六章）；要深思时，模型必须拿着证据链说话，不能凭空发挥（第七章）；而过了这一切之后，后台还要把零散事实合并成 observation——合并时不许做算术、不许静默覆盖、必须留历史、必须数清证据（第八章）。再往下，每一个 bank 是一个隔离的脑，每种语言是它自己的语言，每一次写入要先过密钥安检，每一类思考可以用不同价格的模型（第九章）。

这就是"学习秩序"：**它不替 Agent 变聪明，它约束经验沉淀成记忆的那条路径不发生混乱**。RAG 关心"这一次把相关文档找出来"，而 Hindsight 关心"一百次之后，这个 Agent 关于同一个人、同一件事、同一个项目，有没有形成一个前后一致、可被证伪、还带着证据的认识"。

开源世界里不缺能存向量的库，缺的是对"记忆该如何随时间生长"这件事有一整套明确、可执行、可审计主张的系统。Hindsight 把这套主张写进了 23000 行的 `memory_engine`、3763 行的 consolidator 和那些近乎苛刻的 prompt 规则里。读懂它，你读懂的不只是一个产品，而是一种"怎么让 AI 慢慢变聪明而不是慢慢变糊涂"的工程回答。