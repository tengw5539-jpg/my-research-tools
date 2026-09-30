# 综述溯源 — AI 助手指南

> 核心目标：从系统综述/Meta分析 PDF 中提取纳入研究的文献信息，并下载所有原文PDF。
> 所有脚本位于 `scripts/` 目录，通过 `python scripts/<name>.py` 调用。
>
> **通用约定**：处理案例的脚本统一支持 `--name <案例名>`（指向 `output/<案例名>/`）；
> 不传时若 `output/` 下只有一个案例自动选中，多个则报错列出候选。
> 公共逻辑（路径/进度key/命名/PDF校验/停用词）都在 `scripts/common.py`，改那里即可全局生效。

---

## 用户交互流程（必读）

```
你要求"提取这篇综述的纳入文献"
  ↓
我询问：「你要执行哪种模式？」
  ├── ① 快速模式 —— 4字段（作者/DOI/标题/年份）
  ├── ② 核心模式 —— 实际产出 5 字段（first_author/doi/title/year/journal）
  └── ③ 全量提取模式 —— 不预设字段
          ↓
[若选完整模式] 我**如实说明当前实际只能提取 5 个字段**，表格里的
样本量/效应量/研究设计等尚未接通 → 等你确认 → 执行
[若选全量模式] 我说明不预设字段 → 分析表格结构 → 动态提取
          ↓
      提取 + 审查
          ↓
  「提取完成。是否执行模块二（PDF批量下载）？」
  ├── 是 → API层 → Chrome CDP → **Panda985兜底** → 验证
  └── 否 → 结束
          ↓
 PDF下载完成后：
  「是否用 Panda985 (https://sc.panda985.com/index.html) 检索未下载到的文献？」
  ├── 是 → 打开 Panda985 搜索每个缺失 DOI/标题 → 逐一捡漏
  └── 否 → 结束
```

---

## 三种提取模式

### 模式 1：快速模式（4 字段）

```bash
python scripts/extract_included_studies.py "论文.pdf" \
    --refs refs.json --ref-pages "38-41" \
    --title "论文标题" --citation "Author (Year) Journal" \
    --output "output/论文名/论文名.xlsx"

python scripts/review_dois.py "output/论文名/论文名.xlsx" "论文.pdf" \
    --ref-pages "38-41" --json "output/论文名/extracted_data.json"
```

### 模式 2：完整模式 —— ⚠️ 实际只产出 5 个字段

```bash
python scripts/extract_full_table.py "论文.pdf" \
    --refs refs.json --ref-pages "38-41" \
    --output "output/论文名/"
```

**诚实说明**：`FIELD_DEFS` 里声明了 21 个字段，但主流程 `extract_full()` 只从
**参考文献列表**取值，实际有值的只有 5 个：

```
first_author, doi, title, year, journal
```

其余 16 个（`sample_size` / `study_design` / `effect_size` / `ci_lower` / `ci_upper` /
`quality_score` …）**一律输出为空字符串**，`extract_full_table.py:508` 那里统一置空。
文件下半部分的表格解析函数（`detect_table_pages` / `parse_table_with_grid` /
`parse_table_with_blocks`）目前是**没有任何调用点的原型**，`--auto-detect` / `--mode`
两个参数已作为死参数移除。

运行结束后脚本会打印每个字段的填充率。**不要向用户承诺 21 字段，也不要把空值
当成"该研究没有这项数据"。**

### 模式 3：全量提取模式

⚠️ 与模式 2 同样的限制：目前没有真正实现"逐篇分析原文表格结构、动态识别字段"。
实际做法仍是先取核心标识（作者/DOI/标题/年份），再由 AI 人工逐篇读原文补字段，
最后回填 JSON。**向用户说明这一点，不要说成自动化全字段提取。**

---

## 模块二：PDF 批量下载

### 下载顺序（多层降级）

