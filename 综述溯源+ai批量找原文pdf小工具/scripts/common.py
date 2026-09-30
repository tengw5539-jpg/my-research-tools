# -*- coding: utf-8 -*-
"""
common.py — 全流程公共模块（路径解析 / 状态文件 / 命名 / PDF 校验）
=================================================================
抽取自 scripts/ 各脚本中重复实现的部分，统一事实唯一来源。

解决的问题：
  P1  progress key 三套不一 → 统一为 f"{case}_{no}"
  P2  案例名硬编码 + output/文献pdf 不存在 → resolve_case_dir() 自动识别
  P9  领域停用词硬编码 → 通用表 + 可选扩展
  P17 PDF 命名两套 → pdf_name() 唯一实现（作者_年份_标题）
  P38 verify_pdf 三份重复 → verify_content() 唯一实现

Python: 3.10+   依赖: pymupdf(fitz)
"""
import json
import os
import re
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent       # 项目根
OUTPUT_DIR = BASE_DIR / 'output'


# ============================================================
# 1. 案例目录解析
# ============================================================
def list_cases():
    """列出 output/ 下所有含 extracted_data.json 的案例目录。"""
    cases = []
    if not OUTPUT_DIR.is_dir():
        return cases
    for d in sorted(OUTPUT_DIR.iterdir()):
        if d.is_dir() and (d / 'extracted_data.json').exists():
            cases.append(d)
    return cases


def resolve_case_dir(name=None):
    """解析案例目录。

    优先级：显式 name > output/ 下唯一案例 > 报错并列出可选。
    修复原 download_parallel/scihub_batch/rename_pdfs 中硬编码 '文献pdf'
    且该目录不存在导致开箱即崩的问题（P2）。
    """
    if name:
        d = OUTPUT_DIR / name
        if not (d / 'extracted_data.json').exists():
            raise SystemExit(
                f'[ERROR] output/{name}/extracted_data.json 不存在。\n'
                f'  可先用 prep_from_info.py --name {name} 生成，'
                f'或检查目录名是否正确。'
            )
        return d

    cases = list_cases()
    if len(cases) == 1:
        return cases[0]
    if not cases:
        raise SystemExit(
            f'[ERROR] {OUTPUT_DIR} 下没有找到任何案例（缺少 extracted_data.json）。\n'
            f'  先运行 python scripts/prep_from_info.py --name <案例名>'
        )
    names = ', '.join(c.name for c in cases)
    raise SystemExit(
        f'[ERROR] output/ 下有 {len(cases)} 个案例，请用 --name 指定其一：{names}'
    )


def case_paths(case_dir):
    """返回案例的标准文件布局。"""
    case_dir = Path(case_dir)
    return {
        'dir': case_dir,
        'json': case_dir / 'extracted_data.json',
        'pdfs': case_dir / 'pdfs',
        'progress': case_dir / 'download_progress.json',
    }


# ============================================================
# 2. JSON 读写（统一 encoding + with 句柄）
# ============================================================
def load_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ============================================================
# 3. 进度文件 —— 统一 key + 旧格式迁移
# ============================================================
OK_STATUS = ('ok', 'already_done')


def progress_key(case, rec):
    """统一进度键：{case}_{no}

    原先三套并存（download_parallel/scihub_batch 用 '文献pdf_{ref}'，
    panda985 用 '{目录名}_{ref}'），导致各层看不到彼此的进度（P1）。
    """
    return f"{case}_{rec.get('no')}"


def load_progress(prog_path, records, case):
    """读取进度，并把旧格式 key 迁移到新格式。

    迁移规则：旧 key 形如 '<前缀>_<ref>'，按 ref 反查 no；
    若后缀本身就是 no 且不与任何 ref 冲突，则直接采用。
    迁移后会剔除「成功但文件已不存在」的条目，避免假进度。
    """
    raw = load_json(prog_path, default={}) or {}
    if not raw or not records:
        return raw if isinstance(raw, dict) else {}

    ref2no = {}
    for r in records:
        if r.get('ref') is not None:
            ref2no[str(r['ref'])] = r.get('no')
    ref_set = set(ref2no)
    nos = set()
    for r in records:
        try:
            nos.add(int(r['no']))
        except (TypeError, ValueError):
            pass

    out = {}
    migrated = 0
    # 已经是规范格式的 key 直接保留：否则 ref 与 no 取值域重叠时
    # （某条记录的 ref 恰好等于另一条记录的 no）会被反复重映射到别的记录上。
    canonical = set()
    for r in records:
        try:
            canonical.add(f"{case}_{int(r['no'])}")
        except (TypeError, ValueError):
            pass

    for key, val in raw.items():
        if key in canonical:
            out[key] = val
            continue
        new_key = None
        if isinstance(key, str) and '_' in key:
            suffix = key.rsplit('_', 1)[1]
            if suffix in ref_set:
                new_key = f"{case}_{ref2no[suffix]}"
            elif suffix.isdigit() and int(suffix) in nos:
                new_key = f"{case}_{int(suffix)}"
        if new_key is None:
            continue
        if new_key != key:
            migrated += 1
        out[new_key] = val

    # 剔除成功但文件不存在的假进度
    dropped = 0
    for key, val in list(out.items()):
        if isinstance(val, dict) and val.get('status') in OK_STATUS:
            p = val.get('pdf_path') or ''
            if p and not os.path.exists(p):
                del out[key]
                dropped += 1

    if migrated or dropped:
        print(f'  [progress] 迁移旧格式 {migrated} 条，剔除失效 {dropped} 条')
        save_json(prog_path, out)
    return out


def save_progress(prog_path, data):
    save_json(prog_path, data)


