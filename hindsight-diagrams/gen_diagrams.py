#!/usr/bin/env python3
"""Generate Hindsight technical diagrams as SVG, then convert to PNG via cairosvg."""

import cairosvg
import os

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

# Color palette - professional tech blue/teal
C_BG = "#ffffff"
C_PRIMARY = "#1a5276"
C_SECONDARY = "#2980b9"
C_ACCENT = "#16a085"
C_WARN = "#d35400"
C_LIGHT = "#ebf5fb"
C_LIGHT2 = "#e8f8f5"
C_BORDER = "#bdc3c7"
C_TEXT = "#2c3e50"
C_TEXT_LIGHT = "#7f8c8d"
C_ARROW = "#566573"

def svg_header(w, h):
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif">
<rect width="{w}" height="{h}" fill="{C_BG}"/>'''

def box(x, y, w, h, text, fill=C_LIGHT, stroke=C_SECONDARY, text_color=C_TEXT, font_size=13, rx=6, bold=False):
    weight = "bold" if bold else "normal"
    lines = text.split("\n")
    line_h = font_size + 4
    total_h = len(lines) * line_h
    start_y = y + h/2 - total_h/2 + font_size
    tspan = ""
    for i, line in enumerate(lines):
        dy = 0 if i == 0 else line_h
        tspan += f'<tspan x="{x+w/2}" dy="{dy}">{line}</tspan>'
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/><text x="{x+w/2}" y="{start_y}" text-anchor="middle" fill="{text_color}" font-size="{font_size}" font-weight="{weight}">{tspan}</text>'

def arrow(x1, y1, x2, y2, label="", color=C_ARROW, dashed=False):
    dash = ' stroke-dasharray="5,3"' if dashed else ""
    marker = f'<marker id="arrow{abs(hash(label+str(x1)))%10000}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="{color}"/></marker>'
    line = f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="1.5"{dash} marker-end="url(#arrow{abs(hash(label+str(x1)))%10000})"/>'
    label_text = ""
    if label:
        mx, my = (x1+x2)/2, (y1+y2)/2
        label_text = f'<rect x="{mx-30}" y="{my-10}" width="60" height="18" rx="3" fill="{C_BG}" opacity="0.9"/><text x="{mx}" y="{my+3}" text-anchor="middle" fill="{color}" font-size="10">{label}</text>'
    return marker + line + label_text

def label(x, y, text, size=11, color=C_TEXT_LIGHT, anchor="middle"):
    return f'<text x="{x}" y="{y}" text-anchor="{anchor}" fill="{color}" font-size="{size}">{text}</text>'

def title(x, y, text, size=16):
    return f'<text x="{x}" y="{y}" text-anchor="middle" fill="{C_PRIMARY}" font-size="{size}" font-weight="bold">{text}</text>'

# ============================================================
# 1. System Architecture Overview
# ============================================================
def gen_system_architecture():
    w, h = 900, 620
    s = svg_header(w, h)
    s += title(w/2, 35, "Hindsight 系统架构总览")

    # Clients layer
    s += label(60, 75, "客户端层", 12, C_PRIMARY, "start")
    clients = [
        (60, 90, 150, 45, "Python SDK"),
        (230, 90, 150, 45, "Node.js SDK"),
        (400, 90, 150, 45, "Go SDK"),
        (570, 90, 150, 45, "CLI (Rust)"),
        (740, 90, 120, 45, "REST API"),
    ]
    for x, y, bw, bh, t in clients:
        s += box(x, y, bw, bh, t, C_LIGHT2, C_ACCENT, font_size=12)

    # API Server
    s += label(60, 170, "服务层", 12, C_PRIMARY, "start")
    s += box(60, 185, 780, 60, "FastAPI Server (api/http.py · 10436行)\n同步路径: retain / recall / reflect · MCP Endpoint · Admin API", C_LIGHT, C_SECONDARY, font_size=13, bold=True)

    # Memory Engine
    s += box(60, 270, 780, 70, "MemoryEngine (engine/memory_engine.py · 23543行)\n编排核心: retain_async / recall_async / reflect_async\nPer-operation LLM 配置 · OperationValidator · TenantExtension", "#fef9e7", C_WARN, font_size=13, bold=True)

    # Engine components
    s += label(60, 365, "引擎层", 12, C_PRIMARY, "start")
    engines = [
        (60, 380, 175, 55, "Retain Pipeline\nengine/retain/"),
        (250, 380, 175, 55, "Search/Recall\nengine/search/"),
        (440, 380, 175, 55, "Reflect Agent\nengine/reflect/"),
        (630, 380, 210, 55, "Consolidation\nengine/consolidation/"),
    ]
    for x, y, bw, bh, t in engines:
        s += box(x, y, bw, bh, t, C_LIGHT, C_SECONDARY, font_size=12)

    # External dependencies
    s += label(60, 460, "外部依赖", 12, C_PRIMARY, "start")
    deps = [
        (60, 475, 175, 55, "LLM Providers\n25+ (OpenAI/Anthropic/\nGemini/Groq/Ollama...)"),
        (250, 475, 175, 55, "Embeddings\n远程 / 本地 ONNX /\nsentence-transformers"),
        (440, 475, 175, 55, "Cross-Encoder\nflashrank / Google /\njina-mlx"),
        (630, 475, 210, 55, "PostgreSQL + pgvector\n(或 Oracle 23ai)\n嵌入式 pg0"),
    ]
    for x, y, bw, bh, t in deps:
        s += box(x, y, bw, bh, t, C_LIGHT2, C_ACCENT, font_size=11)

    # Worker
    s += box(60, 550, 380, 50, "Worker (worker/poller.py · 2166行)\nasync_operations 队列 · Consolidation · Mental Model 刷新", "#fdf2e9", C_WARN, font_size=12)
    s += box(460, 550, 380, 50, "Webhooks / Audit / Extensions\n生命周期事件通知 · 审计日志 · 多租户扩展", "#fdf2e9", C_WARN, font_size=12)

    # Arrows
    for cx in [135, 305, 475, 645, 800]:
        s += arrow(cx, 135, cx, 183)
    s += arrow(450, 245, 450, 268)
    s += arrow(450, 340, 450, 378)
    for cx in [147, 337, 527, 735]:
        s += arrow(cx, 435, cx, 473)
    s += arrow(250, 520, 250, 548, "", C_WARN)
    s += arrow(650, 520, 650, 548, "", C_WARN)

    s += "</svg>"
    return s

# ============================================================
# 2. Learning Loop (retain/recall/reflect/consolidation)
# ============================================================
def gen_learning_loop():
    w, h = 800, 520
    s = svg_header(w, h)
    s += title(w/2, 35, "Hindsight 学习闭环：Retain → Recall → Reflect → Consolidation")

    # Central circle concept
    cx, cy, r = 400, 280, 120
    s += f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{C_LIGHT}" stroke="{C_PRIMARY}" stroke-width="2"/>'
    s += f'<text x="{cx}" y="{cy-15}" text-anchor="middle" fill="{C_PRIMARY}" font-size="16" font-weight="bold">Memory Bank</text>'
    s += f'<text x="{cx}" y="{cy+10}" text-anchor="middle" fill="{C_TEXT}" font-size="12">隔离的记忆存储</text>'
    s += f'<text x="{cx}" y="{cy+30}" text-anchor="middle" fill="{C_TEXT_LIGHT}" font-size="11">world facts · experiences</text>'
    s += f'<text x="{cx}" y="{cy+48}" text-anchor="middle" fill="{C_TEXT_LIGHT}" font-size="11">observations · mental models</text>'

    # Four operations around the circle
    # Retain - top
    s += box(300, 70, 200, 55, "Retain 写入\n信息 → 事实 → 实体 → 链接 → 索引", C_LIGHT2, C_ACCENT, font_size=12, bold=True)
    s += arrow(400, 125, 400, 165, "写入")

    # Recall - right
    s += box(580, 240, 180, 55, "Recall 召回\n四臂并行 → RRF → Rerank", C_LIGHT, C_SECONDARY, font_size=12, bold=True)
    s += arrow(520, 280, 578, 280, "查询")

    # Reflect - bottom
    s += box(300, 410, 200, 55, "Reflect 思考\n多步 Agent · 证据 grounding", "#fef9e7", C_WARN, font_size=12, bold=True)
    s += arrow(400, 395, 400, 355, "推理", C_WARN)

    # Consolidation - left
    s += box(40, 240, 180, 55, "Consolidation 巩固\n事实 → 观察 → 心智模型", "#fdf2e9", "#c0392b", font_size=12, bold=True)
    s += arrow(220, 280, 282, 280, "学习", "#c0392b")

    # Cycle arrows
    s += arrow(500, 98, 590, 240, "", C_ARROW, True)
    s += arrow(590, 310, 500, 410, "", C_ARROW, True)
    s += arrow(300, 438, 210, 310, "", C_ARROW, True)
    s += arrow(210, 250, 300, 100, "", C_ARROW, True)

    # Annotations
    s += label(690, 180, "同步调用", 10, C_TEXT_LIGHT)
    s += label(690, 380, "同步调用", 10, C_TEXT_LIGHT)
    s += label(100, 180, "后台异步", 10, "#c0392b")
    s += label(100, 380, "后台异步", 10, "#c0392b")

    s += label(w/2, 500, "Retain 和 Recall 是同步路径；Consolidation 在后台 Worker 中运行；Reflect 是同步的多步推理", 11, C_TEXT_LIGHT)

    s += "</svg>"
    return s

# ============================================================
# 3. Retain Pipeline
# ============================================================
def gen_retain_pipeline():
    w, h = 960, 480
    s = svg_header(w, h)
    s += title(w/2, 35, "Retain 流水线：一条信息如何变成记忆")

    steps = [
        (30, 80, 130, 60, "HTTP 请求\nretain /\nretain_batch", C_LIGHT2, C_ACCENT),
        (185, 80, 130, 60, "文档切分\nchunking\nmarkitdown", C_LIGHT, C_SECONDARY),
        (340, 80, 130, 60, "事实抽取\nLLM\nfact_extraction", C_LIGHT, C_SECONDARY),
        (495, 80, 130, 60, "实体解析\nentity_resolver\n归一化", C_LIGHT, C_SECONDARY),
        (650, 80, 130, 60, "链接创建\nmemory_links\n7种link_type", C_LIGHT, C_SECONDARY),
        (805, 80, 130, 60, "嵌入+索引\nembedding\nBM25 vector", C_LIGHT2, C_ACCENT),
    ]
    for x, y, bw, bh, t, fill, stroke in steps:
        s += box(x, y, bw, bh, t, fill, stroke, font_size=11)
    for i in range(5):
        x1 = 30 + (i+1)*155
        s += arrow(x1, 110, x1+25, 110)

    # Detail boxes below each step
    details = [
        (30, 180, 130, 120, "输入:\n· content 文本\n· context 上下文\n· timestamp\n· metadata/tags\n· document_id", C_LIGHT, C_BORDER),
        (185, 180, 130, 120, "chunks 表:\n· chunk_id\n· document_id\n· chunk_index\n· chunk_text\n· content_hash", C_LIGHT, C_BORDER),
        (340, 180, 130, 120, "memory_units:\n· text\n· fact_type\n· event_date\n· occurred_start/end\n· confidence_score", C_LIGHT, C_BORDER),
        (495, 180, 130, 120, "entities 表:\n· canonical_name\n· mention_count\n· first/last_seen\nunit_entities:\n· 多对多关联", C_LIGHT, C_BORDER),
        (650, 180, 130, 120, "memory_links:\n· temporal\n· semantic · entity\n· causes/caused_by\n· enables/prevents", C_LIGHT, C_BORDER),
        (805, 180, 130, 120, "memory_units:\n· embedding(384)\n· search_vector\n· pgvector 索引\n· BM25 索引\n(5种后端)", C_LIGHT, C_BORDER),
    ]
    for x, y, bw, bh, t, fill, stroke in details:
        s += box(x, y, bw, bh, t, fill, stroke, font_size=10)

    # Exception paths
    s += label(30, 340, "异常路径与保障", 13, C_WARN, "start")
    exceptions = [
        (30, 355, 280, 90, "并发控制\n· retain_same_document_concurrency\n· 同一 document 的并发 retain 串行化\n· entity_prune_race 防护", "#fdf2e9", C_WARN),
        (330, 355, 280, 90, "预算控制\n· memory_budget.py\n· fact_budget_selection\n· 超限时选择最重要的事实\n· sub_batch 处理", "#fdf2e9", C_WARN),
        (630, 355, 300, 90, "失败恢复\n· LLM 失败时 json-repair 兜底\n· embedding_coalescer 合并嵌入请求\n· consolidation_failed_at 标记\n· Worker 重试 (async_operations)", "#fdf2e9", C_WARN),
    ]
    for x, y, bw, bh, t, fill, stroke in exceptions:
        s += box(x, y, bw, bh, t, fill, stroke, font_size=11)

    s += label(w/2, 470, "核心编排: engine/retain/orchestrator.py (4491行) · 事实抽取: fact_extraction.py (3627行)", 11, C_TEXT_LIGHT)

    s += "</svg>"
    return s

# ============================================================
# 4. Recall Four-Arm Fusion
# ============================================================
def gen_recall_fusion():
    w, h = 900, 560
    s = svg_header(w, h)
    s += title(w/2, 35, "Recall 检索链路：四臂并行 → RRF 融合 → Cross-Encoder 重排序")

    # Query input
    s += box(350, 65, 200, 45, "查询 Query\nbank_id + query_text", C_LIGHT2, C_ACCENT, font_size=13, bold=True)

    # Query analysis
    s += box(350, 130, 200, 40, "Query Analyzer\n时间表达式解析 (dateparser)", C_LIGHT, C_SECONDARY, font_size=11)
    s += arrow(450, 110, 450, 128)

    # Four arms
    arms = [
        (40, 210, 180, 80, "Semantic 语义臂\n· pgvector 余弦距离\n· embedding(384维)\n· <=> 向量距离算子", C_LIGHT, C_SECONDARY),
        (250, 210, 180, 80, "Keyword 关键词臂\n· BM25 精确匹配\n· 5种后端实现\n· bm25_term_selection", C_LIGHT, C_SECONDARY),
        (460, 210, 180, 80, "Graph 图谱臂\n· entity/temporal/causal\n· graph_retrieval.py\n· link_expansion", C_LIGHT, C_SECONDARY),
        (670, 210, 180, 80, "Temporal 时间臂\n· occurred_start/end\n· 时间范围过滤\n· temporal_extraction", C_LIGHT, C_SECONDARY),
    ]
    for x, y, bw, bh, t, fill, stroke in arms:
        s += box(x, y, bw, bh, t, fill, stroke, font_size=11)

    # Arrows from query analyzer to arms
    s += arrow(380, 170, 130, 208, "", C_ARROW, True)
    s += arrow(420, 170, 340, 208, "", C_ARROW, True)
    s += arrow(480, 170, 550, 208, "", C_ARROW, True)
    s += arrow(520, 170, 760, 208, "", C_ARROW, True)

    # RRF Fusion
    s += box(250, 330, 400, 50, "Reciprocal Rank Fusion (RRF)\nscore = Σ 1/(k + rank)  融合四臂结果，去重排序", "#fef9e7", C_WARN, font_size=12, bold=True)
    for cx in [130, 340, 550, 760]:
        s += arrow(cx, 290, 450, 328, "", C_ARROW)

    # Reranking
    s += box(250, 410, 400, 50, "Cross-Encoder 重排序\n精确语义匹配 · flashrank/Google/jina-mlx · reranking.py", C_LIGHT2, C_ACCENT, font_size=12, bold=True)
    s += arrow(450, 380, 450, 408)

    # Budget trim
    s += box(250, 485, 400, 45, "Token Budget 裁剪\n按 recall_budget 截断 · fact_type 优先级 · recall_boost", C_LIGHT, C_SECONDARY, font_size=12)
    s += arrow(450, 460, 450, 483)

    # Output
    s += box(700, 410, 160, 120, "召回结果\n· memory_units 列表\n· 相关度分数\n· 实体/链接信息\n· 来源证据", "#e8f8f5", C_ACCENT, font_size=11)
    s += arrow(650, 507, 700, 470, "最终结果")

    s += label(w/2, 550, "入口: recall_async (memory_engine.py:8223) · 核心: engine/search/retrieval.py (940行)", 11, C_TEXT_LIGHT)

    s += "</svg>"
    return s

# ============================================================
# 5. Data Model ER Diagram
# ============================================================
def gen_data_model():
    w, h = 850, 600
    s = svg_header(w, h)
    s += title(w/2, 30, "Hindsight 核心数据模型 (PostgreSQL + pgvector)")

    # banks
    s += box(330, 55, 190, 70, "banks\n┌─────────────────────┐\n│ bank_id (PK)        │\n│ disposition (JSON)  │\n│ mission/personality │\n│ config (JSON)       │\n└─────────────────────┘", "#fef9e7", C_WARN, font_size=10)

    # documents
    s += box(50, 170, 180, 80, "documents\n┌─────────────────────┐\n│ id (PK)             │\n│ bank_id (FK)        │\n│ original_text (CLOB)│\n│ content_hash        │\n│ metadata/tags       │\n└─────────────────────┘", C_LIGHT, C_SECONDARY, font_size=10)

    # chunks
    s += box(260, 170, 160, 70, "chunks\n┌──────────────────┐\n│ chunk_id (PK)    │\n│ document_id (FK) │\n│ chunk_index      │\n│ chunk_text       │\n└──────────────────┘", C_LIGHT, C_SECONDARY, font_size=10)

    # memory_units - central
    s += box(450, 160, 220, 130, "memory_units (核心)\n┌──────────────────────────┐\n│ id (PK) RAW(16)          │\n│ bank_id (FK) 分区键      │\n│ document_id / chunk_id   │\n│ text (CLOB)              │\n│ embedding VECTOR(384)    │\n│ event_date / occurred_*  │\n│ fact_type: world/        │\n│   experience/observation │\n│ confidence / proof_count │\n│ source_memory_ids        │\n│ search_vector (BM25)     │\n│ history (JSON)           │\n└──────────────────────────┘", "#eaf2f8", C_PRIMARY, font_size=9, bold=True)

    # entities
    s += box(700, 170, 130, 70, "entities\n┌────────────────┐\n│ id (PK)        │\n│ bank_id (FK)   │\n│ canonical_name │\n│ mention_count  │\n└────────────────┘", C_LIGHT2, C_ACCENT, font_size=10)

    # unit_entities
    s += box(700, 270, 130, 55, "unit_entities\n┌──────────────┐\n│ unit_id (FK) │\n│ entity_id(FK)│\n└──────────────┘", C_LIGHT2, C_ACCENT, font_size=10)

    # memory_links
    s += box(450, 320, 220, 80, "memory_links\n┌──────────────────────────┐\n│ from_unit_id (FK)        │\n│ to_unit_id (FK)          │\n│ link_type: temporal/     │\n│   semantic/entity/       │\n│   causes/caused_by/      │\n│   enables/prevents       │\n│ entity_id / weight       │\n└──────────────────────────┘", C_LIGHT, C_SECONDARY, font_size=9)

    # mental_models
    s += box(50, 320, 180, 90, "mental_models\n┌─────────────────────┐\n│ id (PK)             │\n│ bank_id (FK)        │\n│ subtype: directive/ │\n│   pinned            │\n│ name / description  │\n│ source_query        │\n│ content / embedding │\n│ observations (JSON) │\n│ trigger (JSON)      │\n│ max_tokens          │\n└─────────────────────┘", C_LIGHT2, C_ACCENT, font_size=9)

    # invalidated
    s += box(260, 320, 160, 80, "invalidated_\nmemory_units\n┌──────────────────┐\n│ (memory_units    │\n│  完整副本)       │\n│ invalidation_    │\n│   reason         │\n│ invalidated_at   │\n│ entity_ids       │\n│ (无 embedding)   │\n└──────────────────┘", "#fdf2e9", C_WARN, font_size=9)

    # async_operations
    s += box(50, 450, 180, 70, "async_operations\n┌─────────────────────┐\n│ operation_id (PK)   │\n│ bank_id (FK)        │\n│ operation_type      │\n│ status: pending/    │\n│   processing/       │\n│   completed/failed  │\n│ worker_id / retry   │\n└─────────────────────┘", C_LIGHT, C_SECONDARY, font_size=9)

    # webhooks
    s += box(260, 450, 160, 60, "webhooks\n┌──────────────────┐\n│ id / bank_id     │\n│ url / secret     │\n│ event_types      │\n│ enabled          │\n└──────────────────┘", C_LIGHT, C_SECONDARY, font_size=10)

    # audit_log
    s += box(450, 450, 220, 60, "audit_log\n┌──────────────────────────┐\n│ id / action / transport  │\n│ bank_id / started_at     │\n│ request / response (JSON)│\n└──────────────────────────┘", C_LIGHT, C_SECONDARY, font_size=10)

    # directives
    s += box(700, 350, 130, 65, "directives\n┌────────────────┐\n│ id / bank_id   │\n│ name / content │\n│ priority       │\n│ is_active      │\n└────────────────┘", C_LIGHT2, C_ACCENT, font_size=10)

    # Relationships
    s += arrow(425, 90, 140, 168, "1:N", C_ARROW)
    s += arrow(425, 90, 340, 168, "1:N", C_ARROW)
    s += arrow(425, 90, 560, 158, "1:N", C_ARROW)
    s += arrow(425, 90, 765, 168, "1:N", C_ARROW)
    s += arrow(230, 210, 260, 210, "1:N", C_ARROW)
    s += arrow(420, 210, 450, 210, "1:N", C_ARROW)
    s += arrow(420, 225, 450, 360, "", C_ARROW)
    s += arrow(670, 225, 700, 295, "N:M", C_ACCENT)
    s += arrow(560, 290, 560, 318, "1:N", C_ARROW)
    s += arrow(425, 90, 140, 318, "1:N", C_ARROW, True)
    s += arrow(425, 90, 765, 380, "1:N", C_ARROW, True)
    s += arrow(425, 90, 140, 448, "1:N", C_ARROW, True)
    s += arrow(425, 90, 340, 448, "1:N", C_ARROW, True)
    s += arrow(425, 90, 560, 448, "1:N", C_ARROW, True)

    s += label(w/2, 550, "memory_units 按 bank_id 自动列表分区 (PARTITION BY LIST AUTOMATIC) · 向量维度 384 · 同时支持 Oracle 23ai", 11, C_TEXT_LIGHT)
    s += label(w/2, 575, "observation_sources 表记录 observation 的证据链 (observation_id, source_id)", 10, C_TEXT_LIGHT)

    s += "</svg>"
    return s

# ============================================================
# 6. Reflect Agent Loop
# ============================================================
def gen_reflect_loop():
    w, h = 850, 520
    s = svg_header(w, h)
    s += title(w/2, 35, "Reflect 链路：多步推理 Agent（engine/reflect/agent.py · 2155行）")

    # Input
    s += box(320, 60, 210, 45, "Reflect 请求\nbank_id + query + disposition", C_LIGHT2, C_ACCENT, font_size=12, bold=True)

    # Agent loop box
    s += f'<rect x="80" y="130" width="690" height="300" rx="10" fill="{C_LIGHT}" stroke="{C_PRIMARY}" stroke-width="1.5" stroke-dasharray="8,4"/>'
    s += label(100, 155, "Reflect Agent 循环", 13, C_PRIMARY, "start")

    # Step 1: Recall
    s += box(110, 175, 160, 60, "1. Recall 召回\n调用 recall 工具\n获取相关记忆", C_LIGHT, C_SECONDARY, font_size=11)

    # Step 2: Reason
    s += box(310, 175, 160, 60, "2. LLM 推理\n分析召回内容\n形成初步判断", C_LIGHT, C_SECONDARY, font_size=11)

    # Step 3: Tool call
    s += box(510, 175, 160, 60, "3. 工具调用\nsearch_observations\nget_mental_model", C_LIGHT, C_SECONDARY, font_size=11)

    # Step 4: Evidence check
    s += box(310, 270, 160, 60, "4. 证据 Grounding\n每个结论必须\n引用 source_memory", "#fef9e7", C_WARN, font_size=11)

    # Step 5: Continue or finish
    s += box(510, 270, 160, 60, "5. 判断是否继续\n需要更多信息?\n→ 回到步骤1", C_LIGHT, C_SECONDARY, font_size=11)

    # Disposition influence
    s += box(110, 270, 160, 60, "Disposition 影响\nskepticism /\nliteralism / empathy", "#fdf2e9", "#c0392b", font_size=11)

    # Arrows within loop
    s += arrow(270, 205, 310, 205)
    s += arrow(470, 205, 510, 205)
    s += arrow(590, 235, 590, 268)
    s += arrow(510, 300, 470, 300)
    s += arrow(310, 300, 270, 300, "", C_ARROW)
    s += arrow(190, 270, 190, 235, "", "#c0392b")
    # Loop back
    s += arrow(190, 330, 190, 370, "", C_ARROW, True)
    s += arrow(190, 370, 590, 370, "", C_ARROW, True)
    s += arrow(590, 370, 590, 330, "", C_ARROW, True)
    s += label(400, 385, "循环直到满足停止条件（达到 max_steps 或判断信息充分）", 10, C_TEXT_LIGHT)

    # Output
    s += box(320, 455, 210, 45, "结构化输出\nreflect_response (JSON)\n可写入 mental_model", C_LIGHT2, C_ACCENT, font_size=12, bold=True)
    s += arrow(425, 430, 425, 453)
    s += arrow(425, 105, 425, 128)

    # Tools list
    s += label(730, 175, "Reflect 可用工具:", 11, C_PRIMARY, "start")
    tools = ["· recall (记忆召回)", "· search_observations", "· get_mental_model", "· list_directives", "· entity_lookup", "· temporal_query"]
    for i, t in enumerate(tools):
        s += label(730, 195 + i*18, t, 10, C_TEXT)

    s += "</svg>"
    return s

# ============================================================
# 7. Consolidation Flow
# ============================================================
def gen_consolidation():
    w, h = 900, 500
    s = svg_header(w, h)
    s += title(w/2, 35, "Consolidation 后台链路：记忆如何学习和进化")

    # Trigger
    s += box(50, 70, 180, 50, "触发条件\n· retain 后标记\n· 定时调度\n· mental_model trigger", C_LIGHT2, C_ACCENT, font_size=11)

    # Worker picks up
    s += box(270, 70, 180, 50, "Worker 轮询\nasync_operations\nstatus=pending", C_LIGHT, C_SECONDARY, font_size=11)
    s += arrow(230, 95, 270, 95)

    # Consolidator
    s += box(490, 60, 200, 70, "Consolidator\nengine/consolidation/\nconsolidator.py (3763行)", "#fef9e7", C_WARN, font_size=12, bold=True)
    s += arrow(450, 95, 490, 95)

    # Steps inside consolidator
    steps = [
        (50, 180, 180, 80, "1. 选择未巩固事实\nconsolidated_at IS NULL\n按 bank 分组\nscope 并行控制", C_LIGHT, C_SECONDARY),
        (270, 180, 180, 80, "2. LLM 归纳\nconsolidation/prompts.py\n从多条事实生成\nobservation 候选", C_LIGHT, C_SECONDARY),
        (490, 180, 180, 80, "3. 去重与合并\nconsolidation_dedup\n匹配已有 observation\nproof_count++", C_LIGHT, C_SECONDARY),
        (710, 180, 160, 80, "4. 写入观察\nfact_type=observation\n保留 source_memory_ids\n证据链完整", C_LIGHT2, C_ACCENT),
    ]
    for x, y, bw, bh, t, fill, stroke in steps:
        s += box(x, y, bw, bh, t, fill, stroke, font_size=10)
    for i in range(3):
        s += arrow(230+i*220, 220, 270+i*220, 220)

    # Downstream
    s += label(50, 300, "下游影响", 13, C_PRIMARY, "start")

    downstream = [
        (50, 315, 250, 80, "Mental Model 刷新\n· trigger.refresh_after_consolidation\n· 定时 cron (croniter)\n· 写入 mental_models.content\n· history 保留版本", C_LIGHT, C_SECONDARY),
        (330, 315, 250, 80, "Webhook 通知\n· retain / consolidation / refresh\n· 生命周期事件\n· webhooks 表配置\n· 签名验证 (secret)", C_LIGHT, C_SECONDARY),
        (610, 315, 260, 80, "可观测性\n· audit_log 记录\n· Prometheus metrics\n· operation progress\n· consolidation_failed_at", C_LIGHT, C_SECONDARY),
    ]
    for x, y, bw, bh, t, fill, stroke in downstream:
        s += box(x, y, bw, bh, t, fill, stroke, font_size=10)

    # Evidence chain explanation
    s += box(50, 425, 820, 55, "Observation 证据链: observation (memory_units row, fact_type='observation') ← observation_sources (observation_id, source_id) ← source memory_units\n新证据到达时: proof_count++ · 强化/弱化/扩展现有信念 · 不静默覆盖 (refine rather than overwrite)", "#eaf2f8", C_PRIMARY, font_size=11)

    s += label(w/2, 495, "关键设计: retain 只负责写入原始记忆，学习（归纳/巩固/刷新）全部发生在后台 consolidation 路径", 11, C_TEXT_LIGHT)

    s += "</svg>"
    return s


# Generate all diagrams
diagrams = {
    "01_system_architecture": gen_system_architecture,
    "02_learning_loop": gen_learning_loop,
    "03_retain_pipeline": gen_retain_pipeline,
    "04_recall_fusion": gen_recall_fusion,
    "05_data_model": gen_data_model,
    "06_reflect_loop": gen_reflect_loop,
    "07_consolidation_flow": gen_consolidation,
}

for name, gen_fn in diagrams.items():
    svg_content = gen_fn()
    svg_path = os.path.join(OUT_DIR, f"{name}.svg")
    png_path = os.path.join(OUT_DIR, f"{name}.png")
    with open(svg_path, "w", encoding="utf-8") as f:
        f.write(svg_content)
    cairosvg.svg2png(bytestring=svg_content.encode("utf-8"), write_to=png_path, output_width=1800)
    print(f"Generated: {name}.png ({os.path.getsize(png_path)} bytes)")

print("\nAll diagrams generated successfully!")
