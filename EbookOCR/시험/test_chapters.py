#!/usr/bin/env python3
"""장 설정·내보내기 시험 (견본 책 캡처 9쪽). 사용: python 시험/test_chapters.py
임시 폴더에 견본 책을 만들어 ebook_export.py 를 돌리고 기대 결과를 확인한다. 실패하면 종료 코드 1."""
from __future__ import annotations

import io
import json
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import bookpages  # noqa: E402
import ebook_export  # noqa: E402

SAMPLE_MD = (HERE / "견본_교정.md").read_text(encoding="utf-8")
CONFIG = {
    "chapters": [
        {"capture": 3, "page": 1, "title": "1장 시작", "part": "Part 1. 기초", "split": "chapter", "exclude": False},
        {"capture": 6, "page": 4, "title": "2장 도구", "part": "Part 1. 기초", "split": "topic", "exclude": False},
    ],
    "page_fixes": [{"capture": 9, "page": 8}],
    "skip_pages": [7],
    "toc": [{"capture": 2, "items": [{"level": 0, "text": "프롤로그"}, {"level": 1, "text": "연구의 고통"}, {"level": 0, "text": "Part 1. 도구의 이해"}, {"level": 1, "text": "1장. 무엇이 다른가"}]}],
}
fails = []


def check(name, ok, detail=""):
    print(("  통과 " if ok else "  실패 ") + name + ("" if ok else f"\n      {detail}"))
    if not ok:
        fails.append(name)


def lines(path: Path):
    return [l for l in path.read_text(encoding="utf-8").split("\n") if l.strip()]


def export(folder: Path, *extra):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = ebook_export.main([str(folder), "--only", "ai", *extra])
    return rc, buf.getvalue()


def make_book(root: Path, with_config: bool) -> Path:
    from PIL import Image
    folder = root / "책"
    folder.mkdir()
    for i in range(1, 10):
        Image.new("RGB", (20, 20), "white").save(folder / f"page_{i:04d}.png")
    out = root / "책_OCR"
    out.mkdir()
    (out / "책_교정.md").write_text(SAMPLE_MD, encoding="utf-8")
    if with_config:
        (out / "책_장설정.json").write_text(json.dumps(CONFIG, ensure_ascii=False), encoding="utf-8")
    return folder


