#!/usr/bin/env python3
"""Generate Hindsight technical diagrams using matplotlib (PNG output)."""

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import os

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

# Try Chinese fonts
plt.rcParams['font.sans-serif'] = ['PingFang SC', 'Heiti SC', 'Arial Unicode MS', 'STHeiti', 'SimHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

# Colors
C_PRIMARY = '#1a5276'
C_SECONDARY = '#2980b9'
C_ACCENT = '#16a085'
C_WARN = '#d35400'
C_DANGER = '#c0392b'
C_LIGHT = '#ebf5fb'
C_LIGHT2 = '#e8f8f5'
C_LIGHT3 = '#fef9e7'
C_LIGHT4 = '#fdf2e9'
C_LIGHT5 = '#eaf2f8'
C_BORDER = '#bdc3c7'
C_TEXT = '#2c3e50'
C_ARROW = '#566573'

def new_fig(w, h, title):
    fig, ax = plt.subplots(1, 1, figsize=(w, h), dpi=150)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis('off')
    ax.set_title(title, fontsize=16, fontweight='bold', color=C_PRIMARY, pad=15, loc='center')
    return fig, ax

def draw_box(ax, x, y, w, h, text, fill=C_LIGHT, border=C_SECONDARY, fontsize=9, bold=False, text_color=C_TEXT):
    """Draw a rounded rectangle with centered text. x,y is bottom-left in axes coords (0-100)."""
    box = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.3", 
                         facecolor=fill, edgecolor=border, linewidth=1.5)
    ax.add_patch(box)
    weight = 'bold' if bold else 'normal'
    ax.text(x + w/2, y + h/2, text, ha='center', va='center', fontsize=fontsize,
            color=text_color, fontweight=weight, wrap=True)

def draw_arrow(ax, x1, y1, x2, y2, color=C_ARROW, dashed=False, label='', fontsize=8):
    style = '--' if dashed else '-'
    ax.annotate('', xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle='->', color=color, lw=1.5, linestyle=style))
    if label:
        mx, my = (x1+x2)/2, (y1+y2)/2
        ax.text(mx, my, label, ha='center', va='center', fontsize=fontsize, 
                color=color, bbox=dict(boxstyle='round,pad=0.2', facecolor='white', edgecolor='none', alpha=0.9))

def draw_label(ax, x, y, text, fontsize=9, color=C_TEXT, ha='center'):
    ax.text(x, y, text, fontsize=fontsize, color=color, ha=ha, va='center')

