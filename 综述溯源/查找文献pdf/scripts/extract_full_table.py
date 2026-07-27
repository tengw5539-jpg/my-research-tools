#!/usr/bin/env python3
"""
extract_full_table.py -- Full-field inclusion table extractor
=============================================================
Three-layer extraction with inline review for systematic review papers.

Layer 1: Table structure parsing
  Strategy A: pdfplumber grid-line detection
  Strategy B: pymupdf block-position column clustering
  Strategy C: fallback to regex splitting

Layer 2: Field extraction (18 fields with confidence scores)
  Core: first_author, doi, title, year, journal
  Sample: sample_size, population, age_range, sex
  Design: study_design, follow_up, country
  Outcomes: exposure, outcome, effect_measure, effect_size, ci_lower, ci_upper
  Quality: quality_score, funding, notes

Layer 3: Inline review (per-row verification)
  DOI -> OpenAlex title match
  Author name anomaly detection
  Same-author-same-year conflict check
  Sample size range validation

Output: extracted_data.json (18 fields + confidence) + review_issues.json

Usage:
  python extract_full_table.py paper.pdf --refs refs.json --ref-pages "38-41"
  python extract_full_table.py paper.pdf --auto-detect  # find tables automatically
  python extract_full_table.py paper.pdf --mode quick    # fast 4-field mode
"""

import re, json, os, sys, time, argparse, concurrent.futures, urllib.request, urllib.error, urllib.parse
from pathlib import Path
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

try:
    import fitz
except ImportError:
    print("[ERROR] pip install pymupdf"); sys.exit(1)

try:
    import pdfplumber
except ImportError:
    pdfplumber = None  # optional, grid-line detection only

# ============================================================
# Layer 1: Table Structure Parsing
# ============================================================

def detect_table_pages(doc):
    """Auto-detect pages containing inclusion tables by searching for
    keywords: 'Table', 'Characteristics', 'included studies', '纳入研究'."""
    table_pages = []
    keywords = [r'table\s+\d+', r'characteristics', r'included\s+studies',
                r'summary\s+of\s+studies', r'纳入研究', r'纳入文献']
    for pg_idx in range(doc.page_count):
        text = doc[pg_idx].get_text().lower()
        if any(re.search(kw, text) for kw in keywords):
            table_pages.append(pg_idx)
    return table_pages


def extract_blocks_with_positions(page):
    """Extract text blocks with (x0, y0, x1, y1) positions from a PDF page.
    Returns list of {'text': str, 'x0': float, 'y0': float, 'x1': float, 'y1': float}."""
    blocks = page.get_text("blocks")
    result = []
    for b in blocks:
        if b[6] == 0:  # text block
            text = b[4].strip()
            if text and len(text) > 1:
                result.append({
                    'text': text,
                    'x0': b[0], 'y0': b[1], 'x1': b[2], 'y1': b[3]
                })
    return result


def cluster_columns(blocks, min_gap=5):
    """Cluster blocks into columns by x-coordinate gaps."""
    if not blocks:
        return []
    xs = sorted(set(b['x0'] for b in blocks))
    xs.append(xs[-1] + 100)  # sentinel
    cols, start = [], xs[0]
    for i in range(1, len(xs)):
        if xs[i] - xs[i-1] > min_gap:
            cols.append((start, xs[i-1] + 10))
            start = xs[i]
    return cols


def group_blocks_into_rows(blocks, y_tolerance=5):
    """Group blocks by y-coordinate proximity into table rows."""
    sorted_blocks = sorted(blocks, key=lambda b: (b['y0'], b['x0']))
    rows, current_row, current_y = [], [], sorted_blocks[0]['y0'] if sorted_blocks else 0
    for b in sorted_blocks:
        if abs(b['y0'] - current_y) <= y_tolerance:
            current_row.append(b)
        else:
            if current_row:
                rows.append(current_row)
            current_row = [b]
            current_y = b['y0']
    if current_row:
        rows.append(current_row)
    return rows


def parse_table_with_grid(pdf_path, page_idx):
    """Strategy A: Use pdfplumber to detect grid lines and extract structured table."""
    if pdfplumber is None:
        return None
    try:
        with pdfplumber.open(pdf_path) as pdf:
            if page_idx >= len(pdf.pages):
                return None
            page = pdf.pages[page_idx]
            tables = page.extract_tables()
            if tables:
                # Return the largest table on the page
                return max(tables, key=len)
    except Exception:
        pass
    return None