| 层 | 来源 | VPN | 命中率 | 执行方式 |
|----|------|-----|--------|---------|
| L0 | **数据准备** | 否 | — | `python scripts/prep_from_info.py --name <案例名>`（信息表→JSON，含DOI补全） |
| L1 | Europe PMC / Unpaywall / OpenAlex / Semantic Scholar | 否 | ~40% | `python scripts/download_parallel.py`（并发，自动跳过不可用层） |
| L2 | 出版商 meta 标签 | 否 | ~20% | 同上脚本自动 |
| L3 | Sci-Hub 镜像（sg 优先免验证） | **是** | ~40% | 启动调试Chrome → `python scripts/scihub_batch.py` |
| **L4** | **Panda985 搜索** | **是** | ~5% | `python scripts/panda985_search.py`（含内容验证） |
| **L5** | **全网搜索**（政府报告/期刊官网/机构库） | 否 | ~5% | WebSearch 定向搜索，见「全网搜索捡漏」 |
| L6 | 验证 | 否 | — | `python scripts/verify_pdfs.py` + `list_missing.py` |
| L7 | 交付命名 | 否 | — | `python scripts/rename_pdfs.py`（第一作者+题目） |

> **Chrome 调试启动**：优先用 `scripts/launch_chrome_cdp.cmd`（独立 user-data-dir，不杀现有浏览器）。`launch_chrome_for_scihub.cmd` 会 taskkill 所有 Chrome，慎用。

### 全网搜索捡漏方法（L5）

Sci-Hub/Panda985 下不到的文献，用 WebSearch 定向搜索非标准来源：

| 来源 | 适用 | 方法 |
|------|------|------|
| **政府研究报告**（CARB/EPA） | ATS 老文献 | WebSearch `"标题" filetype:pdf site:.gov` → 报告常完整收录原文 |
| **期刊官网** | 非主流/OA期刊 | 找 `citation_pdf_url` meta 或官网 PDF 下载按钮 |
| **大学机构库** | 高校作者新文献 | research.xxx.edu/en/publications 门户 |
| **文献互助平台** | 付费墙兜底 | 全国图书馆参考咨询联盟 ucdrs.superlib.net、掌桥科研 |

### Panda985 使用说明
1. 在 Chrome 中打开 https://sc.panda985.com/index.html
2. 输入标题 → 检索页每篇右侧有「一键下载」→ 弹窗点「SCI-HUB」
3. 下载后**必须内容验证**（脚本已内置），误下载自动删除

---

## 审查检查项（review_dois.py）

| 检查项 | 级别 | 范围 | 内容 |
|--------|------|------|------|
| DOI 唯一性 | CRITICAL | 全部 | 同一DOI分配给多篇文献 |
| DOI 标题匹配 | **ERROR** | **全部** | **改进：从抽样改为全量检查** |
| 单作者论文 | ERROR | 全部 | 不含"et al."的文献是否被遗漏 |
| 作者名异常 | ERROR | 全部 | PDF页眉文本混入作者字段 |
| 同作者同年冲突 | WARNING | 全部 | 同年多篇论文的DOI是否混淆 |
| DOI 验证 | WARNING | **全部** | **改进：全量 OpenAlex 验证** |

**通过标准**：0 CRITICAL + 0 ERROR

---

## 踩坑记录

### 提取阶段

| 问题 | 表现 | 原因 | 对策 |
|------|------|------|------|
| **DOI 交错匹配** | 同作者同年多篇论文DOI互换 | CrossRef 关键词模糊 | 提取后用 OpenAlex 全量验证+标题对比 |
| **单作者论文丢失** | 计数比PRISMA少 | "et al." 正则过滤 | 加 fallback 正则捕获单作者 |
| **背景引用混入** | 多出若干条非纳入文献 | 正文引用混杂在表格页 | 手动核验 PRISMA 数字 |
| **出版商格式差异** | MDPI/Springer/Frontiers 参考文献格式完全不同 | 无统一标准 | 多路解析策略轮换 |
| **DOI 爬虫限流** | 429 Too Many Requests | CrossRef 频率限制 | 限制请求频率+重试队列 |

### 下载阶段

