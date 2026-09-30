# 项目审查报告 — 综述溯源 + AI 批量找原文 PDF 工具

> 审查日期：2026-10-01 | 审查范围：`scripts/` 全部 13 个脚本、`查找文献pdf/`、`.claude/skills/lit-review-extractor/`、README/CLAUDE/SKILL 文档
> **本次仅审查，未修改任何代码。** 所有改动需你确认后执行。

---

## 一、项目梳理

### 1.1 技术栈

| 层 | 技术 |
|----|------|
| 语言 | Python 3.13（`__pycache__` 为 cpython-313） |
| PDF 解析 | PyMuPDF (`fitz`)、pdfplumber（可选，网格线检测） |
| 网络 | `requests`（批量下载）、`urllib`（提取/审查脚本） |
| 解析 | BeautifulSoup4 |
| 表格 | pandas（读 Excel）、openpyxl（改 Excel）、xlsxwriter（写 Excel） |
| 浏览器 | Playwright + Chrome CDP（`localhost:9222`），仅 Sci-Hub / Panda985 层 |
| 外部 API | OpenAlex、CrossRef、Unpaywall、Europe PMC、Semantic Scholar |
| 非 API 源 | Sci-Hub 镜像（sg/st/ru）、Panda985、X-MOL、673 Scholar |

### 1.2 目录结构

```
综述溯源+ai批量找原文pdf小工具/
├── CLAUDE.md / README.md          # 人类 + AI 操作指南（内容高度重复）
├── .claude/skills/lit-review-extractor/
│   ├── SKILL.md                   # skill 形态（v4.0）
│   ├── scripts/                   # ★ scripts/ 的副本，11/12 完全相同
│   └── scripts_backup_0727/       # 7 个历史备份脚本
├── scripts/                       # ★ 事实上的唯一真源（13 个）
├── 查找文献pdf/                   # ★ 旧版独立工具包（8 个脚本）
├── output/Morici_2020/            # 唯一产出案例（extracted_data.json + 26 PDFs）
└── pdf/综述(1).pdf                # 输入综述
```

### 1.3 核心模块职责

| 脚本 | 职责 | 输入 → 输出 |
|------|------|------------|
| `prep_from_info.py` | 数据准备：信息表→JSON，OpenAlex 补 DOI | `信息表.xlsx` → `extracted_data.json` |
| `extract_included_studies.py` | 快速模式（4 字段） | 综述 PDF → xlsx + `extracted_data.json` |
| `extract_full_table.py` | 完整模式（宣称 21 字段） | 综述 PDF → `extracted_data.json` + `review_issues.json` |
| `review_dois.py` | 独立审查（6 条规则） | JSON + PDF → 审查报告 |
| `download_pdfs.py` | 11 层下载引擎（被复用） | — |
| `download_parallel.py` | ⭐推荐：API 层并发下载（3 线程） | JSON → pdfs + `download_progress.json` |
| `scihub_batch.py` | ⭐推荐：Sci-Hub 批量（中文验证码修复版） | 同上 |
| `panda985_search.py` | Panda985 捡漏（含内容验证） | 同上 |
| `verify_pdfs.py` / `verify_merged.py` | PDF 内容交叉验证 | pdfs + 记录 → 验证报告 |
| `list_missing.py` / `rename_pdfs.py` | 缺失清单 / 交付重命名 | — |

### 1.4 主要数据流

```
综述 PDF ──extract_*──> extracted_data.json ──┬── review_dois.py ──> 审查报告
信息表.xlsx ─prep_from_info──┘                 │
                                               ├── download_parallel.py (L1–L8)
                                               ├── scihub_batch.py      (L3)
                                               └── panda985_search.py   (L4)
                                                        ↓
                                        pdfs/*.pdf + download_progress.json
                                                        ↓
                              verify_pdfs.py / verify_merged.py → list_missing.py → rename_pdfs.py
```

**共享状态**：`download_progress.json`（键 → `{status, pdf_path, source, details}`）是全流程唯一的跨脚本状态文件，也是最大的隐患点（见 P1）。

