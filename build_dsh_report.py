from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Iterable

from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.fonts import addMapping
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "report-source.md"
OUTPUT = ROOT / "output" / "pdf" / "DeepSeek_DSH_深度剖析_2026-08-31.pdf"

PAGE_W, PAGE_H = A4
LEFT = 18 * mm
RIGHT = 18 * mm
TOP = 18 * mm
BOTTOM = 17 * mm
CONTENT_W = PAGE_W - LEFT - RIGHT

INK = HexColor("#132238")
MUTED = HexColor("#5A697D")
BLUE = HexColor("#155EEF")
BLUE_DARK = HexColor("#0B3AA4")
CYAN = HexColor("#19B5D8")
PALE_BLUE = HexColor("#EAF1FF")
PALE_CYAN = HexColor("#E8FAFD")
PALE_GREY = HexColor("#F4F6F8")
LINE = HexColor("#D8DFE8")
GREEN = HexColor("#0F8B6D")
AMBER = HexColor("#C47700")
RED = HexColor("#C53D43")


def register_fonts() -> None:
    body_candidates = [
        Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
        Path("/System/Library/Fonts/STHeiti Light.ttc"),
    ]
    head_candidates = [
        Path("/System/Library/Fonts/STHeiti Medium.ttc"),
        Path("/System/Library/Fonts/Hiragino Sans GB.ttc"),
        body_candidates[0],
    ]
    body = next((p for p in body_candidates if p.exists()), None)
    head = next((p for p in head_candidates if p.exists()), None)
    if body is None or head is None:
        raise RuntimeError("No CJK-capable system font found")
    pdfmetrics.registerFont(TTFont("DSHBody", str(body), subfontIndex=0))
    pdfmetrics.registerFont(TTFont("DSHHead", str(head), subfontIndex=0))
    addMapping("DSHBody", 0, 0, "DSHBody")
    addMapping("DSHBody", 1, 0, "DSHHead")


register_fonts()


BASE = getSampleStyleSheet()
STYLES = {
    "body": ParagraphStyle(
        "Body",
        parent=BASE["BodyText"],
        fontName="DSHBody",
        fontSize=9.2,
        leading=15.0,
        textColor=INK,
        spaceAfter=5.5,
        splitLongWords=True,
        allowWidows=0,
        allowOrphans=0,
    ),
    "small": ParagraphStyle(
        "Small",
        parent=BASE["BodyText"],
        fontName="DSHBody",
        fontSize=7.6,
        leading=11.5,
        textColor=MUTED,
        spaceAfter=3,
    ),
    "meta": ParagraphStyle(
        "Meta",
        parent=BASE["BodyText"],
        fontName="DSHBody",
        fontSize=8.1,
        leading=13,
        textColor=MUTED,
        spaceAfter=2,
    ),
    "h1": ParagraphStyle(
        "Heading1",
        parent=BASE["Heading1"],
        fontName="DSHHead",
        fontSize=21,
        leading=27,
        textColor=BLUE_DARK,
        spaceBefore=7,
        spaceAfter=12,
        keepWithNext=True,
    ),
    "h2": ParagraphStyle(
        "Heading2",
        parent=BASE["Heading2"],
        fontName="DSHHead",
        fontSize=13.5,
        leading=19,
        textColor=BLUE_DARK,
        spaceBefore=10,
        spaceAfter=7,
        keepWithNext=True,
    ),
    "h3": ParagraphStyle(
        "Heading3",
        parent=BASE["Heading3"],
        fontName="DSHHead",
        fontSize=10.8,
        leading=15,
        textColor=INK,
        spaceBefore=7,
        spaceAfter=4,
        keepWithNext=True,
    ),
    "bullet": ParagraphStyle(
        "Bullet",
        parent=BASE["BodyText"],
        fontName="DSHBody",
        fontSize=9.0,
        leading=14.3,
        textColor=INK,
        leftIndent=5.5 * mm,
        firstLineIndent=-3.8 * mm,
        bulletIndent=0,
        spaceAfter=3.5,
    ),
    "quote": ParagraphStyle(
        "Quote",
        parent=BASE["BodyText"],
        fontName="DSHBody",
        fontSize=9.3,
        leading=15,
        textColor=BLUE_DARK,
        leftIndent=5 * mm,
        rightIndent=4 * mm,
        borderColor=CYAN,
        borderWidth=1.2,
        borderPadding=(5, 7, 5, 9),
        backColor=PALE_CYAN,
        spaceBefore=5,
        spaceAfter=8,
    ),
    "table": ParagraphStyle(
        "TableCell",
        parent=BASE["BodyText"],
        fontName="DSHBody",
        fontSize=7.3,
        leading=10.6,
        textColor=INK,
    ),
    "table_head": ParagraphStyle(
        "TableHead",
        parent=BASE["BodyText"],
        fontName="DSHHead",
        fontSize=7.5,
        leading=10.5,
        textColor=colors.white,
    ),
}


