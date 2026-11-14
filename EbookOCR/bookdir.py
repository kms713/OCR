#!/usr/bin/env python3
"""
책 폴더 위치 (여러 PC에서 같은 책을 이어서 작업할 때)
=====================================================

이 폴더에 '책폴더.txt'(경로 한 줄)가 있으면, 프로그램에 준 'books\\책이름' 을
그 경로 아래 '책이름' 으로 바꿔 읽고 씁니다. 예) 책폴더.txt = G:\\내 드라이브\\전자책
→ books\\aieo 는 G:\\내 드라이브\\전자책\\aieo, 결과는 G:\\내 드라이브\\전자책\\aieo_OCR.
책폴더.txt 가 없으면 지금처럼 프로그램 폴더 안의 books 를 씁니다. 책폴더.txt 는 PC마다 따로 둡니다(git 에 올리지 않음).

설정:  python bookdir.py          (현재 위치를 보여 주고 새 경로를 물어봄. 책폴더_설정.bat)
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG = HERE / "책폴더.txt"


def books_root() -> Path | None:
    """책폴더.txt 의 경로. 없거나 비었으면 None."""
    try:
        for line in CONFIG.read_bytes().decode("utf-8-sig", "replace").splitlines():
            t = line.strip().strip('"').strip()
            if t and not t.startswith("#"):
                return Path(t).expanduser()
    except OSError:
        pass
    return None


def book_names(root: Path) -> list[str]:
    """책 폴더 안의 책 이름 (결과 폴더 _OCR 제외), 가나다순 — 목록 번호의 기준."""
    try:
        return sorted((d.name for d in root.iterdir() if d.is_dir() and not d.name.endswith(("_OCR", "_OCR_GPU"))),
                      key=lambda n: (n.casefold(), n))
    except OSError:
        return []


def resolve(p: str | Path) -> Path:
    """'books\\책이름…' 을 책폴더.txt 의 경로 아래로 바꾼다. 그 밖의 경로는 그대로.
    책이름 자리에 번호를 쓰면(books\\3) 목록(--list)의 그 번호 책으로 본다. 단 그 이름의 폴더가 실제로 있으면 그 폴더."""
    p = Path(p)
    root = books_root()
    parts = Path(str(p).replace("\\", "/")).parts
    if not p.is_absolute() and parts and parts[0].lower() == "books":
        base = root if root is not None else HERE / "books"
        rest = list(parts[1:])
        if rest and rest[0].isdigit() and not (base / rest[0]).exists():
            names = book_names(base)
            n = int(rest[0])
            if 1 <= n <= len(names):
                rest[0] = names[n - 1]
                print(f"{n}번 책: {rest[0]}")
        return base.joinpath(*rest) if root is not None else Path("books").joinpath(*rest)
    return p


def result_dir(folder: Path, output: str | None, title: str | None = None) -> Path:
    """OCR 결과 폴더. -o 가 없으면 <폴더>_OCR, 그것이 없고 그래픽카드 결과(<폴더>_OCR_GPU)만 있으면 그쪽.
    둘 다 있으면 교정 중인 파일(책이름_교정.md)이 있는 쪽, 그것도 같으면 <폴더>_OCR."""
    if output:
        return resolve(output)
    cpu = folder.with_name(folder.name + "_OCR")
    gpu = folder.with_name(folder.name + "_OCR_GPU")
    if not gpu.is_dir():
        return cpu
    if not cpu.is_dir():
        return gpu
    t = title or folder.name
    if (gpu / f"{t}_교정.md").is_file() and not (cpu / f"{t}_교정.md").is_file():
        return gpu
    return cpu


def list_books() -> int:
    """bat 에서 책 이름을 묻기 전에: 어느 폴더에서 찾는지와 그 안의 책 목록."""
    root = books_root() or HERE / "books"
    print(f"책 폴더: {root}" + ("" if books_root() else "  (기본 위치. 클라우드 폴더를 쓰려면 책폴더_설정.bat)"))
    if not root.is_dir():
        print("  [안내] 이 폴더가 없습니다. 클라우드 앱이 켜져 있는지, 책폴더_설정.bat 의 경로가 맞는지 확인하세요."
              if books_root() else "  (아직 책이 없습니다. 열 책이 없으면 이 창을 닫으세요)")
        return 0
    names = book_names(root)
    if names:
        for i, n in enumerate(names, start=1):
            done = (root / f"{n}_OCR").is_dir() or (root / f"{n}_OCR_GPU").is_dir()
            print(f"  {i:>3}. {n}" + ("" if done else "   (아직 OCR 전)"))
    else:
        print("  (책이 없습니다. 캡처한 책 폴더를 이 폴더에 넣으세요)")
    return 0


def main() -> int:
    if "--list" in sys.argv[1:]:
        return list_books()
    cur = books_root()
    print("지금 책 폴더:", cur if cur else f"{HERE / 'books'} (기본)")
    print("클라우드 동기화 폴더 등 새 경로를 붙여 넣고 Enter (그대로 두려면 그냥 Enter, 기본으로 되돌리려면 - 입력)")
    try:
        new = input("> ").strip().strip('"').strip()
    except EOFError:
        return 0
    if not new:
        print("바꾸지 않았습니다.")
        return 0
    if new == "-":
        CONFIG.unlink(missing_ok=True)
        print("기본(프로그램 폴더 안 books)으로 되돌렸습니다.")
        return 0
    p = Path(new).expanduser()
    if not p.is_dir():
        print(f"[오류] 폴더가 없습니다: {p}\n  클라우드 앱(Google Drive·OneDrive)이 켜져 있는지, 경로가 맞는지 확인하세요.")
        return 1
    CONFIG.write_bytes((str(p) + "\n").encode("utf-8"))
    books = sorted(d.name for d in p.iterdir() if d.is_dir() and not d.name.endswith(("_OCR", "_OCR_GPU")))
    print(f"저장했습니다: {p}")
    print("이 폴더의 책:", ", ".join(books) if books else "(아직 없음)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
