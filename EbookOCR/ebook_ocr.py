#!/usr/bin/env python3
"""
전자책 캡처 OCR — 페이지 이미지 폴더를 'AI 지식용' Markdown 한 파일로
=====================================================================

ebook_capture.py 로 찍은 page_0001.png ... 폴더를 읽어 본문 글자만 뽑습니다.
글자 인식은 시험지 OCR 과 같은 PaddleOCR 엔진(ocr_paddle.py)을 그대로 씁니다.

처리 방식
    1) 그림·사진 제외: 글자 영역을 지운 뒤에도 '큰 덩어리'로 남는 부분을 그림으로 보고,
       그 안에서 읽힌 글자(그림 속 글씨·잡음)는 버립니다.
    2) 머리말·꼬리말·쪽 번호 제거: 위·아래 가장자리에서 여러 쪽에 반복되는 줄과 숫자뿐인 줄을 뺍니다.
    3) 문단 복원: 화면 폭 때문에 생긴 줄바꿈을 이어 붙이고, 들여쓰기·줄 간격·문장 끝으로 문단을 나눕니다.
       쪽이 바뀌며 끊긴 문장도 이어 붙입니다. 마지막에 한국어 띄어쓰기를 교정합니다 (Kiwi). 본문보다 큰 글자 줄은 제목(##)으로 표시합니다.
       본문보다 작은 글자 줄은 각주로 보고 '> 주:' 로 따로 적어 본문 문장이 끊기지 않게 합니다.
    4) 쪽마다 인식 결과를 캐시에 저장하므로, 중간에 멈춰도 다시 실행하면 이어서 합니다.

사용 예 (Windows에서는 python 대신 py -3.12)
    python ebook_ocr.py 책이름                     # 책이름 폴더의 page_*.png → 책이름_OCR\\책이름.md
    python ebook_ocr.py 책이름 --page-marks        # 문단 사이에 <!-- p.12 --> 쪽 표시 넣기
    python ebook_ocr.py 책이름 --keep-pictures     # 그림 영역 글자도 버리지 않기
    python ebook_ocr.py 책이름 --redo              # 캐시를 무시하고 처음부터 다시 인식

출력
    <결과폴더>/<책이름>.md      AI 지식에 넣을 최종본 (문단 단위)
    <결과폴더>/<책이름>.txt     쪽별 원문 줄 (검토용, 쪽 구분선 포함)
    <결과폴더>/cache/           쪽별 인식 결과 (이어 하기용)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
# ocr_paddle.py 는 이 폴더에 복사해 두거나, 저장소의 시험지 OCR 폴더에서 가져온다
for _d in (HERE, HERE.parent / "OCR" / "ExamOCR_build"):
    if (_d / "ocr_paddle.py").is_file():
        sys.path.insert(0, str(_d))
        break

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
CACHE_VERSION = 1

# 문장이 끝났다고 볼 끝 글자
SENTENCE_END = re.compile(r"[.?!…。」』\"”’')\]>:;]$")
# 쪽 번호가 붙은 짧은 머리말·꼬리말: "4 | 프롤로그", "1장 시작하며 23"
FOOTER = re.compile(r"^\d{1,4}\s*[|│ㅣ·\-–—]?\s*\S.{0,40}$|^.{0,40}\S\s*[|│ㅣ·\-–—]?\s*\d{1,4}$")
# 각주 표시 기호만 있는 줄
NOTE_MARK = re.compile(r"^[\s•·∙●*※†‡]+$")
# 숫자뿐인 줄 (쪽 번호·진행률): 12 / - 12 - / 12 / 300 / 12쪽 / 37%
PAGE_NO = re.compile(r"^[\s\-–—·|]*(p\.?\s*)?\d{1,4}(\s*(/|of)\s*\d{1,4})?\s*(쪽|페이지|%)?[\s\-–—·|]*$", re.I)


# ----------------------------------------------------------------------------
# 자료 구조
# ----------------------------------------------------------------------------
@dataclass
class Row:
    text: str
    box: list[int]  # [x1, y1, x2, y2]
    score: float  # 줄 안 글상자들의 최저 신뢰도

    @property
    def h(self) -> int:
        return max(1, self.box[3] - self.box[1])


@dataclass
class Page:
    no: int
    name: str
    width: int
    height: int
    rows: list[Row]
    pictures: list[list[int]]  # 그림으로 판정한 영역


# ----------------------------------------------------------------------------
# 1) 쪽 인식
# ----------------------------------------------------------------------------
def picture_regions(img: np.ndarray, text_boxes: list[list[int]], min_fill: float) -> list[list[int]]:
    """글자 상자를 지운 뒤에도 남는 큰 덩어리 = 그림·사진 영역.

    · 배경색은 쪽의 가장 흔한 밝기로 잡아 흰 바탕·종이색 바탕 모두 처리한다.
    · 줄·밑줄처럼 가늘거나, 표 테두리처럼 속이 빈(채움 비율 < min_fill) 덩어리는 그림으로 보지 않는다.
    """
    import cv2

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    sat = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)[:, :, 1]
    bg = int(np.bincount(gray.ravel(), minlength=256).argmax())
    mask = ((np.abs(gray.astype(np.int16) - bg) > 24) | (sat > 60)).astype(np.uint8)

    h, w = gray.shape
    heights = [b[3] - b[1] for b in text_boxes]
    lh = int(np.median(heights)) if heights else max(12, h // 60)
    pad = max(2, lh // 6)
    for x1, y1, x2, y2 in text_boxes:
        mask[max(0, y1 - pad):y2 + pad, max(0, x1 - pad):x2 + pad] = 0

    k = max(3, lh // 2)
    closed = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (k, k)))
    n, _, stats, _ = cv2.connectedComponentsWithStats(closed, connectivity=8)
    out = []
    for i in range(1, n):
        x, y, bw, bh, _ = stats[i]
        if bw < 3 * lh or bh < 3 * lh or bw * bh < 0.01 * w * h:
            continue
        fill = float(mask[y:y + bh, x:x + bw].mean())
        if fill >= min_fill:
            out.append([int(x), int(y), int(x + bw), int(y + bh)])
    return out


def inside(box: list[int], region: list[int]) -> bool:
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    return region[0] <= cx <= region[2] and region[1] <= cy <= region[3]


def group_rows(items) -> list[Row]:
    """글상자를 줄로 묶는다 (ocr_paddle.group_lines 와 같은 기준, 줄 좌표를 함께 남김)."""
    rows: list[list] = []
    for it in sorted(items, key=lambda x: (x.cy, x.box[0])):
        if rows:
            row = rows[-1]
            row_cy = np.mean([r.cy for r in row])
            row_h = np.mean([r.h for r in row])
            if abs(it.cy - row_cy) <= 0.5 * min(row_h, it.h):
                row.append(it)
                continue
        rows.append([it])

    out = []
    for row in rows:
        row.sort(key=lambda x: x.box[0])
        text = " ".join(it.text.strip() for it in row)
        box = [min(it.box[0] for it in row), min(it.box[1] for it in row),
               max(it.box[2] for it in row), max(it.box[3] for it in row)]
        out.append(Row(text, box, min(it.score for it in row)))
    return out


def ocr_image(ocr, img: np.ndarray, no: int, name: str, args) -> Page:
    import ocr_paddle as op

    results = ocr.predict(np.ascontiguousarray(img))
    res = results[0] if results else None
    items = op.to_items(res, args.min_score) if res is not None else []
    pictures = [] if args.keep_pictures else picture_regions(img, [it.box for it in items], args.picture_fill)
    items = [it for it in items if not any(inside(it.box, p) for p in pictures)]
    h, w = img.shape[:2]
    return Page(no, name, w, h, group_rows(items), pictures)


def page_to_json(p: Page) -> dict:
    d = asdict(p)
    d["version"] = CACHE_VERSION
    return d


def page_from_json(d: dict) -> Page:
    return Page(d["no"], d["name"], d["width"], d["height"], [Row(**r) for r in d["rows"]], d["pictures"])


# ----------------------------------------------------------------------------
# 2) 머리말·꼬리말 제거
# ----------------------------------------------------------------------------
def _norm_key(text: str) -> str:
    return re.sub(r"\s+", "", re.sub(r"\d+", "#", text))


def strip_headers(pages: list[Page], band: float) -> None:
    """위·아래 가장자리(band 비율) 줄 중 쪽 번호, 쪽 번호가 붙은 짧은 줄, 여러 쪽에 반복되는 줄을 뺀다."""
    def edge(p: Page, r: Row) -> bool:
        return r.box[3] <= p.height * band or r.box[1] >= p.height * (1 - band)

    counts: dict[str, int] = {}
    for p in pages:
        for k in {_norm_key(r.text) for r in p.rows if edge(p, r)}:
            counts[k] = counts.get(k, 0) + 1
    limit = max(3, int(0.2 * len(pages)))
    repeated = {k for k, c in counts.items() if c >= limit}
    for p in pages:
        p.rows = [r for r in p.rows if not (edge(p, r) and (
            PAGE_NO.match(r.text) or FOOTER.match(r.text) or _norm_key(r.text) in repeated))]


# ----------------------------------------------------------------------------
# 3) 문단 복원
# ----------------------------------------------------------------------------
@dataclass
class Para:
    text: str
    page: int
    heading: bool = False
    note: bool = False  # 각주 (본문보다 작은 글자)
    open_end: bool = False  # 쪽 끝에서 문장이 끝나지 않음 (다음 쪽과 이어질 수 있음)
    cont_start: bool = False  # 쪽 첫 줄이 들여쓰기 없이 시작 (앞 쪽 문단의 이어짐일 수 있음)


HANGUL = "\uac00-\ud7a3"
WRAP_CHAR = False  # True: 한글끼리 이어지는 줄은 붙여 쓴다 (--wrap char, 띄어쓰기 교정을 켜면 기본)
SOFT = "\u2060"  # 붙여 이은 줄 경계 표시 (띄어쓰기 교정이 이 자리를 판단하고, 저장 전에 지운다)


def join_text(a: str, b: str) -> str:
    """줄 이어 붙이기. 영어 단어가 하이픈으로 끊긴 경우만 붙여 쓰고, 나머지는 띄어 쓴다.

    --wrap char 이면 한글 사이(따옴표·괄호를 사이에 둔 경우 포함)는 붙여 쓴다.
    (글자 단위로 줄을 바꾸는 뷰어는 줄 끝이 단어 중간인 경우가 대부분이라서)
    """
    if re.search(r"[A-Za-z]-$", a) and re.match(r"[a-z]", b):
        return a[:-1] + b
    if WRAP_CHAR and re.search(f"[{HANGUL}][\"'’”)」』〉》]?$", a) and re.match(f"[\"'‘“(「『〈《]?[{HANGUL}]", b):
        return a + SOFT + b
    return f"{a} {b}"


def book_metrics(pages: list[Page]) -> tuple[float, float]:
    """본문 글자 높이와 줄 간격(윗변 사이 거리)의 대표값."""
    hs = [r.h for p in pages for r in p.rows]
    pitches = [b.box[1] - a.box[1] for p in pages for a, b in zip(p.rows, p.rows[1:]) if b.box[1] > a.box[1]]
    lh = float(np.median(hs)) if hs else 20.0
    pitch = float(np.median(pitches)) if pitches else lh * 1.6
    return lh, pitch


def page_margins(p: Page) -> tuple[float, float] | None:
    """쪽의 본문 왼쪽·오른쪽 끝. 줄이 적으면 믿을 수 없어 None."""
    if len(p.rows) < 3:
        return None
    return float(np.percentile([r.box[0] for r in p.rows], 10)), float(np.percentile([r.box[2] for r in p.rows], 90))


def page_paragraphs(p: Page, lh: float, pitch: float, book_margins: tuple[float, float] | None) -> list[Para]:
    rows = p.rows
    if not rows:
        return []
    # 줄이 적은 쪽은 책 전체의 여백을 쓴다 (한 줄짜리 쪽이 '꽉 찬 줄'로 보여 다음 쪽과 잘못 이어지지 않게)
    left, right = page_margins(p) or book_margins or (min(r.box[0] for r in rows), max(r.box[2] for r in rows))

    paras: list[Para] = []
    cur: Para | None = None  # 지금 이어 붙이는 본문 문단
    prev: Row | None = None  # 직전 본문 줄
    note: Para | None = None  # 지금 이어 붙이는 각주
    for r in rows:
        if r.h < 0.75 * lh:  # 작은 글자 = 각주. 본문 흐름(cur·prev)은 건드리지 않는다
            if NOTE_MARK.match(r.text):
                continue
            if note is not None and paras and paras[-1] is note:
                note.text = join_text(note.text, r.text)
            else:
                note = Para(r.text, p.no, note=True)
                paras.append(note)
            continue
        note = None
        # 큰 글자 줄 = 제목. 단, 마침표로 끝나는 줄은 본문 (짧은 줄은 글상자가 커 보일 때가 있음)
        heading = r.h > 1.3 * lh and not r.text.rstrip().endswith(".")
        if heading and cur is not None and cur.heading and prev is not None and r.box[1] - prev.box[3] < r.h:
            cur.text = f"{cur.text} {r.text}"  # 두 줄로 된 제목은 한 제목으로
            prev = r
            continue
        indent = r.box[0] - left > 0.6 * lh
        gap = prev is not None and r.box[1] - prev.box[1] > 1.6 * pitch
        prev_short = prev is not None and prev.box[2] < right - 2 * lh and SENTENCE_END.search(prev.text)
        new = cur is None or heading or cur.heading or indent or gap or prev_short
        if new:
            cur = Para(r.text, p.no, heading=heading)
            paras.append(cur)
        else:
            cur.text = join_text(cur.text, r.text)
        prev = r

    body = [r for r in rows if r.h >= 0.75 * lh]
    texts = [x for x in paras if not x.note]
    if body and texts:
        last = body[-1]
        texts[-1].open_end = not texts[-1].heading and not (
            SENTENCE_END.search(last.text) and last.box[2] < right - 2 * lh)
        texts[0].cont_start = not texts[0].heading and body[0].box[0] - left <= 0.6 * lh
    return paras


def build_paragraphs(pages: list[Page]) -> list[Para]:
    lh, pitch = book_metrics(pages)
    ms = [m for m in map(page_margins, pages) if m is not None]
    book_margins = (float(np.median([m[0] for m in ms])), float(np.median([m[1] for m in ms]))) if ms else None
    out: list[Para] = []
    last_text: Para | None = None  # 마지막 본문 문단 (그 뒤에 각주가 와도 이어 붙일 수 있게)
    for p in pages:
        paras = page_paragraphs(p, lh, pitch, book_margins)
        first = next((x for x in paras if not x.note), None)
        if first is not None and last_text is not None and last_text.open_end and first.cont_start:
            last_text.text = join_text(last_text.text, first.text)
            last_text.open_end = first.open_end
            paras.remove(first)
        for x in paras:
            if not x.note:  # 본문 속 각주 표시(•) 지우기
                x.text = re.sub(r"\s*[•∙]\s*(?=\S)", "", x.text).strip()
        out.extend(paras)
        last_text = next((x for x in reversed(out) if not x.note), last_text)
    return out


SPACING_MIN_RUN = 6  # 띄어쓰기 없이 이만큼 이상 붙은 덩어리만 교정 (짧은 낱말·합성어는 그대로)


def merge_spaces(marked: str, fixed: str) -> str:
    """교정 결과에서 '새로 넣은 띄어쓰기'만 가져온다. 있던 띄어쓰기는 지우지 않고,
    짧은 덩어리(전자책, 인공지능의, 제1장 등)는 쪼개지 않는다. 붙여 이은 줄 경계(SOFT)는 길이와 상관없이 따른다."""
    orig, soft = "", set()
    for c in marked:
        if c == SOFT:
            soft.add(len(orig))
        else:
            orig += c
    if orig.replace(" ", "") != fixed.replace(" ", ""):
        return orig  # 글자가 바뀌었으면 손대지 않음
    inserts: set[int] = set()  # orig 의 이 위치 앞에 띄어쓰기를 넣을 후보
    i = j = 0
    while i < len(orig) and j < len(fixed):
        if orig[i] == fixed[j]:
            i += 1
            j += 1
        elif fixed[j] == " ":
            inserts.add(i)
            j += 1
        else:  # orig[i] == " " (교정기가 지운 띄어쓰기) → 그대로 둠
            i += 1
    # 덩어리 = 띄어쓰기와 줄 경계 사이. 긴 덩어리 안쪽 또는 줄 경계에만 띄어쓰기를 넣는다
    bounds = sorted({0, len(orig)} | soft | {m.start() for m in re.finditer(" ", orig)}
                    | {m.end() for m in re.finditer(" ", orig)})
    long_pos = set()
    for a, b in zip(bounds, bounds[1:]):
        if b - a >= SPACING_MIN_RUN and " " not in orig[a:b]:
            long_pos.update(range(a + 1, b))
    ok = inserts & (soft | long_pos)
    return "".join((" " if i in ok else "") + c for i, c in enumerate(orig))


def fix_spacing(paras: list[Para]) -> None:
    """한국어 띄어쓰기 교정 (Kiwi). OCR 이 빠뜨린 띄어쓰기만 넣고, 있는 띄어쓰기는 지우지 않는다."""
    try:
        from kiwipiepy import Kiwi
    except ImportError:
        print("[알림] kiwipiepy 가 없어 띄어쓰기 교정을 건너뜁니다 (설치.bat 를 다시 실행하면 설치됩니다).")
        return
    print("띄어쓰기 교정 중...")
    kiwi = Kiwi()
    targets = [x for x in paras if re.search(f"[{HANGUL}]", x.text)]
    plain = [x.text.replace(SOFT, "") for x in targets]
    for x, fixed in zip(targets, kiwi.space(plain, reset_whitespace=False)):
        x.text = merge_spaces(x.text, fixed)


# ----------------------------------------------------------------------------
# 4) 저장
# ----------------------------------------------------------------------------
def write_markdown(paras: list[Para], path: Path, title: str, page_marks: bool) -> None:
    lines = [f"# {title}", ""]
    last_page = None
    for para in paras:
        para.text = para.text.replace(SOFT, "")
        if page_marks and para.page != last_page:
            lines += [f"<!-- p.{para.page} -->", ""]
            last_page = para.page
        if para.heading:
            lines += [f"## {para.text}", ""]
        elif para.note:
            lines += [f"> 주: {para.text}", ""]
        else:
            lines += [para.text, ""]
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_raw(pages: list[Page], path: Path) -> None:
    out = []
    for p in pages:
        out.append(f"===== {p.no}쪽 ({p.name}){'  [그림 %d개 제외]' % len(p.pictures) if p.pictures else ''} =====")
        out += [r.text for r in p.rows]
        out.append("")
    path.write_text("\n".join(out), encoding="utf-8")


# ----------------------------------------------------------------------------
# 실행
# ----------------------------------------------------------------------------
def collect_pages(folder: Path) -> list[Path]:
    files = [f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in IMAGE_EXTS and not f.stem.startswith("test_")]
    key = lambda f: [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", f.stem)]  # noqa: E731
    return sorted(files, key=key)


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="전자책 캡처 이미지 폴더 → AI 지식용 Markdown")
    ap.add_argument("folder", help="page_0001.png ... 가 들어 있는 폴더")
    ap.add_argument("-o", "--output", help="결과 폴더 (기본: <폴더>_OCR)")
    ap.add_argument("--title", help="책 제목 (기본: 폴더 이름)")
    ap.add_argument("--page-marks", action="store_true", help="Markdown 에 <!-- p.N --> 쪽 표시 넣기")
    ap.add_argument("--no-spacing", action="store_true", help="한국어 띄어쓰기 교정(Kiwi) 끄기")
    ap.add_argument("--wrap", choices=["word", "char"],
                    help="줄 이을 때: word(띄어 씀) | char(한글끼리 붙여 씀). "
                         "기본: 띄어쓰기 교정을 켜면 char(교정기가 필요한 곳만 띄움), 끄면 word")
    ap.add_argument("--keep-pictures", action="store_true", help="그림 판정을 끄고 모든 글자 유지")
    ap.add_argument("--picture-fill", type=float, default=0.12,
                    help="그림 판정 채움 비율 (기본 0.12, 낮출수록 선 그림까지 그림으로 봄)")
    ap.add_argument("--header-band", type=float, default=0.1,
                    help="머리말·꼬리말로 볼 위·아래 가장자리 비율 (기본 0.1)")
    ap.add_argument("--keep-headers", action="store_true", help="머리말·꼬리말·쪽 번호 제거 끄기")
    ap.add_argument("--min-score", type=float, default=0.5, help="이 신뢰도 미만 글상자는 버림 (기본 0.5)")
    ap.add_argument("--redo", action="store_true", help="캐시를 무시하고 모든 쪽을 다시 인식")
    ap.add_argument("--device", default="auto", help="auto(기본) | cpu | gpu")
    ap.add_argument("--engine", choices=["paddle", "onnx"], default="paddle", help="계산 엔진 (ocr_paddle.py 와 같음)")
    ap.add_argument("--no-mkldnn", action="store_true", help="CPU 가속 끄기 (PaddlePaddle 3.3.x 오류 회피용)")
    return ap.parse_args(argv)


def main(argv=None) -> int:
    global WRAP_CHAR
    args = parse_args(argv)
    WRAP_CHAR = (args.wrap or ("word" if args.no_spacing else "char")) == "char"
    folder = Path(args.folder)
    if not folder.is_dir():
        print(f"[오류] 폴더가 없습니다: {folder}")
        return 1
    files = collect_pages(folder)
    if not files:
        print(f"[오류] 이미지가 없습니다: {folder}")
        return 1
    out_dir = Path(args.output) if args.output else folder.with_name(folder.name + "_OCR")
    cache = out_dir / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    title = args.title or folder.name

    pages: list[Page] = []
    ocr = None
    started = time.monotonic()
    done_now = 0
    for no, f in enumerate(files, start=1):
        cf = cache / f"{f.stem}.json"
        if not args.redo and cf.is_file() and cf.stat().st_mtime >= f.stat().st_mtime:
            d = json.loads(cf.read_text(encoding="utf-8"))
            if d.get("version") == CACHE_VERSION and d.get("min_score") == args.min_score \
                    and d.get("keep_pictures") == args.keep_pictures and d.get("picture_fill") == args.picture_fill:
                p = page_from_json(d)
                p.no = no
                pages.append(p)
                continue
        import ocr_paddle as op

        if ocr is None:
            print("OCR 엔진 준비 중... (처음엔 모델을 내려받아 시간이 걸립니다)")
            ocr = op.build_ocr(op.default_options(device=args.device, engine=args.engine, no_mkldnn=args.no_mkldnn))
        p = ocr_image(ocr, op.load_image(f), no, f.name, args)
        d = page_to_json(p)
        d.update(min_score=args.min_score, keep_pictures=args.keep_pictures, picture_fill=args.picture_fill)
        cf.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        pages.append(p)
        done_now += 1
        el = time.monotonic() - started
        print(f"\r  {no}/{len(files)}쪽 인식 ({el / done_now:.1f}초/쪽)", end="", flush=True)
    if done_now:
        print()

    write_raw(pages, out_dir / f"{title}.txt")
    if not args.keep_headers:
        strip_headers(pages, args.header_band)
    paras = build_paragraphs(pages)
    if not args.no_spacing:
        fix_spacing(paras)
    md = out_dir / f"{title}.md"
    write_markdown(paras, md, title, args.page_marks)

    n_pic = sum(len(p.pictures) for p in pages)
    chars = sum(len(x.text) for x in paras)
    print(f"완료: {len(pages)}쪽 → 문단 {len(paras)}개, {chars:,}자, 그림 {n_pic}개 제외")
    print(f"  최종본: {md.resolve()}")
    print(f"  검토용: {(out_dir / f'{title}.txt').resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