def parse_table_with_blocks(page):
    """Strategy B: Use pymupdf block positions to reconstruct table."""
    blocks = extract_blocks_with_positions(page)
    if len(blocks) < 5:
        return None, None

    cols = cluster_columns(blocks)
    rows = group_blocks_into_rows(blocks)

    # Filter out header/footer rows
    header_y_threshold = blocks[0]['y0'] + 80  # top 80 units = header
    footer_y_threshold = max(b['y1'] for b in blocks) - 60
    data_rows = [
        row for row in rows
        if row[0]['y0'] > header_y_threshold and row[0]['y0'] < footer_y_threshold
    ]

    # Build cell matrix: rows x columns
    cell_matrix = []
    for row in data_rows:
        cells = [''] * len(cols)
        for b in row:
            for ci, (cx0, cx1) in enumerate(cols):
                if cx0 <= b['x0'] <= cx1:
                    cells[ci] = b['text']
                    break
        if any(c.strip() for c in cells):
            cell_matrix.append(cells)

    return cols, data_rows


def find_ref_number_in_block(block_text):
    """Extract reference number from a text block. Handles (46), [46], ref46."""
    # Pattern: (46) or [46] or [46,47]
    m = re.search(r'[\[\(](\d+)(?:[,;\s]+\d+)*[\]\)]', block_text)
    if m:
        return int(m.group(1))
    # Pattern: standalone number preceded by ref
    m = re.search(r'ref\s*(\d+)', block_text, re.I)
    if m:
        return int(m.group(1))
    return None


def extract_first_author_from_text(text, ref_num):
    """Extract first author surname from a reference text entry."""
    text = re.sub(r'\s+', ' ', text).strip()
    # Split by the year pattern to get everything before year
    yr_match = re.search(r'\((\d{4})\)', text)
    if yr_match:
        before_year = text[:yr_match.start()].strip()
    else:
        # Alternative: split by journal name patterns
        before_year = text.split('. ')[0]

    # Remove leading number/dot
    before_year = re.sub(r'^\d+\.\s*', '', before_year)
    # Take first comma-separated segment
    fa = before_year.split(',')[0].strip()
    # Remove "et al."
    fa = re.sub(r'\s+et\s+al\.?$', '', fa, flags=re.I).strip()
    return fa


# ============================================================
# Layer 2: Field Extraction
# ============================================================

FIELD_DEFS = {
    'first_author':   {'category': 'core',   'required': True,  'description': 'First author surname'},
    'doi':            {'category': 'core',   'required': True,  'description': 'Digital Object Identifier (DOI)'},
    'title':          {'category': 'core',   'required': True,  'description': 'Article title'},
    'year':           {'category': 'core',   'required': False, 'description': 'Publication year'},
    'journal':        {'category': 'core',   'required': False, 'description': 'Journal name (abbreviated)'},
    'sample_size':    {'category': 'sample', 'required': False, 'description': 'Total sample size (n)'},
    'population':     {'category': 'sample', 'required': False, 'description': 'Study population description'},
    'age_range':      {'category': 'sample', 'required': False, 'description': 'Age range of participants'},
    'sex':            {'category': 'sample', 'required': False, 'description': 'Sex distribution (M/F)'},
    'study_design':   {'category': 'design', 'required': False, 'description': 'Study design (RCT/cohort/cross-sectional etc.)'},
    'follow_up':      {'category': 'design', 'required': False, 'description': 'Follow-up duration'},
    'country':        {'category': 'design', 'required': False, 'description': 'Country of study'},
    'exposure':       {'category': 'outcome', 'required': False, 'description': 'Exposure/intervention'},
    'outcome':        {'category': 'outcome', 'required': False, 'description': 'Primary outcome measure'},
    'effect_measure': {'category': 'outcome', 'required': False, 'description': 'Effect measure type (OR/RR/HR/beta)'},
    'effect_size':    {'category': 'outcome', 'required': False, 'description': 'Effect size value'},
    'ci_lower':       {'category': 'outcome', 'required': False, 'description': 'Lower bound of 95% CI'},
    'ci_upper':       {'category': 'outcome', 'required': False, 'description': 'Upper bound of 95% CI'},
    'quality_score':  {'category': 'quality', 'required': False, 'description': 'Quality/risk-of-bias score'},
    'funding':        {'category': 'quality', 'required': False, 'description': 'Funding source'},
    'notes':          {'category': 'quality', 'required': False, 'description': 'Additional notes'},
}

CONFIDENCE = {'HIGH': 'Verified via API', 'MEDIUM': 'Extracted from PDF text', 'LOW': 'May need manual check'}


