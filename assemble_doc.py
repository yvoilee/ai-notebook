#!/usr/bin/env python3
"""Assemble the three part files into one complete Hindsight technical document."""

import re
import os

BASE = "/Users/bytedance/workdir/ai-workspace/agent架构"
IMG_DIR = os.path.join(BASE, "hindsight-diagrams")

def read_file(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def strip_header_comments(text):
    """Remove HTML comment headers at the top of files."""
    text = re.sub(r'^<!--.*?-->\s*', '', text, flags=re.DOTALL)
    return text

def normalize_part1(text):
    """Part 1: # 一、 -> ## 一、, ## 1.1 -> ### 1.1"""
    lines = text.split('\n')
    result = []
    for line in lines:
        if line.startswith('# 一、') or line.startswith('# 二、') or line.startswith('# 五、'):
            line = '#' + line  # # -> ##
        elif line.startswith('## 1.') or line.startswith('## 2.') or line.startswith('## 5.'):
            line = '#' + line  # ## -> ###
        result.append(line)
    return '\n'.join(result)

def normalize_part2(text):
    """Part 2: ## 第三章 -> ## 三、, remove file title, fix code block # lines"""
    lines = text.split('\n')
    result = []
    in_code = False
    for line in lines:
        # Skip the file title
        if line.startswith('# Hindsight 技术文档（Part 2'):
            continue
        # Track code blocks
        if line.strip().startswith('```'):
            in_code = not in_code
            result.append(line)
            continue
        if in_code:
            result.append(line)
            continue
        # Normalize chapter headers
        if line.startswith('## 第三章'):
            line = '## 三、存储内核：记忆如何被组织'
        elif line.startswith('## 第四章'):
            line = '## 四、运行时核心模块'
        elif line.startswith('## 第六章'):
            line = '## 六、Recall 链路：一次查询如何召回记忆'
        elif line.startswith('## 第七章'):
            line = '## 七、Reflect 链路：Agent 如何深度思考'
        # Section headers ## 3.1 -> ### 3.1
        elif re.match(r'^## \d+\.\d+', line):
            line = '#' + line  # ## -> ###
        result.append(line)
    return '\n'.join(result)

def normalize_part3(text):
    """Part 3: ## 第八章 -> ## 八、, remove file title"""
    lines = text.split('\n')
    result = []
    in_code = False
    for line in lines:
        if line.startswith('# Hindsight 技术文档（第三部分'):
            continue
        if line.strip().startswith('```'):
            in_code = not in_code
            result.append(line)
            continue
        if in_code:
            result.append(line)
            continue
        if line.startswith('## 第八章'):
            line = '## 八、Consolidation 与后台链路：记忆如何学习和进化'
        elif line.startswith('## 第九章'):
            line = '## 九、Hindsight 的关键设计思想（本文归纳）'
        elif line.startswith('## 第十章'):
            line = '## 十、它适合什么，不适合什么'
        elif line.startswith('## 第十一章'):
            line = '## 十一、源码阅读地图'
        elif line.startswith('## 第十二章'):
            line = '## 十二、Hindsight 上手'
        elif line.startswith('## 结语'):
            line = '## 结语：Hindsight 真正控制的是"学习秩序"'
        elif re.match(r'^## \d+\.\d+', line):
            line = '#' + line
        result.append(line)
    return '\n'.join(result)

def extract_chapter(text, chapter_marker, next_markers):
    """Extract a chapter from text by marker."""
    lines = text.split('\n')
    start = None
    end = len(lines)
    for i, line in enumerate(lines):
        if start is None and line.startswith(chapter_marker):
            start = i
        elif start is not None:
            for nm in next_markers:
                if line.startswith(nm):
                    end = i
                    break
            if end < len(lines):
                break
    if start is None:
        return ""
    return '\n'.join(lines[start:end])

# Read all parts
part1 = strip_header_comments(read_file(os.path.join(BASE, "hindsight_part1_retain.md")))
part2 = strip_header_comments(read_file(os.path.join(BASE, "hindsight_part2_recall_reflect.md")))
part3 = strip_header_comments(read_file(os.path.join(BASE, "hindsight_part3_consolidation_design.md")))

# Normalize
part1 = normalize_part1(part1)
part2 = normalize_part2(part2)
part3 = normalize_part3(part3)

# Extract chapters in order
ch1 = extract_chapter(part1, '## 一、', ['## 二、'])
ch2 = extract_chapter(part1, '## 二、', ['## 五、'])
ch3 = extract_chapter(part2, '## 三、', ['## 四、'])
ch4 = extract_chapter(part2, '## 四、', ['## 六、'])
ch5 = extract_chapter(part1, '## 五、', [])
ch6 = extract_chapter(part2, '## 六、', ['## 七、'])
ch7 = extract_chapter(part2, '## 七、', [])
ch8 = extract_chapter(part3, '## 八、', ['## 九、'])
ch9 = extract_chapter(part3, '## 九、', ['## 十、'])
ch10 = extract_chapter(part3, '## 十、', ['## 十一、'])
ch11 = extract_chapter(part3, '## 十一、', ['## 十二、'])
ch12 = extract_chapter(part3, '## 十二、', ['## 结语'])
conclusion = extract_chapter(part3, '## 结语', [])

# Image insertion helpers
def img_tag(name, caption):
    return f'\n\n![{caption}]({os.path.join(IMG_DIR, name)})\n\n'

# Assemble with part headers and images
doc = """# 看懂 Hindsight：从仿生记忆结构到 Agent 学习闭环

> 参考文档：[看懂 DeepSeek Harness：从插件内核到 Agent 执行闭环](https://bytedance.larkoffice.com/wiki/BGCuwF19YiEuzDk3Rgnc3bbtnLh)
> 源码基线：Hindsight v0.10.1 · MIT License · [github.com/vectorize-io/hindsight](https://github.com/vectorize-io/hindsight)

"""

# Part 1
doc += "# 第一部分：认识 Hindsight\n\n"
doc += ch1.strip() + "\n\n"
doc += ch2.strip() + "\n\n"

# Insert learning loop diagram in chapter 2
doc = doc.replace(
    "## 2.1 整体模型：retain / recall / reflect 的学习闭环",
    "## 2.1 整体模型：retain / recall / reflect 的学习闭环" + img_tag("02_learning_loop.png", "Hindsight 学习闭环")
)

# Part 2
doc += "# 第二部分：拆解系统架构\n\n"
doc += ch3.strip() + "\n\n"
# Insert data model diagram after chapter 3 intro
doc = doc.replace(
    "### 3.1",
    img_tag("05_data_model.png", "Hindsight 核心数据模型") + "\n### 3.1",
    1
)
doc += ch4.strip() + "\n\n"
# Insert system architecture in chapter 4
doc = doc.replace(
    "### 4.1",
    img_tag("01_system_architecture.png", "Hindsight 系统架构总览") + "\n### 4.1",
    1
)

# Part 3
doc += "# 第三部分：追踪核心执行链路\n\n"
doc += ch5.strip() + "\n\n"
# Insert retain pipeline in chapter 5
doc = doc.replace(
    "### 5.1",
    img_tag("03_retain_pipeline.png", "Retain 流水线") + "\n### 5.1",
    1
)
doc += ch6.strip() + "\n\n"
# Insert recall fusion in chapter 6
doc = doc.replace(
    "### 6.1",
    img_tag("04_recall_fusion.png", "Recall 四臂检索融合") + "\n### 6.1",
    1
)
doc += ch7.strip() + "\n\n"
# Insert reflect loop in chapter 7
doc = doc.replace(
    "### 7.1",
    img_tag("06_reflect_loop.png", "Reflect Agent 循环") + "\n### 7.1",
    1
)

# Part 4
doc += "# 第四部分：理解设计取舍\n\n"
doc += ch8.strip() + "\n\n"
# Insert consolidation flow in chapter 8
doc = doc.replace(
    "### 8.1",
    img_tag("07_consolidation_flow.png", "Consolidation 后台链路") + "\n### 8.1",
    1
)
doc += ch9.strip() + "\n\n"
doc += ch10.strip() + "\n\n"
doc += ch11.strip() + "\n\n"
doc += ch12.strip() + "\n\n"
doc += conclusion.strip() + "\n"

# Write output
output_path = os.path.join(BASE, "hindsight_technical_doc_full.md")
with open(output_path, "w", encoding="utf-8") as f:
    f.write(doc)

# Stats
total_chars = len(doc)
cjk_chars = len(re.findall(r'[\u4e00-\u9fff]', doc))
print(f"Assembled document: {output_path}")
print(f"Total characters: {total_chars}")
print(f"CJK characters: {cjk_chars}")
print(f"Lines: {doc.count(chr(10))}")
print(f"Images referenced: {doc.count('.png)')}")

# Verify all chapters present
for i, title in enumerate(["一、Hindsight", "二、先建立", "三、存储内核", "四、运行时", "五、Retain", 
                            "六、Recall", "七、Reflect", "八、Consolidation", "九、Hindsight", 
                            "十、它适合", "十一、源码", "十二、Hindsight", "结语"], 1):
    found = title in doc
    print(f"  Ch {i}: {'✓' if found else '✗'} {title}")
