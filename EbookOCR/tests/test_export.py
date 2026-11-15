"""내보내기 시험 (요청서 3장 기대 결과 4~10).  실행: python tests/test_export.py"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, SAMPLE, make_book  # noqa: E402

sys.path.insert(0, str(ROOT))
import ebook_chapters as chap  # noqa: E402


def export(book, *args):
    r = subprocess.run([sys.executable, str(ROOT / "ebook_export.py"), str(book), *args],
                       capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def parts(out):
    d = out / "책_AI용_나눔"
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(d.glob("*.md"))}


def lines(t):
    return [x for x in t.split("\n") if x.strip()]


def test_config():
    book, out = make_book()
    log = export(book)  # 요청서 10: 폴더만 주고 실행
    fs = parts(out)
    assert sorted(fs) == ["책.앞부분.md", "책.챕터01.md", "책.챕터02.md", "책.챕터02.대주제01.md"], list(fs)  # 4
    c1 = lines(fs["책.챕터01.md"])
    assert c1[:7] == ["# 책", "파트: Part 1. 기초", "쪽: p.1–p.3", "## 1장 시작", "[p.1]", "[p.2]", "### 1-1 개요"], c1[:7]  # 5
    t2 = fs["책.챕터02.md"]; c2 = lines(t2)
    assert c2[:5] == ["# 책", "파트: Part 1. 기초", "쪽: p.4–p.6", "## 2장 도구", "[p.4]"], c2[:5]  # 6
    assert t2.count("2장 도구") == 1 and "[p.5]" not in t2
    assert c2[-2:] == ["[p.6]", "앞 문장이 끝난다."], c2[-2:]
    d1 = lines(fs["책.챕터02.대주제01.md"])
    assert d1[:7] == ["# 책", "파트: Part 1. 기초", "쪽: p.6–p.8", "## 2장 도구", "[p.6]", "### 2-1 설치", "첫 문장이다."], d1  # 7
    assert d1[-1] == "[p.8]" or d1[-2:] == ["[p.8]", "설치 본문이다."], d1[-2:]
    assert "p.7" not in "".join(fs.values())  # 뺀 쪽
    assert "챕터01" in log and "뺀 쪽" in log
    # 8: 워드 제목 단계
    import docx
    d = docx.Document(str(out / "책_완성본.docx"))
    st = {p.text: p.style.name for p in d.paragraphs}
    assert st["2장 도구"] == "Heading 1" and st["2-1 설치"] == "Heading 2", st


def test_no_marks():
    book, out = make_book()
    export(book, "--no-page-marks")
    assert "[p." not in "".join(parts(out).values())


def test_legacy():  # 9: 설정 파일이 없으면 예전과 같게 (골든 비교)
    for lvl in (1, 2):
        book, out = make_book(with_config=False, edited=False)
        export(book, "--no-page-marks", "--split-level", str(lvl))
        gold = SAMPLE / "golden_legacy" / f"split{lvl}"
        got = parts(out)
        assert sorted(got) == sorted(p.name for p in gold.glob("*.md")), sorted(got)
        for p in gold.glob("*.md"):
            assert got[p.name] == p.read_text(encoding="utf-8"), p.name
    assert (out / "책_AI용.md").read_text(encoding="utf-8") == (SAMPLE / "golden_legacy" / "AI용.md").read_text(encoding="utf-8")
    # 쪽 표시 기본 켬 → 캡처 번호 그대로
    book, out = make_book(with_config=False, edited=False)
    export(book)
    assert "[p.8]" in (out / "책_AI용.md").read_text(encoding="utf-8")


def test_missing_markers():  # 글 없는 쪽(1,3)의 쪽 표시가 없어도 같은 결과
    book, out = make_book()
    f = out / "책_교정.md"
    f.write_text(f.read_text(encoding="utf-8").replace("<!-- p.1 -->\n\n", "").replace("<!-- p.3 -->\n\n", ""), encoding="utf-8")
    export(book)
    fs = parts(out)
    assert lines(fs["책.챕터01.md"])[:5] == ["# 책", "파트: Part 1. 기초", "쪽: p.1–p.3", "## 1장 시작", "[p.1]"]


def test_excluded_chapter_numbering():
    book, out = make_book()
    cfgp = out / "책_장설정.json"
    cfg = json.loads(cfgp.read_text(encoding="utf-8"))
    cfg["chapters"][0]["exclude"] = True
    cfgp.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    log = export(book)
    names = sorted(parts(out))
    assert "책.챕터01.md" not in names and "책.챕터02.md" in names, names  # 번호는 그대로 유지
    assert "제외" in log


def test_chapters_unit():
    cfg = chap.normalize({"chapters": [{"capture": 3, "page": 1, "title": "a"}, {"capture": 6, "page": 4, "title": "b"}],
                          "page_fixes": [{"capture": 9, "page": 8}, {"capture": 6, "page": 99}], "skip_pages": [7]})
    assert chap.book_page(2, cfg) is None and chap.page_label(2, cfg) == "앞2"
    assert chap.book_page(5, cfg) == 3 and chap.book_page(9, cfg) == 8
    assert chap.book_page(6, cfg) == 99  # 같은 캡처면 번호 교정이 이김
    assert chap.page_label(5, chap.empty()) == "5"


if __name__ == "__main__":
    n = 0
    for k, v in list(globals().items()):
        if k.startswith("test_"):
            v(); n += 1; print("통과:", k)
    print(f"{n}개 통과")
