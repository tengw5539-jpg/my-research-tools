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
  → API层 → Chrome CDP → 我问「是否用Panda985兜底？」→ 你选择
  → 验证 → 完成
```

---

## 三种提取模式

| 模式 | 字段数 | 脚本 | 适用场景 |
|------|--------|------|---------|
| **快速模式** | 4（作者/DOI/标题/年份） | `extract_included_studies.py` | 简单确认 |
| **完整模式** | 21（含效应量/样本量等） | `extract_full_table.py` | Meta分析 |
| **全量模式** | 不预设，动态识别 | `extract_full_table.py --mode exhaustive` | 表格结构特殊 |

---

## 下载策略（5层）

| 层 | 来源 | VPN | 命令 |
|----|------|-----|------|
| L1 | Europe PMC / Unpaywall / OpenAlex | 否 | `python scripts/download_pdfs.py --skip-vpn` |
| L2 | 出版商meta | 否 | 同上自动 |
| L3 | Sci-Hub + Chrome CDP | 是 | Chrome调试 → `python scripts/scihub_batch.py` |
| **L4** | **Panda985 (https://sc.panda985.com/index.html)** | **是** | **Sci-Hub后询问用户→手动搜索** |
| L5 | 验证 | 否 | `python scripts/verify_pdfs.py` |

---

## 前置条件

```bash
pip install pymupdf openpyxl beautifulsoup4 requests playwright
python -m playwright install chromium
```

## 实际案例

| 论文 | 纳入 | DOI覆盖 | PDF覆盖 |
|------|------|---------|---------|
| Andrade 2023 | 58 | 100% | 100% |
| Hung 2022 | 59 | 97% | 100% |
| Gandhi 2022 | 7 | 100% | 100% |
| Morici 2020 | 19 | 100% | 95% |

## 脚本速查

| 脚本 | 功能 |
|------|------|
| `scripts/extract_included_studies.py` | 快速提取4字段 |
| `scripts/extract_full_table.py` | 完整/全量提取21+字段 |
| `scripts/review_dois.py` | 全量审查（6项检查） |
| `scripts/download_pdfs.py` | API层下载 |
| `scripts/scihub_batch.py` | Chrome CDP批量下载 |
| `scripts/panda985_search.py` | Panda985兜底搜索 |
| `scripts/verify_pdfs.py` | PDF交叉验证 |