### 1.5 架构优点

1. **分层降级 + 断点续跑**设计正确，容错能力强，是本项目最有价值的部分。
2. **下载后 fitz 内容验证**（DOI 精确匹配 + 标题关键词 + 作者）有效避免了 Panda985 遍历链接的误下载。
3. 实战踩坑沉淀进文档（中英文验证码、`challenge` 误匹配、扫描版/多语言/中文文献处理）——这批经验比代码本身更值钱。
4. 脚本职责单一、CLI 参数清晰，单脚本可读性好。
5. `download_parallel.py` 自动探测 CDP 可用性并跳过不可用层，降级判断做得干净。

### 1.6 架构隐患

1. **没有统一配置层**：每个脚本各自算 `BASE`、`DIR`，各自硬编码案例名 → 状态文件 key 规则分裂。
2. **三份代码副本已产生版本漂移**（`extract_included_studies.py` 差 10 行；`panda985_search.py` 差 277 行；`scihub_batch.py` 差 243 行）。
3. **零测试、零日志、零依赖清单**，全部靠 `print` + `sys.stdout.reconfigure`。
4. **通过修改被导入模块的全局变量做配置**（`download_parallel.py` 改 `dp.SKIP_VPN`、`dp.DOWNLOADERS`），耦合脆弱且不可测试。
5. **文档与代码已脱节**：README 说 6 层、SKILL.md 说 8 层、代码是 11 层；文档称 21 字段，实际只产出 5 个非空字段。

---

## 二、问题汇总表

**严重级别**：高 = 会导致崩溃/结果错误/数据损坏；中 = 影响可维护性或特定场景失败；低 = 规范与可读性。

