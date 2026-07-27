---
name: lit-review-extractor
description: |
  综述论文纳入文献提取 + PDF下载。三个提取模式：(1) 快速4字段 (2) 完整21字段 (3) 全量不预设字段。
  提取完成后询问是否执行模块二PDF下载；Sci-Hub下载完毕后询问是否用Panda985捡漏。
  触发：用户要求"提取纳入研究""整理纳入文献""追溯引用""导出纳入文献""提取Table 1""下载PDF""找全文"等。
compatibility: requires Python 3.10+, pymupdf, openpyxl, beautifulsoup4, requests, playwright
metadata:
  version: "3.1"
  skill-author: "Lit-Review Team"
  modules: ["extraction-quick", "extraction-full", "exhaustive", "pdf-download"]
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
API层下载 (download_pdfs.py --skip-vpn)
  ↓
Chrome CDP层 (scihub_batch.py)
  ↓
[Panda985询问] "是否用 Panda985 (https://sc.panda985.com/index.html) 检索未下载到的文献？"
  ├── 是 → 引导用户在 Chrome 中逐篇搜索缺失文献
  └── 否 → 结束
  ↓
验证 (verify_pdfs.py)
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
> **② 完整模式** → 21 字段：含样本量、研究设计、效应量、质量评分等
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
> **① 是** → 5 层下载流水线：API层 → Chrome CDP → Panda985兜底 → 验证
> **② 否** → 结束

### Panda985 兜底询问模板

> Sci-Hub 下载完成。仍有 **N 篇**未下载到。
>
> 是否用 **Panda985 (https://sc.panda985.com/index.html)** 检索这些文献？
>
> Panda985 是一个中文学术搜索引擎，可能找到 Sci-Hub 没有收录的 PDF。
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

## 模式 2：完整模式 — 21 字段

```bash
python scripts/extract_full_table.py "论文.pdf" \
    --refs refs.json --ref-pages "38-41" \
    --output "output/论文名/"
```

21 字段清单与置信度见 CLAUDE.md 中的完整表格。

---

## 模式 3：全量提取模式

不预设字段。
1. 先用快速模式提取核心标识
2. 逐篇分析原文表格列结构
3. 动态识别所有可用字段
4. 输出灵活数据结构，每篇字段集可能不同

---

## 模块二：PDF 批量下载

### 5 层下载策略

| 层 | 来源 | VPN | 命中率 | 命令 |
|----|------|-----|--------|------|
| L1 | Europe PMC / Unpaywall / OpenAlex / Semantic Scholar | 否 | ~40% | `python scripts/download_pdfs.py --skip-vpn` |
| L2 | 出版商 meta | 否 | ~20% | 同上（自动） |
| L3 | Sci-Hub + Chrome CDP | **是** | ~40% | Chrome 调试 + `python scripts/scihub_batch.py` |
| **L4** | **Panda985 (https://sc.panda985.com/index.html)** | **是** | ~5% | **L3后由用户确认→在Chrome中逐篇搜索** |
| L5 | 验证 | 否 | — | `python scripts/verify_pdfs.py` |

### Panda985 兜底流程

L3 完成后，如果仍有文献未下载：

1. 提示用户：**"是否用 Panda985 检索剩余的 N 篇？"**
2. 用户确认后，在 Chrome 中打开 https://sc.panda985.com/index.html
3. 对每篇缺失文献，输入 DOI 或完整标题进行搜索
4. 找到后点击下载，保存到 `output/论文名/pdfs/`
5. 全部完成后运行 `python scripts/verify_pdfs.py` 验证

### 已知问题

| 问题 | 表现 | 对策 |
|------|------|------|
| DOI 交错匹配 | 同作者同年论文DOI互换 | 提取后用 OpenAlex 全量验证+标题对比 |
| 单作者论文丢失 | 计数比PRISMA少 | 手动确认补漏 |
| 背景引用混入 | 多出非纳入文献 | 核对 PRISMA 流程图数字 |
| 出版商格式差异 | MDPI/Springer/Frontiers 参考文献不同 | 多路解析策略 |
| Chrome 断连 | TargetClosedError | 检查 Chrome 调试窗口 |
| Panda985 无结果 | 收录范围有限 | 提示用户手动搜索 |
