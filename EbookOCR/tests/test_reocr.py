"""영역 다시 읽기 시험: 표 넣기(글 없는 영역 → 저절로 다시 읽어 표 초안), 그림 넣기('이 영역 글자 다시 읽기').
PaddleOCR 없이 돌리려고 가짜 엔진을 쓴다: 이미지의 검은 네모를 찾아 정해 둔 글자로 돌려준다.
좌표 되돌리기(여백·2배 확대)는 실제 엔진과 같은 코드(ebook_ocr.ocr_region)를 지난다.
실행: python tests/test_reocr.py   (편집기 부분은 Playwright 필요)"""
from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, make_book  # noqa: E402

sys.path.insert(0, str(ROOT))
import ebook_ocr  # noqa: E402
import ebook_review  # noqa: E402

PORT = 8793
# 쪽 5에 그린 2×2 표 (쪽 픽셀 좌표). 그림으로 판정돼 OCR 글이 버려진 상황 (캐시에 글상자 없음)
CELLS = [([60, 200, 150, 225], "구분"), ([220, 200, 300, 225], "값"),
         ([60, 250, 150, 275], "속도"), ([220, 250, 300, 275], "12")]
TABLE_BOX = [40, 180, 340, 300]


def _runs(mask_1d: np.ndarray) -> list[tuple[int, int]]:
    out, start = [], None
    for i, v in enumerate(list(mask_1d) + [False]):
        if v and start is None:
            start = i
        elif not v and start is not None:
            out.append((start, i)); start = None
    return out


def blobs(img: np.ndarray) -> list[list[int]]:
    """검은 네모들의 [x1, y1, x2, y2] (위 줄부터, 줄 안은 왼쪽부터). 격자로 놓인 네모만 다룬다."""
    dark = (img.min(axis=2) if img.ndim == 3 else img) < 128
    out = []
    for y1, y2 in _runs(dark.any(axis=1)):
        for x1, x2 in _runs(dark[y1:y2].any(axis=0)):
            out.append([x1, y1, x2, y2])
    return out


class FakeOCR:
    """PaddleOCR.predict 흉내: 받은 그림(잘라 덧대고 키운 것)에서 검은 네모를 찾아 CELLS 글자를 차례로 붙인다."""
    def __init__(self):
        self.shapes = []

    def predict(self, img):
        self.shapes.append(img.shape)
        bs = blobs(img)
        texts = [t for _, t in CELLS][:len(bs)]
        return [{"rec_texts": texts, "rec_scores": [0.99] * len(texts), "rec_boxes": bs[:len(texts)]}]


def page_image(n_cells=4) -> np.ndarray:
    img = np.full((560, 400, 3), 255, dtype=np.uint8)
    for (x1, y1, x2, y2), _ in CELLS[:n_cells]:
        img[y1:y2, x1:x2] = 0
    return img


def test_region_unit():
    eng = FakeOCR()
    boxes, rows = ebook_ocr.ocr_region(eng, page_image(), TABLE_BOX)
    assert eng.shapes and eng.shapes[0][0] > (TABLE_BOX[3] - TABLE_BOX[1]) * 2, eng.shapes  # 작은 영역은 2배로 키워 읽음
    assert [b.text for b in boxes] == ["구분", "값", "속도", "12"], boxes
    for b, (want, _) in zip(boxes, CELLS):  # 쪽 좌표로 되돌아왔는지 (반올림 1px 허용)
        assert all(abs(p - q) <= 1 for p, q in zip(b.box, want)), (b.box, want)
    assert [r.text for r in rows] == ["구분 값", "속도 12"], rows
    try:
        ebook_ocr.ocr_region(eng, page_image(), [10, 10, 14, 14])
        raise AssertionError("너무 작은 영역을 받아들임")
    except ValueError:
        pass


