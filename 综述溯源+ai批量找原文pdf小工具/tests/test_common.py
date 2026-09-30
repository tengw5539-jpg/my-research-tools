# -*- coding: utf-8 -*-
"""
common.py 的单元测试（纯函数，不联网、不碰 output/ 真实数据）

运行:
  python -m pytest tests/ -v
  python tests/test_common.py          # 没装 pytest 时的简易运行器
"""
import json
import os
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / 'scripts'
sys.path.insert(0, str(SCRIPTS))

import common


# ---------------------------------------------------------
# clean_doi
# ---------------------------------------------------------
def test_clean_doi_strips_prefix_and_case():
    assert common.clean_doi('https://doi.org/10.1234/AbC') == '10.1234/abc'
    assert common.clean_doi('http://dx.doi.org/10.1234/AbC') == '10.1234/abc'
    assert common.clean_doi('10.1234/AbC.') == '10.1234/abc'
    assert common.clean_doi('') == ''
    assert common.clean_doi(None) == ''


# ---------------------------------------------------------
# sanitize / pdf_name
# ---------------------------------------------------------
def test_sanitize_removes_illegal_chars():
    s = common.sanitize('A/B:C*D?E"F<G>H|I')
    for ch in '/\\:*?"<>|':
        assert ch not in s


def test_sanitize_truncates():
    assert len(common.sanitize('x' * 500, n=90)) <= 90


def test_pdf_name_is_deterministic():
    a = common.pdf_name('Smith J', 'Air pollution and exercise', '2020')
    b = common.pdf_name('Smith J', 'Air pollution and exercise', '2020')
    assert a == b
    assert a.endswith('.pdf')
    assert a.startswith('Smith_J_2020_')
    for ch in '/\\:*?"<>|':
        assert ch not in a


def test_pdf_name_handles_missing_author():
    n = common.pdf_name('', 'Some title', '')
    assert n.startswith('Unknown')


# ---------------------------------------------------------
# progress key + 迁移
# ---------------------------------------------------------
RECORDS = [
    {'no': 1, 'ref': '1', 'title': 'T1', 'doi': '10.1/a', 'first_author': 'A'},
    {'no': 2, 'ref': '2', 'title': 'T2', 'doi': '10.2/b', 'first_author': 'B'},
]


def test_progress_key_is_uniform():
    assert common.progress_key(' Morici_2020', RECORDS[0]) == ' Morici_2020_1'
    assert common.progress_key('c', RECORDS[1]) == 'c_2'


def test_load_progress_migrates_legacy_keys(tmp_path):
    prog = tmp_path / 'download_progress.json'
    prog.write_text(json.dumps({
        '文献pdf_1': {'no': 1, 'status': 'ok', 'pdf_path': ''},
        'morici_2': {'no': 2, 'status': 'ok', 'pdf_path': ''},
    }), encoding='utf-8')
    out = common.load_progress(prog, RECORDS, 'Morici_2020')
    # 两种旧格式都应收敛到同一套 key
    assert set(out) == {'Morici_2020_1', 'Morici_2020_2'}


def test_load_progress_drops_missing_files(tmp_path):
    prog = tmp_path / 'download_progress.json'
    prog.write_text(json.dumps({
        'Morici_2020_1': {'no': 1, 'status': 'ok', 'pdf_path': str(tmp_path / 'nope.pdf')},
        'Morici_2020_2': {'no': 2, 'status': 'ok', 'pdf_path': str(prog)},  # 真实存在
    }), encoding='utf-8')
    out = common.load_progress(prog, RECORDS, 'Morici_2020')
    assert 'Morici_2020_1' not in out      # 文件不存在 → 剔除，避免假进度
    assert 'Morici_2020_2' in out


def test_load_progress_missing_file_returns_empty(tmp_path):
    out = common.load_progress(tmp_path / 'absent.json', RECORDS, 'c')
    assert out == {}


def test_done_numbers():
    prog = {
        'c_1': {'no': 1, 'status': 'ok'},
        'c_2': {'no': 2, 'status': 'failed'},
        'c_3': {'no': 3, 'status': 'already_done'},
    }
    assert common.done_numbers(prog) == {1, 3}