| # | 问题 | 位置 | 级别 | 建议方案 |
|---|------|------|------|----------|
| P1 | **progress key 规则三套**，`文献pdf_{ref}` / `morici_{ref}` / `{dir首段}_{ref}` 互不认账 → 跨层重复下载、漏判已完成 | `download_parallel.py:38,53`、`scihub_batch.py:150`、`panda985_search.py:36,314` | **高** | 统一 `key = f"{case}_{no}"`（用 `no` 不用 `ref`），抽公共函数 |
| P2 | **案例名硬编码 `'文献pdf'`，而 `output/文献pdf` 目录不存在** → 三个脚本开箱即 `FileNotFoundError` | `download_parallel.py:38`、`scihub_batch.py:14`、`rename_pdfs.py:12` | **高** | 统一 `--name` 参数；缺省时自动识别 `output/` 下唯一子目录 |
| P3 | **`download_progress.json` 缺失时崩溃**（panda985 已修，另两个未修） | `scihub_batch.py:83`、`rename_pdfs.py:17` | **高** | 不存在时视为空进度（对齐 panda985 的写法） |
| P4 | **`download_one` 验证失败仍写盘并 return，不再尝试后续层** → 第一层返回垃圾即终止全部 11 层 | `download_pdfs.py:531-540` | **高** | 验证不通过则 `continue` 下一层（**行为变更，需确认**） |
| P5 | **验证异常时返回 `True`（放行）** → fitz 打不开的 PDF 被当成"验证通过" | `download_pdfs.py:488`、`scihub_batch.py:61`、`panda985_search.py:88` | **高** | 返回 `(False, 'unverifiable')` 或标记 `uncertain` 待人工（**行为变更**） |
| P6 | **`verify_pdfs.py` 用「文件名 vs 记录标题」匹配**，而文件名正是从记录生成的 → 自证式校验，形同虚设；`pdf_text` 参数根本没用 | `verify_pdfs.py:47,66-69` | **高** | 改为对 `pdf_text` 做关键词匹配，DOI 优先 |
| P7 | **硬编码单篇论文补丁** `.replace('[ref 15]','Yu')` | `verify_pdfs.py:49` | **高** | 删除；改从 `ref_texts` 回填作者 |
| P8 | **`extract_full_table.py` 声称 21 字段 / 三层表格解析，实际只填 5 个字段**；Layer1 的 6 个函数（`detect_table_pages` 等）**全部未被调用**；`--auto-detect` / `--mode` 参数定义了不使用 | `extract_full_table.py:53-174, 508-510, 555-557` | **高** | 二选一：文档降级为「5 字段」（低成本）/ 真正实现表格解析（高成本） |
| P9 | **领域停用词硬编码**（air pollution / exercise 词汇表）→ 换个课题验证逻辑即失效 | `scihub_batch.py:71`、`panda985_search.py:103`、`verify_merged.py:37` | **高** | 抽公共停用词表 + `--stopwords` 可选扩展 |
| P10 | **18 处裸 `except:`** → 吞掉 `KeyboardInterrupt`/`SystemExit`，Ctrl+C 无效且掩盖真实错误 | `download_pdfs.py` 占 15 处 | 中 | 全部改为 `except Exception:` |
| P11 | **依赖清单不全**：README 的 pip 命令缺 `xlsxwriter`（`extract_included_studies.py` 必需）、`pdfplumber`（可选）；无 `requirements.txt` | `README.md:18` | 中 | 补 `requirements.txt`，README 与之对齐 |
| P12 | **`requests.Session` 全局共享 + 3 线程并发**，Session 非线程安全 | `download_pdfs.py:116` + `download_parallel.py:77` | 中 | 改 `threading.local()` 每线程独立 Session |
| P13 | **相对 PDF 路径永远拼 `https://sci-hub.sg`** → 在 st/ru 镜像下拼出错误域名 | `scihub_batch.py:45` | 中 | 用当前 `page.url` 的 origin 做 `urljoin` |
| P14 | `int(k.split('_')[1])` 遇非数字 key 抛 `ValueError`；结尾硬编码 `/47` | `scihub_batch.py:84, 159` | 中 | try/except 包裹；总数从 `len(recs)` 取 |
| P15 | **浏览器资源无 try/finally**：异常时 page/browser 泄漏，Chrome 调试实例易崩 | `scihub_batch.py:88-156`、`panda985_search.py:132-325` | 中 | `try/finally` 保证 `page.close()` + `p.stop()` |
| P16 | **文件句柄未用 `with`**：`json.dump(prog, open(...))` | `scihub_batch.py:154`、`rename_pdfs.py:62` | 中 | 改 `with open(...) as f` |
| P17 | **PDF 命名规则两套**：`作者_年份_标题`（download_pdfs / panda985）vs `作者_标题`（scihub_batch / rename_pdfs）→ 同一篇可能被下两次，「已存在」判断失效 | 4 个脚本 | 中 | 统一为一个函数（**会影响已有文件名，需确认**） |
| P18 | **`update_excel` 每次在 `max_column+1` 追加两列**，重复运行会不断累加 `PDF Status`/`PDF File` 列 → 不幂等 | `download_pdfs.py:633-634` | 中 | 先扫描是否已存在同名表头列，存在则复用 |
| P19 | **Unpaywall 邮箱硬编码** `<上一个案例遗留的机构邮箱，已移除>`（他人域名，且是上一个案例的遗留） | `download_pdfs.py:53` | 中 | `os.environ.get('UNPAYWALL_EMAIL')` 或 `--email` |
| P20 | **`review_dois.py` 仍是抽样检查**，且硬编码 `refs [51,64,76]` → 与 CLAUDE.md/SKILL.md 宣称的「全量检查」不符 | `review_dois.py:193` | 中 | 改为全量（注意 OpenAlex 限流，需加节流） |
| P21 | 同上文件：网络失败被判为「DOI 无效」ERROR → 误报 | `review_dois.py:208` | 中 | 区分「解析失败」与「网络错误」，后者记 WARNING |
| P22 | **`elif doi: is_green = True`** → 未经 OpenAlex 验证的 DOI 也标绿，与「绿色=已验证」文档矛盾 | `extract_included_studies.py:419-420` | 中 | 未验证应标黄/红 |
| P23 | **`verify_merged.py` 死代码**：`has_cn` 在 :107 已 return，:128-131 永不执行；且 :94 与 :129 重复计算 | `verify_merged.py:94,107,128-131` | 中 | 删除 :128-131 与重复计算 |
| P24 | **`panda985_search.py` 复用 `contexts[0].pages[0]`**（用户正在看的标签页），可能把用户页面导航走；`scihub_batch.py` 用 `new_page()`，两者行为不一致 | `panda985_search.py:135` | 中 | 统一改 `new_page()` |
| P25 | **`download_parallel.py` 是模块级脚本**（导入即执行全部逻辑），无法被复用/测试 | `download_parallel.py:38-93` | 中 | 包进 `main()` + `if __name__` |
| P26 | **`prep_from_info.py` 的 `int(rec['year'])`** 遇 `'2020a'`/`'nan'` 抛 `ValueError` | `prep_from_info.py:125,130` | 中 | 正则提取 4 位年份 + 兜底 |
| P27 | 硬编码拼写纠正 `(reposnses\|deisel\|dieseal)` —— 针对特定案例的 typo | `prep_from_info.py:44` | 中 | 移除或外置为可配置词典 |
| P28 | **`str(row['DOI']) != 'nan'`** 字符串比较判 NaN，脆弱 | `verify_merged.py:92` | 中 | 改 `pd.notna()` |
| P29 | **三份代码副本 + `scripts_backup_0727/` + 已提交的 `__pycache__`** | 全局 | 中 | 单一真源，其余删除或构建时同步 |
| P30 | **零测试**（0 个测试文件），重构无安全网 | — | 中 | 先给纯函数（`clean_doi`/`sanitize`/`verify_pdf`/`match_score`）补 pytest |
| P31 | **无请求节流/退避**：CrossRef 只 `sleep(0.5~1)`，CLAUDE.md 已记录 429 限流但代码未处理 | `extract_full_table.py:460`、`extract_included_studies.py:221` | 中 | 加指数退避 + 429 重试 |
| P32 | 「有效 PDF」阈值三套：200B / 5000B / 8000B | `download_pdfs.py:142,531`、`scihub_batch.py:128` | 低 | 统一常量 |
| P33 | 注释与结构不符：`BASE_DIR = ... # 查找文献pdf/` 实为项目根 | `download_pdfs.py:51` | 低 | 改注释 |
| P34 | 层编号体系三份：README 6 层 / SKILL.md 8 层 / 代码 11 层 | 文档 + `download_pdfs.py:495` | 低 | 统一为代码 11 层，文档对齐 |
| P35 | `urllib.parse` 未显式 import（依赖 `urllib.request` 的导入副作用，可运行但脆弱） | `extract_included_studies.py:201` | 低 | 显式 `import urllib.parse` |
| P36 | 模块 docstring 位置错误（写在 import 之后，实为空语句） | `extract_included_studies.py:4`、`review_dois.py:4` | 低 | 移到文件首行 |
| P37 | 几乎无类型标注；`L1_pmc` 实为 Europe PMC 但标签叫 `PMC` | 全局 | 低 | 逐步补 typing；标签改名 |
| P38 | `verify_pdf` 三份重复实现（download_pdfs / scihub_batch / panda985） | 3 个文件 | 低 | 抽公共 `verify.py` |
| P39 | `.gitignore` 忽略 `*.pdf`，但 `output/Morici_2020/pdfs/` 下 26 个 PDF 已在仓库内（历史遗留） | `.gitignore:23` | 低 | 加 `output/**/pdfs/` |

