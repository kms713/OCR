"""내보내기 시험 (요청서 v3 3절 기대 결과 4~11).  실행: python tests/test_export.py"""
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


HEAD1 = ["---", "책: 책", "파트: Part 1. 기초", "챕터: 1장 시작", "쪽: p.1–p.3", "---"]


def test_config():
    book, out = make_book()
    log = export(book)  # 11: 폴더만 주고 실행 (5_내보내기.bat 와 같은 호출)
    fs = parts(out)
    assert sorted(fs) == ["책.앞부분.md", "책.챕터01.md", "책.챕터02.md", "책.챕터02.대주제01.md"], list(fs)  # 4
    f0 = fs["책.앞부분.md"]; c0 = lines(f0)  # 5
    assert c0[:4] == ["---", "책: 책", "챕터: 앞부분", "쪽: p.앞1–p.앞2"], c0[:5]
    k = c0.index("[p.앞2]")
    assert c0[k + 1:k + 4] == ["**목차**", "- Part 1. 기초", "  - 1장 시작"], c0[k:]
    assert "차례" not in f0 and "......" not in f0
    t1 = fs["책.챕터01.md"]; c1 = lines(t1)  # 6
    assert c1[:9] == HEAD1 + ["[p.1]", "[p.2]", "# 1.1 개요"], c1[:9]
    assert t1.split("---\n")[2].startswith("\n[p.1]")  # 머리 다음 빈 줄 하나, 그다음 첫 쪽 표시
    assert not any(x.lstrip("#").strip() in ("책", "1장 시작") for x in c1 if x.startswith("#")), c1
    t2 = fs["책.챕터02.md"]; c2 = lines(t2)  # 7
    assert c2[:7] == ["---", "책: 책", "파트: Part 1. 기초", "챕터: 2장 도구", "쪽: p.4–p.6", "---", "[p.4]"], c2[:7]
    assert c2[7] == "들어가는 글이다."
    assert t2.count("2장 도구") == 1 and "[p.5]" not in "".join(fs.values())
    assert c2[-2:] == ["[p.6]", "앞 문장이 끝난다."], c2[-2:]
    d1 = lines(fs["책.챕터02.대주제01.md"])  # 8
    assert d1[:10] == ["---", "책: 책", "파트: Part 1. 기초", "챕터: 2장 도구", "대주제: 2.1 설치", "쪽: p.6–p.8", "---",
                       "[p.6]", "# 2.1 설치", "첫 문장이다."], d1
    assert d1[-2:] == ["[p.8]", "설치 본문이다."], d1[-2:]
    assert not any(x.startswith("#") and "책" == x.lstrip("# ") for v in fs.values() for x in lines(v))
    assert "챕터01" in log and "뺀 쪽" in log and "나눈 파일 4개" in log
    # 9: 워드 제목 단계, 머리 문단
    import docx
    d = docx.Document(str(out / "책_완성본.docx"))
    st = {p.text: p.style.name for p in d.paragraphs}
    assert st["1.1 개요"] == "Heading 1" and st["2.1 설치"] == "Heading 1", st
    assert st["책"] == "머리 책" and st["2장 도구"] == "머리 챕터" and st["파트: Part 1. 기초"] == "머리 파트", st
    assert "목차" in st and "Part 1. 기초" in st


def test_no_print_pages():  # 인쇄 쪽 번호 없음: 책 쪽 = 캡처 번호, 머리 '쪽:' 끝에 (캡처 번호)
    book, out = make_book()
    cfgp = out / "책_장설정.json"
    cfg = json.loads(cfgp.read_text(encoding="utf-8")); cfg["no_print_pages"] = True
    cfgp.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    export(book)
    c1 = lines(parts(out)["책.챕터01.md"])
    assert c1[4] == "쪽: p.3–p.5 (캡처 번호)" and c1[6] == "[p.3]", c1[:8]


def test_warnings():  # 챕터명과 같은 제목이 시작 쪽 밖 / 본문 없는 챕터 파일 → 경고 (멈추지 않음)
    book, out = make_book()
    f = out / "책_교정.md"
    t = f.read_text(encoding="utf-8").replace("설치 본문이다.", "## 1장 시작\n\n설치 본문이다.")
    t = t.replace("들어가는 글이다.", "## 들어가며").replace("앞 문장이 끝난다.\n\n# 2.1 설치", "# 2.1 설치")
    f.write_text(t, encoding="utf-8")
    log = export(book)
    assert "[경고] 2건" in log and "캡처 9" in log and "본문 없이" in log, log