def inline_markup(text: str) -> str:
    placeholders: list[str] = []

    def stash(value: str) -> str:
        placeholders.append(value)
        return f"@@DSH{len(placeholders) - 1}@@"

    def link_repl(match: re.Match[str]) -> str:
        label = html.escape(match.group(1), quote=False)
        url = html.escape(match.group(2), quote=True)
        return stash(f'<link href="{url}" color="#155EEF"><u>{label}</u></link>')

    def code_repl(match: re.Match[str]) -> str:
        code = html.escape(match.group(1), quote=False)
        return stash(f'<font name="Courier" color="#0B3AA4">{code}</font>')

    text = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", link_repl, text)
    text = re.sub(r"`([^`]+)`", code_repl, text)
    text = html.escape(text, quote=False)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    for idx, value in enumerate(placeholders):
        text = text.replace(f"@@DSH{idx}@@", value)
    return text


def cell(text: str, header: bool = False) -> Paragraph:
    return Paragraph(inline_markup(text.strip()), STYLES["table_head" if header else "table"])


class ArchitectureDiagram(Flowable):
    def __init__(self, width: float):
        super().__init__()
        self.width = width
        # Reserve a full diagram page. The former 151 mm canvas placed the
        # profile boxes above the flowable's own top edge, which made them
        # overlap the title when ReportLab positioned the drawing.
        self.height = 230 * mm

    def wrap(self, avail_width: float, avail_height: float) -> tuple[float, float]:
        return min(self.width, avail_width), self.height

    def draw_box(self, x: float, y: float, w: float, h: float, title: str, subtitle: str,
                 fill: colors.Color, stroke: colors.Color = LINE) -> None:
        c = self.canv
        c.setFillColor(fill)
        c.setStrokeColor(stroke)
        c.setLineWidth(0.8)
        c.roundRect(x, y, w, h, 5, fill=1, stroke=1)
        c.setFillColor(INK)
        c.setFont("DSHHead", 8.4)
        c.drawCentredString(x + w / 2, y + h - 12, title)
        c.setFillColor(MUTED)
        c.setFont("DSHBody", 6.8)
        for i, line in enumerate(subtitle.split("\n")):
            c.drawCentredString(x + w / 2, y + h - 23 - i * 8.5, line)

    def arrow(self, x1: float, y1: float, x2: float, y2: float) -> None:
        c = self.canv
        c.setStrokeColor(BLUE)
        c.setFillColor(BLUE)
        c.setLineWidth(1.1)
        c.line(x1, y1, x2, y2)
        angle = 3.2
        if abs(x2 - x1) > abs(y2 - y1):
            direction = 1 if x2 > x1 else -1
            c.line(x2, y2, x2 - direction * 5, y2 + angle)
            c.line(x2, y2, x2 - direction * 5, y2 - angle)
        else:
            direction = 1 if y2 > y1 else -1
            c.line(x2, y2, x2 + angle, y2 - direction * 5)
            c.line(x2, y2, x2 - angle, y2 - direction * 5)

    def draw(self) -> None:
        c = self.canv
        w = self.width
        c.setFillColor(INK)
        c.setFont("DSHHead", 14)
        c.drawString(0, self.height - 10, "DSH 运行时：插件树包围一条可重建的执行脊柱")
        c.setFillColor(MUTED)
        c.setFont("DSHBody", 7.4)
        c.drawString(0, self.height - 25, "图中蓝色箭头表示在线控制流；底部事件流是恢复、回放、分叉、UI 与审计的共同事实源。")

        top_y = self.height - 55 - 28 * mm
        gap = 5 * mm
        profile_w = (w - 3 * gap) / 4
        for i, (title, sub) in enumerate([
            ("Web", "浏览器交互\n会话与设置"),
            ("Headless", "一次性任务\n自动化运行"),
            ("SDK / ACP", "stdio JSON-RPC\n程序化集成"),
            ("Agent Preset", "按会话组合\n工具 / Skills / persona"),
        ]):
            self.draw_box(i * (profile_w + gap), top_y, profile_w, 28 * mm, title, sub, PALE_BLUE)

        cordis_y = top_y - 42 * mm
        self.draw_box(0, cordis_y, w, 27 * mm, "Cordis plugin tree", "services + typed events + scopes + reversible effects + dependency-driven lifecycle", PALE_CYAN, CYAN)
        self.arrow(w / 2, top_y, w / 2, cordis_y + 27 * mm)

        spine_y = cordis_y - 48 * mm
        boxes = [
            ("Inbox", "followup / steer / inject"),
            ("Prompt + Tools", "scoped assembly / schemas"),
            ("LLM seam", "provider / model / stream"),
            ("Tool pipeline", "policy / execute / result"),
        ]
        bw = (w - 3 * gap) / 4
        for i, (title, sub) in enumerate(boxes):
            x = i * (bw + gap)
            self.draw_box(x, spine_y, bw, 29 * mm, title, sub, colors.white)
            if i < len(boxes) - 1:
                self.arrow(x + bw, spine_y + 14.5 * mm, x + bw + gap, spine_y + 14.5 * mm)

        log_y = spine_y - 36 * mm
        self.draw_box(0, log_y, w, 23 * mm, "Append-only SessionEvent log", "turn / step / user / assistant chunk+message / tool call+result / request header / plugin events", PALE_GREY)
        for i in range(4):
            x = i * (bw + gap) + bw / 2
            self.arrow(x, spine_y, x, log_y + 23 * mm)

        provider_y = log_y - 28 * mm
        c.setFillColor(MUTED)
        c.setFont("DSHBody", 7.1)
        c.drawCentredString(w / 2, provider_y + 20, "可替换 capability providers")
        labels = ["LLM adapters", "fs / subprocess", "sandbox", "storage", "MCP", "subagents"]
        sw = (w - 5 * gap) / 6
        for i, label in enumerate(labels):
            x = i * (sw + gap)
            c.setFillColor(PALE_BLUE if i % 2 == 0 else PALE_CYAN)
            c.setStrokeColor(LINE)
            c.roundRect(x, provider_y - 3, sw, 13, 3, fill=1, stroke=1)
            c.setFillColor(INK)
            c.setFont("DSHBody", 6.3)
            c.drawCentredString(x + sw / 2, provider_y + 1.5, label)