### 安全性专项

| 项 | 结论 |
|----|------|
| 硬编码密钥 / Token | **未发现**（仅有硬编码邮箱、邮箱地址，非密钥） |
| 输入校验 | 缺失：PDF 路径、Excel 列名、`--ref-pages` 均无校验（`--ref-pages "abc"` 直接 `ValueError` 退出） |
| CDP 9222 无鉴权 | **设计使然但需知情**：本机任意程序可接管该浏览器实例并用你的登录态访问站点 |
| `credentials: 'include'` 的页内 fetch | 下载出版商 PDF 所必需，但会把站点 cookie 带出，建议仅在调试实例中使用 |
| Sci-Hub 使用 | 合规风险提示已在 README 中给出文献传递等替代方案，建议保留并前置 |

---

## 三、推荐的高优先级改动清单

排序依据：**严重度 × 改动成本**（先做又严重又便宜的）。每项标注：位置 / 原因 / 预期收益 / 副作用。

### 第一批：能立刻消除崩溃与错误结果（建议先做）

| 序 | 改动 | 位置 | 原因 | 预期收益 | 副作用 | 级别 | 成本 |
|----|------|------|------|----------|--------|------|------|
| 1 | 统一案例目录解析：新增 `--name` 参数，缺省自动识别 `output/` 下唯一子目录 | `download_parallel.py:38`、`scihub_batch.py:14`、`rename_pdfs.py:12` | 硬编码 `'文献pdf'` 且该目录不存在，三个脚本开箱即崩 | 开箱可跑，换案例不用改源码 | 无（旧行为本就崩溃） | 高 | 低 |
| 2 | 统一 progress key 为 `f"{case}_{no}"` | `download_parallel.py:53`、`scihub_batch.py:150`、`panda985_search.py:314` | 三套 key 导致跨层状态互不可见 | 各层共享真实进度，杜绝重复下载 | **已生成的旧 progress 文件 key 对不上**，需一次性迁移脚本或接受重跑一次 | 高 | 中 |
| 3 | `download_progress.json` 缺失时视为空进度 | `scihub_batch.py:83`、`rename_pdfs.py:17` | 首次运行即崩 | 首次运行可用 | 无 | 高 | 低 |
| 4 | `verify_pdfs.py` 改为用 PDF 正文匹配；删除 `'[ref 15]'` 硬编码 | `verify_pdfs.py:47-69` | 现逻辑是拿文件名自证，验不出错文献 | 真正能发现「下错文献」 | 匹配阈值需重新校准，可能短期产生更多 WARNING | 高 | 中 |
| 5 | 裸 `except:` → `except Exception:` | `download_pdfs.py` 等 18 处 | 吞掉 Ctrl+C、掩盖真实错误 | 可中断、可诊断 | 原本被静默吞掉的异常会暴露出来，可能看到更多报错 | 中 | 低 |
| 6 | 补 `requirements.txt`，README 安装命令与之对齐 | 新增文件 + `README.md:18` | 缺 `xlsxwriter` 导致快速模式直接退出 | 新环境一次装齐 | 无 | 中 | 低 |