def test_no_marks():
    book, out = make_book()
    export(book, "--no-page-marks")
    assert "[p." not in "".join(parts(out).values())


def test_legacy():  # 10: 설정 파일이 없으면 지금 판과 같은 방식으로 나눔 (머리·제목 단계는 새 동작, 골든 비교)
    for lvl in (1, 2):
        book, out = make_book(with_config=False, edited=False)
        export(book, "--no-page-marks", "--split-level", str(lvl))
        gold = SAMPLE / "golden_legacy" / f"split{lvl}"
        got = parts(out)
        assert sorted(got) == sorted(p.name for p in gold.glob("*.md")), sorted(got)
        for p in gold.glob("*.md"):
            assert got[p.name] == p.read_text(encoding="utf-8"), p.name
    assert (out / "책_AI용.md").read_text(encoding="utf-8") == (SAMPLE / "golden_legacy" / "AI용.md").read_text(encoding="utf-8")
    # 쪽 표시 기본 켬 → 캡처 번호 그대로, 쪽 맨 위에서 나뉘면 쪽 표시는 새 파일에
    book, out = make_book(with_config=False, edited=False)
    export(book)
    assert "[p.8]" in (out / "책_AI용.md").read_text(encoding="utf-8")
    fs = parts(out)
    first = {k: lines(v)[lines(v).index("---", 1) + 1] for k, v in fs.items()}
    assert first["01_1.1 개요.md"] == "[p.4]" and first["02_2장 도구.md"] == "[p.6]", first


def test_missing_markers():  # 글 없는 쪽(1,3)의 쪽 표시가 없어도 같은 결과
    book, out = make_book()
    f = out / "책_교정.md"
    f.write_text(f.read_text(encoding="utf-8").replace("<!-- p.1 -->\n\n", "").replace("<!-- p.3 -->\n\n", ""), encoding="utf-8")
    export(book)
    fs = parts(out)
    assert lines(fs["책.챕터01.md"])[:7] == HEAD1 + ["[p.1]"]


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


def test_old_title_line():  # 옛 파일 첫 줄 '# 책제목' 만 책 제목, 그 뒤의 '#' 은 본문 제목 1단계
    import ebook_export as ex
    pz = ex.parse_markdown("# 책\n\n<!-- p.1 -->\n\n# 1.1 가\n\n###### 깊은\n\n본문", ROOT)
    assert [(b.kind, b.level) for b in pz.blocks if b.kind in ("title", "heading")] == [("title", 1), ("heading", 1), ("heading", 6)]
    pz = ex.parse_markdown("<!-- p.1 -->\n\n# 1.1 가", ROOT)
    assert pz.blocks[1].kind == "heading"


def test_chapters_unit():
    cfg = chap.normalize({"chapters": [{"capture": 3, "page": 1, "title": "a"}, {"capture": 6, "page": 4, "title": "b"}],
                          "page_fixes": [{"capture": 9, "page": 8}, {"capture": 6, "page": 99}], "skip_pages": [7]})
    assert chap.book_page(2, cfg) is None and chap.page_label(2, cfg) == "앞2"
    assert chap.book_page(5, cfg) == 3 and chap.book_page(9, cfg) == 8
    assert chap.book_page(6, cfg) == 99  # 같은 캡처면 번호 교정이 이김
    assert chap.page_label(5, chap.empty()) == "5"
    cfg2 = chap.normalize({"chapters": [{"capture": 4, "title": "x"}], "no_print_pages": True,
                           "toc": [{"capture": 2, "items": [{"level": 1, "text": " a  b "}, {"text": ""}]}]})
    assert cfg2["chapters"][0]["page"] == 4 and chap.page_label(2, cfg2) == "2"  # 쪽 번호를 비우면 캡처 번호
    assert cfg2["toc"] == [{"capture": 2, "items": [{"level": 1, "text": "a b"}]}]


if __name__ == "__main__":
    n = 0
    for k, v in list(globals().items()):
        if k.startswith("test_"):
            v(); n += 1; print("통과:", k)
    print(f"{n}개 통과")
