# PDF检索下载工具包 -- 系统综述纳入文献原文批量获取

## 目录结构

```
综述溯源/
├── CLAUDE.md                          <- AI 助手指南
├── README.md                          <- 人类操作指南
├── 信息表.xlsx                        <- 用户文献信息表（可选）
├── scripts/
│   ├── prep_from_info.py              <- 数据准备：信息表→JSON（含DOI补全）
│   ├── download_parallel.py           <- 推荐：API层并发下载
│   ├── download_pdfs.py               <- 主入口：11层降级下载（旧版）
│   ├── scihub_batch.py                <- Sci-Hub Chrome CDP批量（修复版）
│   ├── panda985_search.py             <- Panda985搜索（含内容验证）
│   ├── launch_chrome_cdp.cmd          <- 推荐：启动调试Chrome（不杀现有）
│   ├── launch_chrome_for_scihub.cmd   <- 旧版启动（会杀所有Chrome，慎用）
│   ├── extract_included_studies.py    <- 提取DOI/作者/标题
│   ├── review_dois.py                 <- 审查提取质量
│   ├── verify_pdfs.py                 <- PDF验证
│   ├── list_missing.py                <- 缺失清单
│   └── rename_pdfs.py                 <- 重命名（第一作者+题目）
└── output/                            <- 项目输出目录
    └── 你的论文名/
        ├── extracted_data.json
        ├── download_progress.json     <- 断点续传
        └── pdfs/                      <- 下载的PDF原文
```

## 前置条件

```bash
pip install pymupdf openpyxl beautifulsoup4 requests pandas playwright
python -m playwright install chromium
```

## 完整工作流（四步）

### 步骤零：数据准备（有信息表时）

```bash
# 从 信息表.xlsx 生成 extracted_data.json，自动补全缺失DOI
python scripts/prep_from_info.py --name 文献pdf
```

### 步骤一：提取纳入文献信息（无信息表时）

```bash
python scripts/extract_included_studies.py "综述.pdf" \
    --refs papers/论文名/refs.json \
    --ref-pages "38-41" --title "论文标题" --citation "Author (Year) Journal" \
    --output "papers/论文名/result.xlsx"

python scripts/review_dois.py "papers/论文名/result.xlsx" "综述.pdf" \
    --ref-pages "38-41" --json "papers/论文名/extracted_data.json"
```

### 步骤二：API层下载（L1-L8，无需VPN）

```bash
python scripts/download_parallel.py
```

这会自动发现 output/ 下所有包含 extracted_data.json 的目录，并发下载：
- L1: Europe PMC 全文 PDF
- L2: Unpaywall OA PDF
- L3: OpenAlex OA URL
- L4: Semantic Scholar OA PDF
- L5: 出版商 citation_pdf_url meta
- L6-L8: 镜像/学术搜索

预计覆盖率：30-40%。

### 步骤三：Sci-Hub 批量下载（L3，需VPN）

```bash
# 1. 启动调试Chrome（推荐，不杀现有浏览器）
scripts/launch_chrome_cdp.cmd
# 2. 在 Chrome 中访问 https://sci-hub.sg，如遇验证码手动通过
# 3. 运行批量下载
python scripts/scihub_batch.py
```

**关键**：修复版已覆盖中文验证码检测 + 内容验证 + 多镜像轮换。

### 步骤四：Panda985 捡漏（需VPN）

```bash
python scripts/panda985_search.py
```

流程：搜索标题 → 每篇右侧「一键下载」→ 弹窗点「SCI-HUB」→ 跳转下载。

### 步骤五：全网搜索补漏（无需VPN）

用 WebSearch 定向搜索非标准来源：
- **政府研究报告**（CARB/EPA）：ATS 老文献常被完整收录
- **期刊官网**：找 citation_pdf_url meta
- **大学机构库**：research.xxx.edu/en/publications

### 步骤六：验证 + 交付

```bash
python scripts/verify_pdfs.py
python scripts/list_missing.py
python scripts/rename_pdfs.py   # 重命名为「第一作者+题目」
```

## 11层下载策略详解（download_pdfs.py 原始版）

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

1. **Sci-Hub中文验证码**：只检测英文 `captcha` 会漏检"你是机器人吗？"，须覆盖中英文
2. **"challenge"误匹配**：标题含 challenge 会被当验证码，**先找PDF再判断标题**
3. **Chrome调试实例崩溃**：ECONNREFUSED 9222 → 删除 user-data-dir 干净重启
4. **Panda985误下载**：会下到会议摘要集/无关文章 → 必须 fitz 内容验证
5. **新文献付费墙**（2023+）：无OA版本 → 全国图书馆参考咨询联盟/联系作者
6. **老文献未收录**（ATS 1982-83）：查 CARB/EPA 政府研究报告
7. **断点续传**：download_progress.json 自动记录，重复运行只处理失败项
