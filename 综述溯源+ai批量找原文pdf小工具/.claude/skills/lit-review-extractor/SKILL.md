---
name: lit-review-extractor
description: |
  综述论文纳入文献提取 + PDF下载。三个提取模式：(1) 快速4字段 (2) 核心字段（实际产出 5 个）
  (3) 全量不预设字段。提取完成后询问是否执行模块二PDF下载；Sci-Hub下载完毕后询问是否用
  Panda985捡漏，最后可全网搜索（政府报告/期刊官网/机构库）补漏。
  触发：用户要求"提取纳入研究""整理纳入文献""追溯引用""导出纳入文献""提取Table 1""下载PDF""找全文"等。
compatibility: requires Python 3.10+, pymupdf, openpyxl, beautifulsoup4, requests, pandas, xlsxwriter, playwright
metadata:
  version: "4.1"
  skill-author: "Lit-Review Team"
  modules: ["extraction-quick", "extraction-full", "exhaustive", "pdf-download", "web-rescue"]
  verification: ["review-dois", "pdf-cross-verify"]
---

# Literature Review Extractor — 综述纳入文献提取器

## 核心交互流程

```
用户要求提取
  ↓
[模式选择] "你要执行哪种模式？ ①快速 ②完整 ③全量？"
  ↓
[若完整] 展示21字段清单 → 等待确认
[若全量] 说明不预设字段 → 动态提取
  ↓
提取 + 审查（review_dois.py）
  ↓
[模块二询问] "是否执行PDF批量下载？"
  ↓ 是
数据准备 (prep_from_info.py，若有信息表.xlsx)
  ↓
API层下载 (download_parallel.py)
  ↓
Chrome CDP层 (scihub_batch.py 修复版)
  ↓
[Panda985询问] "是否用 Panda985 检索未下载到的文献？"
  ├── 是 → Panda985 一键下载 → SCI-HUB
  └── 否 → 跳下一层
  ↓
[全网搜索] 政府报告/期刊官网/机构库 (WebSearch 定向)
  ↓
验证 (verify_pdfs.py) → 重命名 (rename_pdfs.py)
  ↓
结束
```

---

## 模式选择与执行模板

### 模式选择提问

> 你要执行哪种提取模式？
>
> **① 快速模式** → 4 字段：第一作者、DOI、文章标题、年份
>
> **② 核心模式** → 实际产出 5 字段：first_author, doi, title, year, journal
>   （FIELD_DEFS 里声明的样本量/研究设计/效应量等 **取不到值**，见下方说明）
>
> **③ 全量提取模式** → 不预设字段，逐篇分析原文动态提取

### 完整模式确认提问

> 完整模式将提取以下 21 个字段：
>
> **核心标识**（HIGH置信度）: first_author, doi, title, year, journal
> **样本信息**（MEDIUM）: sample_size, population, age_range, sex
> **研究设计**（MEDIUM）: study_design, follow_up, country
> **结局数据**（MEDIUM）: exposure, outcome, effect_measure, effect_size, ci_lower, ci_upper
> **质量评价**（LOW+手动）: quality_score, funding, notes
>
> 确认执行吗？

### 模块二询问模板

> 提取+审查通过。是否执行模块二（PDF批量下载）？
>
> **① 是** → 8 层下载流水线：数据准备 → API层 → Sci-Hub → Panda985 → 全网搜索 → 验证
> **② 否** → 结束

### Panda985 兜底询问模板

