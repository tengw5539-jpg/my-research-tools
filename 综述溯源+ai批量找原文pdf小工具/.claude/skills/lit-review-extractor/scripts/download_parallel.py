# -*- coding: utf-8 -*-
"""
download_parallel.py — 并发版 PDF 下载器
- 复用 download_pdfs.py 的多层下载逻辑
- 禁用不可用层（Scholar673 长期超时）
- 无 Chrome CDP 时跳过 Playwright/Panda985 层
- N 线程并发 + 进度持久化

用法:
  python scripts/download_parallel.py                 # 自动识别 output/ 下唯一案例
  python scripts/download_parallel.py --name Morici_2020
  python scripts/download_parallel.py --workers 5
"""
import sys, os, time, argparse, threading
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import common
import download_pdfs as dp

CDP_PORT = 9222


def cdp_available(port=CDP_PORT):
    try:
        import urllib.request
        urllib.request.urlopen(f'http://localhost:{port}/json/version', timeout=2)
        return True
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser(description='并发 PDF 下载（API 层，多层降级）')
    ap.add_argument('--name', '-n', help='案例目录名（留空则自动识别 output/ 下唯一案例）')
    ap.add_argument('--workers', '-w', type=int, default=3, help='并发线程数（默认 3）')
    ap.add_argument('--keep-scholar673', action='store_true',
                    help='保留 Scholar673 层（默认移除，该源长期超时）')
    args = ap.parse_args()

    case_dir = common.resolve_case_dir(args.name)
    paths = common.case_paths(case_dir)
    case = case_dir.name

    records = common.load_json(paths['json'], default=[])
    if not records:
        raise SystemExit(f'[ERROR] {paths["json"]} 为空或不存在')

    # ---- 下载器调优（原先写死在模块顶层，现收敛到 main 内）----
    dp.SKIP_VPN = False
    dp.REQ_TIMEOUT = 15
    dp.DL_TIMEOUT = 30
    if not args.keep_scholar673:
        dp.DOWNLOADERS = [x for x in dp.DOWNLOADERS if x[0] != 'Scholar673']

    if not cdp_available():
        dp.DOWNLOADERS = [x for x in dp.DOWNLOADERS if x[0] not in ('Playwright', 'Panda985')]
        print('[info] Chrome CDP 不可用，跳过 Playwright/Panda985 层')

    common.ensure_dir(paths['pdfs'])
    progress = common.load_progress(paths['progress'], records, case)

    def key_of(r):
        return common.progress_key(case, r)

    todo = []
    for r in records:
        p = progress.get(key_of(r))
        if isinstance(p, dict) and p.get('status') in common.OK_STATUS:
            continue
        todo.append((key_of(r), r))

    print(f'\n[并发下载] 案例={case}  待处理 {len(todo)}/{len(records)} 篇 (并发{args.workers})')
    print(f'[输出目录] {paths["pdfs"]}')
    print(f'[层列表] {[x[0] for x in dp.DOWNLOADERS]}')

    if not todo:
        print('\n全部已下载，无待处理条目。')
        return

    def run_one(pair):
        rk, rec = pair
        status, pdf_path, source, detail = dp.download_one(rec, paths['pdfs'])
        return rk, {'no': rec.get('no'), 'ref': rec.get('ref', '?'),
                    'author': rec.get('first_author', ''), 'doi': rec.get('doi', ''),
                    'status': status, 'pdf_path': pdf_path or '',
                    'source': source or '', 'details': detail or ''}

    done = ok = 0
    lock = threading.Lock()
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(run_one, pair): pair for pair in todo}
        for fut in as_completed(futs):
            try:
                rk, res = fut.result()
            except Exception as e:
                print(f'  [异常] {type(e).__name__}: {e}')
                continue
            with lock:
                progress[rk] = res
                common.save_progress(paths['progress'], progress)
                done += 1
            if res['status'] in common.OK_STATUS:
                ok += 1
                print(f"  [{done}/{len(todo)}] #{res['no']} OK {res['source']} ({res['details'][:50]})")
            elif res['status'] == 'no_doi':
                print(f"  [{done}/{len(todo)}] #{res['no']} NO DOI")
            else:
                print(f"  [{done}/{len(todo)}] #{res['no']} {res['status'].upper()} ({res['details'][:60]})")

    dt = time.time() - t0
    print(f'\n[完成] OK={ok} FAIL={len(todo)-ok} 耗时 {dt/60:.1f} 分钟')
    print(f'[进度文件] {paths["progress"]}')


if __name__ == '__main__':
    main()