class DshDocTemplate(BaseDocTemplate):
    def __init__(self, filename: str):
        super().__init__(
            filename,
            pagesize=A4,
            leftMargin=LEFT,
            rightMargin=RIGHT,
            topMargin=TOP,
            bottomMargin=BOTTOM,
            title="DeepSeek Harness（DSH）深度剖析",
            author="OpenAI Codex research synthesis",
            subject="Architecture, runtime, security and adoption analysis of DeepSeek Harness",
        )
        frame = Frame(LEFT, BOTTOM, CONTENT_W, PAGE_H - TOP - BOTTOM, id="normal")
        self.addPageTemplates([PageTemplate(id="main", frames=frame, onPage=draw_page)])
        self._bookmark_counter = 0

    def beforeDocument(self) -> None:
        # multiBuild performs multiple passes to resolve the TOC. Bookmark keys
        # must be stable across passes or the index can never converge.
        self._bookmark_counter = 0

    def afterFlowable(self, flowable: Flowable) -> None:
        if not isinstance(flowable, Paragraph):
            return
        style = flowable.style.name
        if style not in {"Heading1", "Heading2", "Heading3"}:
            return
        level = {"Heading1": 0, "Heading2": 1, "Heading3": 2}[style]
        text = flowable.getPlainText()
        key = f"h{self._bookmark_counter}"
        self._bookmark_counter += 1
        self.canv.bookmarkPage(key)
        self.canv.addOutlineEntry(text, key, level=level, closed=False)
        self.notify("TOCEntry", (level, text, self.page, key))