def save(fig, name):
    path = os.path.join(OUT_DIR, f"{name}.png")
    fig.savefig(path, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    print(f"  Generated: {name}.png ({os.path.getsize(path)} bytes)")

# ============================================================
# 1. System Architecture
# ============================================================
def gen_system_architecture():
    fig, ax = new_fig(14, 9, "Hindsight 系统架构总览")
    
    # Clients
    draw_label(ax, 3, 93, "客户端层", 10, C_PRIMARY, 'left')
    clients = [("Python SDK",5), ("Node.js SDK",22), ("Go SDK",39), ("CLI (Rust)",56), ("REST API",73)]
    for name, x in clients:
        draw_box(ax, x, 86, 14, 6, name, C_LIGHT2, C_ACCENT, 9)
    
    # API Server
    draw_label(ax, 3, 80, "服务层", 10, C_PRIMARY, 'left')
    draw_box(ax, 5, 71, 90, 7, "FastAPI Server (api/http.py · 10436行)\n同步路径: retain / recall / reflect · MCP Endpoint · Admin API", 
             C_LIGHT, C_SECONDARY, 9, True)
    
    # Memory Engine
    draw_box(ax, 5, 60, 90, 8, "MemoryEngine (engine/memory_engine.py · 23543行)\n编排核心: retain_async / recall_async / reflect_async · Per-operation LLM 配置 · 扩展点", 
             C_LIGHT3, C_WARN, 9, True)
    
    # Engine layer
    draw_label(ax, 3, 55, "引擎层", 10, C_PRIMARY, 'left')
    engines = [("Retain Pipeline\nengine/retain/", 5), ("Search/Recall\nengine/search/", 28), 
               ("Reflect Agent\nengine/reflect/", 51), ("Consolidation\nengine/consolidation/", 74)]
    for name, x in engines:
        draw_box(ax, x, 46, 21, 7, name, C_LIGHT, C_SECONDARY, 8)
    
    # External deps
    draw_label(ax, 3, 41, "外部依赖", 10, C_PRIMARY, 'left')
    deps = [("LLM Providers\n25+ 提供商", 5), ("Embeddings\n远程/本地ONNX", 28), 
            ("Cross-Encoder\nflashrank/Google", 51), ("PostgreSQL+pgvector\n或 Oracle 23ai", 74)]
    for name, x in deps:
        draw_box(ax, x, 32, 21, 7, name, C_LIGHT2, C_ACCENT, 8)
    
    # Worker + extensions
    draw_box(ax, 5, 20, 43, 7, "Worker (worker/poller.py · 2166行)\nasync_operations 队列 · Consolidation · Mental Model 刷新", 
             C_LIGHT4, C_WARN, 8)
    draw_box(ax, 52, 20, 43, 7, "Webhooks / Audit / Extensions\n生命周期事件 · 审计日志 · 多租户/存储扩展", 
             C_LIGHT4, C_WARN, 8)
    
    # Arrows
    for x in [12, 29, 46, 63, 80]:
        draw_arrow(ax, x, 86, x, 78)
    draw_arrow(ax, 50, 71, 50, 68)
    draw_arrow(ax, 50, 60, 50, 53)
    for x in [15, 38, 61, 84]:
        draw_arrow(ax, x, 46, x, 39)
    draw_arrow(ax, 26, 32, 26, 27, C_WARN)
    draw_arrow(ax, 74, 32, 74, 27, C_WARN)
    
    draw_label(ax, 50, 12, "版本 0.10.1 · MIT License · 向量维度 384 · 生产 HTTP 强制 aiohttp 异步", 8, C_ARROW)
    
    save(fig, "01_system_architecture")

# ============================================================
# 2. Learning Loop
# ============================================================
def gen_learning_loop():
    fig, ax = new_fig(12, 8, "Hindsight 学习闭环：Retain → Recall → Reflect → Consolidation")
    
    # Central bank
    draw_box(ax, 38, 42, 24, 16, "Memory Bank\n(隔离的记忆存储)\nworld facts · experiences\nobservations · mental models", 
             C_LIGHT5, C_PRIMARY, 9, True)
    
    # Retain (top)
    draw_box(ax, 35, 78, 30, 8, "Retain 写入\n信息→事实→实体→链接→索引", C_LIGHT2, C_ACCENT, 9, True)
    draw_arrow(ax, 50, 78, 50, 58, label="写入")
    
    # Recall (right)
    draw_box(ax, 70, 46, 25, 8, "Recall 召回\n四臂并行→RRF→Rerank", C_LIGHT, C_SECONDARY, 9, True)
    draw_arrow(ax, 62, 50, 70, 50, label="查询")
    
    # Reflect (bottom)
    draw_box(ax, 35, 18, 30, 8, "Reflect 思考\n多步Agent·证据grounding", C_LIGHT3, C_WARN, 9, True)
    draw_arrow(ax, 50, 42, 50, 26, label="推理", color=C_WARN)
    
    # Consolidation (left)
    draw_box(ax, 5, 46, 25, 8, "Consolidation 巩固\n事实→观察→心智模型", C_LIGHT4, C_DANGER, 9, True)
    draw_arrow(ax, 30, 50, 38, 50, label="学习", color=C_DANGER)
    
    # Cycle arrows
    draw_arrow(ax, 65, 78, 82, 54, dashed=True)
    draw_arrow(ax, 82, 46, 65, 26, dashed=True)
    draw_arrow(ax, 35, 22, 18, 46, dashed=True)
    draw_arrow(ax, 18, 54, 35, 78, dashed=True)
    
    draw_label(ax, 88, 68, "同步调用", 7, C_ARROW)
    draw_label(ax, 88, 32, "同步调用", 7, C_ARROW)
    draw_label(ax, 12, 68, "后台异步", 7, C_DANGER)
    draw_label(ax, 12, 32, "后台异步", 7, C_DANGER)
    
    draw_label(ax, 50, 8, "Retain 和 Recall 是同步路径；Consolidation 在后台 Worker 运行；Reflect 是同步多步推理", 8, C_ARROW)
    
    save(fig, "02_learning_loop")

# ============================================================
# 3. Retain Pipeline
# ============================================================
def gen_retain_pipeline():
    fig, ax = new_fig(15, 8, "Retain 流水线：一条信息如何变成记忆")
    
    steps = [
        ("HTTP请求\nretain/retain_batch", 2, C_LIGHT2, C_ACCENT),
        ("文档切分\nchunking", 16, C_LIGHT, C_SECONDARY),
        ("事实抽取\nLLM", 30, C_LIGHT, C_SECONDARY),
        ("实体解析\nentity_resolver", 44, C_LIGHT, C_SECONDARY),
        ("链接创建\n7种link_type", 58, C_LIGHT, C_SECONDARY),
        ("嵌入+索引\nembedding/BM25", 72, C_LIGHT2, C_ACCENT),
        ("写入\nmemory_units", 86, C_LIGHT5, C_PRIMARY),
    ]
    for name, x, fill, border in steps:
        draw_box(ax, x, 72, 12, 10, name, fill, border, 8)
    for i in range(6):
        draw_arrow(ax, 14+i*14, 77, 16+i*14, 77)
    
    # Detail row
    details = [
        ("输入:\ncontent/context\ntimestamp/metadata", 2),
        ("chunks表:\nchunk_id/chunk_index\nchunk_text/hash", 16),
        ("memory_units:\ntext/fact_type\nevent_date/confidence", 30),
        ("entities表:\ncanonical_name\nmention_count", 44),
        ("memory_links:\ntemporal/semantic\nentity/causal", 58),
        ("memory_units:\nembedding(384)\nsearch_vector", 72),
        ("同时写入:\nentities/unit_entities\nmemory_links", 86),
    ]
    for name, x in details:
        draw_box(ax, x, 55, 12, 12, name, C_LIGHT, C_BORDER, 7)
    
    # Exception paths
    draw_label(ax, 3, 48, "异常路径与保障", 10, C_WARN, 'left')
    exceptions = [
        ("并发控制\n同文档SELECT FOR UPDATE\nentity_prune_race防护", 2),
        ("预算控制\nmemory_budget.py\n按字节预算限流", 34),
        ("失败恢复\njson-repair兜底\nembedding_coalescer\nWorker重试", 66),
    ]
    for name, x in exceptions:
        draw_box(ax, x, 33, 30, 12, name, C_LIGHT4, C_WARN, 8)
    
    draw_label(ax, 50, 25, "核心编排: engine/retain/orchestrator.py (4491行) · 事实抽取: fact_extraction.py (3627行)", 8, C_ARROW)
    draw_label(ax, 50, 20, "设计取舍: 贵操作(LLM/trigram/ANN)推到事务外/提交后; 检索依赖写(fact/边)压进一个事务", 8, C_PRIMARY)
    
    save(fig, "03_retain_pipeline")

# ============================================================
# 4. Recall Fusion
# ============================================================
def gen_recall_fusion():
    fig, ax = new_fig(13, 9, "Recall 检索链路：四臂并行 → RRF 融合 → Cross-Encoder 重排序")
    
    # Input
    draw_box(ax, 37, 86, 26, 7, "查询 Query\nbank_id + query_text", C_LIGHT2, C_ACCENT, 9, True)
    
    # Query analyzer
    draw_box(ax, 37, 76, 26, 6, "Query Analyzer\n时间表达式解析 (dateparser)", C_LIGHT, C_SECONDARY, 8)
    draw_arrow(ax, 50, 86, 50, 82)
    
    # Four arms
    arms = [
        ("Semantic 语义臂\npgvector余弦距离\nembedding(384维)", 3),
        ("Keyword 关键词臂\nBM25精确匹配\n5种后端实现", 27),
        ("Graph 图谱臂\nentity/temporal/causal\ngraph_retrieval", 51),
        ("Temporal 时间臂\noccurred_start/end\n时间范围过滤", 75),
    ]
    for name, x in arms:
        draw_box(ax, x, 58, 22, 12, name, C_LIGHT, C_SECONDARY, 8)
    
    # Arrows to arms
    for x in [14, 38, 62, 86]:
        draw_arrow(ax, 50, 76, x, 70, dashed=True)
    
    # RRF
    draw_box(ax, 25, 44, 50, 7, "Reciprocal Rank Fusion (RRF)\nscore = Σ 1/(k + rank) · 融合四臂结果，去重排序", 
             C_LIGHT3, C_WARN, 9, True)
    for x in [14, 38, 62, 86]:
        draw_arrow(ax, x, 58, 50, 51)
    
    # Rerank
    draw_box(ax, 25, 33, 50, 7, "Cross-Encoder 重排序\n精确语义匹配 · flashrank/Google/jina-mlx", C_LIGHT2, C_ACCENT, 9, True)
    draw_arrow(ax, 50, 44, 50, 40)
    
    # Budget
    draw_box(ax, 25, 22, 50, 6, "Token Budget 裁剪\n按 recall_budget 截断 · fact_type 优先级", C_LIGHT, C_SECONDARY, 8)
    draw_arrow(ax, 50, 33, 50, 28)
    
    # Output
    draw_box(ax, 78, 28, 18, 12, "召回结果\nmemory_units列表\n相关度分数\n实体/链接\n来源证据", C_LIGHT2, C_ACCENT, 8)
    draw_arrow(ax, 75, 25, 78, 34, label="最终结果")
    
    draw_label(ax, 50, 14, "入口: recall_async (memory_engine.py:8223) · 核心: engine/search/retrieval.py (940行)", 8, C_ARROW)
    
    save(fig, "04_recall_fusion")

# ============================================================
# 5. Data Model
# ============================================================
def gen_data_model():
    fig, ax = new_fig(14, 10, "Hindsight 核心数据模型 (PostgreSQL + pgvector)")
    
    # banks (top center)
    draw_box(ax, 38, 88, 24, 8, "banks\nbank_id(PK) · disposition(JSON)\nmission · personality · config", C_LIGHT3, C_WARN, 8, True)
    
    # Row 1
    draw_box(ax, 3, 72, 20, 10, "documents\nid(PK) · bank_id(FK)\noriginal_text · content_hash\nmetadata · tags", C_LIGHT, C_SECONDARY, 7)
    draw_box(ax, 27, 74, 17, 8, "chunks\nchunk_id(PK)\ndocument_id(FK)\nchunk_index · chunk_text", C_LIGHT, C_SECONDARY, 7)
    draw_box(ax, 48, 70, 26, 14, "memory_units (核心)\nid(PK) · bank_id(分区键)\nembedding VECTOR(384)\nfact_type: world/experience/\n  observation\nconfidence · proof_count\nsource_memory_ids · history\nsearch_vector(BM25)", C_LIGHT5, C_PRIMARY, 7, True)
    draw_box(ax, 78, 74, 18, 8, "entities\nid(PK) · bank_id(FK)\ncanonical_name\nmention_count", C_LIGHT2, C_ACCENT, 7)
    
    # Row 2
    draw_box(ax, 3, 54, 20, 12, "mental_models\nid(PK) · bank_id(FK)\nsubtype: directive/pinned\nname · source_query\ncontent · embedding\nobservations(JSON)\ntrigger(JSON) · max_tokens", C_LIGHT2, C_ACCENT, 7)
    draw_box(ax, 27, 56, 17, 10, "invalidated_\nmemory_units\n(完整副本+)\ninvalidation_reason\ninvalidated_at\nentity_ids\n(无embedding)", C_LIGHT4, C_WARN, 7)
    draw_box(ax, 48, 54, 26, 12, "memory_links\nfrom_unit_id · to_unit_id\nlink_type: temporal/\nsemantic/entity/causes/\ncaused_by/enables/prevents\nentity_id · weight", C_LIGHT, C_SECONDARY, 7)
    draw_box(ax, 78, 60, 18, 6, "unit_entities\nunit_id(FK)\nentity_id(FK) N:M", C_LIGHT2, C_ACCENT, 7)
    
    # Row 3
    draw_box(ax, 3, 36, 20, 10, "async_operations\noperation_id(PK)\noperation_type · status\npending/processing/\ncompleted/failed\nworker_id · retry_count", C_LIGHT, C_SECONDARY, 7)
    draw_box(ax, 27, 38, 17, 8, "webhooks\nid · bank_id\nurl · secret\nevent_types\nenabled", C_LIGHT, C_SECONDARY, 7)
    draw_box(ax, 48, 38, 26, 8, "audit_log\nid · action · transport\nbank_id · started_at\nrequest/response(JSON)", C_LIGHT, C_SECONDARY, 7)
    draw_box(ax, 78, 44, 18, 8, "directives\nid · bank_id\nname · content\npriority · is_active", C_LIGHT2, C_ACCENT, 7)
    
    # observation_sources
    draw_box(ax, 48, 24, 26, 7, "observation_sources\nobservation_id(FK) · source_id(FK)\n(Observation 的证据链)", C_LIGHT5, C_PRIMARY, 7)
    
    # Relationships (simplified)
    draw_arrow(ax, 50, 88, 13, 82, dashed=True)
    draw_arrow(ax, 50, 88, 35, 82, dashed=True)
    draw_arrow(ax, 50, 88, 61, 84, dashed=True)
    draw_arrow(ax, 50, 88, 87, 82, dashed=True)
    draw_arrow(ax, 23, 77, 27, 78)
    draw_arrow(ax, 44, 77, 48, 77)
    draw_arrow(ax, 74, 77, 78, 77)
    draw_arrow(ax, 61, 70, 61, 66)
    draw_arrow(ax, 87, 74, 87, 66)
    draw_arrow(ax, 50, 88, 13, 66, dashed=True)
    draw_arrow(ax, 50, 88, 87, 52, dashed=True)
    
    draw_label(ax, 50, 16, "memory_units 按 bank_id 自动列表分区 · 向量维度384 · 同时支持 Oracle 23ai (功能对等)", 8, C_ARROW)
    draw_label(ax, 50, 11, "fact_type CHECK约束: world/experience/observation · link_type CHECK约束: 7种类型", 8, C_ARROW)
    
    save(fig, "05_data_model")

# ============================================================
# 6. Reflect Loop
# ============================================================
def gen_reflect_loop():
    fig, ax = new_fig(13, 8.5, "Reflect 链路：多步推理 Agent (engine/reflect/agent.py · 2155行)")
    
    # Input
    draw_box(ax, 37, 88, 26, 6, "Reflect 请求\nbank_id + query + disposition", C_LIGHT2, C_ACCENT, 9, True)
    
    # Loop box
    loop_box = FancyBboxPatch((8, 28), 84, 54, boxstyle="round,pad=0.5",
                               facecolor=C_LIGHT, edgecolor=C_PRIMARY, linewidth=1.5, linestyle='--')
    ax.add_patch(loop_box)
    draw_label(ax, 12, 79, "Reflect Agent 循环", 10, C_PRIMARY, 'left')
    
    # Steps
    draw_box(ax, 12, 64, 18, 9, "1. Recall 召回\n调用recall工具\n获取相关记忆", C_LIGHT, C_SECONDARY, 8)
    draw_box(ax, 35, 64, 18, 9, "2. LLM 推理\n分析召回内容\n形成初步判断", C_LIGHT, C_SECONDARY, 8)
    draw_box(ax, 58, 64, 18, 9, "3. 工具调用\nsearch_observations\nget_mental_model", C_LIGHT, C_SECONDARY, 8)
    draw_box(ax, 35, 48, 18, 9, "4. 证据Grounding\n每个结论必须\n引用source_memory", C_LIGHT3, C_WARN, 8)
    draw_box(ax, 58, 48, 18, 9, "5. 判断是否继续\n需要更多信息?\n→回到步骤1", C_LIGHT, C_SECONDARY, 8)
    draw_box(ax, 12, 48, 18, 9, "Disposition影响\nskepticism/\nliteralism/empathy", C_LIGHT4, C_DANGER, 8)
    
    # Arrows
    draw_arrow(ax, 30, 68, 35, 68)
    draw_arrow(ax, 53, 68, 58, 68)
    draw_arrow(ax, 67, 64, 67, 57)
    draw_arrow(ax, 58, 52, 53, 52)
    draw_arrow(ax, 35, 52, 30, 52)
    draw_arrow(ax, 21, 57, 21, 64, color=C_DANGER)
    # Loop back
    draw_arrow(ax, 21, 48, 21, 38, dashed=True)
    draw_arrow(ax, 21, 38, 67, 38, dashed=True)
    draw_arrow(ax, 67, 38, 67, 48, dashed=True)
    
    draw_label(ax, 44, 35, "循环直到 max_steps 或判断信息充分", 7, C_ARROW)
    
    # Output
    draw_box(ax, 37, 16, 26, 7, "结构化输出\nreflect_response(JSON)\n可写入 mental_model", C_LIGHT2, C_ACCENT, 9, True)
    draw_arrow(ax, 50, 28, 50, 23)
    draw_arrow(ax, 50, 88, 50, 82)
    
    # Tools list
    draw_label(ax, 82, 76, "Reflect可用工具:", 8, C_PRIMARY, 'left')
    tools = ["· recall (记忆召回)", "· search_observations", "· get_mental_model", "· list_directives", "· entity_lookup", "· temporal_query"]
    for i, t in enumerate(tools):
        draw_label(ax, 82, 71-i*4, t, 7, C_TEXT, 'left')
    
    save(fig, "06_reflect_loop")

# ============================================================
# 7. Consolidation Flow
# ============================================================
def gen_consolidation():
    fig, ax = new_fig(14, 8.5, "Consolidation 后台链路：记忆如何学习和进化")
    
    # Trigger
    draw_box(ax, 3, 82, 18, 8, "触发条件\nretain后标记\n定时调度\nmental_model trigger", C_LIGHT2, C_ACCENT, 8)
    draw_box(ax, 25, 82, 18, 8, "Worker轮询\nasync_operations\nstatus=pending", C_LIGHT, C_SECONDARY, 8)
    draw_arrow(ax, 21, 86, 25, 86)
    draw_box(ax, 47, 80, 22, 10, "Consolidator\nengine/consolidation/\nconsolidator.py (3763行)", C_LIGHT3, C_WARN, 9, True)
    draw_arrow(ax, 43, 86, 47, 86)
    
    # Steps
    steps = [
        ("1. 选择未巩固事实\nconsolidated_at IS NULL\n按bank分组", 3),
        ("2. LLM归纳\nconsolidation/prompts.py\n从多条事实生成候选", 27),
        ("3. 去重与合并\nconsolidation_dedup\n匹配已有observation\nproof_count++", 51),
        ("4. 写入观察\nfact_type=observation\n保留source_memory_ids\n证据链完整", 75),
    ]
    for name, x in steps:
        draw_box(ax, x, 62, 22, 12, name, C_LIGHT, C_SECONDARY, 8)
    for i in range(3):
        draw_arrow(ax, 25+i*24, 68, 27+i*24, 68)
    
    # Downstream
    draw_label(ax, 3, 54, "下游影响", 10, C_PRIMARY, 'left')
    downstream = [
        ("Mental Model刷新\ntrigger.refresh_after_\nconsolidation + cron(croniter)\n写入content + history", 3),
        ("Webhook通知\nretain/consolidation/refresh\n生命周期事件\n签名验证(secret)", 35),
        ("可观测性\naudit_log记录\nPrometheus metrics\nconsolidation_failed_at", 67),
    ]
    for name, x in downstream:
        draw_box(ax, x, 36, 30, 14, name, C_LIGHT, C_SECONDARY, 8)
    
    # Evidence chain
    draw_box(ax, 3, 18, 94, 10, "Observation 证据链:  observation(memory_units, fact_type='observation')  ←  observation_sources(observation_id, source_id)  ←  source memory_units\n新证据到达时: proof_count++ · 强化/弱化/扩展现有信念 · 不静默覆盖 (refine rather than overwrite)", 
             C_LIGHT5, C_PRIMARY, 9)
    
    draw_label(ax, 50, 10, "关键设计: retain只负责写入原始记忆，学习(归纳/巩固/刷新)全部发生在后台consolidation路径", 8, C_ARROW)
    
    save(fig, "07_consolidation_flow")


# Generate all
print("Generating Hindsight technical diagrams...")
gen_system_architecture()
gen_learning_loop()
gen_retain_pipeline()
gen_recall_fusion()
gen_data_model()
gen_reflect_loop()
gen_consolidation()
print("\nAll diagrams generated!")