def serve(book_dir, out_dir, engine):
    b = ebook_review.Book(book_dir, out_dir, "책")
    b.ensure_work_file()
    ebook_review.Book._ocr = engine
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), ebook_review.make_handler(b))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def post(path, obj):
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", data=json.dumps(obj).encode(), method="POST",
                                 headers={"X-Ebook-Review": "1", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_no_engine():  # 엔진이 없는 PC(교정용 가벼운 설치): 안내 오류
    try:
        import paddleocr  # noqa: F401
        print("  (PaddleOCR 이 있어 엔진 없음 시험은 건너뜀)")
        return
    except ImportError:
        pass
    book, out = make_book(with_config=False, edited=False)
    httpd = serve(book, out, None)
    try:
        code, j = post("/api/reocr", {"page": 5, "box": TABLE_BOX})
        assert code == 503 and "설치.bat" in j["error"], (code, j)
    finally:
        httpd.shutdown(); httpd.server_close()


def test_editor():
    from PIL import Image
    from playwright.sync_api import sync_playwright
    book, out = make_book(with_config=False, edited=False)
    Image.fromarray(page_image()).save(book / "page_0005.png")
    httpd = serve(book, out, FakeOCR())
    try:
        code, j = post("/api/reocr", {"page": 5, "box": TABLE_BOX})
        assert code == 200 and [b["text"] for b in j["boxes"]] == ["구분", "값", "속도", "12"], (code, j)
        with sync_playwright() as pw:
            try:
                br = pw.chromium.launch()
            except Exception:
                br = pw.chromium.launch(executable_path="/opt/pw-browsers/chromium")
            pg = br.new_page()
            pg.goto(f"http://127.0.0.1:{PORT}/")
            pg.wait_for_function("document.getElementById('status').textContent === '준비됨'")
            pg.fill("#pageNo", "5"); pg.press("#pageNo", "Enter")
            pg.wait_for_function("document.getElementById('imgTitle').textContent.includes('5')")
            pg.wait_for_function("(() => { const i = document.getElementById('pageImg'); return i.complete && i.naturalWidth > 0; })()")
            pg.wait_for_timeout(100)
            ed = lambda: pg.input_value("#editor")  # noqa: E731

            # 표 넣기: 고른 영역에 OCR 글이 없으면 저절로 다시 읽어 표 초안
            pg.evaluate(f"() => {{ pendingBox = {TABLE_BOX}; openTableDialog(pendingBox); }}")
            pg.wait_for_function("document.getElementById('tblText').value.includes('속도')")
            md = pg.input_value("#tblText").split("\n")
            assert md == ["| 구분 | 값 |", "|---|---|", "| 속도 | 12 |"], md
            assert "다시 읽은 글 4개" in pg.inner_text("#tblInfo"), pg.inner_text("#tblInfo")
            pg.click("#tblOk")
            assert "| 구분 | 값 |\n|---|---|\n| 속도 | 12 |" in ed(), ed()

            # 그림 넣기: '이 영역 글자 다시 읽기' → 그림 대신 본문 글로
            pg.evaluate(f"() => {{ pendingBox = {TABLE_BOX}; openFigDialog(); }}")
            assert pg.is_hidden("#figOcrBox")
            pg.click("#figReocr")
            pg.wait_for_function("document.getElementById('figOcr').value.length > 0")
            assert pg.input_value("#figOcr") == "구분 값\n속도 12", pg.input_value("#figOcr")
            pg.click("#figOcrAlt")
            assert pg.input_value("#figAlt") == "구분 값 속도 12"
            pg.click("#figOcrText")
            assert not pg.eval_on_selector("#figDlg", "d => d.open")
            assert "구분 값\n\n속도 12" in ed() and "![" not in ed(), ed()
            br.close()
    finally:
        httpd.shutdown(); httpd.server_close()
        ebook_review.Book._ocr = None


if __name__ == "__main__":
    test_region_unit(); print("통과: test_region_unit")
    test_no_engine(); print("통과: test_no_engine")
    test_editor(); print("통과: test_editor")