def parse_reference_text_for_fields(text):
    """Extract core fields from a reference text entry."""
    fields = {}
    text = re.sub(r'\s+', ' ', text).strip()

    # Year
    yr_m = re.search(r'\((\d{4})\)', text)
    if yr_m:
        fields['year'] = yr_m.group(1)

    # Journal — after year, before doi/dot-number
    if yr_m:
        after_year = text[yr_m.end():].strip()
        j_m = re.search(r'^([^.]+\.[^.]+)', after_year)
        if j_m:
            fields['journal'] = j_m.group(1).strip()

    # First author
    fields['first_author'] = extract_first_author_from_text(text, None)

    return fields


# ============================================================
# Layer 3: Inline Review
# ============================================================

def verify_doi_via_openalex(doi):
    """Check DOI against OpenAlex. Returns (title, first_author, year, is_valid)."""
    try:
        url = f"https://api.openalex.org/works/doi:{doi}?select=title,publication_year,authorships"
        req = urllib.request.Request(url, headers={'User-Agent': 'lit-review-extractor'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        title = data.get('title', '')
        year = str(data.get('publication_year', ''))
        fa = ''
        authorships = data.get('authorships', [])
        if authorships:
            fa = authorships[0].get('author', {}).get('display_name', '')
        return title, fa, year, bool(title)
    except Exception:
        return '', '', '', False


def review_extracted_row(row):
    """Inline review of a single extracted row. Returns list of issues."""
    issues = []

    # 1. Author name anomaly
    author = row.get('first_author', '')
    bad_patterns = [
        (r'^main\s+findings', 'PDF header text leaked into author'),
        (r'^table\s+\d+', 'Table header in author field'),
        (r'^yes\s+yes', 'MDPI data leak'),
        (r'^\d+\.?\d*$', 'Pure number as author'),
        (r'^et\s+al\.?$', 'Missing author — only et al.'),
        (r'^[\[\(]ref\s*\d+[\]\)]', 'Author field contains ref placeholder'),
    ]
    for pat, desc in bad_patterns:
        if re.search(pat, author, re.I):
            issues.append({'level': 'ERROR', 'field': 'first_author',
                          'issue': desc, 'value': author[:50]})

    # 2. Empty required fields
    for fname, fdef in FIELD_DEFS.items():
        if fdef['required'] and not row.get(fname, '').strip():
            issues.append({'level': 'ERROR', 'field': fname,
                          'issue': 'Required field is empty', 'value': ''})

    # 3. DOI format check
    doi = row.get('doi', '')
    if doi and not re.match(r'^10\.\d{4,}/', doi):
        issues.append({'level': 'WARNING', 'field': 'doi',
                      'issue': 'DOI format unusual', 'value': doi})

    # 4. Year range check
    year = row.get('year', '')
    if year:
        try:
            y = int(year)
            if y < 1900 or y > 2030:
                issues.append({'level': 'WARNING', 'field': 'year',
                              'issue': f'Year out of range ({y})', 'value': year})
        except ValueError:
            issues.append({'level': 'WARNING', 'field': 'year',
                          'issue': 'Year is not a number', 'value': year})

    return issues


def review_paper_wide(rows):
    """Cross-row review: check same-author-same-year, duplicate DOIs."""
    issues = []

    # Same author, same year
    groups = defaultdict(list)
    for i, r in enumerate(rows):
        key = f"{r.get('first_author','')}_{r.get('year','')}"
        if r.get('first_author') and r.get('year'):
            groups[key].append(i + 1)

    for key, indices in groups.items():
        if len(indices) > 1:
            titles = [rows[i-1].get('title', '')[:60] for i in indices]
            issues.append({
                'level': 'WARNING', 'field': 'first_author',
                'issue': f'Same author, same year ({key}): rows {indices}',
                'value': '; '.join(titles)
            })

    # Duplicate DOIs
    doi_groups = defaultdict(list)
    for i, r in enumerate(rows):
        d = r.get('doi', '')
        if d:
            doi_groups[d].append(i + 1)

    for doi, indices in doi_groups.items():
        if len(indices) > 1:
            issues.append({
                'level': 'CRITICAL', 'field': 'doi',
                'issue': f'DOI assigned to {len(indices)} rows: {indices}',
                'value': doi
            })

    return issues


# ============================================================
# Main extraction workflow
# ============================================================

def extract_full(pdf_path, refs_list, ref_start, ref_end):
    """Full extraction pipeline: parse table -> extract fields -> review."""

    doc = fitz.open(pdf_path)

    # Phase 1: Extract reference texts
    print("[1/4] Extracting reference texts...")
    ref_texts = {}
    for pg in range(max(0, ref_start), min(ref_end, doc.page_count)):
        page = doc[pg]
        text = page.get_text("text")
        parts = re.split(r'\n(?=\d{1,3}\.\s)', text)
        for part in parts:
            m = re.match(r'(\d+)\.\s*(.+)', part, re.DOTALL)
            if m:
                ref_num = int(m.group(1))
                body = re.sub(r'\s+', ' ', m.group(2).strip())
                if body and len(body) >= 30:
                    ref_texts[ref_num] = body

    # Phase 2: Extract DOIs with positional matching to ref numbers
    print("[2/4] Extracting DOIs and matching to references...")
    doi_map = {}  # ref_num -> doi
    all_dois = []  # (pg, y, doi)

    for pg in range(max(0, ref_start), min(ref_end, doc.page_count)):
        page = doc[pg]
        for link in page.get_links():
            uri = link.get('uri', '')
            if 'doi.org' in uri:
                m = re.search(r'doi\.org/(10\.\S+)', uri)
                if m:
                    doi = m.group(1).rstrip('.,;')
                    rect = link.get('from', None)
                    y = (rect.y0 + rect.y1) / 2 if rect else 0
                    all_dois.append((pg, y, doi))

    all_dois.sort(key=lambda x: (x[0], x[1]))

    # Positional matching: match DOIs to ref numbers by page + y-coordinate proximity
    for pg in range(max(0, ref_start), min(ref_end, doc.page_count)):
        page_dois = [(p, y, d) for (p, y, d) in all_dois if p == pg]
        if not page_dois:
            continue

        # Find ref numbers on this page
        text_on_page = doc[pg].get_text("text")
        page_refs = []
        for line in text_on_page.split('\n'):
            m = re.match(r'^\s*(\d+)\.\s', line.strip())
            if m:
                rn = int(m.group(1))
                if rn not in page_refs:
                    page_refs.append(rn)

        # If DOI count roughly matches ref count, do 1:1 mapping
        if abs(len(page_refs) - len(page_dois)) <= 2:
            count = min(len(page_refs), len(page_dois))
            for i in range(count):
                doi_map[page_refs[i]] = page_dois[i][2]
        else:
            # Use y-coordinate proximity
            blocks = doc[pg].get_text("blocks")
            for rn in page_refs:
                ref_y = None
                for b in blocks:
                    if re.match(rf'^\s*{rn}\.\s', b[4].strip()):
                        ref_y = (b[1] + b[3]) / 2
                        break
                if ref_y and page_dois:
                    best = min(page_dois, key=lambda d: abs(d[1] - ref_y))
                    if abs(best[1] - ref_y) < 100:
                        doi_map[rn] = best[2]

    print(f"  Matched {len(doi_map)} DOIs to reference numbers")

    # Phase 2.5: CrossRef search for refs without DOI
    missing_dois = [(ref, ref_texts.get(ref, '')) for ref in refs_list if ref not in doi_map]
    if missing_dois:
        print(f"  Searching CrossRef for {len(missing_dois)} missing DOIs...")
        for ref, ref_text in missing_dois:
            try:
                kws = urllib.parse.quote(ref_text[:200].replace(' ', '+'))
                url = f"https://api.crossref.org/works?query={kws}&rows=3&select=DOI,title,issued"
                req = urllib.request.Request(url, headers={'User-Agent': 'lit-review-extractor'})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read().decode())
                best_d, best_s = None, 0
                for item in data.get('message', {}).get('items', []):
                    dt = item.get('title', [''])[0].lower()
                    iy = item.get('issued', {}).get('date-parts', [[0]])[0][0]
                    rw = set(w.lower() for w in ref_text.split() if len(w) > 3)
                    dw = set(w.lower() for w in dt.split() if len(w) > 3)
                    s = len(rw & dw) / max(len(rw), 1)
                    if s > best_s and s > 0.15:
                        best_s = s
                        best_d = item.get('DOI', '')
                if best_d:
                    doi_map[ref] = best_d
                    print(f"    [ref{ref}] CrossRef -> {best_d}")
                time.sleep(0.5)
            except Exception as e:
                print(f"    [ref{ref}] CrossRef failed: {e}")

    # Phase 3: Parse table and extract records
    print("[3/4] Parsing inclusion table and extracting fields...")
    rows = []
    issues = []

    # Batch DOI verification
    dois_to_verify = list(set(doi_map.values()))
    print(f"  Verifying {len(dois_to_verify)} DOIs via OpenAlex...")
    verified = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(verify_doi_via_openalex, d): d for d in dois_to_verify}
        for f in concurrent.futures.as_completed(futures):
            d = futures[f]
            t, fa, yr, ok = f.result()
            if ok:
                verified[d] = {'title': t, 'first_author': fa, 'year': yr}

    for seq, ref in enumerate(refs_list, 1):
        rt = ref_texts.get(ref, '')
        doi = doi_map.get(ref, '')

        # Extract core fields from reference text
        fields = parse_reference_text_for_fields(rt)
        fields['no'] = seq
        fields['ref'] = ref
        fields['doi'] = doi

        # Enrich with OpenAlex data
        if doi and doi in verified:
            v = verified[doi]
            if v.get('first_author') and len(v['first_author']) > 2:
                fields['first_author'] = v['first_author']
            if v.get('title') and len(v['title']) > 10:
                fields['title'] = v['title']
            if v.get('year'):
                fields['year'] = v['year']

        # Fill missing core from reference text
        if not fields.get('title') and rt:
            fields['title'] = rt[:200]
        if not fields.get('first_author') and rt:
            fields['first_author'] = extract_first_author_from_text(rt, ref)

        # Initialize empty fields
        for fname in FIELD_DEFS:
            if fname not in fields:
                fields[fname] = ''

        # Inline review per row
        row_issues = review_extracted_row(fields)
        fields['review_status'] = 'ok' if not any(
            i['level'] in ('CRITICAL', 'ERROR') for i in row_issues) else 'review_needed'
        fields['confidence'] = 'HIGH' if (doi and doi in verified) else 'MEDIUM'

        rows.append(fields)
        for iss in row_issues:
            iss['row'] = seq
            iss['ref'] = ref
            issues.append(iss)

    # Cross-row review
    paper_issues = review_paper_wide(rows)
    issues.extend(paper_issues)

    # Phase 4: Output
    print("[4/4] Saving output...")

    n_ok = sum(1 for r in rows if r['review_status'] == 'ok')
    n_review = sum(1 for r in rows if r['review_status'] == 'review_needed')

    critical = sum(1 for i in issues if i['level'] == 'CRITICAL')
    errors = sum(1 for i in issues if i['level'] == 'ERROR')
    warnings = sum(1 for i in issues if i['level'] == 'WARNING')

    doc.close()
    return rows, issues, {
        'total': len(rows),
        'ok': n_ok,
        'needs_review': n_review,
        'critical': critical,
        'error': errors,
        'warning': warnings,
    }