### 第二批：正确性提升（涉及行为变更，需你拍板）

| 序 | 改动 | 位置 | 原因 | 预期收益 | 副作用 | 级别 | 成本 |
|----|------|------|------|----------|--------|------|------|
| 7 | 验证不通过时**继续尝试下一层**，而非写盘返回 | `download_pdfs.py:531-540` | 首层返回垃圾文件即终止后续 10 层 | 命中率提升 | **行为变更**：不再保留 `uncertain` 文件；耗时增加 | 高 | 低 |
| 8 | 验证异常不再返回 `True` | `download_pdfs.py:488`、`scihub_batch.py:61`、`panda985_search.py:88` | 打不开的 PDF 被判为通过 | 不再静默放行可疑文件 | **行为变更**：少数文件会转为 `uncertain`/失败，需人工确认 | 高 | 低 |
| 9 | 领域停用词抽为公共表 + `--stopwords` 扩展 | `scihub_batch.py:71`、`panda985_search.py:103`、`verify_merged.py:37` | 换课题即失效 | 工具可复用到其他综述 | 默认行为不变，除非传参 | 高 | 低 |
| 10 | `update_excel` 幂等化：复用已存在的状态列 | `download_pdfs.py:633` | 重复运行无限追加列 | Excel 不再膨胀 | 无 | 中 | 低 |
| 11 | 浏览器资源 `try/finally`；`new_page()` 统一 | `scihub_batch.py:88-156`、`panda985_search.py:132-325` | 异常泄漏 page，且会劫持用户标签页 | Chrome 调试实例更稳、不干扰用户 | 无 | 中 | 低 |
| 12 | Sci-Hub 相对路径用 `page.url` origin 拼接 | `scihub_batch.py:45` | 非 sg 镜像下拼错域名 | 镜像轮换真正生效 | 无 | 中 | 低 |