def done_numbers(progress):
    """从进度中提取已成功下载的 no 集合。"""
    nos = set()
    for val in progress.values():
        if isinstance(val, dict) and val.get('status') in OK_STATUS:
            try:
                nos.add(int(val.get('no')))
            except (TypeError, ValueError):
                continue
    return nos


# ============================================================
# 4. 文件名与 DOI 清洗
# ============================================================
_WIN_BAD = '/\\:*?"<>|'


def sanitize(s, n=90):
    """清洗非法文件名字符并限长。统一各脚本的 sanitize/sani 实现。"""
    s = str(s or '')
    for c in _WIN_BAD:
        s = s.replace(c, '_')
    s = re.sub(r'[\x00-\x1f]', '', s)
    s = re.sub(r'\s+', ' ', s).strip().rstrip('.')
    return s[:n].rstrip(' .')


def clean_doi(s):
    """归一化 DOI：去 doi.org 前缀、转小写、去尾部句点。"""
    if not s:
        return ''
    doi = str(s).strip()
    doi = re.sub(r'^https?://(dx[.])?doi[.]org/', '', doi, flags=re.I)
    return doi.lower().rstrip('.')


def pdf_name(author, title, year=''):
    """统一 PDF 文件名：第一作者_年份_标题.pdf

    原先 download_pdfs/panda985 用「作者_年份_标题」，
    scihub_batch/rename_pdfs 用「作者_标题」（P17），导致同一篇可能下两次、
    「文件已存在」判断失效。现统一为前者——与 output/ 已有交付文件一致。
    """
    fa = (author or 'Unknown').strip().replace(' ', '_').replace(',', '')
    if not fa:
        fa = 'Unknown'
    return f"{fa}_{year}_{sanitize(title or 'NoTitle')}"[:180] + '.pdf'


# ============================================================
# 5. PDF 字节判定与内容校验
# ============================================================
MIN_PDF_BYTES = 5000      # 低于此大小视为无效/占位 PDF


def is_pdf(content, ct=''):
    """判断字节流是否为 PDF。"""
    if not content:
        return False
    if content[:5] == b'%PDF-':
        return True
    if b'%PDF-' in content[:1024]:
        return True
    return 'application/pdf' in (ct or '').lower()


# 通用英文停用词（与学科无关）。领域词请用 add_stopwords 扩展。
STOPWORDS = {
    'that', 'this', 'with', 'from', 'have', 'been', 'were', 'they', 'their',
    'which', 'about', 'these', 'those', 'into', 'than', 'also', 'after',
    'between', 'other', 'should', 'could', 'would', 'during', 'among',
    'using', 'being', 'introduction', 'methods', 'results', 'discussion',
    'conclusion', 'abstract', 'study', 'effect', 'effects', 'and', 'the',
    'for', 'of', 'with',
}


def add_stopwords(words):
    """追加领域停用词（用于噪声词过滤，不建议放实义词）。"""
    STOPWORDS.update(w.lower() for w in words)


def title_keywords(title, min_len=5):
    """提取标题实义关键词（去停用词）。"""
    return {w for w in re.findall(rf'[a-zA-Z]{{{min_len},}}', (title or '').lower())
            if w not in STOPWORDS}


DOI_IN_TEXT = re.compile(r'10[.]\d{4,}/[^\s)\]}<>]{5,60}', re.I)


def extract_doi(text):
    """从 PDF 文本中提取 DOI，失败返回 None。"""
    if not text:
        return None
    m = DOI_IN_TEXT.search(text)
    return m.group(0).rstrip('.,;)}]').lower() if m else None


def doi_match(pdf_doi, exp_doi, n=20):
    """DOI 前缀比对（容忍截断与尾部差异）。"""
    if not pdf_doi or not exp_doi:
        return False
    return pdf_doi[:n] in exp_doi or exp_doi[:n] in pdf_doi


def verify_content(content, rec, min_hit=0.35, pages=3):
    """校验下载到的 PDF 是否为期望文献。

    返回 (ok, detail)。要点：
      - DOI 前缀匹配为金标准
      - 无法解析（fitz 打不开）一律判 False —— 修复原先异常返回 True 放行的问题（P5）
      - 无文本层判 True 但标注 scanned（扫描版允许人工后续确认）
    """
    tmp_path = None
    try:
        import fitz
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        doc = fitz.open(tmp_path)
        text = ''
        for i in range(min(pages, doc.page_count)):
            text += doc[i].get_text()
        page_count = doc.page_count
        doc.close()
    except Exception as e:                      # 不再裸 except
        return False, f'unverifiable:{type(e).__name__}'
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    if len(text.strip()) < 50:
        return True, f'scanned({page_count}p)'

    exp_doi = clean_doi(rec.get('doi', ''))
    if doi_match(extract_doi(text), exp_doi):
        return True, 'doi'

    kws = title_keywords(rec.get('title', ''))
    if not kws:
        return True, 'nokw'
    low = text.lower()
    hit = sum(1 for w in kws if w in low)
    ok = hit / len(kws) >= min_hit
    return ok, f'title {hit}/{len(kws)}'


# ============================================================
# 6. 小工具
# ============================================================
def ensure_dir(p):
    Path(p).mkdir(parents=True, exist_ok=True)
    return Path(p)


# 可选：项目根目录的 domain_stopwords.txt 追加领域停用词（每行一个，# 开头为注释）。
# 原先这些词被硬编码在三个脚本里（空气污染/运动课题专用），换课题即失效（P9）。
# 现在默认只保留通用英文停用词，领域词放这里，可随时换。
_domain_file = BASE_DIR / 'domain_stopwords.txt'
if _domain_file.exists():
    add_stopwords(l.strip() for l in _domain_file.read_text(encoding='utf-8').splitlines()
                  if l.strip() and not l.startswith('#'))
