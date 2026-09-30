# 🧪 我的科研工具集 — My Research Tools

> 作者：tengw5539-jpg
> 用途：科研工作中积累的工具集，持续更新中

三个工具串成一条线：**找到原文 PDF → 读它（翻译）→ 消化进自己的知识库**。

## 工具总览

| 目录 | 解决什么问题 | 入口 |
|------|------|------|
| 📂 [综述溯源 + ai 批量找原文 pdf 小工具](<综述溯源+ai批量找原文pdf小工具/README.md>) | 给一篇系统综述 PDF，提取全部纳入文献 + 批量下载原文 PDF | `README.md` |
| 📂 [Zotero × AI × Obsidian 工作流](<zotero-chatgpt-obsidian 工作流/README.md>) | Zotero 里的 PDF 自动变成 Obsidian 可溯源中文精读笔记 | `README.md` |
| 📂 [Zotero pdf2zh 插件本地化](<zotero的pf2fn插件的使用说明和本地化使用报告（使用workbuddy的白嫖额度实现成本翻译。其他agent也可以实现）/README.md>) | Zotero 一键 PDF 双语翻译，且 API 费用为 0 | `00-阅读导航.md` |

---

## 📂 综述溯源 + ai 批量找原文 pdf 小工具

**干什么**：把一篇系统综述 / Meta 分析 PDF 丢进去，自动提取所有纳入文献信息（作者 / 年份 / DOI / 期刊…），再按多层降级策略批量下载原文 PDF，最后逐篇交叉验证确保没下错。

**亮点**
- **两种提取模式**：快速 4 字段 / 核心 5 字段
  （⚠️ 早期文档宣传过"21 字段"，但样本量、效应量、研究设计等**目前取不到值** —— 正文表格解析仍是未接入的原型，详见子目录 README）
- **多层下载降级**：Europe PMC / Unpaywall / OpenAlex / Semantic Scholar → 出版商 meta 标签 → Sci-Hub → Panda985 → 全网搜索（政府报告 / 期刊官网 / 机构库）→ 人工兜底
- **下载后按 PDF 正文校验**（DOI 精确匹配 + 作者 + 标题关键词），不是看文件名自证
- **实测成绩**：空气污染×运动×健康综述 47 篇下到 38 篇（81%）；累计 5 篇综述、85 篇纳入文献

**从哪进**：
- [`README.md`](<综述溯源+ai批量找原文pdf小工具/README.md>) — 人类操作指南（含全网搜索捡漏方法）
- [`CLAUDE.md`](<综述溯源+ai批量找原文pdf小工具/CLAUDE.md>) — AI 助手指南（含交互流程、踩坑记录）
- [`CODE_REVIEW.md`](<综述溯源+ai批量找原文pdf小工具/CODE_REVIEW.md>) — 代码审查报告（问题清单 + 优先级）
- `.claude/skills/lit-review-extractor/` — 同能力的 skill 形态，装了就能直接触发

**怎么用**：
```bash
cd "综述溯源+ai批量找原文pdf小工具"
pip install -r requirements.txt
python scripts/prep_from_info.py --name <案例名>     # 信息表 → 下载输入
python scripts/download_parallel.py --name <案例名>   # API 层并发下载
python scripts/verify_pdfs.py                        # 验证
python scripts/reconcile_progress.py --apply         # 进度与磁盘对不上时回填
```
> 所有处理案例的脚本都支持 `--name`；不传时，若 `output/` 下只有一个案例会自动选中。

**什么时候找它**：跟 AI 说「提取这篇综述的纳入文献」「下载这些文献的 PDF」「找全文」。

**工程状况**：公共逻辑（路径 / 进度 key / 文件命名 / PDF 校验 / 停用词）统一收在
`scripts/common.py`；`tests/` 下 17 个 pytest 用例全绿；三份脚本副本用
`scripts/sync_scripts.py` 单向同步（只写不删、覆盖前自动备份）。

---

## 📂 Zotero × AI × Obsidian 工作流

**干什么**：把 Zotero 里的 PDF 论文，自动转成 Obsidian 中**可检索、可溯源**的中文精读笔记，并能基于「你自己读过的内容」做有据可查的问答与综述。

核心约束：**AI 只能基于你库里真实存在的笔记回答，找不到就明说「未找到足够依据」**，每条结论都能点回原始笔记。

**解决三个痛点**：读了就忘 / 引用靠编 / 笔记散乱。

**从哪进**：
- [`README.md`](<zotero-chatgpt-obsidian 工作流/README.md>) — 总览 + 一分钟上手 + 9 个 skill 一览
- `01-配置指南.md` — 从零搭一遍（换电脑 / 重装看这篇）
- `02-使用手册.md` — 日常怎么用、说什么话
- `03-目录结构说明.md` / `04-常见问题.md`
- `skill包/` — 9 个 skill（7 个核心工作流 + 2 个 ScanSci 下载）
- `初始模子/` — 空 vault 框架，复制即用

**什么时候找它**：跟 AI 说「处理 Zotero 里 XX 分类的论文」；提问时开场加一句「基于当前 ResearchVault 项目文件检索」即可触发**严格检索模式**。

> ⚠️ skill 里的论文库路径是**写死的**。vault 换位置后必须跑一次 `工具脚本\repath_skills.py`，否则 skill 会去找旧路径。

---

## 📂 Zotero pdf2zh 插件本地化（零 API 成本翻译）

**干什么**：`pdf2zh_next` 内置一个叫 `claudecode` 的引擎，本来要 spawn 官方付费 CLI 去调模型。本方案把它换成 spawn **本地 Agent**（WorkBuddy / Claude Code / Codex 等）—— 排版还原、双语对照、字体嵌入全部保持官方水准，但调用的模型就是正在和你对话的那个 Agent，**API 费用为 0**。

**从哪进**：
- `00-阅读导航.md` — **先读这篇**：导航 + 三分钟上手 + 四条红线
- `01-全程对话总结.md` — 这套东西怎么一版版改出来的、每一代踩的坑
- `02-配置教程（从零到可用）.md` — 环境 / Server / 插件 / 缓存投毒治理
- `03-使用说明.md` — 日常最常看
- `04-技术报告与使用指南.md` — 架构、协议、排错手册
- `skill/SKILL.md` — 给 AI Agent 加载的技能文件
- `tools/` — 5 个排查与验收脚本（`pullwait` / `dualcheck` / `cache_purge` 等）

**四条不能破的规矩**（详见导航文档）
1. **队列目录下禁止删除**，清理只能用 `archive <批次>`
2. **一轮 pull→push 必须在 110 秒内**（引擎侧 120 秒硬超时，超时不报错、静默回填英文原文）
3. **陪跑期间不要中途停手**，否则整批超时**且污染译文缓存**，下次再翻还是英文
4. **一次只陪跑一篇论文**，多篇并行会连锁超时

---

> 更多工具待添加 🚧
