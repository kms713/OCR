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
        {"capture": 3, "page": 1, "title": "1장 시작", "split": "chapter", "exclude": False},
        {"capture": 6, "page": 4, "title": "2장 도구", "split": "topic", "exclude": False},
    ],
    "page_fixes": [{"capture": 9, "page": 8}],
    "skip_pages": [7],
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
        c1 = lines(d / "책.챕터01.md")
        check("챕터01 시작 순서", c1[:5] == ["# 책", "[p.1]", "## 1장 시작", "[p.2]", "### 대주제A"], c1[:6])
        c2 = lines(d / "책.챕터02.md")
        check("챕터02는 [p.4]로 시작", c2[:2] == ["# 책", "[p.4]"], c2[:3])
        check("2장 도구 한 번만", sum(1 for l in c2 if "2장 도구" in l) == 1, c2)
        alltext = "".join(p.read_text(encoding="utf-8") for p in d.glob("*.md"))
        check("[p.5] 어디에도 없음", "[p.5]" not in alltext)
        c3 = lines(d / "책.챕터02.대주제01.md")
        check("대주제 파일 시작 순서", c3[:4] == ["# 책", "## 2장 도구", "[p.6]", "### 대주제B"], c3[:5])
        check("대주제 파일 뒤에 [p.8]", "[p.8]" in c3, c3)
        check("챕터02에 …끝난다. 가 남음", any("끝난다." in l for l in c2), c2)
        a0 = lines(d / "책.앞부분.md")
        check("앞부분은 [p.앞1]로 시작", a0[:2] == ["# 책", "[p.앞1]"], a0[:3])
        check("요약에 뺀 쪽 표시", "뺀 쪽: 캡처 7" in log, log)
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
        check("쪽 표시는 앞N 으로", "[p.앞4]" in whole and not any(l.startswith("## 책") for l in whole), whole[:12])
    print("\n" + ("모두 통과" if not fails else f"실패 {len(fails)}건: {fails}"))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
