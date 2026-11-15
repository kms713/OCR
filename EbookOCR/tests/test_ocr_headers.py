"""OCR 마무리 단계 시험: 글자로 읽힌 것은 모두 남는다.
  · 머리말·꼬리말 자동 제거를 뺐으므로 쪽 맨 위·아래 줄이 그대로 남는다
    (이전에는 '1. 분석할 …' 같은 번호 목록이 쪽 맨 위 두 줄이면 '쪽 번호 붙은 머리말'로 보고 지웠다)
  · 화면 캡처처럼 작은 글자가 빽빽한 곳도 글자는 남기고 점선 '그림?' 표시만 한다
  · 그림 영역 글자를 버리던 예전 캐시는 그림 영역이 있던 쪽만 다시 인식 대상
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
# 화면 캡처 속 작은 글 (본문 높이 0.6배 미만, 10개가 빽빽하게): 예전에는 그림으로 보고 뺐다
TINY = [(f"작은글{i}", 400 + (i // 2) * 25, 40 + (i % 2) * 100) for i in range(10)]


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
        if no == 2:
            rows += [{"text": t, "box": [x, y, x + 60, y + 10], "score": 0.99} for t, y, x in TINY]
        d = {"no": no, "name": name, "width": 400, "height": 600, "rows": rows, "pictures": [], "boxes": rows,
             "version": eo.CACHE_VERSION, "min_score": 0.5, "keep_pictures": False, "picture_fill": 0.12}
        (out / "cache" / f"page_{no:04d}.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        names.append(name)
    assert eo.main([str(book), "--no-spacing"]) == 0
    md = (out / "책_교정용.md").read_text(encoding="utf-8")
    for want in ("1. 분석할 논문 여러 편 체크", "2. 프롬프트에 추가", "소요 시간은 약 30", "머리말 반복 줄 2", "11", "13"):
        assert want in md, (want, md)
    assert all(t in md for t, _, _ in TINY), md  # 화면 캡처 속 작은 글도 남음
    c2 = json.loads((out / "cache" / "page_0002.json").read_text(encoding="utf-8"))
    assert c2.get("screens"), c2.get("screens")  # 대신 점선 '그림?' 영역으로 표시
    # 캐시를 그대로 쓸지
    base_d = {"version": eo.CACHE_VERSION, "boxes": [], "min_score": 0.5}
    assert eo.cache_usable({**base_d, "all_text": True, "pictures": [[0, 0, 9, 9]]}, 0.5)
    assert eo.cache_usable({**base_d, "keep_pictures": False, "pictures": []}, 0.5)  # 예전 캐시, 그림 없던 쪽
    assert not eo.cache_usable({**base_d, "keep_pictures": False, "pictures": [[0, 0, 9, 9]]}, 0.5)  # 글자를 버렸던 쪽
    assert not eo.cache_usable({**base_d, "all_text": True, "pictures": []}, 0.3)
    print("OCR 시험 통과 (맨 위·아래 줄, 화면 캡처 속 작은 글 남음, 예전 캐시 판정)")


if __name__ == "__main__":
    main()