# ---------------------------------------------------------
# 停用词 / DOI 匹配
# ---------------------------------------------------------
def test_title_keywords_drops_stopwords():
    # 注意：项目根的 domain_stopwords.txt 会额外加载领域词，
    # 所以这里用一句含实义词的标题来测，而不是纯领域词。
    kws = common.title_keywords('Pulmonary responses to diesel exhaust in cyclists during exercise')
    assert 'pulmonary' not in kws or 'during' not in kws
    assert 'during' not in kws
    assert 'diesel' in kws and 'cyclists' in kws
    assert all(len(w) >= 5 for w in kws)


def test_doi_match():
    assert common.doi_match('10.1234/abcde', '10.1234/abcde')
    # 提取出的 DOI 带尾部句点，记录里没有 → 仍应判为一致
    assert common.doi_match('10.1234/abcde.', '10.1234/abcde')
    assert not common.doi_match('', '10.1234/abcde')
    assert not common.doi_match('99.9999/zzzzz', '10.1234/abcde')


def test_extract_doi():
    # 正则要求斜杠后至少 5 个字符，故用足够长的后缀
    assert common.extract_doi('see doi: 10.1234/xyzab for details') == '10.1234/xyzab'
    assert common.extract_doi('https://doi.org/10.5555/qrstu') == '10.5555/qrstu'
    assert common.extract_doi('no identifier here') is None
    assert common.extract_doi('') is None


# ---------------------------------------------------------
# verify_content（需要 pymupdf）
# ---------------------------------------------------------
def _make_pdf(tmp_path: Path, text: str, name='t.pdf') -> bytes:
    try:
        import fitz
    except ImportError:
        return b'%PDF-1.4\n' + b'x' * 200
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), text, fontsize=11)
    p = tmp_path / name
    doc.save(str(p))
    doc.close()
    return p.read_bytes()


def test_verify_content_accepts_matching_title(tmp_path):
    try:
        import fitz  # noqa: F401
    except ImportError:
        return  # 没装 pymupdf 时跳过
    data = _make_pdf(tmp_path, 'Pulmonary responses to diesel exhaust in cyclists')
    rec = {'title': 'Pulmonary responses to diesel exhaust in cyclists', 'doi': '10.1/abc'}
    ok, detail = common.verify_content(data, rec)
    assert ok, detail


def test_verify_content_rejects_unrelated_pdf(tmp_path):
    try:
        import fitz  # noqa: F401
    except ImportError:
        return
    data = _make_pdf(tmp_path, 'Quantum chromodynamics on the lattice: a modern review')
    rec = {'title': 'Pulmonary responses to diesel exhaust in cyclists', 'doi': '10.1/abc'}
    ok, detail = common.verify_content(data, rec)
    assert not ok


def test_verify_content_rejects_broken_bytes():
    """原先异常时返回 True（放行），现在必须是 False。"""
    ok, detail = common.verify_content(b'not a pdf at all', {'title': 'X', 'doi': ''})
    assert not ok
    assert 'unverifiable' in detail


def test_verify_content_marks_scanned(tmp_path):
    """无文本层（纯图片/空白页）应判为 scanned 待人工确认，而不是当作"内容不符"删掉。"""
    try:
        doc = __import__('fitz').open()
    except ImportError:
        return
    out = tmp_path / 'blank.pdf'
    doc.new_page()
    doc.save(str(out))
    doc.close()
    data = out.read_bytes()
    ok, detail = common.verify_content(data, {'title': 'X', 'doi': ''})
    assert ok and 'scanned' in detail


# ---------------------------------------------------------
# 简易运行器（无 pytest 时）
# ---------------------------------------------------------
def _iter_tests():
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            yield name, fn


if __name__ == '__main__':
    import inspect
    import tempfile as _tf
    passed = failed = skipped = 0
    tmp_root = Path(_tf.mkdtemp())
    for i, (name, fn) in enumerate(_iter_tests()):
        tmp = tmp_root / f'run{i}'
        tmp.mkdir(exist_ok=True)
        kw = {'tmp_path': tmp} if 'tmp_path' in inspect.signature(fn).parameters else {}
        try:
            fn(**kw)
            passed += 1
            print(f'  PASS  {name}')
        except AssertionError as e:
            failed += 1
            print(f'  FAIL  {name}: {e}')
        except Exception as e:
            failed += 1
            print(f'  ERROR {name}: {type(e).__name__}: {e}')
    print(f'\n{passed} passed, {failed} failed')
    sys.exit(1 if failed else 0)
