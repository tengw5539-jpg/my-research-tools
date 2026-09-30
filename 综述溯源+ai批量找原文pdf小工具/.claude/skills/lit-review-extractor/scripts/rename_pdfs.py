# -*- coding: utf-8 -*-
"""
rename_pdfs.py — 将下载的 PDF 归一为「第一作者_年份_题目.pdf」
从 download_progress.json 读取成功记录，按记录的 title/first_author/year 重命名。
命名规则与 common.pdf_name() 一致，因此重复运行是幂等的（已是标准名则跳过）。

用法:
  python scripts/rename_pdfs.py                        # 自动识别 output/ 下唯一案例
  python scripts/rename_pdfs.py --name Morici_2020
"""
import sys, os, argparse
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import common


def main():
    ap = argparse.ArgumentParser(description='PDF 归一名（第一作者_年份_题目）')
    ap.add_argument('--name', '-n', help='案例目录名（留空则自动识别 output/ 下唯一案例）')
    args = ap.parse_args()

    case_dir = common.resolve_case_dir(args.name)
    paths = common.case_paths(case_dir)

    recs = common.load_json(paths['json'], default=[])
    if not recs:
        raise SystemExit(f'[ERROR] {paths["json"]} 为空或不存在')
    no2rec = {r.get('no'): r for r in recs}

    # 原实现 progress 文件缺失即崩溃；改为按空进度处理
    progress = common.load_json(paths['progress'], default={}) or {}
    if not isinstance(progress, dict):
        progress = {}

    renamed = skipped = err = 0
    for rk, p in progress.items():
        if not isinstance(p, dict) or p.get('status') not in common.OK_STATUS:
            continue
        old = p.get('pdf_path', '')
        if not old or not os.path.exists(old):
            print(f'  [skip] 文件不存在: {old}')
            skipped += 1
            continue
        rec = no2rec.get(p.get('no'))
        if not rec:
            print(f'  [skip] 无记录: no={p.get("no")}')
            skipped += 1
            continue
        newp = paths['pdfs'] / common.pdf_name(
            rec.get('first_author', 'Unknown'), rec.get('title', ''), rec.get('year', ''))
        if os.path.abspath(old) == os.path.abspath(str(newp)):
            renamed += 1
            continue
        if newp.exists():
            print(f'  [冲突] 目标已存在，跳过: {newp.name}')
            skipped += 1
            continue
        try:
            os.rename(old, str(newp))
            p['pdf_path'] = str(newp)
            renamed += 1
        except OSError as e:
            print(f'  [err] {old} -> {newp}: {e}')
            err += 1

    common.save_json(paths['progress'], progress)
    print(f'\n重命名完成: {renamed} 已就位, {skipped} 跳过, {err} 错误')
    print(f'输出目录: {paths["pdfs"]}')
    if paths['pdfs'].is_dir():
        for f in sorted(os.listdir(paths['pdfs'])):
            print(f'  {f}')


if __name__ == '__main__':
    main()