> Sci-Hub 下载完成。仍有 **N 篇**未下载到。
>
> 是否用 **Panda985 (https://sc.panda985.com/index.html)** 检索这些文献？
>
> Panda985 是一个中文学术搜索引擎，检索页每篇右侧有「一键下载」→ 弹窗点「SCI-HUB」跳转下载。
>
> **① 是** → 在 Chrome 中打开 Panda985，逐篇搜索
> **② 否** → 结束

---

## 模式 1：快速模式 — 4 字段

```bash
python scripts/extract_included_studies.py "论文.pdf" \
    --refs refs.json --ref-pages "38-41" \
    --title "论文标题" --citation "Author (Year) Journal" \
    --output "output/结果.xlsx"

python scripts/review_dois.py "output/结果.xlsx" "论文.pdf" \
    --ref-pages "38-41" --json "output/extracted_data.json"
```

### 审查检查项（全量）

| 检查项 | 级别 | 范围 | 内容 |
|--------|------|------|------|
| DOI 唯一性 | CRITICAL | 全部 | 同一DOI分配给多篇 |
| DOI 标题匹配 | ERROR | **全部** | OpenAlex 标题 vs 参考文献原文 |
| 单作者论文 | ERROR | 全部 | 不含"et al."的遗漏 |
| 作者名异常 | ERROR | 全部 | 页眉混入 |
| 同作者同年 | WARNING | 全部 | DOI混淆 |
| DOI 验证 | WARNING | **全部** | OpenAlex 全量验证 |

> 注意：DOI 标题匹配检查和 DOI 验证已从抽样升级为**全量检查**，确保不遗漏任何错误。

---

## 模式 2：核心字段模式 —— ⚠️ 实际只产出 5 字段

```bash
python scripts/extract_full_table.py "论文.pdf" \
    --refs refs.json --ref-pages "38-41" \
    --output "output/论文名/"
```

实际有值的字段：**first_author, doi, title, year, journal**。
其余 16 个（sample_size / study_design / effect_size / ci_lower / ci_upper /
quality_score …）一律为空字符串 —— 正文表格解析尚未接入主流程。

> 向用户确认时必须如实说明，**不要按 21 字段介绍**。运行结束脚本会打印字段填充率。

---

## 模式 3：全量提取模式

不预设字段。
1. 先用快速模式提取核心标识
2. 逐篇分析原文表格列结构
3. 动态识别所有可用字段
4. 输出灵活数据结构，每篇字段集可能不同

---

## 模块二：PDF 批量下载

### 8 层降级策略

| 层 | 来源 | VPN | 命中率 | 命令 |
|----|------|-----|--------|------|
| L0 | **数据准备** | 否 | — | `python scripts/prep_from_info.py --name <案例名>` |
| L1 | Europe PMC / Unpaywall / OpenAlex / Semantic Scholar | 否 | ~40% | `python scripts/download_parallel.py` |
| L2 | 出版商 meta | 否 | ~20% | 同上（自动） |
| L3 | Sci-Hub 镜像（sg 免验证优先） | **是** | ~40% | Chrome 调试 + `python scripts/scihub_batch.py` |
| **L4** | **Panda985** | **是** | ~5% | `python scripts/panda985_search.py` |
| **L5** | **全网搜索**（政府报告/期刊官网/机构库） | 否 | ~5% | WebSearch 定向搜索 |
| L6 | 验证 | 否 | — | `python scripts/verify_pdfs.py` + `verify_merged.py` + `list_missing.py` |
| L7 | 交付命名 | 否 | — | `python scripts/rename_pdfs.py`（第一作者+题目） |

### 增强版验证（verify_merged.py）

合并多批 PDF 后，用增强版验证（支持多语言/扫描版/中文/严格匹配）：

```bash
python scripts/verify_merged.py --pdfdir "合并全部PDF" --xlsx "信息表.xlsx"
# 输出: ok / weak / scanned / cn_verify / multilang / suspicious / unmatched
```

| 情况 | 处理 |
|------|------|
| 波斯语/非拉丁文献 | 检测非ASCII占比 → multilang 待人工确认 |
| 中文文献 | 按作者前缀匹配 + 中文特殊处理 |
| 扫描版 | OCR 确认或标注 scanned |
| 同作者多篇 | 作者前缀 + 唯一关键词严格匹配 |

### Panda985 使用流程

1. 提示用户：**"是否用 Panda985 检索剩余的 N 篇？"**
2. 用户确认后，在 Chrome 中打开 https://sc.panda985.com/index.html
3. 输入标题 → 检索页每篇右侧「一键下载」→ 弹窗点「SCI-HUB」
4. 跳转到 Sci-Hub 后，输入 DOI 搜索下载
5. 脚本已内置**内容验证**（自动删除误下载）

### 全网搜索捡漏方法（L5）

Sci-Hub/Panda985 下不到的文献，用 WebSearch 定向搜索非标准来源：

| 来源 | 适用 | 方法 |
|------|------|------|
| **政府研究报告**（CARB/EPA） | ATS 老文献 | WebSearch `"标题" filetype:pdf site:.gov` → 报告常完整收录原文 |
| **期刊官网** | 非主流/OA期刊 | 找 `citation_pdf_url` meta 或官网 PDF 下载按钮 |
| **大学机构库** | 高校作者新文献 | research.xxx.edu/en/publications 门户 |
| **文献互助平台** | 付费墙兜底 | 全国图书馆参考咨询联盟 ucdrs.superlib.net、掌桥科研 zhangqiaokeyan.com |

---

## 实战经验（v4.0 新增）

### 验证码处理
- Sci-Hub 有**中文验证码**"你是机器人吗？"，只检测英文 `captcha` 会漏检导致误判失败
- **验证码检测要覆盖中英文**，且**先找 PDF 再判断标题**（标题含 "challenge" 等词会误判）
- 遇到验证码：Chrome 里手动过，或换镜像（sg 通常免验证）

### Chrome 调试实例
- 用**独立 user-data-dir**（如 `C:/temp/chrome_debug_new`），不影响日常浏览器
- 调试实例易崩溃，崩溃后干净重启：删除 user-data-dir 再启动
- 尽量少开/关 tab，`expect_popup` 处理要小心

### 下载后必须验证内容
- Panda985 遍历链接会下到**错误文献**（会议摘要集、无关文章）
- 每个 PDF 用 fitz 提取首页 → DOI 精确匹配 + 标题关键词对比
- 只有验证通过才保存，否则删除

### 已知问题

| 问题 | 表现 | 对策 |
|------|------|------|
| DOI 交错匹配 | 同作者同年论文DOI互换 | 提取后用 OpenAlex 全量验证+标题对比 |
| 单作者论文丢失 | 计数比PRISMA少 | 手动确认补漏 |
| 背景引用混入 | 多出非纳入文献 | 核对 PRISMA 流程图数字 |
| 出版商格式差异 | MDPI/Springer/Frontiers 参考文献不同 | 多路解析策略 |
| Chrome 断连 | TargetClosedError | 检查 Chrome 调试窗口 |
| 中文验证码漏检 | 老文献被误判失败 | 中英文特征全覆盖，先找PDF再判标题 |
| Panda985 误下载 | 下到会议摘要集/无关文章 | 下载后 fitz 内容验证 |
| 新文献付费墙 | 2023+文献各源下不到 | 全国图书馆参考咨询联盟/联系作者 |
