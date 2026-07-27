# 综述溯源 — 纳入文献提取与PDF原文下载工具

## 这是什么？

一套**完全自动化的系统综述文献提取与PDF原文下载工具**。把综述PDF给你，它能：

1. **提取所有纳入文献信息** — 三种模式可选
2. **自动下载原文PDF** — 5层降级策略，从Europe PMC到Panda985全覆盖
3. **验证每篇PDF** — 逐篇交叉验证DOI/标题/作者，确保100%对应

已在4篇综述上验证（143篇纳入文献）。

---

## 前置条件（一次性）

```bash
pip install pymupdf openpyxl beautifulsoup4 requests playwright
python -m playwright install chromium
```

---

## 三种提取模式

| 模式 | 字段 | 脚本 | 适用场景 |
|------|------|------|---------|
| **① 快速模式** | 4字段（作者/DOI/标题/年份） | `extract_included_studies.py` | 简单确认 |
| **② 完整模式** | 21字段（含效应量/样本量/设计等） | `extract_full_table.py` | Meta分析 |
| **③ 全量提取** | 不预设字段，动态识别 | `extract_full_table.py --mode exhaustive` | 表格结构特殊 |

---

## 完整工作流

```bash
# Step 1: 提取（三种模式之一）
python scripts/extract_included_studies.py "论文.pdf" --refs refs.json --ref-pages "38-41" --output "output/结果.xlsx"

# Step 2: 审查（必须到 0 CRITICAL + 0 ERROR）
python scripts/review_dois.py "output/结果.xlsx" "论文.pdf" --ref-pages "38-41" --json "output/extracted_data.json"

# Step 3: 下载PDF — API层（无需VPN）
python scripts/download_pdfs.py --skip-vpn

# Step 4: 下载PDF — Chrome CDP层（需VPN）
# 先双击 scripts/launch_chrome_for_scihub.cmd
# 在打开的Chrome中打开 https://sci-hub.st 过掉验证码
python scripts/scihub_batch.py

# Step 5: Panda985兜底 — 询问用户后手动搜索
# 在Chrome中打开 https://sc.panda985.com/index.html
# 逐篇搜索缺失文献

# Step 6: 验证
python scripts/verify_pdfs.py
```

---

## 下载策略（5层）

| 层 | 来源 | VPN | 命中率 |
|----|------|-----|--------|
| L1 | Europe PMC / Unpaywall / OpenAlex / Semantic Scholar | 否 | ~40% |
| L2 | 出版商meta | 否 | ~20% |
| L3 | Sci-Hub + Chrome CDP | 是 | ~40% |
| **L4** | **Panda985 (https://sc.panda985.com/index.html)** | **是** | **~5%** |
| L5 | 验证 | 否 | — |

> **Panda985兜底**：Sci-Hub下载完成后，仍有缺失的文献 → 打开 https://sc.panda985.com/index.html → 逐篇搜索DOI/标题 → 手动下载。

---

## 项目结构

```
综述溯源/
├── README.md                         ← 本文档
├── CLAUDE.md                         ← AI 助手指南（含交互流程）
├── scripts/                          ← 所有脚本
│   ├── extract_included_studies.py   ← 快速模式（4字段）
│   ├── extract_full_table.py         ← 完整/全量模式（21+字段）
│   ├── review_dois.py                ← 审查
│   ├── download_pdfs.py              ← API层下载
│   ├── scihub_batch.py               ← Chrome CDP下载
│   ├── panda985_search.py            ← Panda985兜底搜索
│   ├── verify_pdfs.py                ← PDF验证
│   └── launch_chrome_for_scihub.cmd
├── output/                           ← 项目输出（4篇综述）
├── pdf/                              ← 原始综述PDF
└──查找文献pdf/                       ← 独立可复用工具集
```

## Excel 颜色说明

| 🟢 绿色 | PDF 下载成功 + 已验证 |
| 🔴 红色 | 全部层失败，需手动查找 |
| 🟡 黄色 | 下载成功但验证不确定 |

## 常见问题

**Q: refs.json 怎么写？** 打开PDF纳入文献表格，按表格从上到下顺序记录每篇的引用编号 `[N]`。

**Q: 老论文（<1990）下载不到？** 老论文可能无电子版或不在Sci-Hub收录中，需手动查找。
