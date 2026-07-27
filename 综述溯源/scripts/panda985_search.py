#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
L11: Panda985 Google Scholar search -> publisher page -> PDF download
=====================================================================
Flow: search title on panda985 -> click first result -> find PDF on publisher -> download

Prerequisites:
  chrome.exe --remote-debugging-port=9222 --user-data-dir=C:/temp/chrome_debug

Usage:
  python panda985_search.py
"""

import base64, json, os, re, sys, time, urllib.parse
from pathlib import Path
from urllib.parse import urljoin

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BASE = Path(__file__).parent.parent
OUTPUT = BASE / 'papers'
ALT_OUTPUT = BASE / 'output'  # Also scan output/ for paper data


def discover_papers():
    papers = {}
    for base_dir, label in [(OUTPUT, 'papers'), (ALT_OUTPUT, 'output')]:
        if not base_dir.exists():
            continue
        for d in sorted(os.listdir(str(base_dir))):
            full = base_dir / d
            if not full.is_dir(): continue
            jp = full / 'extracted_data.json'
            if not jp.exists(): continue
            key = d.split('_')[0][:10]
            if len(key) < 3:
                key = d.replace(' ', '_')[:10]
            papers[key] = {'d': str(full), 'j': 'extracted_data.json'}
    return papers


PAPERS = discover_papers()


def load_failed(key):
    cfg = PAPERS[key]
    base_dir = Path(cfg['d'])
    jp = base_dir / cfg['j']
    pp = base_dir / 'download_progress.json'
    with open(jp, encoding='utf-8') as f: recs = json.load(f)
    if not pp.exists():
        # No progress file = everything needs download
        prog = {}
        failed = list(recs)
    else:
        prog = json.load(open(pp, encoding='utf-8'))
        failed = []
        for r in recs:
            rk = f"{key}_{r.get('ref','?')}"
            if rk not in prog or prog[rk].get('status') not in ('ok', 'already_done'):
                failed.append(r)
    return failed, base_dir / 'pdfs', pp, prog


def sani(s):
    for c in '/\\:*?"<>|':
        s = s.replace(c, '_')
    return re.sub(r'[\x00-\x1f]', '', s.strip())[:90].rstrip('. ')


def fname(a, t, y=''):
    fa = (a or 'X').strip().replace(' ', '_').replace(',', '')
    return (f"{fa}_{y}_{sani(t or 'X')}"[:180] + '.pdf').rstrip('. ')


def main():
    from playwright.sync_api import sync_playwright

    # Collect all failed papers
    all_failed = []
    info = {}
    for k in PAPERS:
        failed, pdf_dir, pp, prog = load_failed(k)
        all_failed.extend([(k, r) for r in failed])
        info[k] = (pdf_dir, pp, prog)

    if not all_failed:
        print("All papers already downloaded!")
        return

    print(f"\n{len(all_failed)} papers to download via Panda985 search\n")

    # Connect Chrome CDP
    p = sync_playwright().start()
    try:
        b = p.chromium.connect_over_cdp('http://localhost:9222')
        page = b.contexts[0].pages[0] if b.contexts[0].pages else b.contexts[0].new_page()
    except Exception:
        print("ERROR: Chrome CDP not available.")
        print("Start Chrome with:")
        print('  chrome.exe --remote-debugging-port=9222 --user-data-dir=C:/temp/chrome_debug')
        p.stop()
        return

    print(f"Connected: {page.title()[:60]}\n")

    ok = 0
    fail = 0
    total = len(all_failed)

    for idx, (paper_key, rec) in enumerate(all_failed):
        doi = (rec.get('doi', '') or '').replace('https://doi.org/', '').strip().lower()
        author = rec.get('first_author', '')
        title = rec.get('title', '')
        year = rec.get('year', '')
        ref = rec.get('ref', '?')

        if not doi and not title:
            fail += 1
            continue

        pdf_dir, pp, prog = info[paper_key]
        out = pdf_dir / fname(author, title, year)
        os.makedirs(pdf_dir, exist_ok=True)

        tag = f"[{idx+1:3d}/{total}] {paper_key[:4]} ref{str(ref):3s} {author[:18]}"

        # Delay between papers
        if idx > 0:
            time.sleep(5)

        try:
            # Step 1: Search on Panda985 by title
            # Prefer title search (higher hit rate than DOI)
            if title and len(title) > 10:
                query = title[:120]
            elif doi:
                query = doi
            else:
                fail += 1
                continue

            search_url = f'https://sc.panda985.com/scholar?q={urllib.parse.quote(query)}&hl=en'

            print(f'{tag}  searching...', end=' ', flush=True)
            page.goto(search_url, wait_until='domcontentloaded', timeout=45000)
            time.sleep(3)

            # Check captcha
            t = (page.title() or '').lower()
            if 'verify' in t or 'captcha' in t or 'robot' in t or '安全' in page.title():
                print('captcha! skip')
                fail += 1
                continue

            # Step 2: Click first external result
            clicked = False
            # Google Scholar results use h3 > a or .gs_rt > a
            for sel in ['h3 a', '.gs_rt a', '.gs_ttl a']:
                for a in page.query_selector_all(sel):
                    href = a.get_attribute('href') or ''
                    if href.startswith('http') and 'panda985' not in href and 'google' not in href:
                        a.click()
                        time.sleep(5)
                        clicked = True
                        break
                if clicked:
                    break

            # Fallback: any external link
            if not clicked:
                for a in page.query_selector_all('a[href]'):
                    href = a.get_attribute('href') or ''
                    if href.startswith('http') and 'panda985' not in href and 'google' not in href:
                        page.goto(href, wait_until='domcontentloaded', timeout=45000)
                        time.sleep(5)
                        clicked = True
                        break

            if not clicked:
                print('no results')
                fail += 1
                status = 'failed'
                continue

            # Step 3: Find PDF on publisher page
            pdf_url = None
            for sel in [
                'meta[name="citation_pdf_url"]',
                'a[href$=".pdf"]',
                'a[href*="/pdf/"]',
                'a:has-text("PDF")',
                'a:has-text("Download PDF")',
                'a:has-text("View PDF")',
                'a:has-text("Full Text")',
                'a.pdf-download',
            ]:
                el = page.query_selector(sel)
                if el:
                    src = el.get_attribute('content') or el.get_attribute('href') or ''
                    if src:
                        pdf_url = src if src.startswith('http') else urljoin(page.url, src)
                        break

            if not pdf_url:
                print('no PDF link on publisher')
                fail += 1
                status = 'failed'
                continue

            print(f'downloading...', end=' ', flush=True)

            # Step 4: Download via browser fetch (has cookies)
            result = page.evaluate("""
                async (url) => {
                    try {
                        const r = await fetch(url, {credentials: 'include'});
                        if (!r.ok) return {error: 'HTTP ' + r.status};
                        const buf = await r.arrayBuffer();
                        const bytes = new Uint8Array(buf);
                        let bin = '';
                        for (let i = 0; i < bytes.length; i += 4096)
                            bin += String.fromCharCode.apply(null,
                                bytes.subarray(i, Math.min(i+4096, bytes.length)));
                        return {data: btoa(bin), size: bytes.length};
                    } catch(e) { return {error: e.message}; }
                }
            """, pdf_url)

            if result.get('data'):
                data = base64.b64decode(result['data'])
                sz = len(data)
                if data[:5] == b'%PDF-' and sz > 5000:
                    with open(out, 'wb') as f:
                        f.write(data)
                    ok += 1
                    status = 'ok'
                    print(f'{sz//1024}KB')
                else:
                    fail += 1
                    status = 'failed'
                    print(f'not PDF ({sz}b)')
            else:
                fail += 1
                status = 'failed'
                print(f'fetch: {result.get("error","?")}')

        except Exception as e:
            fail += 1
            status = 'failed'
            print(f'{str(e)[:40]}')

        # Save progress
        rk = f"{paper_key}_{ref}"
        prog[rk] = {
            'no': rec.get('no', idx+1), 'ref': ref, 'author': author, 'doi': doi,
            'status': status,
            'pdf_path': str(out) if status == 'ok' else '',
            'source': 'panda985' if status == 'ok' else '',
            'details': f'{ok}/{total}' if status == 'ok' else 'failed',
        }
        with open(pp, 'w', encoding='utf-8') as f:
            json.dump(prog, f, ensure_ascii=False, indent=2)

    p.stop()
    print(f'\nDone: {ok} ok, {fail} failed')


if __name__ == '__main__':
    main()
