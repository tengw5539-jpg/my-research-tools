# 综述溯源 — AI 助手指南

> 核心目标：从系统综述/Meta分析 PDF 中提取纳入研究的文献信息，并下载所有原文PDF。
> 所有脚本位于 `scripts/` 目录，通过 `python scripts/<name>.py` 调用。

---

## 用户交互流程（必读）

```
你要求"提取这篇综述的纳入文献"
  ↓
我询问：「你要执行哪种模式？」
  ├── ① 快速模式 —— 4字段（作者/DOI/标题/年份）
  ├── ② 完整模式 —— 21字段（含样本量/效应量/研究设计等）
  └── ③ 全量提取模式 —— 不预设字段
          ↓
[若选完整模式] 我展示21字段清单 → 等你确认 → 执行
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

### 模式 2：完整模式（21 字段）

```bash
python scripts/extract_full_table.py "论文.pdf" \
    --refs refs.json --ref-pages "38-41" \
    --output "output/论文名/"
```

### 模式 3：全量提取模式

不预设字段，先取核心标识，然后逐篇分析原文表格结构，动态识别所有可用字段。输出 JSON 每篇文献字段集可能不同。

---

## 模块二：PDF 批量下载

### 下载顺序（5 层）

| 层 | 来源 | VPN | 命中率 | 执行方式 |
|----|------|-----|--------|---------|
| L1 | Europe PMC / Unpaywall / OpenAlex / Semantic Scholar | 否 | ~40% | `python scripts/download_pdfs.py --skip-vpn` |
| L2 | 出版商 meta 标签 | 否 | ~20% | 同上脚本自动 |
| L3 | Sci-Hub 直连 + Chrome CDP | **是** | ~40% | 启动 Chrome 调试 → 过验证码 → `python scripts/scihub_batch.py` |
| **L4** | **Panda985 搜索 (https://sc.panda985.com/index.html)** | **是** | ~5% | **L3 完成后询问用户是否执行 → 手动在 Chrome 中搜索每一篇缺失文献** |
| L5 | 验证 | 否 | — | `python scripts/verify_pdfs.py` |

> **Panda985 使用说明**：L3 完成后，剩余的文献通常 Sci-Hub 没有收录。Panda985 是一个中文学术搜索引擎，可能通过不同渠道获取到 PDF。步骤：
> 1. 在 Chrome 中打开 https://sc.panda985.com/index.html
> 2. 输入缺失文献的 DOI 或完整标题
> 3. 如果找到，点击下载
> 4. 保存到 `output/论文名/pdfs/` 目录

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
| **Sci-Hub 域名被封** | st/ru/se/do 逐一失效 | 国内网络封锁 | 维护域名轮换列表 |
| **开放获取反向被墙** | EHP OA 文章却下不到 | DNS 污染 | 多路由兜底+提示手动 |
| **panda985 脚本缺陷** | download_progress.json 不存在时返回空列表 | 代码逻辑 bug | 不存在时按全量需下载处理 |
| **目录分歧** | scripts/ 和 查找文献pdf/scripts/ 各有一套 | 版本管理失误 | 统一合并 |

---

## 已完成案例

| # | 论文 | 纳入 | DOI覆盖率 | PDF覆盖率 |
|---|------|------|-----------|-----------|
| 1 | Andrade 2023 — IJERPH 20, 3506 | 58 | 58/58 | 58/58 |
| 2 | Hung 2022 — Sports Medicine 52, 139-164 | 59 | 56/59 | 59/59 |
| 3 | Gandhi 2022 — IJERPH 19, 10547 | 7 | 7/7 | 7/7 |
| 4 | Morici 2020 — Frontiers Public Health 8, 575137 | 19 | 19/19 | 18/19 |

---

## 项目结构

```
C:\Users\wangteng\Desktop\综述溯源\
├── CLAUDE.md                ← 本文档
├── README.md                ← 人类操作指南
├── scripts/                 ← 所有可执行脚本
│   ├── extract_included_studies.py   ← 快速模式（4字段）
│   ├── extract_full_table.py         ← 完整/全量模式（21+字段）
│   ├── review_dois.py                ← 独立审查
│   ├── download_pdfs.py              ← API层PDF下载
│   ├── scihub_batch.py               ← Chrome CDP下载
│   ├── panda985_search.py            ← Panda985兜底搜索
│   ├── verify_pdfs.py                ← PDF验证
│   └── launch_chrome_for_scihub.cmd  ← 一键启动Chrome调试
├── output/                  ← 项目输出
├── pdf/                     ← 原始综述PDF
└── .claude/skills/lit-review-extractor/
    └── SKILL.md             ← 技能包定义
```
