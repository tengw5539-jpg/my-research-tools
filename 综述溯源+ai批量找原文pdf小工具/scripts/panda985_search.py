#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
panda985_search.py — Panda985 兜底捡漏
=====================================
Flow: 标题在 Panda985 检索 -> 逐个候选结果 -> 找 PDF -> 下载并内容校验

前置:
  scripts/launch_chrome_cdp.cmd   （Chrome 远程调试端口 9222）

用法:
  python scripts/panda985_search.py                     # 自动识别 output/ 下唯一案例
  python scripts/panda985_search.py --name Morici_2020
"""

import base64, time, argparse, sys
from urllib.parse import urljoin

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import common

CDP_URL = 'http://localhost:9222'

JS_FETCH_B64 = """async (url) => {
    try {
        const r = await fetch(url, {credentials: 'include'});
        if (!r.ok) return {error: 'HTTP ' + r.status};
        const buf = await r.arrayBuffer();
        const bytes = new Uint8Array(buf);
        let bin = '';
        for (let i = 0; i < bytes.length; i += 4096)
            bin += String.fromCharCode.apply(null, bytes.subarray(i, Math.min(i+4096, bytes.length)));
        return {data: btoa(bin), size: bytes.length};
    } catch(e) { return {error: e.message}; }
}"""


def load_failed(records, progress, case):
    """返回尚未成功的记录列表。"""
    keys = {common.progress_key(case, r) for r in records}
    failed = []
    for r in records:
        p = progress.get(common.progress_key(case, r))
        if isinstance(p, dict) and p.get('status') in common.OK_STATUS:
            continue
        failed.append(r)
    return failed


def main():
    from playwright.sync_api import sync_playwright

    ap = argparse.ArgumentParser(description='Panda985 捡漏下载')
    ap.add_argument('--name', '-n', help='案例目录名（留空则自动识别 output/ 下唯一案例）')
    ap.add_argument('--cdp', default=CDP_URL, help='Chrome 调试地址')
    ap.add_argument('--delay', type=float, default=5.0, help='每篇之间的间隔秒数')
    ap.add_argument('--max-candidates', type=int, default=4, help='每条最多尝试几个候选结果')
    args = ap.parse_args()

    case_dir = common.resolve_case_dir(args.name)
    paths = common.case_paths(case_dir)
    case = case_dir.name

    records = common.load_json(paths['json'], default=[])
    if not records:
        raise SystemExit(f'[ERROR] {paths["json"]} 为空或不存在')

    # 进度文件缺失时按「全量待处理」处理（这是本脚本原先已修好的行为，保留）
    progress = common.load_progress(paths['progress'], records, case)
    all_failed = load_failed(records, progress, case)
    if not all_failed:
        print('All papers already downloaded!')
        return

    total = len(all_failed)
    print(f'\n{total} papers to download via Panda985 search\n')
    common.ensure_dir(paths['pdfs'])

    p = sync_playwright().start()
    page = None
    try:
        b = p.chromium.connect_over_cdp(args.cdp)
    except Exception:
        p.stop()
        raise SystemExit('ERROR: Chrome CDP not available.\n'
                         'Start Chrome with:\n'
                         '  chrome.exe --remote-debugging-port=9222 '
                         '--user-data-dir=C:/temp/chrome_debug')
    try:
        # 用新标签页，避免抢占用户正在浏览的页面（原实现取 contexts[0].pages[0]）
        page = b.contexts[0].new_page()
        print(f'Connected: {(page.title() or "")[:60]}\n')

        ok = fail = 0
        for idx, rec in enumerate(all_failed):
            doi = common.clean_doi(rec.get('doi', ''))
            author = rec.get('first_author', '')
            title = rec.get('title', '')
            ref = rec.get('ref', '?')
            out = paths['pdfs'] / common.pdf_name(author, title, rec.get('year', ''))
            tag = f"[{idx+1:3d}/{total}] ref{str(ref):3s} {author[:18]}"
            downloaded, last_detail = False, 'failed'

            if idx > 0:
                time.sleep(args.delay)

            status = 'failed'
            try:
                if title and len(title) > 10:
                    query = title[:120]
                elif doi:
                    query = doi
                else:
                    fail += 1
                    print(f'{tag} 无标题也无 DOI')
                    continue

                print(f'{tag}  searching...', end=' ', flush=True)
                page.goto('https://sc.panda985.com/index.html',
                          wait_until='domcontentloaded', timeout=45000)
                time.sleep(2)
                # 用首页搜索框（比 /scholar URL 更不易触发验证门）
                q = page.query_selector('input[name=q]')
                if not q:
                    print('no search box'); fail += 1; continue
                q.fill(query)
                page.keyboard.press('Enter')
                time.sleep(6)

                cur_title = page.title() or ''
                if ('verify' in cur_title.lower() or 'captcha' in cur_title.lower()
                        or 'robot' in cur_title.lower() or '安全' in cur_title
                        or page.url.startswith('https://sc.panda985.com/verify_gate')):
                    print('captcha! skip'); fail += 1; continue

                # 收集候选链接并去重保序
                all_links = []
                for sel in ['h3 a', '.gs_rt a', '.gs_ttl a', '.gs_r a', '.result a[href]']:
                    for a in page.query_selector_all(sel):
                        href = a.get_attribute('href') or ''
                        txt = (a.inner_text() or '')[:80]
                        if href.startswith('http') and 'panda985' not in href \
                                and 'google' not in href and 'paperyy' not in href:
                            all_links.append((href, txt))
                seen, uniq = set(), []
                for l in all_links:
                    if l[0] not in seen:
                        seen.add(l[0]); uniq.append(l)

                def pri(l):
                    u = l[0].lower()
                    if any(k in u for k in ('.pdf', '/pdf/')): return 0
                    if any(k in u for k in ('pmc', 'ncbi', 'biorxiv', 'frontiersin',
                                            'mdpi', 'sciencedirect')): return 1
                    return 2
                uniq.sort(key=pri)

                if not uniq:
                    print('no results'); fail += 1; continue

                downloaded = False
                for ci, (href, txt) in enumerate(uniq[:args.max_candidates]):
                    print(f'  [{ci+1}] {txt[:35]} {href[:50]}')
                    try:
                        page.goto(href, wait_until='domcontentloaded', timeout=45000)
                        time.sleep(4)
                    except Exception:
                        continue

                    pdf_url = None
                    for sel in ['meta[name="citation_pdf_url"]', 'a[href$=".pdf"]',
                                'a[href*="/pdf/"]', 'a:has-text("Download PDF")',
                                'a:has-text("View PDF")', 'a:has-text("Full Text")',
                                'a:has-text("PDF")', 'a.pdf-download']:
                        try:
                            el = page.query_selector(sel)
                        except Exception:
                            continue
                        if el:
                            src = el.get_attribute('content') or el.get_attribute('href') or ''
                            if src:
                                pdf_url = src if src.startswith('http') else urljoin(page.url, src)
                                break
                    if not pdf_url and href.lower().endswith('.pdf'):
                        pdf_url = href
                    if not pdf_url:
                        continue

                    print(f'  download {pdf_url[:70]}', end=' ', flush=True)
                    try:
                        result = page.evaluate(JS_FETCH_B64, pdf_url)
                    except Exception:
                        continue
                    data = base64.b64decode(result['data']) if result.get('data') else b''
                    if not (data[:5] == b'%PDF-' and len(data) > 5000):
                        print(f'not PDF ({len(data)}b)')
                        continue
                    vok, vdet = common.verify_content(data, rec)
                    if not vok:
                        print(f'内容不符({vdet})!')
                        continue
                    with open(out, 'wb') as f:
                        f.write(data)
                    ok += 1
                    status = 'ok'
                    downloaded = True
                    last_detail = vdet
                    print(f'{len(data)//1024}KB [{vdet}]')
                    break

                if not downloaded:
                    fail += 1
                    print('FAIL (all candidates)')

            except Exception as e:
                fail += 1
                status = 'failed'
                print(f'{type(e).__name__}: {str(e)[:50]}')

            progress[common.progress_key(case, rec)] = {
                'no': rec.get('no', idx + 1), 'ref': ref, 'author': author, 'doi': doi,
                'status': status,
                'pdf_path': str(out) if status == 'ok' else '',
                'source': 'panda985' if status == 'ok' else '',
                'details': last_detail if downloaded else 'failed',
            }
            common.save_progress(paths['progress'], progress)
    finally:
        if page:
            try:
                page.close()
            except Exception:
                pass
        p.stop()

    print(f'\nDone: {ok} ok, {fail} failed')


if __name__ == '__main__':
    main()