### 第三批：架构收敛（成本高，收益长期）

| 序 | 改动 | 位置 | 原因 | 预期收益 | 副作用 | 级别 | 成本 |
|----|------|------|------|----------|--------|------|------|
| 13 | 抽出公共模块 `common.py`（路径解析 / progress key / 文件命名 / PDF 校验 / 停用词） | 新增 | 4 份重复实现 | 改一处生效全局 | 需同步改 13 个脚本的 import | 中 | 中 |
| 14 | 三份副本收敛为一份真源 | `.claude/skills/…/scripts/`、`查找文献pdf/` | 已产生版本漂移 | 消除「改了这处忘了那处」 | 需你决定保留哪份、其余如何处置 | 中 | 中 |
| 15 | `extract_full_table.py`：补齐 21 字段 **或** 文档降级为 5 字段 | 全文 | 文档与实现严重不符 | 消除误导 | 取决于你的选择（见决策点 3） | 高 | 高/低 |
| 16 | 为纯函数补 pytest | 新增 `tests/` | 零测试，重构无网 | 后续改动有安全网 | 需新增 dev 依赖 | 中 | 中 |

---

## 四、需要你确认的决策点

1. **是否允许两处「行为变更」？**（第 7、8 项）
   - 第 7 项：验证失败后继续尝试后续层 → 不再保留 `uncertain` 文件，单次耗时变长，但命中率提高。
   - 第 8 项：验证异常不再放行 → 少数文件会转为待人工确认。
   两者都会改变下载结果集。如果你更看重「保留一切可能有用的文件」，我可以改成「写盘但打标记」的中间方案。

2. **三份副本如何处理？**
   建议 `scripts/` 为真源。`.claude/skills/lit-review-extractor/scripts/` 和 `查找文献pdf/scripts/` 是**删除**、**改为软链**、还是**加一个同步脚本**？考虑到你对删除操作很敏感，我倾向「保留目录 + 加 `sync_scripts.py` 单向同步 + 文档标注真源」，不做任何删除。

3. **`extract_full_table.py` 走哪条路？**
   - (a) 低成本：把 README/CLAUDE/SKILL 中「21 字段」改为「5 字段（year/journal/first_author/title/doi）」，删除未被调用的 6 个表格解析函数和两个死参数。
   - (b) 高成本：真正实现表格结构解析，把 16 个空字段填上。
   如果近期不换课题做完整模式，**建议选 (a)**。

4. **案例目录的默认行为？**
   改成必填 `--name`，还是自动识别 `output/` 下唯一子目录（多个时报错列出）？我倾向后者 + 支持 `--name` 覆盖。

5. **是否统一 PDF 命名规则？**（第 17 项）
   统一后 `output/Morici_2020/pdfs/` 下已有 26 个文件名会不一致（可用 `rename_pdfs.py` 一次性归一）。**要不要动已有文件？**

6. **本次是否要我直接动手改？**
   上面所有条目我都没有落地。你说一声，我按第一批 → 第二批的顺序执行，每批改完给一份 diff 说明。

---

## 附：审查时的静态检查结果

- `python -m py_compile scripts/*.py`：**全部通过**（无语法错误）。
- `xlsxwriter` 在当前托管 Python 3.13.12 中**未安装** → `extract_included_studies.py` 会直接 `sys.exit(1)`；README 的安装命令里没有它。
- 三份副本差异统计：`extract_included_studies.py` 差 10 行、`panda985_search.py` 差 277 行、`scihub_batch.py` 差 243 行、`verify_pdfs.py` 差 2 行；其余 8 个文件与 `scripts/` 完全一致。
- `output/` 下只有 `Morici_2020`，**不存在 `文献pdf` 目录** → 印证 P2。