def main() -> int:
    print("[책 쪽 번호]")
    bp = bookpages.BookPages(bookpages.clean_config(CONFIG))
    check("캡처 1 = 앞1", bp.label(1) == "앞1")
    check("캡처 4 = 2쪽", bp.label(4) == "2")
    check("캡처 9 = 8쪽", bp.label(9) == "8")
    with tempfile.TemporaryDirectory() as t:
        root = Path(t)
        folder = make_book(root, True)
        out = root / "책_OCR"
        rc, log = export(folder)
        d = out / "책_AI용_나눔"
        names = sorted(p.name for p in d.glob("*.md"))
        print("[내보내기: 설정 있음]")
        check("파일 네 개", set(names) == {"책.앞부분.md", "책.챕터01.md", "책.챕터02.md", "책.챕터02.대주제01.md"} and len(names) == 4, names)
        H1 = ["# 책", "파트: Part 1. 기초"]
        c1 = lines(d / "책.챕터01.md")
        check("챕터01 머리·시작 순서", c1[:6] == H1 + ["쪽: p.1–p.3", "## 1장 시작", "[p.1]", "[p.2]"] and c1[6] == "### 1-1 개요", c1[:8])
        c2 = lines(d / "책.챕터02.md")
        check("챕터02 머리", c2[:4] == H1 + ["쪽: p.4–p.6", "## 2장 도구"] and c2[4] == "[p.4]", c2[:6])
        check("2장 도구는 머리에만", sum(1 for l in c2 if "2장 도구" in l) == 1, c2)
        alltext = "".join(p.read_text(encoding="utf-8") for p in d.glob("*.md"))
        check("[p.5] 어디에도 없음", "[p.5]" not in alltext)
        c3 = lines(d / "책.챕터02.대주제01.md")
        check("대주제 파일 머리", c3[:6] == H1 + ["쪽: p.6–p.8", "## 2장 도구", "[p.6]", "### 2-1 설치"], c3[:7])
        check("대주제 파일 뒤에 [p.8]", "[p.8]" in c3 and "첫 문장…" in c3, c3)
        check("챕터02 끝에 [p.6]과 …끝난다.", c2[-2:] == ["[p.6]", "…끝난다."], c2[-3:])
        a0 = lines(d / "책.앞부분.md")
        check("목차 쪽은 목록으로", a0[4:10] == ["[p.앞2]", "**목차**", "- 프롤로그", "  - 연구의 고통", "- Part 1. 도구의 이해", "  - 1장. 무엇이 다른가"] and "차례" not in "".join(a0) and not any("- 2장 도구" == l for l in a0), a0)
        check("앞부분 머리", a0[:4] == ["# 책", "쪽: p.앞1–p.앞2", "## 앞부분", "[p.앞1]"], a0[:5])
        check("요약에 뺀 쪽 표시", "뺀 쪽: 캡처 7" in log, log)
        docx_ok = False
        try:
            from docx import Document
            rc2 = ebook_export.main([str(folder), "--only", "docx"])
            dd = Document(str(out / "책_완성본.docx"))
            st = {p.text: p.style.name for p in dd.paragraphs}
            docx_ok = st.get("2장 도구") == "Heading 1" and st.get("2-1 설치") == "Heading 2" and st.get("1-1 개요") == "Heading 2"
        except ImportError:
            docx_ok = True
        check("Word 제목 1·2 스타일", docx_ok)
        rc, _ = export(folder, "--no-page-marks")
        check("--no-page-marks", "[p." not in "".join(p.read_text(encoding="utf-8") for p in d.glob("*.md")))

        print("[제외한 챕터·번호 유지]")
        cfg = json.loads(json.dumps(CONFIG))
        cfg["chapters"][0]["exclude"] = True
        (out / "책_장설정.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        export(folder)
        names = sorted(p.name for p in d.glob("*.md"))
        check("챕터01 파일 없음, 챕터02 번호 유지", "책.챕터01.md" not in names and "책.챕터02.md" in names, names)

    print("[설정 파일 없음]")
    with tempfile.TemporaryDirectory() as t:
        root = Path(t)
        folder = make_book(root, False)
        rc, log = export(folder)
        d = root / "책_OCR" / "책_AI용_나눔"
        names = sorted(p.name for p in d.glob("*.md"))
        check("오류 없이 끝남", rc == 0, log)
        check("앞부분 파일이 생김", "책.앞부분.md" in names, names)
        whole = lines(root / "책_OCR" / "책_AI용.md")
        check("쪽 표시는 앞N 으로", "[p.앞4]" in whole, whole[:12])
        check("글 속 ## 제목은 챕터로", any(f.name.startswith("책.챕터") for f in d.glob("*.md")), names)
        print("[인쇄 쪽 번호 없는 책]")
    with tempfile.TemporaryDirectory() as t:
        root = Path(t)
        folder = make_book(root, False)
        out = root / "책_OCR"
        cfg = {"no_print_pages": True, "chapters": [
            {"capture": 3, "page": "", "title": "1장 시작", "split": "chapter"},
            {"capture": 6, "page": None, "title": "2장 도구", "split": "chapter"}]}
        (out / "책_장설정.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        rc, log = export(folder)
        d = out / "책_AI용_나눔"
        c1 = lines(d / "책.챕터01.md")
        check("쪽 번호 칸을 비우면 캡처 번호", c1[:4] == ["# 책", "쪽: p.3–p.5 (캡처 3–5)", "## 1장 시작", "[p.3]"], c1[:5])
        check("앞부분도 캡처 번호", lines(d / "책.앞부분.md")[1] == "쪽: p.1–p.2 (캡처 1–2)", lines(d / "책.앞부분.md")[:2])
    print("[남은 # · ## 줄 경고]")
    with tempfile.TemporaryDirectory() as t:
        root = Path(t)
        folder = make_book(root, True)
        out = root / "책_OCR"
        (out / "책_교정.md").write_text(SAMPLE_MD.replace("본문5", "## OCR이 붙인 큰 글자\n\n본문5"), encoding="utf-8")
        rc, log = export(folder)
        check("경고 출력 (쪽 번호와 줄)", "[주의] 본문에 # 또는 ## 줄이 1개" in log and "OCR이 붙인 큰 글자" in log and "캡처 5" in log, log)
        check("챕터명과 같아 지워진 줄은 경고 안 함", "2장 도구" not in log.split("[주의]")[1].split("\n")[1] if "[주의]" in log else False, log)
        check("경고해도 내보내기는 끝남", rc == 0 and (out / "책_AI용_나눔" / "책.챕터01.md").is_file())
    print("\n" + ("모두 통과" if not fails else f"실패 {len(fails)}건: {fails}"))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
