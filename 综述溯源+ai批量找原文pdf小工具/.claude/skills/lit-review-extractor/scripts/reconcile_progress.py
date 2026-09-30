# -*- coding: utf-8 -*-
"""
reconcile_progress.py — 用磁盘上真实存在的 PDF 回填 download_progress.json
========================================================================
背景：pdfs/ 里已经有文件，但 download_progress.json 可能与之不同步
（旧 key 格式、路径失效、人工合并过批次等），导致 list_missing.py 明明有文件
却报「已下 0」。本脚本按 PDF **正文内容**重新认领（而非看文件名），
把能确认的记录标为 ok，写回进度文件。

- 只新增/覆盖 ok 条目，不删除已有 failed 条目
- 目标文件已存在同名新 key 且 pdf_path 有效时不改动
- 默认 dry-run；加 --apply 才写盘
- 会先把原文件备份到 download_progress.json.bak

用法:
  python scripts/reconcile_progress.py                # 预览
  python scripts/reconcile_progress.py --apply        # 写入
  python scripts/reconcile_progress.py --apply --name Morici_2020
"""
import sys, os, argparse, datetime
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import fitz
import common

MIN_SIZE = common.MIN_PDF_BYTES


def pdf_head_text(path, max_pages=3):
    """读取 PDF 前几页文本。"""
    try:
        doc = fitz.open(str(path))
        text = ''
        for i in range(min(max_pages, doc.page_count)):
            text += doc[i].get_text()
        pages = doc.page_count
        doc.close()
        return text, pages
    except Exception as e:
        return '', 0


def score_record(rec, text, filename):
    """给「一条记录」对一个 PDF 打分，越高越匹配。返回 (score, reason)。"""
    exp_doi = common.clean_doi(rec.get('doi', ''))
    pdf_doi = common.extract_doi(text)
    if common.doi_match(pdf_doi, exp_doi, 22):
        return 100, 'doi'

    if len(text.strip()) < 50:
        # 扫描版：只能靠文件名里的作者前缀
        fa = filename.split('_')[0].lower().replace('-', '')
        au = (rec.get('first_author', '') or '').lower().replace(',', '').replace(' ', '')
        return (50, 'scanned-author') if au[:4] and au[:4] in fa else (0, '')

    head = text[:8000].lower()
    score, reasons = 0, []

    au_parts = [w for w in __import__('re').findall(r'[a-z]{3,}',
                (rec.get('first_author', '') or '').lower())]
    if au_parts and any(p in head for p in au_parts[-2:]):
        score += 40
        reasons.append('author')

    kws = common.title_keywords(rec.get('title', ''))
    if kws:
        hits = sum(1 for w in kws if w in head)
        ratio = hits / len(kws)
        if ratio >= 0.6:
            score += 50; reasons.append(f'title{ratio:.0%}')
        elif ratio >= 0.35:
            score += 30; reasons.append(f'title{ratio:.0%}')
        elif ratio >= 0.2:
            score += 15; reasons.append(f'title~{ratio:.0%}')
    return score, '+'.join(reasons)


def main():
    ap = argparse.ArgumentParser(description='用磁盘上的 PDF 回填下载进度')
    ap.add_argument('--name', '-n', help='案例目录名（留空则自动识别）')
    ap.add_argument('--apply', action='store_true', help='写盘（默认只预览）')
    ap.add_argument('--min-score', type=int, default=60,
                    help='认领阈值（默认 60；100=DOI命中，90=作者+强标题）')
    args = ap.parse_args()

    case_dir = common.resolve_case_dir(args.name)
    paths = common.case_paths(case_dir)
    case = case_dir.name

    records = common.load_json(paths['json'], default=[])
    if not records:
        raise SystemExit(f'[ERROR] {paths["json"]} 为空或不存在')
    if not paths['pdfs'].is_dir():
        raise SystemExit(f'[ERROR] 没有 PDF 目录: {paths["pdfs"]}')

    progress = common.load_progress(paths['progress'], records, case)
    files = sorted(f for f in os.listdir(paths['pdfs']) if f.lower().endswith('.pdf'))
    print(f'=== {case}: {len(records)} 条记录 / {len(files)} 个 PDF ===\n')

    already = common.done_numbers(progress)
    used_files, claims = set(), []
    for rec in records:
        if rec.get('no') in already:
            used_files.add(os.path.basename(str(progress[common.progress_key(case, rec)].get('pdf_path', ''))))
            continue
        best = (0, '', None)
        for f in files:
            if f in used_files:
                continue
            p = paths['pdfs'] / f
            if p.stat().st_size < MIN_SIZE:
                continue
            text, _ = pdf_head_text(p)
            sc, reason = score_record(rec, text, f)
            if sc > best[0]:
                best = (sc, reason, f)
        if best[0] >= args.min_score and best[2]:
            used_files.add(best[2])
            claims.append((rec, best[2], best[0], best[1]))

    print(f'认领结果（阈值 {args.min_score}）:')
    for rec, f, sc, reason in claims:
        print(f'  #{rec.get("no"):>3} <- {f[:60]}   [{sc} {reason}]')
    unmatched = [f for f in files if f not in used_files]
    if unmatched:
        print(f'\n未认领的 PDF（{len(unmatched)} 个，需人工核对）:')
        for f in unmatched:
            print(f'  ? {f}')
    still_missing = [r for r in records
                     if r.get('no') not in already and not any(r is c[0] for c in claims)]
    if still_missing:
        print(f'\n仍无 PDF 的记录（{len(still_missing)} 条）:')
        for r in still_missing:
            print(f'  #{r.get("no"):>3} {r.get("first_author", "?")[:20]}')

    if not args.apply:
        print(f'\n预览完成：将新增 {len(claims)} 条 ok。加 --apply 写入。')
        return

    # 写盘前先备份原文件
    bak = paths['progress'].with_suffix(paths['progress'].suffix + '.bak')
    import shutil
    shutil.copy2(paths['progress'], bak)
    print(f'\n已备份原进度文件 -> {bak.name}')

    for rec, f, sc, reason in claims:
        progress[common.progress_key(case, rec)] = {
            'no': rec.get('no'), 'ref': rec.get('ref'), 'author': rec.get('first_author', ''),
            'doi': rec.get('doi', ''), 'status': 'ok',
            'pdf_path': str(paths['pdfs'] / f),
            'source': 'reconciled', 'details': f'{sc} {reason}',
        }
    common.save_progress(paths['progress'], progress)
    print(f'写入 {len(claims)} 条 ok。当前成功数: '
          f'{len(common.done_numbers(progress))}/{len(records)}')


if __name__ == '__main__':
    main()
