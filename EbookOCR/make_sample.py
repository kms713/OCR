#!/usr/bin/env python3
"""
교정기 시험용 샘플 책 만들기
============================

책 폴더(책폴더.txt 의 경로, 없으면 books)에 '샘플책'(쪽 이미지 3장)과 '샘플책_OCR'(OCR 결과처럼 만든 글·줄 상자·
AI 제안)을 만듭니다. OCR·Gemini 없이 교정 편집기(4_교정.bat)와 내보내기(5_내보내기.bat)를 시험할 수 있습니다.

글에는 일부러 잘못을 넣었습니다: 띄어쓰기·빠진 마침표·OCR 오인식(하엿다), 본문에 섞인 각주(▸, ●), 낮은 신뢰도 줄([?]).

사용: python make_sample.py   (샘플책_만들기.bat)
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

from bookdir import HERE, books_root

NAME = "샘플책"
W, H = 1600, 1000           # LD플레이어 캡처처럼 폭이 넓고, 글은 가운데에만
LEFT, RIGHT = 520, 1080     # 글 영역

# 쪽마다 (종류, 이미지에 그릴 바른 글). 종류: h=제목, p=본문, n=작은 글씨(각주), pic=그림, cap=그림 설명
PAGES = [
    [("h", "01-1 샘플 책으로 교정기 시험하기"),
     ("p", "이 책은 교정 편집기를 시험하려고 만든"),
     ("p", "가짜 책입니다. 원본 이미지와 글을 나란히"),
     ("p", "보면서 틀린 곳을 고쳐 보세요. 기다림 없는"),
     ("p", "답변이라는 변화가 모든 것을 바꾸었습니다."),
     ("n", "▸ 이 줄은 본문보다 작은 글씨의 각주입니다."),
     ("p", "그는 집에 갔다고 하였다. 그리고 다음 날"),
     ("p", "아침 일찍 다시 돌아왔다.")],
    [("h", "그림과 각주"),
     ("p", "아래 그림은 주가가 내려가는 모습을 보여 줍니다."),
     ("pic", ""),
     ("cap", "그림 1. 샘플 주가 그래프 (가상 자료)"),
     ("p", "2021년 1주당 113달러였던 주식이 98%"),
     ("p", "떨어졌습니다. 이 줄은 신뢰도가 낮습니다.")],
    [("h", "마무리"),
     ("p", "마지막 쪽입니다. 아래 표는 '표 넣기 모드'로"),
     ("p", "칸을 나눠 넣어 보세요."),
     ("table", [["구분", "클릭 시대", "AI 검색 시대"],
                ["성과 목표", "클릭률(CTR)", "첫 답변 언급률,|출처 카드 수"],
                ["최적화 단위", "페이지 전체", "문장과 문단"]]),
     ("n", "● 출처: 예시 자료, 2026.")],
]

# OCR 결과처럼 만든 교정용 글 (일부러 잘못을 넣음). 쪽마다 문단 목록
MD_PAGES = [
    ["## 01-1 샘플 책으로 교정기 시험하기",
     "이 책은 교정 편집기를 시험하려고 만든 가짜 책입니다 원본 이미지와 글을 나란히 보면서 틀린 곳을 고쳐 보세요. "
     "기다림 없는 답변이라는 변화가 모든 것을 바꾸었습니다 ▸ 이 줄은 본문보다 작은 글씨의 각주입니다.",
     "그는 집에 갔다고 하엿다. 그리고 다음 날 아침 일찍 다시 돌아왔다."],
    ["## 그림과 각주",
     "아래 그림은 주가가 내려가는 모습을 보여 줍니다.",
     "> 주: 그림 1. 샘플 주가 그래프 (가상 자료)",
     "2021년 1 주당 113달러였던 주식이 98 %떨어졌습니다. 이 줄은 신뢰[?]도가 낮습니다."],
    ["## 마무리",
     "마지막 쪽입니다. 아래 표는 '표 넣기 모드'로 칸을 나눠 넣어 보세요.",
     "구분 클릭 시대 AI 검색 시대 성과 목표 클릭률(CTR) 첫 답변 언급률, 출처 카드 수 최적화 단위 페이지 전체 문장과 문단",
     "● 출처: 예시 자료, 2026."],
]

# AI 제안 (원문 문단 → 고친 문단)
SUGGEST = {
    MD_PAGES[0][1]: MD_PAGES[0][1].replace("가짜 책입니다 원본", "가짜 책입니다. 원본")
                                   .replace("바꾸었습니다 ▸", "바꾸었습니다. ▸"),
    MD_PAGES[0][2]: MD_PAGES[0][2].replace("하엿다", "하였다"),
    MD_PAGES[1][3]: MD_PAGES[1][3].replace("1 주당", "1주당").replace("98 %떨어졌습니다", "98% 떨어졌습니다")
                                   .replace("신뢰[?]도", "신뢰도"),
}


def font(size: int):
    from PIL import ImageFont

    for f in (r"C:\Windows\Fonts\malgun.ttf", r"C:\Windows\Fonts\gulim.ttc",
              "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
              "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
              "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"):
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_page(items) -> tuple:
    from PIL import Image, ImageDraw

    im = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(im)
    rows, pics, boxes = [], [], []
    y = 90
    for kind, text in items:
        if kind == "table":  # 가로선만 있는 표. 칸마다 글상자, 한 줄 전체는 OCR 처럼 줄 하나로
            f = font(22)
            xs = [LEFT, LEFT + 150, LEFT + 330, RIGHT]
            d.line([(LEFT, y), (RIGHT, y)], fill=(90, 90, 90), width=2)
            for r, cells in enumerate(text):
                y0 = y + 10
                parts = [c.split("|") for c in cells]
                nl = max(len(p) for p in parts)
                line_boxes = []
                for c, lines in enumerate(parts):
                    yy = y0 + (nl - len(lines)) * 15  # 줄 수가 적은 칸은 세로 가운데
                    for t in lines:
                        bx = d.textbbox((xs[c] + 10, yy), t, font=f)
                        d.text((xs[c] + 10, yy), t, fill=(30, 30, 30), font=f)
                        b = [bx[0] - 2, bx[1] - 3, bx[2] + 2, bx[3] + 3]
                        boxes.append({"text": t, "box": b, "score": 0.97})
                        line_boxes.append((t, b))
                        yy += 30
                # OCR 줄(rows): 세로로 겹치는 칸 글을 한 줄로 묶은 것처럼
                line_boxes.sort(key=lambda tb: (tb[1][1], tb[1][0]))
                for t, b in line_boxes:
                    rows.append({"text": t, "box": b, "score": 0.97})
                y = y0 + nl * 30 + 10
                d.line([(LEFT, y), (RIGHT, y)], fill=(160, 160, 160), width=1)
            y += 18
            continue
        if kind == "pic":
            box = [LEFT + 40, y, RIGHT - 40, y + 240]
            d.rectangle(box, outline=(120, 120, 120), width=2)
            pts = [(box[0] + 20 + i * 45, box[1] + 40 + (i * i * 3) % 150 + i * 6) for i in range(11)]
            d.line(pts, fill=(47, 111, 237), width=4)
            pics.append(box)
            y = box[3] + 18
            continue
        size = {"h": 40, "p": 28, "n": 20, "cap": 20}[kind]
        f = font(size)
        x0, y0, x1, y1 = d.textbbox((LEFT, y), text, font=f)
        d.text((LEFT, y), text, fill=(30, 30, 30) if kind != "cap" else (90, 90, 90), font=f)
        score = 0.55 if "신뢰도가 낮습니다" in text else 0.97
        rows.append({"text": text, "box": [x0 - 2, y0 - 3, x1 + 2, y1 + 3], "score": score})
        boxes.append({"text": text, "box": [x0 - 2, y0 - 3, x1 + 2, y1 + 3], "score": score})
        y = y1 + (30 if kind == "h" else 16)
    d.text((RIGHT - 40, H - 60), str(len(rows)), fill=(150, 150, 150), font=font(18))  # 쪽 번호 흉내
    return im, rows, pics, boxes


def para_id(text: str) -> str:  # ebook_suggest.para_id 와 같게
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]


def main() -> int:
    root = books_root() or HERE / "books"
    book, out = root / NAME, root / f"{NAME}_OCR"
    print(f"책 폴더: {root}")
    if book.exists() or out.exists():
        ans = input(f"'{NAME}' 이 이미 있습니다. 지우고 새로 만들까요? (교정한 내용도 지워짐) [y/N] ").strip().lower()
        if ans != "y":
            print("그대로 두었습니다.")
            return 0
        for p in (book, out):
            if p.exists():
                shutil.rmtree(p)
    (out / "cache").mkdir(parents=True)
    book.mkdir(parents=True)
    for i, items in enumerate(PAGES, start=1):
        im, rows, pics, boxes = draw_page(items)
        im.save(book / f"page_{i:04d}.png")
        cache = {"width": W, "height": H, "rows": rows, "pictures": pics, "boxes": boxes}
        (out / "cache" / f"page_{i:04d}.json").write_bytes(json.dumps(cache, ensure_ascii=False).encode("utf-8"))
    md = [f"# {NAME}", ""]
    for i, paras in enumerate(MD_PAGES, start=1):
        md += [f"<!-- p.{i} -->"]
        for p in paras:
            md += [p, ""]
    (out / f"{NAME}_교정용.md").write_bytes("\n".join(md).encode("utf-8"))
    store = {"version": 1, "checked": sorted(para_id(p) for ps in MD_PAGES for p in ps),
             "items": {para_id(o): {"orig": o, "sug": s, "flags": [], "status": "new"} for o, s in SUGGEST.items()}}
    (out / f"{NAME}_제안.json").write_bytes(json.dumps(store, ensure_ascii=False, indent=1).encode("utf-8"))
    print(f"만들었습니다: {book}  /  {out}")
    print(f"이제 4_교정.bat 를 실행하고 책 이름에 {NAME} 을 입력하세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
