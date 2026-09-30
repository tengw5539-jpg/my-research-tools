# 综述溯源 — 纳入文献提取与 PDF 原文下载工具

## 这是什么？

一套**自动化 + 人工兜底**的系统综述文献提取与 PDF 原文下载工具。把综述 PDF 给你，它能：

1. **提取所有纳入文献信息** — 三种模式可选
2. **自动下载原文 PDF** — 多层降级策略，从 API 层到 Sci-Hub 到政府报告全覆盖
3. **逐篇验证 PDF 内容** — DOI/标题/作者三重交叉核对，杜绝下错文献

已在 **5 篇综述**上验证（85 篇纳入文献），本次"空气污染×运动×健康"综述 **47 篇中下载 38 篇（81%）**。

---

## 前置条件（一次性）

```bash
pip install -r requirements.txt
python -m playwright install chromium   # 仅 Sci-Hub / Panda985 层需要
```

> 注意：`xlsxwriter` 是**必需**依赖（`extract_included_studies.py` 写结果表用它）。
> 旧版 README 的安装命令里漏了它，新环境装上后会直接 `sys.exit(1)`。

---

## 完整工作流

```bash
# Step 0: 数据准备 —— 从信息表生成下载输入
python scripts/prep_from_info.py --name <案例名>
#   ↑ 读取 信息表.xlsx，生成 output/<案例名>/extracted_data.json
#   ↑ 自动用 OpenAlex 补全缺失 DOI

> **关于 `--name`**：下面所有脚本都支持 `--name <案例名>`（指向 `output/<案例名>/`）。
> 不传时，若 `output/` 下只有一个案例会自动选中，有多个则报错并列出候选让你挑。
> 旧版把案例名写死成 `文献pdf`，换案例必须改源码，且该目录不存在导致脚本开箱即崩 —— 已修复。

```bash

# Step 1: 提取（三种模式之一，已有信息表可跳过）
python scripts/extract_included_studies.py "论文.pdf" --refs refs.json --ref-pages "38-41" --output "output/结果.xlsx"

# Step 2: 审查（必须到 0 CRITICAL + 0 ERROR）
python scripts/review_dois.py "output/结果.xlsx" "论文.pdf" --ref-pages "38-41" --json "output/extracted_data.json"

# Step 3: API层下载（无需VPN）
python scripts/download_parallel.py
#   ↑ 并发版，自动跳过不可用层，遇 Chrome CDP 未开则跳过 Playwright/Panda985

# Step 4: Sci-Hub 下载（需 VPN + Chrome 调试）
# ① 启动调试 Chrome（不杀现有浏览器）
scripts/launch_chrome_cdp.cmd
# ② 在打开的 Chrome 里访问 https://sci-hub.sg 过掉验证码（如需要）
python scripts/scihub_batch.py
#   ↑ 修复版：中文验证码检测 + 多镜像轮换 + 下载后内容验证

# Step 5: Panda985 捡漏（需 VPN + Chrome 调试）
python scripts/panda985_search.py
#   ↑ 首页搜索框 + 遍历结果 + 内容验证（自动跳过误下载）

# Step 6: 验证所有 PDF
python scripts/verify_pdfs.py        # 标准验证（按 PDF 正文匹配，非文件名）
python scripts/verify_merged.py --pdfdir "合并全部PDF" --xlsx "信息表.xlsx"   # 增强版（多语言/扫描版/中文）
python scripts/list_missing.py       # 列出缺失文献

# Step 6.5: 进度与磁盘对不上时（有文件却被报缺失），用磁盘上的 PDF 回填进度
python scripts/reconcile_progress.py            # 先预览认领结果
python scripts/reconcile_progress.py --apply    # 确认无误后写入

