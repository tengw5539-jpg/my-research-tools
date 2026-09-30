# 查找文献PDF — 独立工具集

可脱离主项目独立使用的PDF检索下载工具包。把你的论文数据放进 `papers/` 目录即可自动处理。

---

## 前置条件

```bash
pip install pymupdf openpyxl beautifulsoup4 requests playwright
python -m playwright install chromium
```

---

## 使用流程

```bash
# 1. 把你的论文数据放入 papers/：
#    papers/论文名/extracted_data.json

# 2. API 下载（无需 VPN，30-40%命中率）
python scripts/download_pdfs.py --skip-vpn

# 3. Chrome CDP 下载（需 VPN + Chrome 调试模式）
#    双击 scripts/launch_chrome_for_scihub.cmd
#    在 Chrome 中过掉 https://sci-hub.st 验证码
python scripts/scihub_batch.py

# 4. Panda985 兜底（需VPN，Sci-Hub下载完成后仍缺失时使用）
#    打开 https://sc.panda985.com/index.html
#    逐篇搜索缺失文献的DOI或标题，手动下载
python scripts/panda985_search.py

# 5. 验证
python scripts/verify_pdfs.py
```

---

## 下载策略

| 层 | 来源 | VPN | 说明 |
|----|------|-----|------|
| L1 | Europe PMC / Unpaywall / OpenAlex | 否 | API免费下载 |
| L2 | 出版商meta标签 | 否 | 从DOI页面提取PDF链接 |
| L3 | Sci-Hub + Chrome CDP | 是 | 真实浏览器绕过Cloudflare |
| **L4** | **Panda985 (https://sc.panda985.com/index.html)** | **是** | **Sci-Hub未收录的文献兜底** |
| L5 | 验证 | 否 | PDF交叉验证 |

---

## 目录结构

```
查找文献pdf/
├── README.md                       ← 本文档
├── scripts/                        ← 8个脚本
│   ├── download_pdfs.py            ← API层下载
│   ├── scihub_batch.py             ← Chrome CDP批量下载
│   ├── panda985_search.py          ← Panda985兜底搜索
│   ├── verify_pdfs.py              ← PDF交叉验证
│   ├── extract_included_studies.py ← 快速提取（4字段）
│   ├── extract_full_table.py       ← 完整/全量提取（21+字段）
│   ├── review_dois.py              ← 审查
│   └── launch_chrome_for_scihub.cmd
├── papers/                         ← 放你的论文数据
│   └── 论文名/
│       ├── extracted_data.json     ← 必须
│       ├── download_progress.json  ← 自动生成
│       └── pdfs/                   ← 下载的PDF
└── examples/                       ← 示例数据
```

## extracted_data.json 格式

```json
[
  {
    "no": 1, "ref": 23,
    "first_author": "Andersen",
    "doi": "10.1289/ehp.1408698",
    "title": "A study of the combined effects...",
    "year": "2015"
  }
]
```