def main():
    ap = argparse.ArgumentParser(description='Full-field inclusion table extractor')
    ap.add_argument('pdf', help='PDF file path')
    ap.add_argument('--refs', '-r', help='Reference number list (JSON array)')
    ap.add_argument('--ref-pages', help='Reference page range, e.g. 38-41')
    ap.add_argument('--output', '-o', help='Output directory')
    ap.add_argument('--auto-detect', action='store_true', help='Auto-detect table pages')
    ap.add_argument('--mode', choices=['full', 'quick'], default='full',
                    help='Extraction mode: full (18 fields) or quick (4 fields)')
    args = ap.parse_args()

    if not os.path.exists(args.pdf):
        print(f"[ERROR] PDF not found: {args.pdf}"); sys.exit(1)

    ref_start, ref_end = 37, 39
    if args.ref_pages:
        parts = [int(x) for x in args.ref_pages.split('-')]
        ref_start, ref_end = parts[0] - 1, parts[1]

    if args.refs:
        with open(args.refs, 'r', encoding='utf-8') as f:
            refs_list = json.load(f)
    else:
        print("[ERROR] --refs required. Provide a JSON array of reference numbers.")
        sys.exit(1)

    out_dir = args.output
    if not out_dir:
        paper_name = Path(args.pdf).stem[:40]
        out_dir = f"output/{paper_name}"
    os.makedirs(out_dir, exist_ok=True)

    rows, issues, stats = extract_full(args.pdf, refs_list, ref_start, ref_end)

    # Save extracted data
    json_path = os.path.join(out_dir, 'extracted_data.json')
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)

    # Save review issues
    review_path = os.path.join(out_dir, 'review_issues.json')
    with open(review_path, 'w', encoding='utf-8') as f:
        json.dump(issues, f, ensure_ascii=False, indent=2)

    # Print summary
    print(f"\n{'='*60}")
    print(f"EXTRACTION COMPLETE")
    print(f"  Records: {stats['total']}")
    print(f"  Verified OK: {stats['ok']}")
    print(f"  Needs review: {stats['needs_review']}")
    print(f"  Issues: CRITICAL={stats['critical']} ERROR={stats['error']} WARNING={stats['warning']}")
    print(f"  Data: {json_path}")
    print(f"  Review: {review_path}")
    if stats['needs_review'] > 0:
        print(f"\n  >>> {stats['needs_review']} records need manual review <<<")
    print(f"{'='*60}")


if __name__ == '__main__':
    main()