def draw_page(canvas, doc) -> None:
    canvas.saveState()
    if doc.page == 1:
        canvas.setFillColor(BLUE_DARK)
        canvas.rect(0, PAGE_H - 86 * mm, PAGE_W, 86 * mm, fill=1, stroke=0)
        canvas.setFillColor(CYAN)
        canvas.circle(PAGE_W - 22 * mm, PAGE_H - 22 * mm, 11 * mm, fill=1, stroke=0)
        canvas.setFillColor(BLUE)
        canvas.circle(PAGE_W - 38 * mm, PAGE_H - 38 * mm, 18 * mm, fill=1, stroke=0)
        canvas.restoreState()
        return
    canvas.setStrokeColor(LINE)
    canvas.setLineWidth(0.5)
    canvas.line(LEFT, PAGE_H - 12.5 * mm, PAGE_W - RIGHT, PAGE_H - 12.5 * mm)
    canvas.setFillColor(MUTED)
    canvas.setFont("DSHBody", 6.8)
    canvas.drawString(LEFT, PAGE_H - 10.5 * mm, "DEEPSEEK HARNESS / ARCHITECTURE REVIEW")
    canvas.drawRightString(PAGE_W - RIGHT, PAGE_H - 10.5 * mm, "源码基线 0.1.2-alpha.2 / 0a53fb5")
    canvas.line(LEFT, 10.8 * mm, PAGE_W - RIGHT, 10.8 * mm)
    canvas.drawString(LEFT, 7.3 * mm, "研究日期 2026-08-31")
    canvas.drawRightString(PAGE_W - RIGHT, 7.3 * mm, f"{doc.page}")
    canvas.restoreState()


def cover_story() -> list[Flowable]:
    title_style = ParagraphStyle(
        "CoverTitle", fontName="DSHHead", fontSize=30, leading=38,
        textColor=colors.white, alignment=TA_LEFT,
    )
    sub_style = ParagraphStyle(
        "CoverSub", fontName="DSHBody", fontSize=12, leading=19,
        textColor=HexColor("#DCE9FF"), alignment=TA_LEFT,
    )
    label_style = ParagraphStyle(
        "CoverLabel", fontName="DSHHead", fontSize=8.3, leading=11,
        textColor=CYAN, alignment=TA_LEFT,
    )
    story: list[Flowable] = [
        Spacer(1, 12 * mm),
        Paragraph("DEEP RESEARCH / SOURCE-LEVEL REVIEW", label_style),
        Spacer(1, 7 * mm),
        Paragraph("DeepSeek Harness<br/>（DSH）深度剖析", title_style),
        Spacer(1, 6 * mm),
        Paragraph("从 Cordis、事件溯源与 PTC，到安全边界、性能证据和采用决策", sub_style),
        Spacer(1, 56 * mm),
    ]
    meta = [
        ["研究基线", "dsh-v0.1.2-alpha.2 / commit 0a53fb55"],
        ["研究日期", "2026-08-31"],
        ["证据范围", "官方源码、设计文档、论文、发布说明与独立安全研究"],
        ["核心判断", "架构样本价值高；生产安全与兼容性成熟度仍不足"],
    ]
    table = Table(
        [[Paragraph(f"<b>{inline_markup(k)}</b>", STYLES["small"]), Paragraph(inline_markup(v), STYLES["body"])] for k, v in meta],
        colWidths=[28 * mm, CONTENT_W - 28 * mm],
        hAlign="LEFT",
    )
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("BOX", (0, 0), (-1, -1), 0.8, LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("BACKGROUND", (0, 0), (0, -1), PALE_BLUE),
    ]))
    story.extend([table, Spacer(1, 8 * mm), Paragraph("面向 Agent 架构师、平台工程师与技术决策者", STYLES["meta"]), PageBreak()])
    return story


