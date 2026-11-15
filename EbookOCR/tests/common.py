"""시험 공용: 견본 책(9쪽)을 임시 폴더에 풀어 놓는다. 쪽 이미지는 PIL 로 즉석에서 만든다."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent  # EbookOCR
SAMPLE = HERE / "sample"


def make_book(with_config: bool = True, edited: bool = True) -> tuple[Path, Path]:
    """(책 폴더, 결과 폴더) 를 돌려준다. edited=True 면 편집기 조작 (가)·(나)를 한 결과로 고쳐 둔다:
    (가) 일괄 정리로 '## 1.1 개요' → '# 1.1 개요', (나) 8쪽에서 '2.1 설치'를 골라 [#]."""
    from PIL import Image, ImageDraw
    base = Path(tempfile.mkdtemp(prefix="ebook_test_"))
    book, out = base / "책", base / "책_OCR"
    book.mkdir(); out.mkdir()
    for i in range(1, 10):
        im = Image.new("RGB", (400, 560), "white")
        ImageDraw.Draw(im).text((20, 20), f"capture {i}", fill="black")
        im.save(book / f"page_{i:04d}.png")
    for name in ("책_교정.md", "책_교정용.md"):
        shutil.copy(SAMPLE / "책_OCR" / name, out / name)
    if with_config:
        shutil.copy(SAMPLE / "책_OCR" / "책_장설정.json", out / "책_장설정.json")
    if edited:
        f = out / "책_교정.md"
        t = f.read_text(encoding="utf-8")
        old = "앞 문장이 끝난다. 2.1 설치 첫 문장이다."
        assert old in t and "## 1.1 개요" in t
        t = t.replace("## 1.1 개요", "# 1.1 개요").replace(old, "앞 문장이 끝난다.\n\n# 2.1 설치\n\n첫 문장이다.")
        f.write_text(t, encoding="utf-8")
    return book, out
