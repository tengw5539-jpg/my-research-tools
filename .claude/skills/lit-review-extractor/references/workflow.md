# PDF检索下载工具包 -- 系统综述纳入文献原文批量获取

## 目录结构

```
查找文献pdf/
├── README.md                          <- 本文档
├── scripts/
│   ├── download_pdfs.py               <- 主入口：11层降级下载（L1-L11）
│   ├── scihub_batch.py                <- Sci-Hub Chrome CDP批量下载
│   ├── panda985_search.py             <- Panda985搜索->出版商->PDF下载
│   ├── launch_chrome_for_scihub.cmd   <- Windows启动Chrome调试模式
│   ├── extract_included_studies.py    <- 提取DOI/作者/标题
│   └── review_dois.py                 <- 审查提取质量
├── examples/
│   ├── extracted_data.json            <- 示例提取数据
│   └── refs.json                      <- 示例引用编号列表
└── papers/                            <- 论文输出目录（放这里）
    └── 你的论文名/
        ├── extracted_data.json
        ├── download_progress.json     <- 断点续传
        ├── refs.json
        └── pdfs/                       <- 下载的PDF原文
```

## 前置条件

```bash
# 1. 安装Python依赖（一次性）
pip install pymupdf openpyxl beautifulsoup4 requests playwright
python -m playwright install chromium

# 2. （仅限L9-L11，可选）打开全局VPN
# 3. （仅限L9-L11，可选）启动Chrome调试模式
#    双击 scripts\launch_chrome_for_scihub.cmd
```

## 完整工作流（三步）

### 步骤一：提取纳入文献信息

```bash
# 1. 准备 refs.json -- 按PDF表格顺序记录所有引用编号
# 2. 提取
python scripts/extract_included_studies.py "综述.pdf" \
    --refs papers/论文名/refs.json \
    --ref-pages "38-41" \
    --title "论文标题" \
    --citation "Author (Year) Journal" \
    --output "papers/论文名/result.xlsx"

# 3. 审查
python scripts/review_dois.py "papers/论文名/result.xlsx" "综述.pdf" \
    --ref-pages "38-41" \
    --json "papers/论文名/extracted_data.json"

# 4. 修复问题至 0 CRITICAL + 0 ERROR
```

### 步骤二：API层下载（L1-L8，无需VPN）

```bash
python scripts/download_pdfs.py --skip-vpn
```

这会自动发现 papers/ 下所有包含 extracted_data.json 的目录，依次尝试：
- L1: Europe PMC 全文 PDF
- L2: Unpaywall OA PDF
- L3: OpenAlex OA URL
- L4: Semantic Scholar OA PDF
- L5: 出版商 citation_pdf_url meta
- L6: Sci-Hub panda985 镜像
- L7: X-MOL 学术搜索
- L8: 673 Scholar Google Scholar镜像

预计覆盖率：30-40%。完成后 Excel 绿色=成功，红色=失败。

### 步骤三：Chrome CDP 批量下载（L9-L11，需VPN）

```bash
# 1. 双击 launch_chrome_for_scihub.cmd
# 2. 在弹出的 Chrome 中打开 https://sci-hub.st，过掉验证码
# 3. 运行批量下载
python scripts/scihub_batch.py

# 4. （可选兜底）Panda985搜索
python scripts/panda985_search.py
```

预计最终覆盖率：85-97%。剩余的通常是无DOI老论文（<1990）或会议摘要。

### 步骤四：验证

```bash
# 检查各论文的PDF数量
python scripts/download_pdfs.py --dry-run

# 或手动查看
for d in papers/*/pdfs/; do echo "$(basename $(dirname $d)): $(ls "$d" | wc -l)"; done
```

## 11层下载策略详解

| 层 | 方法 | VPN | 命中率 | 原理 |
|----|------|-----|--------|------|
| L1 | Europe PMC | 否 | 40% | DOI->PMCID->europepmc.org?pdf=render |
| L2 | Unpaywall | 否 | 15% | best_oa_location.url_for_pdf |
| L3 | OpenAlex | 否 | 10% | open_access.oa_url |
| L4 | Semantic Scholar | 否 | 10% | openAccessPdf.url |
| L5 | 出版商 | 否 | 20% | citation_pdf_url meta标签 |
| L6 | Sci-Hub镜像 | 否 | 5% | panda985 embed/iframe |
| L7 | X-MOL | 否 | 2% | 中文学术搜索 |
| L8 | 673 Scholar | 否 | 2% | Google Scholar镜像 |
| L9 | Sci-Hub直连 | 是 | 30% | sci-hub.se/ru/st |
| L10 | Playwright | 是 | 20% | 真实浏览器+点击按钮 |
| L11 | Panda985搜索 | 是 | 5% | 搜标题->出版商->PDF |

## 典型踩坑

1. **Sci-Hub域名选择**：sci-hub.st（通用）+ sci-hub.jp（老论文/特殊DOI格式）
2. **Cloudflare反爬**：必须用Chrome CDP连接你的真实浏览器
3. **DOI中的斜杠**：如 10.1164/ajrccm/140.1.211，sci-hub.st 可能不收，换 sci-hub.jp
4. **编码问题**：所有脚本使用纯英文注释，避免中文字符导致的编码错误
5. **断点续传**：download_progress.json 自动记录，重复运行只处理失败项