# Step 7: 归一名交付（第一作者_年份_题目，幂等，重跑安全）
python scripts/rename_pdfs.py
```

---

## 下载策略（多层降级）

| 层 | 来源 | VPN | 命中率 | 执行 |
|----|------|-----|--------|------|
| L1 | Europe PMC / Unpaywall / OpenAlex / Semantic Scholar | 否 | ~40% | `download_parallel.py` |
| L2 | 出版商 meta 标签 | 否 | ~20% | 同上（自动） |
| L3 | Sci-Hub 直连（sg 镜像免验证） | 是 | ~40% | Chrome 调试 + `scihub_batch.py` |
| L4 | Panda985 搜索 | 是 | ~5% | `panda985_search.py` |
| L5 | **全网搜索**（政府报告/期刊官网/机构库） | 否 | ~5% | WebSearch 定向搜索 |
| L6 | 人工兜底（文献传递/作者索取） | — | — | 见下文 |

> **关于层编号**：上表是按"来源大类"划分的口径（README/CLAUDE 用）。
> 代码实现是 `download_pdfs.py` 的 `DOWNLOADERS` 列表，**共 11 层**
> （PMC / Unpaywall / OpenAlex / SemScholar / Publisher / SciHub-Mirror / X-MOL /
> Scholar673 / SciHub-Direct / Playwright / Panda985）。两者不是一回事，别混用。
> `download_parallel.py` 默认剔除长期超时的 Scholar673，并可用 `--keep-scholar673` 保留。

> **关键发现**：Sci-Hub 只收录部分老文献。新文献（2023+）付费墙、ATS 老文献可能未收录、会议摘要无全文 —— 这些需要**全网搜索**找非标准来源。

---

## 全网搜索捡漏方法（本次实战总结）

### ✅ 政府研究报告 = 老文献富矿
ATS 老文献（如 Am Rev Respir Dis 1982）在 Sci-Hub 没有，但**资助机构的研究报告**完整收录原文：
- 加州 CARB：`ww2.arb.ca.gov/sites/default/files/classic/research/...`
- EPA NEPIS：`nepis.epa.gov`
- **方法**：WebSearch 搜 `"标题关键词" filetype:pdf site:.gov` → 下载报告 → fitz 搜索关键词定位原文页 → 提取独立 PDF

### ✅ 期刊官网 = 捡漏金矿
- 非主流期刊官网常免费提供 PDF（伊朗期刊、中文期刊、OA 期刊）
- 方法：找 `citation_pdf_url` meta 标签，或官网 PDF 下载按钮

### ✅ 大学机构库
- Monash/中山/北大等机构的门户（research.xxx.edu/en/publications）
- 常收录作者自存版；但部分需登录

### 🔴 剩余付费墙文献的合规兜底
1. **全国图书馆参考咨询联盟**：http://www.ucdrs.superlib.net —— 免费文献传递，填表后邮箱收 PDF
2. **掌桥科研**：https://www.zhangqiaokeyan.com —— 文献互助/单篇购买
3. **ResearchGate**：给作者发私信索取
4. **邮件索取**：PubMed 找通讯作者邮箱

---

## 项目结构

```
综述溯源+ai批量找原文pdf小工具/
├── requirements.txt                  ← 依赖清单（pip install -r requirements.txt）
├── domain_stopwords.txt              ← 领域停用词（换课题只需改这里，别写死进脚本）
├── CLAUDE.md                         ← AI 助手指南（含交互流程）
├── README.md                         ← 本文档
├── CODE_REVIEW.md                    ← 代码审查报告（问题清单 + 优先级）
├── tests/                            ← pytest 单元测试（python -m pytest tests/）
├── .claude/skills/                   ← lit-review-extractor（skill 形态副本）
├── scripts/                          ← 【唯一真源】所有可执行脚本
│   ├── common.py                     ← 【公共模块】路径解析/进度key/命名/PDF校验/停用词
│   ├── prep_from_info.py             ← 【数据准备】信息表 → extracted_data.json（含DOI补全）
│   ├── extract_included_studies.py   ← 快速模式（4字段）
│   ├── extract_full_table.py         ← 核心字段提取（目前实际产出 5 个字段，见文件头）
│   ├── review_dois.py                ← 独立审查
│   ├── download_parallel.py          ← 【推荐】API层并发下载
│   ├── download_pdfs.py              ← 下载引擎（多层降级），被 download_parallel 复用
│   ├── scihub_batch.py               ← 【推荐】Sci-Hub 批量（中文验证码+内容验证）
│   ├── panda985_search.py            ← Panda985 捡漏（含内容验证）
│   ├── verify_pdfs.py                ← PDF 验证（按正文 DOI/作者/标题匹配）
│   ├── verify_merged.py              ← 增强版验证（多语言/扫描版/中文）
│   ├── reconcile_progress.py         ← 用磁盘上的 PDF 回填 download_progress.json
│   ├── list_missing.py               ← 列出缺失文献
│   ├── rename_pdfs.py                ← 归一名（第一作者_年份_题目，幂等）
│   ├── sync_scripts.py               ← scripts/ → 副本目录单向同步（只写不删，自动备份）
│   ├── launch_chrome_cdp.cmd         ← 启动调试Chrome（不杀现有浏览器，推荐）
│   └── launch_chrome_for_scihub.cmd  ← 旧版启动（会杀掉所有Chrome，慎用）
├── 查找文献pdf/                      ← 旧版独立工具包（已冻结，未同步本轮改动）
├── output/                           ← 项目输出（按案例分目录）
│   └── Morici_2020/                  ← 示例案例
└── pdf/                              ← 原始综述PDF
```

> **三份副本**：`scripts/` 是唯一真源，`.claude/skills/.../scripts/` 是给 skill 用的镜像
> （已用 `sync_scripts.py --targets skill` 同步），`查找文献pdf/` 是历史版本，本轮**刻意未动**。
> 改动后用 `python scripts/sync_scripts.py --apply` 同步，该脚本只写不删、覆盖前自动备份。

---

## 实战经验（重要）

### 🔧 验证码处理
- Sci-Hub 有**中文验证码**"你是机器人吗？"，只检测英文 `captcha` 会漏检导致误判失败
- **验证码检测要覆盖中英文**，且**先找 PDF 再判断标题**（标题含 "challenge" 等词会误判）
- 遇到验证码：`launch_chrome_cdp.cmd` 打开的 Chrome 里手动过，或换镜像（sg 通常免验证）

### 🔧 Chrome 调试实例
- 用**独立 user-data-dir**（如 `C:/temp/chrome_debug_new`），不影响日常浏览器
- 调试实例易崩溃，崩溃后干净重启：删除 user-data-dir 再启动
- 尽量少开/关 tab，`expect_popup` 处理要小心

### 🔧 下载后必须验证内容
- Panda985 遍历链接会下到**错误文献**（会议摘要集、无关文章）
- 每个 PDF 用 fitz 提取首页 → DOI 精确匹配 + 标题关键词对比
- 只有验证通过才保存，否则删除

### 🔧 特殊文献的验证（verify_merged.py 增强版）
| 情况 | 表现 | 处理 |
|------|------|------|
| **波斯语/非拉丁文献** | 正文无英文字母，英文关键词匹配失败 | 检测非ASCII占比→标注 multilang 待人工确认 |
| **中文文献** | 标题是中文，英文关键词无法匹配 | 按作者前缀匹配 + 中文特殊处理 |
| **扫描版** | PDF 无文本层（纯图片） | OCR 确认或标注 scanned |
| **乱码版** | 字体编码问题，文本层乱码 | OCR 确认（如 Adams 2000） |
| **同作者多篇** | 同作者多篇文件名匹配错乱 | 作者前缀 + 标题唯一关键词严格匹配 |

```bash
# 合并多批 PDF 后统一验证
python scripts/verify_merged.py --pdfdir "合并全部PDF" --xlsx "信息表.xlsx"
# 输出: ok / weak / scanned / cn_verify / multilang / suspicious / unmatched
```

### 🔧 本轮重构改动对照（详见 CODE_REVIEW.md）

| 旧版问题 | 修复 |
|---------|------|
| 中文验证码漏检 | 中英文特征全覆盖 |
| `challenge` 误匹配 | 先找 PDF 再判断标题 |
| 逐篇串行太慢 | `download_parallel.py` 并发（默认 3 线程，`--workers` 可调） |
| Panda985 误下载 | 下载后 fitz 内容验证 |
| Chrome CDP 未开也硬试 | 自动检测跳过 Playwright/Panda985 层 |
| **案例名写死 `文献pdf`，该目录还不存在** | 统一 `--name`，缺省自动识别 `output/` 下唯一案例 |
| **三个脚本各自一套 progress key** | 统一 `{案例}_{no}`，载入时自动迁移旧 key |
| **`download_progress.json` 缺失即崩** | 按空进度处理 |
| **验证不通过仍写盘并中断后续层** | 记录后继续下一层；全部层都不符才判 uncertain |
| **PDF 解析异常反而返回"通过"** | 一律判不通过（`unverifiable`） |
| **verify_pdfs 拿文件名自证** | 改为比对 PDF 正文（DOI/作者/标题关键词） |
| **`requests.Session` 多线程共用** | 改为每线程独立 Session |
| **重复跑一次 Excel 就多两列** | `update_excel` 幂等，复用已有的状态列 |
| **18 处裸 `except:`** | 全部收窄为 `except Exception:` |
| **领域停用词硬编码在 3 个脚本里** | 外置到 `domain_stopwords.txt` |
| **`review_dois` 说是全量实为抽样** | 改为全量 + 429 退避重试；网络失败降级 WARNING 不算 ERROR |
| **0 测试** | `tests/test_common.py`（17 个用例），`pytest` 全绿 |

> ⚠️ **行为变更（会影响结果，知悉后再用）**
> 1. 内容验证不通过的文件**不再落盘**，会继续尝试后续下载层。
> 2. 无法解析的 PDF 不再被当作"验证通过"放行（原先会静默写成 ok）。
> 3. `extract_included_studies.py` 中"OpenAlex 查不到的 DOI"不再标绿。
> 4. Sci-Hub / Panda985 改用独立新标签页，不再抢占你正在浏览的那个页面。

---

## Excel 颜色说明

| 🟢 绿色 | PDF 下载成功 + 已验证 |
| 🔴 红色 | 全部层失败，需手动查找 |
| 🟡 黄色 | 下载成功但验证不确定 / 误下已删 |

## 常见问题

**Q: 信息表.xlsx 怎么用？** 运行 `python scripts/prep_from_info.py --name <案例名>`，自动转换为下载输入，并补全缺失 DOI。

**Q: 有 PDF 文件，list_missing 却报"已下 0"？** 进度文件和磁盘不同步了（旧 key 格式 / 路径失效 / 人工合并过批次）。跑 `python scripts/reconcile_progress.py` 预览，确认认领无误后 `--apply`。

**Q: Sci-Hub 下不到的文献怎么办？** 用 WebSearch 搜政府报告/期刊官网/机构库；仍无则用全国图书馆参考咨询联盟文献传递或联系作者。

**Q: 老论文（<1990）下载不到？** 老论文可能无电子版，优先查 CARB/EPA 等政府研究报告是否收录。

**Q: 换了个课题（不是空气/运动），要改什么？** 只需替换项目根目录的 `domain_stopwords.txt`。正文里那些通用英文停用词在 `scripts/common.py`，一般不用动。

**Q: 怎么确认改动没跑偏？** `python -m pytest tests/ -q`（17 个用例覆盖路径解析、进度迁移、PDF 校验等纯函数）。
