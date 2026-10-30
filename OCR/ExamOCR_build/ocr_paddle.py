#!/usr/bin/env python3
"""
PaddleOCR 한국어 OCR 스크립트
==============================

스캔한 이미지(.png .jpg .jpeg .bmp .tif .tiff .webp)와 PDF를 읽어 HWPX(한글)와 텍스트 파일로 저장합니다.

설치 (최초 1회, 64비트 파이썬 3.12 또는 3.13 필요)
    py -3.12 -m pip install paddlepaddle==3.2.2 paddleocr python-hwpx

    * paddlepaddle 3.3.x는 CPU에서 'ConvertPirAttribute2RuntimeAttribute not support' 오류가 나는
      알려진 버그가 있어 3.2.2로 고정합니다. 3.3.x를 써야 한다면 --no-mkldnn 옵션으로 실행하세요(느려짐).
    * GPU(NVIDIA)를 쓰려면 paddlepaddle 대신 공식 설치 안내에 맞는 paddlepaddle-gpu를 설치하세요.
    * 첫 실행 때 모델(약 100MB)을 인터넷에서 내려받아 캐시합니다. 이후에는 오프라인으로 동작합니다.

처리 방식
    1) 두 단 편집이면 단 경계에서 페이지를 미리 잘라 왼쪽 단 → 오른쪽 단 순서로 읽습니다.
       (가운데 제목·꼬리말처럼 단 경계를 가로지르는 줄은 그 구간만 통째로 읽습니다.)
    2) 글자는 항상 '원본' 이미지에서 읽습니다.
    3) 뒷면 비침 제거 이미지는 판정용으로만 씁니다: 비침 제거 후 잉크가 거의 안 남는 글상자
       (= 뒷면 비침·연한 연필 자국)만 결과에서 뺍니다. 인쇄 글자 인식 결과는 바뀌지 않습니다.
    4) 테두리가 있는 표·박스는 HWPX에서 칸 하나짜리 표로 감싸 그 안에 글을 넣습니다.
       칸 구조는 살리지 않고, 위쪽이 뚫린 <보기>형 박스도 하나의 표로 봅니다. 글자·순서는 바뀌지 않습니다.

사용 예 (Windows에서는 python 대신 py -3.12)
    python ocr_paddle.py 시험지.pdf --mark-low 0.6
    python ocr_paddle.py 시험지.pdf --show-dropped          # 걸러낸 글상자를 각 페이지 끝에 따로 표시(검토용)
    python ocr_paddle.py 시험지.pdf --no-filter             # 걸러내기 끄기
    python ocr_paddle.py 시험지.pdf --layout single         # 두 단 분리 끄기
    python ocr_paddle.py 시험지.pdf --format txt            # HWPX 없이 텍스트만
    python ocr_paddle.py 시험지.pdf --no-table              # 표·박스를 표로 감싸지 않고 줄글로만
    python ocr_paddle.py 스캔폴더 -o 결과 --recursive

출력
    결과폴더/<파일이름>.hwpx     한글 문서 (페이지마다 쪽 나눔)
    결과폴더/<파일이름>.txt      텍스트 (PDF는 페이지 구분선 포함)
    결과폴더/<파일이름>.json     (--json) 글상자 좌표·신뢰도·제외 여부 포함 상세 결과
    결과폴더/vis/<파일이름>/     (--vis) 구간별 인식 영역을 그린 확인용 이미지
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}
PDF_EXTS = {".pdf"}
OUTPUT_FORMATS = {"hwpx", "txt"}

# 한국어 인식 모델 (한국어·영어·숫자 지원). 검출 모델은 언어와 무관합니다.
REC_MODEL = "korean_PP-OCRv5_mobile_rec"
DET_MODEL_ACCURATE = "PP-OCRv5_server_det"
DET_MODEL_FAST = "PP-OCRv5_mobile_det"

# 해상도 기준: A4를 300dpi로 그렸을 때 폭 약 2480~3035px. 형태학 커널 크기 등을 이 폭에 비례해 맞춘다.
REF_WIDTH = 3035


# ----------------------------------------------------------------------------
# 자료 구조
# ----------------------------------------------------------------------------
@dataclass
class Item:
    text: str
    score: float
    box: list[int]  # [x1, y1, x2, y2] (페이지 전체 기준 좌표)
    region: int = 0  # 읽은 구간 번호 (읽는 순서)
    ink: float | None = None  # 비침 제거 후 잉크 잔존율 (0~1)
    dropped: bool = False  # 비침·연한 자국으로 판정돼 결과에서 뺐는지

    @property
    def cy(self) -> float:
        return (self.box[1] + self.box[3]) / 2

    @property
    def h(self) -> float:
        return max(1, self.box[3] - self.box[1])


@dataclass
class PageResult:
    page: int  # 1부터 시작
    items: list[Item] = field(default_factory=list)  # 걸러낸 것 포함 전체
    lines: list[str] = field(default_factory=list)
    # lines와 같은 길이: 그 줄이 들어 있는 표·박스 번호 (표 밖이면 None). 비어 있으면 표 정보 없음
    line_boxes: list[int | None] = field(default_factory=list)

    @property
    def kept(self) -> list[Item]:
        return [it for it in self.items if not it.dropped]

    @property
    def mean_score(self) -> float:
        k = self.kept
        return float(np.mean([it.score for it in k])) if k else 0.0


# ----------------------------------------------------------------------------
# 입력 수집 / 읽기
# ----------------------------------------------------------------------------
def collect_inputs(paths: list[str], recursive: bool) -> list[Path]:
    files: list[Path] = []
    for p in map(Path, paths):
        if p.is_dir():
            it = p.rglob("*") if recursive else p.glob("*")
            files.extend(sorted(f for f in it if f.is_file() and f.suffix.lower() in IMAGE_EXTS | PDF_EXTS))
        elif p.is_file():
            if p.suffix.lower() in IMAGE_EXTS | PDF_EXTS:
                files.append(p)
            else:
                print(f"[건너뜀] 지원하지 않는 형식: {p}", file=sys.stderr)
        else:
            print(f"[건너뜀] 경로 없음: {p}", file=sys.stderr)
    seen, unique = set(), []
    for f in files:
        key = f.resolve()
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return unique


def load_image(path: Path) -> np.ndarray:
    """한글 경로에서도 깨지지 않도록 바이트로 읽어서 디코딩 (Windows의 cv2.imread 한글 경로 문제 회피)."""
    import cv2

    data = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)  # BGR
    if img is None:
        raise ValueError("이미지를 읽을 수 없습니다 (손상되었거나 지원하지 않는 형식)")
    return img


def render_pdf(path: Path, dpi: int) -> list[np.ndarray]:
    """PDF 각 페이지를 지정 해상도로 렌더링해 BGR 배열 목록으로 반환."""
    import cv2
    import pypdfium2 as pdfium  # paddleocr 설치 시 함께 설치됨

    pages = []
    pdf = pdfium.PdfDocument(str(path))
    try:
        for i in range(len(pdf)):
            page = pdf[i]
            pil = page.render(scale=dpi / 72).to_pil().convert("RGB")
            pages.append(cv2.cvtColor(np.asarray(pil), cv2.COLOR_RGB2BGR))
            page.close()
    finally:
        pdf.close()
    return pages


# ----------------------------------------------------------------------------
# 판정용 전처리 (원본은 건드리지 않음)
# ----------------------------------------------------------------------------
def flatten(img: np.ndarray) -> np.ndarray:
    """종이 배경 밝기를 추정해 나눠서 밝기를 고르게 만든 회색조 이미지 (글자=어둡게, 종이=255 근처)."""
    import cv2

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    w = gray.shape[1]
    k_dil = max(3, w // 200) | 1
    k_med = max(5, w // 100) | 1
    bg = cv2.medianBlur(cv2.dilate(gray, np.ones((k_dil, k_dil), np.uint8)), k_med)
    return cv2.divide(gray, bg, scale=255)


def ink_ratio(norm: np.ndarray, box: list[int], level: int) -> float:
    """글상자 안 잉크 중, level보다 진해서 비침 제거 후에도 남는 잉크의 비율."""
    x1, y1, x2, y2 = box
    h, w = norm.shape
    x1, x2 = max(0, x1), min(w, x2)
    y1, y2 = max(0, y1), min(h, y2)
    if x2 <= x1 or y2 <= y1:
        return 0.0
    patch = norm[y1:y2, x1:x2].astype(np.int64)
    total = (255 - patch).sum()
    if total <= 0:
        return 0.0
    kept = (255 - np.where(patch > level, 255, patch)).sum()
    return float(kept / total)


# ----------------------------------------------------------------------------
# 단(段) 분석: 읽기 전에 페이지를 구간으로 나눈다
# ----------------------------------------------------------------------------
def text_line_blobs(norm: np.ndarray) -> list[Item]:
    """진한 잉크만으로 글줄 덩어리를 대략 찾는다 (단 경계 판단용, OCR 아님)."""
    import cv2

    h, w = norm.shape
    s = w / REF_WIDTH
    bw = (norm < 140).astype(np.uint8) * 255
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (max(3, int(25 * s)), max(1, int(5 * s))))
    bw = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, k)
    n, _, stats, _ = cv2.connectedComponentsWithStats(bw)
    blobs = []
    for i in range(1, n):
        x, y, bw_, bh, _ = stats[i]
        if 20 * s < bh < 120 * s and bw_ > 40 * s and bw_ < w * 0.9:
            blobs.append(Item("", 1.0, [int(x), int(y), int(x + bw_), int(y + bh)]))
    return blobs


def find_gutter(items: list[Item], width: int) -> int | None:
    """두 단 문서의 단 사이 세로 경계(x좌표)를 찾는다. 두 단이 아니면 None.

    페이지 가운데 35~65% 구간에서 글상자를 가로지르는 개수가 가장 적은 x를 고르고,
    양쪽에 글이 고르게(각 20% 이상) 있으며 가로지르는 상자가 5% 이하일 때만 두 단으로 본다.
    """
    if len(items) < 10:
        return None
    n = len(items)
    step = max(1, width // 400)
    candidates = []
    for x in range(int(width * 0.35), int(width * 0.65), step):
        left = sum(1 for it in items if it.box[2] <= x)
        right = sum(1 for it in items if it.box[0] >= x)
        if left < 0.2 * n or right < 0.2 * n:
            continue
        candidates.append((n - left - right, x))
    if not candidates:
        return None
    best = min(c for c, _ in candidates)
    if best > 0.05 * n:
        return None
    # 꼬리말·제목 한두 개 때문에 경계 후보가 한쪽으로 쏠리지 않도록 약간의 여유를 둔다
    tol = max(1, int(0.01 * n))
    xs = [x for c, x in candidates if c <= best + tol]
    runs, run = [], [xs[0]]
    for x in xs[1:]:
        if x - run[-1] <= step:
            run.append(x)
        else:
            runs.append(run)
            run = [x]
    runs.append(run)
    longest = max(runs, key=len)
    return longest[len(longest) // 2]


def find_vertical_rule(norm: np.ndarray, g: int) -> tuple[int, int, int] | None:
    """단 경계 근처의 세로 구분선을 찾는다. (선의 x, 시작 y, 끝 y) 또는 None.

    시험지처럼 가운데 세로선이 있으면, 그 선이 있는 높이만 두 단이고 위(제목)·아래(꼬리말)는 통째로 읽어야 한다.
    """
    import cv2

    h, w = norm.shape
    s = w / REF_WIDTH
    # 글 배치로 추정한 경계(g) 주변만이 아니라 페이지 가운데 35~65% 전체에서 세로선을 찾는다
    x0, x1 = min(max(0, g - int(80 * s)), int(w * 0.35)), max(min(w, g + int(80 * s)), int(w * 0.65))
    # 세로로 긴 구조(구분선)만 남기기: 글자 획은 짧아서 사라짐. 스캔 기울기·끊김을 감안해 너그럽게 본다
    strip = (norm[:, x0:x1] < 200).astype(np.uint8)
    vert = cv2.morphologyEx(strip, cv2.MORPH_OPEN,
                            cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(15, int(60 * s)))))
    col = vert.sum(axis=0)
    if col.size == 0 or col.max() < 0.15 * h:
        return None
    c = int(np.argmax(col))
    lx = x0 + c
    tol = max(3, int(20 * s))
    rows = vert[:, max(0, c - tol): c + tol + 1].any(axis=1)
    gap = max(10, int(60 * s))  # 스캔 끊김 허용
    best, start, last = (0, 0, 0), None, None
    for y in np.flatnonzero(rows):
        if start is None or y - last > gap:
            if start is not None and last - start > best[0]:
                best = (last - start, start, last)
            start = y
        last = y
    if start is not None and last - start > best[0]:
        best = (last - start, start, last)
    if best[0] < 0.4 * h:
        return None
    return lx, int(best[1]), int(best[2])


def _shrink_by_side_rows(blobs: list[Item], g: int, top_cut: int, bottom_cut: int, h: int) -> tuple[int, int]:
    """구분선이 없는 위·아래 부분 중, 왼쪽·오른쪽 단 글줄이 나란히 있는 줄(단 사이가 크게 빈 줄)부터는 단으로 읽게 한다.

    구분선이 첫 문제 아래에서 시작하는 시험지에서 왼쪽·오른쪽 문제가 한 줄로 섞이는 것을 막는다.
    그런 줄이 없으면 경계를 그대로 둔다 (제목·꼬리말은 지금처럼 통째로 읽음).
    """
    def rows_in(y_top, y_bot):
        zone = sorted((b for b in blobs if b.box[1] >= y_top and b.box[3] <= y_bot), key=lambda b: b.box[1])
        rows: list[list[Item]] = []
        for b in zone:
            if rows:
                ry1 = min(x.box[1] for x in rows[-1])
                ry2 = max(x.box[3] for x in rows[-1])
                if min(ry2, b.box[3]) - max(ry1, b.box[1]) > 0.5 * min(ry2 - ry1, b.box[3] - b.box[1]):
                    rows[-1].append(b)
                    continue
            rows.append([b])
        return rows

    def kind(row):
        """'full' = 페이지를 가로지르는 줄(제목 등), 'side' = 양쪽 단 글줄이 나란히 있는 줄, 'one' = 한쪽에만 있는 줄."""
        if any(b.box[0] < g < b.box[2] for b in row):
            return "full"
        left = [b.box[2] for b in row if b.box[2] <= g]
        right = [b.box[0] for b in row if b.box[0] >= g]
        if not (left and right):
            return "one"
        height = max(b.box[3] for b in row) - min(b.box[1] for b in row)
        return "side" if min(right) - max(left) >= height else "full"

    # 위쪽: 마지막 '가로지르는 줄'(머리글) 아래에 '나란한 줄'이 있으면, 그 머리글 바로 아래부터 단으로 읽는다.
    # 가로지르는 줄이 없으면(머리글이 표 칸으로 나뉜 경우 등) 판단하지 않고 그대로 둔다.
    rows = rows_in(0, top_cut)
    kinds = [kind(r) for r in rows]
    if "full" in kinds:
        last_full = len(kinds) - 1 - kinds[::-1].index("full")
        if "side" in kinds[last_full + 1:]:
            top_cut = min(b.box[1] for b in rows[last_full + 1])
    # 아래쪽도 같은 방식 (첫 '가로지르는 줄' 위에 '나란한 줄'이 있으면 그 줄까지 단으로)
    rows = rows_in(bottom_cut, h)
    kinds = [kind(r) for r in rows]
    if "full" in kinds:
        first_full = kinds.index("full")
        if "side" in kinds[:first_full]:
            bottom_cut = max(b.box[3] for b in rows[first_full - 1])
    return top_cut, bottom_cut


def plan_regions(norm: np.ndarray, layout: str) -> tuple[list[tuple[int, int, int, int]], int | None]:
    """읽을 구간 목록을 읽는 순서대로 만든다. [(x1, y1, x2, y2), ...], 단 경계 x.

    두 단이면: (가로지르는 줄이 없는 세로 구간마다) 왼쪽 단 → 오른쪽 단, 가로지르는 줄이 있는 구간은 통째로.
    """
    h, w = norm.shape
    if layout != "auto":
        return [(0, 0, w, h)], None
    blobs = text_line_blobs(norm)
    g = find_gutter(blobs, w)
    if g is None:
        return [(0, 0, w, h)], None

    s = w / REF_WIDTH
    pad = max(2, int(10 * s))
    rule = find_vertical_rule(norm, g)
    top_cut, bottom_cut = 0, h
    if rule is not None:
        # 세로 구분선이 있으면 선 위치에서 자르고, 선이 없는 위·아래 부분(제목·꼬리말)은 통째로 읽는다.
        # 경계에 걸친 글줄은 단 쪽에 남기도록, 위쪽 경계는 그 줄 위로 올리고 아래쪽 경계는 그 줄 아래로 내린다.
        g, top_cut, bottom_cut = rule
        top_cut, bottom_cut = _shrink_by_side_rows(blobs, g, top_cut, bottom_cut, h)
        moved = True
        while moved:
            moved = False
            for b in blobs:
                if b.box[1] < top_cut < b.box[3]:
                    top_cut, moved = b.box[1], True
                if b.box[1] < bottom_cut < b.box[3]:
                    bottom_cut, moved = b.box[3], True
    # 구분선 구간 안에서 단 경계를 가로지르는 글줄의 세로 범위 → 같은 높이에 걸친 다른 글줄까지 포함하도록 넓힌다
    spans = [[b.box[1], b.box[3]] for b in blobs
             if b.box[0] < g < b.box[2] and b.box[3] > top_cut and b.box[1] < bottom_cut]
    changed = True
    while changed:
        changed = False
        for sp in spans:
            for b in blobs:
                if b.box[1] < sp[1] and b.box[3] > sp[0] and (b.box[1] < sp[0] or b.box[3] > sp[1]):
                    sp[0], sp[1] = min(sp[0], b.box[1]), max(sp[1], b.box[3])
                    changed = True
    spans = [[max(0, a - pad), min(h, b + pad)] for a, b in spans]
    if top_cut > 0:
        spans.append([0, top_cut])
    if bottom_cut < h:
        spans.append([bottom_cut, h])
    spans.sort()
    merged: list[list[int]] = []
    for a, b in spans:
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])

    regions: list[tuple[int, int, int, int]] = []
    cur = 0
    min_band = max(8, int(15 * s))

    def add_columns(y1, y2):
        if y2 - y1 >= min_band:
            regions.append((0, y1, g, y2))
            regions.append((g, y1, w, y2))

    for a, b in merged:
        add_columns(cur, a)
        regions.append((0, a, w, b))
        cur = b
    add_columns(cur, h)
    return regions, g


# ----------------------------------------------------------------------------
# 표·박스 찾기: 테두리가 있는 사각형만 (칸 구조는 보지 않는다)
# ----------------------------------------------------------------------------
def _segments(mask: np.ndarray, vertical: bool) -> list[tuple[int, int, int]]:
    """선 마스크의 덩어리마다 (위치, 시작, 끝). 세로선이면 (x, y1, y2), 가로선이면 (y, x1, x2)."""
    import cv2

    n, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    segs = []
    for i in range(1, n):
        x, y, bw, bh, _ = stats[i]
        segs.append((int(x + bw // 2), int(y), int(y + bh)) if vertical else (int(y + bh // 2), int(x), int(x + bw)))
    return segs


def find_boxes(norm: np.ndarray) -> list[list[int]]:
    """테두리가 있는 표·박스의 바깥 사각형 [x1, y1, x2, y2] 목록 (큰 것부터).

    · 길이가 비슷한 세로선 두 개 + 위·아래 가로선으로 사각형을 찾는다.
      위·아래 중 한쪽은 거의 끊김 없이 이어져야 하고(95%), 다른 쪽은 절반 가까이만 있어도 된다(40%).
      → 위쪽 선이 뚫리고 그 자리에 <보기> 같은 제목이 있는 박스도 잡힌다.
    · 칸이 나뉜 표는 바깥 사각형 하나로 본다 (다른 사각형과 겹치는 작은 것은 버림).
    · 페이지·단 전체를 두르는 테두리(높이 60% 초과)는 표로 보지 않는다.
    · 선 없이 글만 늘어놓은 표는 잡히지 않는다 → 지금처럼 줄글로 나온다.
    """
    import cv2

    h, w = norm.shape
    s = w / REF_WIDTH
    ink = (norm < 160).astype(np.uint8)
    # 길게 이어진 획만 남겨 선을 찾는다 (글자 획은 짧아서 사라짐). 스캔 끊김·기울기는 닫기로 메운다
    hor = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(15, int(80 * s)), 1)))
    hor = cv2.morphologyEx(hor, cv2.MORPH_CLOSE,
                           cv2.getStructuringElement(cv2.MORPH_RECT, (max(3, int(15 * s)), max(3, int(5 * s)))))
    ver = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(15, int(60 * s)))))
    ver = cv2.morphologyEx(ver, cv2.MORPH_CLOSE,
                           cv2.getStructuringElement(cv2.MORPH_RECT, (max(3, int(5 * s)), max(3, int(15 * s)))))

    min_w, min_h = 150 * s, 70 * s
    verts = [v for v in _segments(ver, vertical=True) if v[2] - v[1] >= min_h]
    tol = max(4, int(15 * s))

    def coverage(yl: int, yr: int, x1: int, x2: int) -> float:
        """왼쪽 끝 yl에서 오른쪽 끝 yr까지 이은 선을 따라 가로선이 있는 비율 (스캔 기울기 반영)."""
        xs = np.arange(x1, x2 + 1)
        ys = np.rint(np.linspace(yl, yr, xs.size)).astype(int)
        band = np.clip(ys[None, :] + np.arange(-tol, tol + 1)[:, None], 0, h - 1)
        return float(hor[band, xs[None, :]].any(axis=0).mean())

    cands = []
    for i, a in enumerate(verts):
        for b in verts[i + 1:]:
            l, r = (a, b) if a[0] < b[0] else (b, a)
            if r[0] - l[0] < min_w:
                continue
            overlap = min(l[2], r[2]) - max(l[1], r[1])
            if overlap < 0.8 * max(l[2] - l[1], r[2] - r[1]):
                continue
            y1, y2 = min(l[1], r[1]), max(l[2], r[2])
            if y2 - y1 > 0.6 * h:
                continue
            top, bottom = coverage(l[1], r[1], l[0], r[0]), coverage(l[2], r[2], l[0], r[0])
            if max(top, bottom) >= 0.95 and min(top, bottom) >= 0.4:
                cands.append([l[0], y1, r[0], y2])

    boxes: list[list[int]] = []
    for c in sorted(cands, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]), reverse=True):
        if not any(c[0] < o[2] and o[0] < c[2] and c[1] < o[3] and o[1] < c[3] for o in boxes):
            boxes.append(c)
    return boxes


def box_of(it: Item, boxes: list[list[int]]) -> int | None:
    """글상자가 들어 있는 표·박스 번호. 위쪽 테두리에 걸친 제목(<보기> 등)도 그 박스에 넣는다.

    테두리 위쪽에 있는 글은 테두리에 실제로 걸쳐 있을 때만 넣는다 (바로 위 줄이 딸려 들어가지 않게).
    """
    cx = (it.box[0] + it.box[2]) / 2
    for i, (x1, y1, x2, y2) in enumerate(boxes):
        if x1 <= cx <= x2 and it.cy <= y2 and (it.cy >= y1 or (it.box[3] > y1 and it.cy >= y1 - 0.5 * it.h)):
            return i
    return None


# ----------------------------------------------------------------------------
# OCR
# ----------------------------------------------------------------------------
def _is_ascii(p: Path) -> bool:
    try:
        str(p).encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


def find_bundled_models(det_name: str, rec_name: str, subdir: str = "models") -> tuple[Path, Path] | None:
    """프로그램과 함께 배포된 모델 폴더를 찾는다. 없으면 None (→ 인터넷에서 받아 캐시 사용).

    찾는 순서: 환경변수 OCR_MODEL_DIR → (패키징된 exe) exe 옆 subdir → 스크립트 옆 subdir
    subdir: 기본 엔진은 "models", ONNX 엔진은 "models_onnx"
    """
    import os

    candidates = []
    if os.environ.get("OCR_MODEL_DIR"):
        candidates.append(Path(os.environ["OCR_MODEL_DIR"]))
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / subdir)
        if hasattr(sys, "_MEIPASS"):
            candidates.append(Path(sys._MEIPASS) / subdir)
    candidates.append(Path(__file__).resolve().parent / subdir)

    for base in candidates:
        det, rec = base / det_name, base / rec_name
        if det.is_dir() and rec.is_dir():
            return _ascii_safe(det), _ascii_safe(rec)
    return None


def _ascii_safe(model_dir: Path) -> Path:
    """한글 등 비ASCII 문자가 든 경로에서는 Paddle이 모델을 못 여는 경우가 있어,
    그럴 때만 공용 폴더(C:\\Users\\Public\\ExamOCR\\models)에 한 번 복사해서 쓴다."""
    import os
    import shutil

    if _is_ascii(model_dir):
        return model_dir
    public = Path(os.environ.get("PUBLIC", r"C:\Users\Public"))
    target = public / "ExamOCR" / "models" / model_dir.name
    if not _is_ascii(target):
        return model_dir  # 안전한 경로를 못 찾으면 원래 경로로 시도
    src_files = sorted(p.relative_to(model_dir) for p in model_dir.rglob("*") if p.is_file())
    if not all((target / f).is_file() and (target / f).stat().st_size == (model_dir / f).stat().st_size
               for f in src_files):
        shutil.copytree(model_dir, target, dirs_exist_ok=True)
    return target


def build_ocr(args):
    import os

    # 실행할 때마다 모델 서버 접속 여부를 확인하느라 수 초씩 걸리는 단계를 건너뜀 (모델은 이미 캐시됨)
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    from paddleocr import PaddleOCR

    det_name = DET_MODEL_FAST if args.fast else DET_MODEL_ACCURATE
    kwargs = dict(
        text_detection_model_name=det_name,
        text_recognition_model_name=REC_MODEL,
        use_doc_orientation_classify=args.rotate,
        use_textline_orientation=args.rotate,
        use_doc_unwarping=args.unwarp,
    )
    onnx = getattr(args, "engine", "paddle") == "onnx"
    bundled = find_bundled_models(det_name, REC_MODEL, "models_onnx" if onnx else "models")
    if bundled is not None:
        kwargs["text_detection_model_dir"], kwargs["text_recognition_model_dir"] = map(str, bundled)
    if onnx:
        # ONNX Runtime 엔진: 전처리·후처리는 기본 엔진과 같은 코드, 계산만 ONNX Runtime이 한다.
        # 장치를 직접 지정해야 PaddlePaddle(=AVX 필요)를 아예 불러오지 않는다.
        if bundled is None:
            raise RuntimeError("models_onnx 폴더에 ONNX 모델이 없습니다")
        kwargs["engine"] = "onnxruntime"
        kwargs["device"] = "cpu"
        try:
            import onnxruntime

            onnxruntime.set_default_logger_severity(3)  # 변환 모델의 사소한 경고 메시지 숨김
        except Exception:
            pass
        return PaddleOCR(**kwargs)
    if args.device != "auto":
        kwargs["device"] = args.device
    if args.no_mkldnn:
        kwargs["enable_mkldnn"] = False
    return PaddleOCR(**kwargs)


def _field(res, key):
    """PaddleOCR 결과 객체에서 값 꺼내기 (버전별 차이 흡수)."""
    try:
        return res[key]
    except Exception:
        pass
    j = getattr(res, "json", None)
    if isinstance(j, dict):
        return j.get("res", j).get(key)
    return None


def to_items(res, min_score: float, dx: int = 0, dy: int = 0, region: int = 0) -> list[Item]:
    texts = _field(res, "rec_texts") or []
    scores = _field(res, "rec_scores")
    boxes = _field(res, "rec_boxes")
    scores = [] if scores is None else np.asarray(scores).tolist()
    boxes = [] if boxes is None else np.asarray(boxes).tolist()

    items = []
    for text, score, box in zip(texts, scores, boxes):
        if not str(text).strip() or score < min_score:
            continue
        x1, y1, x2, y2 = (int(v) for v in box)
        items.append(Item(str(text), float(score), [x1 + dx, y1 + dy, x2 + dx, y2 + dy], region=region))
    return items


def group_rows(items: list[Item]) -> list[list[Item]]:
    """글상자를 위→아래 순으로 줄 단위로 묶는다 (줄 안은 왼쪽→오른쪽)."""
    rows: list[list[Item]] = []
    for it in sorted(items, key=lambda x: (x.cy, x.box[0])):
        if rows:
            row = rows[-1]
            row_cy = np.mean([r.cy for r in row])
            row_h = np.mean([r.h for r in row])
            if abs(it.cy - row_cy) <= 0.5 * min(row_h, it.h):
                row.append(it)
                continue
        rows.append([it])
    for row in rows:
        row.sort(key=lambda x: x.box[0])
    return rows


def row_text(row: list[Item], mark_low: float) -> str:
    parts = []
    for i, it in enumerate(row):
        text = f"{it.text}[?]" if mark_low > 0 and it.score < mark_low else it.text
        if i > 0:
            gap = it.box[0] - row[i - 1].box[2]
            parts.append("\t" if gap > 1.5 * it.h else " ")
        parts.append(text)
    return "".join(parts)


def group_lines(items: list[Item], mark_low: float) -> list[str]:
    """글상자를 위→아래, 왼쪽→오른쪽 순으로 묶어 줄 단위 텍스트로 만든다."""
    return [row_text(row, mark_low) for row in group_rows(items)]


MAX_ASPECT = 8  # 구간의 가로:세로(또는 세로:가로)가 이보다 길쭉하면 흰 여백을 덧대 비율을 맞춘다


def prepare_crop(img: np.ndarray, norm: np.ndarray, box) -> tuple[np.ndarray | None, int, int]:
    """OCR에 넣을 구간 이미지와, 결과 좌표를 페이지 좌표로 되돌릴 이동량(dx, dy).

    · 진한 잉크가 거의 없는 빈 구간은 넣지 않는다 (None).
    · 아주 얇고 긴 띠(예: 3035x39)는 엔진이 극단적인 크기로 늘렸다 줄이면서 오류를 낼 수 있어,
      위아래(또는 좌우)에 흰 여백을 덧대 비율을 MAX_ASPECT 이내로 맞춘다. 원본 내용은 그대로다.
    """
    import cv2

    x1, y1, x2, y2 = box
    crop = img[y1:y2, x1:x2]
    h, w = crop.shape[:2]
    if h < 16 or w < 16:
        return None, 0, 0
    if int((norm[y1:y2, x1:x2] < 160).sum()) < 50:
        return None, 0, 0
    py = max(0, (w // MAX_ASPECT - h + 1) // 2)
    px = max(0, (h // MAX_ASPECT - w + 1) // 2)
    if py or px:
        crop = cv2.copyMakeBorder(crop, py, py, px, px, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    return np.ascontiguousarray(crop), x1 - px, y1 - py


def ocr_page(ocr, img: np.ndarray, args, vis_out: Path | None, page_no: int) -> PageResult:
    norm = flatten(img)
    regions, gutter = plan_regions(norm, args.layout)

    items: list[Item] = []
    for ri, region in enumerate(regions):
        crop, dx, dy = prepare_crop(img, norm, region)
        if crop is None:
            continue
        results = ocr.predict(crop)
        res = results[0] if results else None
        if res is None:
            continue
        items.extend(to_items(res, args.min_score, dx=dx, dy=dy, region=ri))
        if vis_out is not None:
            vis_out.mkdir(parents=True, exist_ok=True)
            res.save_to_img(str(vis_out / f"page_{page_no:03d}_part_{ri + 1:02d}.png"))

    # 비침·연한 자국 판정 (인식 결과 글자는 바꾸지 않고, 뺄지 말지만 정함)
    for it in items:
        it.ink = ink_ratio(norm, it.box, args.filter_level)
        it.dropped = not args.no_filter and it.ink < args.filter_ratio

    # 구간 순서대로 줄 만들기 (구간 사이 빈 줄). 글자·순서는 표 찾기와 상관없이 같다
    boxes = find_boxes(norm) if getattr(args, "tables", True) else []
    lines: list[str] = []
    line_boxes: list[int | None] = []
    for ri in range(len(regions)):
        rows = group_rows([it for it in items if it.region == ri and not it.dropped])
        if rows:
            if lines:
                lines.append("")
                line_boxes.append(None)
            for row in rows:
                lines.append(row_text(row, args.mark_low))
                # 줄의 글상자가 모두 같은 표 안에 있을 때만 그 표의 줄로 본다
                ids = {box_of(it, boxes) for it in row}
                line_boxes.append(ids.pop() if len(ids) == 1 else None)

    if args.show_dropped:
        dropped = [it for it in items if it.dropped]
        if dropped:
            lines += ["", "----- [걸러낸 글상자: 뒷면 비침·연한 자국으로 판정] -----"]
            lines += [f"{it.text}  (잉크 {it.ink:.2f})" for it in sorted(dropped, key=lambda x: (x.cy, x.box[0]))]
    line_boxes += [None] * (len(lines) - len(line_boxes))
    return PageResult(page=page_no, items=items, lines=lines, line_boxes=line_boxes)


class Stopped(Exception):
    """사용자가 중지를 눌렀을 때."""


def page_count(path: Path) -> int:
    """PDF 쪽수 (이미지는 1)."""
    if path.suffix.lower() not in PDF_EXTS:
        return 1
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(path))
    try:
        return len(pdf)
    finally:
        pdf.close()


def ocr_file(ocr, path: Path, args, vis_dir: Path | None, on_page=None, should_stop=None) -> list[PageResult]:
    """on_page(완료한 쪽 번호, 전체 쪽수): 쪽마다 호출. should_stop(): True면 다음 쪽 전에 Stopped."""
    images = render_pdf(path, args.pdf_dpi) if path.suffix.lower() in PDF_EXTS else [load_image(path)]
    vis_out = vis_dir / path.stem if vis_dir is not None else None
    pages = []
    for idx, img in enumerate(images, start=1):
        if should_stop is not None and should_stop():
            raise Stopped()
        pages.append(ocr_page(ocr, img, args, vis_out, idx))
        if on_page is not None:
            on_page(idx, len(images))
    return pages


def default_options(**overrides) -> argparse.Namespace:
    """명령줄과 같은 기본 설정 (GUI 등에서 사용)."""
    args = parse_args(["_"])
    for k, v in overrides.items():
        setattr(args, k, v)
    return args


def next_free_path(folder: Path, stem: str, suffix: str) -> Path:
    """이미 있으면 덮어쓰지 않고 이름(2), 이름(3) ... 으로."""
    p = folder / f"{stem}{suffix}"
    n = 2
    while p.exists():
        p = folder / f"{stem}({n}){suffix}"
        n += 1
    return p


# ----------------------------------------------------------------------------
# 저장
# ----------------------------------------------------------------------------
def unique_stem(path: Path, used: set[str]) -> str:
    stem, n = path.stem, 2
    while stem in used:
        stem = f"{path.stem}_{n}"
        n += 1
    used.add(stem)
    return stem


def page_blocks(pages: list[PageResult]) -> list[tuple[str | None, list[str]]]:
    """(페이지 제목 줄 또는 None, 본문 줄 목록) 목록."""
    if len(pages) == 1:
        return [(None, pages[0].lines)]
    return [(f"===== {p.page} 페이지 =====", p.lines) for p in pages]


def table_runs(lines: list[str], line_boxes: list[int | None]) -> list[tuple[int | None, list[str]]]:
    """줄 목록을 (표 번호 또는 None, 줄들) 덩어리로 나눈다. 같은 표의 줄은 사이 빈 줄까지 한 덩어리로."""
    ids = line_boxes if len(line_boxes) == len(lines) else [None] * len(lines)
    runs: list[tuple[int | None, list[str]]] = []
    i = 0
    while i < len(lines):
        b = ids[i]
        j = i + 1
        while j < len(lines):
            if ids[j] == b:
                j += 1
            elif b is not None and not lines[j] and j + 1 < len(lines) and ids[j + 1] == b:
                j += 2  # 단 구간 사이 빈 줄 하나를 건너 같은 표가 이어지는 경우
            else:
                break
        runs.append((b, lines[i:j]))
        i = j
    return runs


def write_txt(pages: list[PageResult], path: Path) -> None:
    chunks = []
    for title, lines in page_blocks(pages):
        body = "\n".join(lines)
        chunks.append(f"{title}\n{body}" if title else body)
    path.write_text("\n\n".join(chunks) + "\n", encoding="utf-8")


def write_hwpx(pages: list[PageResult], path: Path) -> None:
    try:
        from hwpx import HwpxDocument
    except ImportError as e:
        raise RuntimeError(
            "HWPX 저장에는 python-hwpx가 필요합니다: py -3.12 -m pip install python-hwpx "
            "(또는 --format txt 로 실행)"
        ) from e

    doc = HwpxDocument.new()
    first_para = doc.paragraphs[0]  # 새 문서에 기본으로 있는 빈 문단
    used_first = False
    page_start = False

    def add_text(text):
        nonlocal used_first, page_start
        if not used_first:
            first_para.text = text
            used_first = True
        elif page_start:
            doc.add_paragraph(text, pageBreak="1")  # 원본 페이지마다 새 쪽에서 시작
        else:
            doc.add_paragraph(text)
        page_start = False

    for pi, ((title, lines), page) in enumerate(zip(page_blocks(pages), pages)):
        page_start = pi > 0
        if title:
            add_text(title)
        if not lines:
            add_text("")
        for box, chunk in table_runs(lines, page.line_boxes):
            if box is None:
                for text in chunk:
                    add_text(text)
            else:
                # 표·박스: 칸 하나짜리 표에 줄마다 문단으로 넣는다
                if page_start or not used_first:
                    add_text("")
                table = doc.add_table(1, 1)
                table.set_cell_text(0, 0, "\n".join(chunk), split_paragraphs=True)
    doc.save_to_path(str(path))


def write_json(pages: list[PageResult], path: Path, src: Path) -> None:
    data = {
        "source": str(src),
        "pages": [
            {
                "page": p.page,
                "mean_score": round(p.mean_score, 4),
                "lines": p.lines,
                "items": [
                    {
                        "text": it.text,
                        "score": round(it.score, 4),
                        "box": it.box,
                        "region": it.region,
                        "ink": None if it.ink is None else round(it.ink, 3),
                        "dropped": it.dropped,
                    }
                    for it in p.items
                ],
            }
            for p in pages
        ],
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_outputs(pages: list[PageResult], out_dir: Path, stem: str, src: Path, args) -> list[Path]:
    written = []
    if "txt" in args.formats:
        p = out_dir / f"{stem}.txt"
        write_txt(pages, p)
        written.append(p)
    if "hwpx" in args.formats:
        p = out_dir / f"{stem}.hwpx"
        write_hwpx(pages, p)
        written.append(p)
    if args.json:
        p = out_dir / f"{stem}.json"
        write_json(pages, p, src)
        written.append(p)
    return written


# ----------------------------------------------------------------------------
# 실행
# ----------------------------------------------------------------------------
def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="PaddleOCR 한국어 OCR — 스캔 이미지/PDF를 HWPX·텍스트로 변환")
    ap.add_argument("inputs", nargs="+", help="이미지·PDF 파일 또는 폴더")
    ap.add_argument("-o", "--output", default="ocr_output", help="결과 폴더 (기본: ocr_output)")
    ap.add_argument("-r", "--recursive", action="store_true", help="폴더 안 하위 폴더까지 처리")
    ap.add_argument("--format", default="hwpx,txt",
                    help="저장 형식, 쉼표로 여러 개 (hwpx, txt). 기본: hwpx,txt")
    ap.add_argument("--json", action="store_true", help="좌표·신뢰도·제외 여부 포함 JSON도 저장")
    ap.add_argument("--vis", action="store_true", help="구간별 인식 영역을 그린 확인용 이미지 저장")
    ap.add_argument("--device", default="auto", help="auto(기본) | cpu | gpu | gpu:0 ...")
    ap.add_argument("--engine", choices=["paddle", "onnx"], default="paddle",
                    help="계산 엔진: paddle(기본) | onnx (AVX 없는 구형 PC용, models_onnx 필요)")
    ap.add_argument("--fast", action="store_true", help="가벼운 검출 모델 (빠르지만 정확도 낮음, 비권장)")
    ap.add_argument("--no-mkldnn", action="store_true", help="CPU 가속(oneDNN) 끄기 — PaddlePaddle 3.3.x 오류 회피용, 느려짐")
    ap.add_argument("--rotate", action="store_true", help="돌아간 페이지·거꾸로 된 글줄 자동 보정")
    ap.add_argument("--unwarp", action="store_true", help="휘어진 문서 사진 펴기 (느림, 스캔본에는 불필요)")
    ap.add_argument("--pdf-dpi", type=int, default=300, help="PDF 렌더링 해상도 (기본 300)")
    ap.add_argument("--layout", choices=["auto", "single"], default="auto",
                    help="auto(기본): 두 단이면 단 경계에서 잘라 단별로 읽음 / single: 페이지 통째로")
    ap.add_argument("--no-filter", action="store_true", help="뒷면 비침·연한 자국 걸러내기 끄기")
    ap.add_argument("--filter-level", type=int, default=180,
                    help="걸러내기 판정 밝기 0~255 (기본 180). 이보다 연한 잉크를 비침으로 봄")
    ap.add_argument("--filter-ratio", type=float, default=0.25,
                    help="글상자 잉크 중 진한 잉크 비율이 이 값 미만이면 뺌 (기본 0.25, 낮출수록 덜 뺌)")
    ap.add_argument("--no-table", dest="tables", action="store_false",
                    help="테두리 있는 표·박스를 HWPX 표로 감싸지 않고 줄글로만 저장")
    ap.add_argument("--show-dropped", action="store_true", help="걸러낸 글상자를 각 페이지 끝에 따로 적기 (검토용)")
    ap.add_argument("--min-score", type=float, default=0.0, help="이 신뢰도 미만 결과는 버림 (0~1, 기본 0=모두 유지)")
    ap.add_argument("--mark-low", type=float, default=0.0, help="이 신뢰도 미만 결과 뒤에 [?] 표시 (교정용, 예: 0.6)")
    args = ap.parse_args(argv)
    args.formats = {f.strip().lower() for f in args.format.split(",") if f.strip()}
    bad = args.formats - OUTPUT_FORMATS
    if bad or not args.formats:
        ap.error(f"--format 에는 {', '.join(sorted(OUTPUT_FORMATS))} 만 쓸 수 있습니다 (입력: {args.format})")
    return args


def main(argv=None) -> int:
    args = parse_args(argv)
    files = collect_inputs(args.inputs, args.recursive)
    if not files:
        print("처리할 파일이 없습니다.", file=sys.stderr)
        return 1
    if "hwpx" in args.formats:
        try:
            import hwpx  # noqa: F401
        except ImportError:
            print("HWPX 저장에는 python-hwpx가 필요합니다. 먼저 설치하세요:\n"
                  "  py -3.12 -m pip install python-hwpx\n"
                  "(HWPX 없이 텍스트만 원하면 --format txt)", file=sys.stderr)
            return 1

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    vis_dir = out_dir / "vis" if args.vis else None

    print("모델 불러오는 중... (첫 실행은 모델 다운로드로 시간이 걸립니다)")
    t0 = time.perf_counter()
    ocr = build_ocr(args)
    print(f"준비 완료 ({time.perf_counter() - t0:.1f}초). 파일 {len(files)}개 처리 시작\n")

    used_stems: set[str] = set()
    failed: list[tuple[Path, str]] = []
    total_pages = 0
    for i, f in enumerate(files, start=1):
        t = time.perf_counter()
        try:
            pages = ocr_file(ocr, f, args, vis_dir)
            written = write_outputs(pages, out_dir, unique_stem(f, used_stems), f, args)
        except Exception as e:  # 한 파일 실패가 전체를 멈추지 않도록
            failed.append((f, str(e)))
            print(f"[{i}/{len(files)}] 실패  {f.name}: {e}", file=sys.stderr)
            continue
        total_pages += len(pages)
        kept = sum(len(p.kept) for p in pages)
        dropped = sum(len(p.items) - len(p.kept) for p in pages)
        scores = [it.score for p in pages for it in p.kept]
        mean = f"{np.mean(scores):.3f}" if scores else "-"
        print(
            f"[{i}/{len(files)}] 완료  {f.name}  →  {', '.join(p.name for p in written)}  "
            f"(페이지 {len(pages)}, 글상자 {kept}, 걸러냄 {dropped}, 평균 신뢰도 {mean}, "
            f"{time.perf_counter() - t:.1f}초)"
        )

    print(f"\n총 {len(files) - len(failed)}개 파일 / {total_pages}페이지 완료 → {out_dir.resolve()}")
    if failed:
        print(f"실패 {len(failed)}개:", file=sys.stderr)
        for f, msg in failed:
            print(f"  - {f}: {msg}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
