# lit-review-extractor — 技能使用指南

## 这个技能能做什么？

当你说下面任意一句，技能自动激活：

- "帮我提取这篇综述的纳入文献"
- "整理这篇 meta 分析纳入的文献，下载所有 PDF 原文"
- "提取这篇系统综述表格里的作者和 DOI"
- "下载这些纳入研究的全文"

自动交互流程：

```
你要求提取 → 我问「哪个模式？（快速/完整/全量）」→ 你选择
  → 执行提取 + 审查 → 我问「是否下载PDF？」→ 你选择
  → 数据准备 → API层 → Chrome CDP → 我问「是否用Panda985兜底？」→ 你选择
  → 全网搜索补漏 → 验证 → 重命名 → 完成
```

---

## 三种提取模式

| 模式 | 字段数 | 脚本 | 适用场景 |
|------|--------|------|---------|
| **快速模式** | 4（作者/DOI/标题/年份） | `extract_included_studies.py` | 简单确认 |
| **完整模式** | 21（含效应量/样本量等） | `extract_full_table.py` | Meta分析 |
| **全量模式** | 不预设，动态识别 | `extract_full_table.py --mode exhaustive` | 表格结构特殊 |

---

## 下载策略（8层降级）

| 层 | 来源 | VPN | 命令 |
|----|------|-----|------|
| L0 | 数据准备（信息表→JSON） | 否 | `python scripts/prep_from_info.py --name 文献pdf` |
| L1 | Europe PMC / Unpaywall / OpenAlex | 否 | `python scripts/download_parallel.py` |
| L2 | 出版商meta | 否 | 同上自动 |
| L3 | Sci-Hub 镜像（sg免验证） | 是 | Chrome调试 → `python scripts/scihub_batch.py` |
| **L4** | **Panda985 (一键下载→SCI-HUB)** | **是** | `python scripts/panda985_search.py` |
| **L5** | **全网搜索**（政府报告/期刊官网/机构库） | 否 | WebSearch 定向搜索 |
| L6 | 验证 | 否 | `python scripts/verify_pdfs.py` + `list_missing.py` |
| L7 | 重命名交付 | 否 | `python scripts/rename_pdfs.py` |

---

## 前置条件

```bash
pip install pymupdf openpyxl beautifulsoup4 requests pandas playwright
python -m playwright install chromium
```

---

## 实战要点（v4.0 新增）

1. **中文验证码**：Sci-Hub 有"你是机器人吗？"，检测须覆盖中英文
2. **先找PDF再判断标题**：标题含 "challenge" 等词会误判验证码
3. **政府报告挖老文献**：ATS 老文献查 CARB/EPA 研究报告（常完整收录原文）
4. **期刊官网捡漏**：找 `citation_pdf_url` meta 或官网 PDF 按钮
5. **下载后内容验证**：fitz 提取首页，DOI+标题关键词核对，防误下载

## 实际案例

| 论文 | 纳入 | DOI覆盖 | PDF覆盖 |
|------|------|---------|---------|
| Andrade 2023 | 58 | 100% | 100% |
| Hung 2022 | 59 | 97% | 100% |
| Gandhi 2022 | 7 | 100% | 100% |
| Morici 2020 | 19 | 100% | 95% |
| 空气污染×运动×健康 | 47 | 94% | **81%**（CARB报告救回2篇ATS老文献） |

## 脚本速查

| 脚本 | 功能 |
|------|------|
| `scripts/prep_from_info.py` | 信息表→JSON（含DOI补全） |
| `scripts/extract_included_studies.py` | 快速提取4字段 |
| `scripts/extract_full_table.py` | 完整/全量提取21+字段 |
| `scripts/review_dois.py` | 全量审查（6项检查） |
| `scripts/download_parallel.py` | API层并发下载 |
| `scripts/scihub_batch.py` | Sci-Hub批量（修复版） |
| `scripts/panda985_search.py` | Panda985捡漏（含内容验证） |
| `scripts/verify_pdfs.py` | PDF交叉验证 |
| `scripts/verify_merged.py` | 增强版验证（多语言/扫描版/中文/严格匹配） |
| `scripts/list_missing.py` | 缺失清单 |
| `scripts/rename_pdfs.py` | 重命名（第一作者+题目） |