def scorecard_story() -> list[Flowable]:
    story: list[Flowable] = [Paragraph("执行摘要", STYLES["h1"])]
    verdict = Paragraph(
        "<b>一句话结论：</b> DSH 是一套可重组、可回放的 Agent runtime 内核与参考发行版，架构创新强；但截至 alpha.2，API / session 兼容性、安全隔离和端到端 benchmark 证据仍不足，不应在缺少外层容器隔离时直接承载不可信工作负载。",
        STYLES["quote"],
    )
    story.append(verdict)
    rows = [
        ["维度", "判断", "原因"],
        ["架构原创性", "强", "Cordis 时空可组合性 + capability seam + event-sourced session"],
        ["扩展能力", "强", "模型、loop、tool、skill、sandbox、storage、UI 均可替换"],
        ["轨迹与审计", "强", "模型可见内容与 request header 可从同一日志重建"],
        ["工程可维护性", "中", "门禁与文档优秀，但 258 packages / 86-row base 组合带来高认知成本"],
        ["生产安全", "弱", "官方未审计；same-world file sandbox；PTC / workflow 不是 OS 隔离"],
        ["兼容稳定性", "弱", "developer preview；破坏性变更；旧 session 无迁移链"],
        ["性能证据", "中-弱", "有认真优化机制，但缺少可解释的公开端到端 benchmark"],
    ]
    data = [[cell(v, header=(r == 0)) for v in row] for r, row in enumerate(rows)]
    table = Table(data, colWidths=[26 * mm, 19 * mm, CONTENT_W - 45 * mm], repeatRows=1)
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), BLUE_DARK),
        ("BOX", (0, 0), (-1, -1), 0.7, LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    for r in range(1, len(rows)):
        style_cmds.append(("BACKGROUND", (0, r), (-1, r), colors.white if r % 2 else PALE_GREY))
        judgment = rows[r][1]
        color = GREEN if judgment == "强" else AMBER if judgment.startswith("中") else RED
        style_cmds.append(("TEXTCOLOR", (1, r), (1, r), color))
    table.setStyle(TableStyle(style_cmds))
    story.extend([table, Spacer(1, 7 * mm)])
    story.append(Paragraph("优先结论", STYLES["h2"]))
    for bullet in [
        "把 DSH 当作 Agent runtime 架构样本与插件平台，而不是单纯的 coding agent UI。",
        "任何比较都必须固定 model / preset / tool mode / permission policy / commit，否则结果没有解释力。",
        "首次试点使用 native + workspace-write + ask，并放进 disposable container / VM；PTC 单独隔离。",
        "只有任务收益、安全边界和升级成本三项同时过线，才进入有限生产。",
    ]:
        story.append(Paragraph(f"• {inline_markup(bullet)}", STYLES["bullet"]))
    story.append(PageBreak())
    story.append(Paragraph("目录", STYLES["h1"]))
    toc = TableOfContents()
    toc.levelStyles = [
        ParagraphStyle("TOC0", fontName="DSHHead", fontSize=9.5, leading=15, leftIndent=0, textColor=BLUE_DARK, spaceBefore=4),
        ParagraphStyle("TOC1", fontName="DSHBody", fontSize=8.4, leading=13, leftIndent=6 * mm, textColor=INK),
        ParagraphStyle("TOC2", fontName="DSHBody", fontSize=7.8, leading=12, leftIndent=12 * mm, textColor=MUTED),
    ]
    story.extend([toc, PageBreak(), ArchitectureDiagram(CONTENT_W), PageBreak()])
    return story


def parse_markdown(lines: Iterable[str]) -> list[Flowable]:
    src = list(lines)
    story: list[Flowable] = []
    paragraph: list[str] = []
    i = 0
    skip_first_title = True

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            text = " ".join(part.strip() for part in paragraph).strip()
            if text:
                story.append(Paragraph(inline_markup(text), STYLES["body"]))
            paragraph = []

    while i < len(src):
        raw = src[i].rstrip("\n")
        line = raw.strip()
        if not line:
            flush_paragraph()
            i += 1
            continue
        if line.startswith("# "):
            flush_paragraph()
            if skip_first_title:
                skip_first_title = False
            else:
                story.append(Paragraph(inline_markup(line[2:]), STYLES["h1"]))
            i += 1
            continue
        if line.startswith("## "):
            flush_paragraph()
            title = line[3:]
            if re.match(r"(?:4|6|8|10|11|12)\.", title) and story:
                story.append(PageBreak())
            story.append(Paragraph(inline_markup(title), STYLES["h2"]))
            i += 1
            continue
        if line.startswith("### "):
            flush_paragraph()
            story.append(Paragraph(inline_markup(line[4:]), STYLES["h3"]))
            i += 1
            continue
        if line.startswith("|") and i + 1 < len(src) and re.match(r"^\s*\|?\s*:?-+", src[i + 1]):
            flush_paragraph()
            rows: list[list[str]] = []
            while i < len(src) and src[i].strip().startswith("|"):
                tline = src[i].strip().strip("|")
                cols = [x.strip() for x in tline.split("|")]
                if not all(re.match(r"^:?-{3,}:?$", col) for col in cols):
                    rows.append(cols)
                i += 1
            max_cols = max(len(r) for r in rows)
            normalized = [r + [""] * (max_cols - len(r)) for r in rows]
            data = [[cell(value, header=(ri == 0)) for value in row] for ri, row in enumerate(normalized)]
            if max_cols == 4:
                widths = [27 * mm, 33 * mm, 42 * mm, CONTENT_W - 102 * mm]
            elif max_cols == 3:
                widths = [28 * mm, 31 * mm, CONTENT_W - 59 * mm]
            else:
                widths = [CONTENT_W / max_cols] * max_cols
            table = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
            cmds = [
                ("BACKGROUND", (0, 0), (-1, 0), BLUE_DARK),
                ("BOX", (0, 0), (-1, -1), 0.7, LINE),
                ("INNERGRID", (0, 0), (-1, -1), 0.35, LINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
            for ri in range(1, len(data)):
                cmds.append(("BACKGROUND", (0, ri), (-1, ri), colors.white if ri % 2 else PALE_GREY))
            table.setStyle(TableStyle(cmds))
            story.extend([table, Spacer(1, 5 * mm)])
            continue
        bullet = re.match(r"^[-*]\s+(.*)", line)
        numbered = re.match(r"^(\d+)\.\s+(.*)", line)
        if bullet or numbered:
            flush_paragraph()
            if bullet:
                prefix, body = "•", bullet.group(1)
            else:
                prefix, body = f"{numbered.group(1)}.", numbered.group(2)
            story.append(Paragraph(f"{prefix} {inline_markup(body)}", STYLES["bullet"]))
            i += 1
            continue
        if line.startswith("**受众**") or line.startswith("**研究日期**") or line.startswith("**源码基线**") or line.startswith("**范围**") or line.startswith("**排除**"):
            flush_paragraph()
            story.append(Paragraph(inline_markup(line.rstrip("  ")), STYLES["meta"]))
            i += 1
            continue
        paragraph.append(line.rstrip("  "))
        i += 1
    flush_paragraph()
    return story


def build() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    text = SOURCE.read_text(encoding="utf-8")
    story = cover_story() + scorecard_story() + parse_markdown(text.splitlines())
    doc = DshDocTemplate(str(OUTPUT))
    doc.multiBuild(story)
    print(OUTPUT)


if __name__ == "__main__":
    build()
