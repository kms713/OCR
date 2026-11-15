"""OCR 마무리 단계 시험: 머리말·꼬리말 자동 제거를 뺐으므로 쪽 맨 위·아래 줄이 그대로 남는다.
(이전에는 '1. 분석할 …' 같은 번호 목록이 쪽 맨 위 두 줄이면 '쪽 번호 붙은 머리말'로 보고 지웠다)
PaddleOCR 없이: 인식 결과 캐시를 직접 만들어 두고 ebook_ocr.main 을 돌린다 (캐시가 있으면 엔진을 부르지 않음).
실행: python tests/test_ocr_headers.py"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ebook_ocr as eo  # noqa: E402

LINES = [  # (글, y) — 줄 높이 24, 번호 목록 줄 사이는 넓게
    ("머리말 반복 줄 7", 20),
    ("1. 분석할 논문 여러 편 체크", 100),
    ("2. 프롬프트에 추가: 표로 정리해줘", 160),
    ("3. 답변에서 논문별 비교 확인", 220),
    ("본문 문장이 이어집니다.", 280),
    ("소요 시간은 약 30", 340),
    ("12", 540),
]


def main():
    from PIL import Image
    base = Path(tempfile.mkdtemp(prefix="ebook_ocr_test_"))
    book, out = base / "책", base / "책_OCR"
    (out / "cache").mkdir(parents=True); book.mkdir()
    names = []
    for no in (1, 2, 3):
        name = f"page_{no:04d}.png"
        Image.new("RGB", (400, 600), "white").save(book / name)
        rows = [{"text": t.replace("7", str(no)).replace("12", str(10 + no)), "box": [40, y, 40 + 14 * len(t), y + 24], "score": 0.99}
                for t, y in LINES]
        d = {"no": no, "name": name, "width": 400, "height": 600, "rows": rows, "pictures": [], "boxes": rows,
             "version": eo.CACHE_VERSION, "min_score": 0.5, "keep_pictures": False, "picture_fill": 0.12}
        (out / "cache" / f"page_{no:04d}.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        names.append(name)
    assert eo.main([str(book), "--no-spacing"]) == 0
    md = (out / "책_교정용.md").read_text(encoding="utf-8")
    for want in ("1. 분석할 논문 여러 편 체크", "2. 프롬프트에 추가", "소요 시간은 약 30", "머리말 반복 줄 2", "11", "13"):
        assert want in md, (want, md)
    print("OCR 머리말·꼬리말 시험 통과 (맨 위·아래 줄이 남음)")


if __name__ == "__main__":
    main()
