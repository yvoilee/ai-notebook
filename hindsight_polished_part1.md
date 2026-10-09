<title>看懂 Hindsight：从仿生记忆结构到 Agent 学习闭环</title>

# 看懂 Hindsight：从仿生记忆结构到 Agent 学习闭环

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