| 问题 | 表现 | 原因 | 对策 |
|------|------|------|------|
| **Chrome 断连** | TargetClosedError | 脚本异常导致 | 加心跳检测+重连 |
| **Cloudflare 验证** | 需要人工点"我不是机器人" | 反爬机制 | 借助 CDP 利用用户已有 Chrome |
| **Sci-Hub 域名被封** | st/ru/se/do 逐一失效 | 国内网络封锁 | 维护域名轮换列表（sg 免验证优先） |
| **开放获取反向被墙** | EHP OA 文章却下不到 | DNS 污染 | 多路由兜底+提示手动 |
| **panda985 脚本缺陷** | download_progress.json 不存在时返回空列表 | 代码逻辑 bug | 不存在时按全量需下载处理 |
| **目录分歧** | scripts/ 和 查找文献pdf/scripts/ 各有一套 | 版本管理失误 | 统一合并 |
| **中文验证码漏检** | 12篇老文献被误判失败 | 只检测英文 captcha，漏中文"你是机器人吗" | 验证码特征覆盖中英文 |
| **challenge 词误匹配** | 标题含"challenge"被当验证码白等240s | 验证码关键词过宽 | 先找PDF再判断标题，移除宽泛词 |
| **Chrome 调试实例崩溃** | ECONNREFUSED 9222 | 反复开关tab、expect_popup、user-data损坏 | 独立干净user-data-dir，崩溃后删除重启 |
| **Panda985 误下载** | 下到会议摘要集/无关文章 | 遍历链接选错目标 | 下载后fitz内容验证（DOI+标题关键词） |
| **波斯语/非拉丁文献验证误判** | 波斯语论文被判"内容不符" | 正文无英文字母，英文关键词匹配失败 | verify_merged.py 检测非ASCII占比→multilang待人工确认 |
| **中文文献验证误判** | 中文标题无法用英文关键词匹配 | 标题是中文 | verify_merged.py 按作者匹配+中文特殊处理 |
| **同作者多篇匹配混淆** | 同作者多篇文献文件名匹配错乱 | 标题关键词重叠 | 严格匹配：作者前缀+唯一关键词，阈值降为1 |
| **扫描版无文本层** | PDF无文本（纯图片） | 扫描版 | OCR确认（pytesseract）或标注scanned待确认 |
| **新文献付费墙** | 2023+文献各源都下不到 | 无OA版本 | 用全国图书馆参考咨询联盟/联系作者 |
| **无DOI会议摘要** | Sci-Hub无法检索 | 只有摘要无全文 | 标题搜索期刊官网/接受无法获取 |
| **Sci-Hub未收录老文献** | 1982-83 ATS文章没有 | 未入库 | 查CARB/EPA政府研究报告是否收录原文 |



---

## 项目结构

```
D:\知识库\my-research-tools\综述溯源+ai批量找原文pdf小工具\
├── CLAUDE.md                ← 本文档
├── README.md                ← 人类操作指南（含全网搜索捡漏方法）
├── .claude/skills/          ← lit-review-extractor（同能力的 skill 形态）
├── scripts/                 ← 所有可执行脚本
│   ├── prep_from_info.py             ← 数据准备：信息表→JSON（含DOI补全）
│   ├── extract_included_studies.py   ← 快速模式（4字段）
│   ├── extract_full_table.py         ← 完整/全量模式（21+字段）
│   ├── review_dois.py                ← 独立审查
│   ├── download_parallel.py          ← 推荐：API层并发下载
│   ├── download_pdfs.py              ← API层原始版（11层）
│   ├── scihub_batch.py               ← 推荐：Sci-Hub批量（修复版）
│   ├── panda985_search.py            ← Panda985捡漏（含内容验证）
│   ├── verify_pdfs.py                ← PDF验证
│   ├── verify_merged.py              ← 增强版PDF验证（多语言/扫描版OCR/中文/严格匹配）
│   ├── list_missing.py               ← 缺失清单
│   ├── rename_pdfs.py                ← 重命名（第一作者+题目）
│   ├── launch_chrome_cdp.cmd         ← 推荐：启动调试Chrome（不杀现有）
│   └── launch_chrome_for_scihub.cmd  ← 旧版（会杀所有Chrome，慎用）
├── 查找文献pdf/             ← 旧版独立工具包（8个脚本，未同步更新）
├── output/                  ← 项目输出（按案例分目录）
│   └── Morici_2020/         ← 示例案例
└── pdf/                     ← 原始综述PDF
```
