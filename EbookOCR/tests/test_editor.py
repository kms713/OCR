"""편집기 시험 (요청서 3장 기대 결과 1~3).  Playwright(Chromium) 필요.  실행: python tests/test_editor.py"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, make_book  # noqa: E402

PORT = 8791


def main():
    from playwright.sync_api import sync_playwright
    book, out = make_book(with_config=False, edited=False)   # 설정·고침 없이 시작해 화면에서 직접 만든다
    srv = subprocess.Popen([sys.executable, str(ROOT / "ebook_review.py"), str(book), "--port", str(PORT), "--no-browser"],
                           cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        for _ in range(50):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{PORT}/", timeout=1); break
            except Exception:
                time.sleep(0.2)
        with sync_playwright() as pw:
            br = pw.chromium.launch()
            pg = br.new_page()
            answer = {"v": None}
            pg.on("dialog", lambda d: d.accept(answer["v"]) if answer["v"] is not None else d.dismiss())
            pg.goto(f"http://127.0.0.1:{PORT}/")
            pg.wait_for_function("document.getElementById('status').textContent === '준비됨'")

            def go(n):
                pg.fill("#pageNo", str(n)); pg.press("#pageNo", "Enter")
                pg.wait_for_function(f"document.getElementById('imgTitle').textContent.includes('{n}')")

            # 설정 없는 책은 예전 이름 그대로
            go(4); assert pg.inner_text("#imgTitle").startswith("4쪽"), pg.inner_text("#imgTitle")

            # 1) 글 없는 3쪽에서 [챕터 시작]
            go(3)
            pg.click("#chapStart")
            pg.fill("#chName", "1장 시작"); pg.fill("#chPart", "Part 1. 기초"); pg.fill("#chPage", "1")
            pg.click("#chOk"); pg.wait_for_function("!document.getElementById('chapDlg').open")
            go(6)
            pg.click("#chapStart")
            assert pg.input_value("#chPart") == "Part 1. 기초", pg.input_value("#chPart")   # 앞 챕터의 파트가 미리 채워짐
            pg.fill("#chName", "2장 도구"); pg.fill("#chPage", "4"); pg.select_option("#chSplit", "topic")
            pg.click("#chOk"); pg.wait_for_function("!document.getElementById('chapDlg').open")
            # 쪽 7 빼기, 쪽 9 번호 교정(prompt 는 값으로 응답)
            go(7); pg.click("#pageSkip")
            answer["v"] = "8"
            go(9); pg.click("#pageFix")
            pg.wait_for_function("document.getElementById('imgTitle').textContent.includes('책 8P')")

            # 2) 쪽 이름
            go(4); assert pg.inner_text("#imgTitle").startswith("책 2P (캡처 4)"), pg.inner_text("#imgTitle")
            go(9); assert pg.inner_text("#imgTitle").startswith("책 8P (캡처 9)"), pg.inner_text("#imgTitle")
            go(2); assert pg.inner_text("#imgTitle").startswith("책 앞2"), pg.inner_text("#imgTitle")
            # 뺀 쪽은 진행률에서 빠짐
            assert "뺀" in pg.inner_text("#progress")

            # 3) 8쪽에서 '2-1 설치' 를 골라 [###]
            go(8)
            pg.evaluate("""() => { const e = document.getElementById('editor'); const k = e.value.indexOf('2-1 설치');
                e.focus(); e.setSelectionRange(k, k + '2-1 설치'.length); }""")
            pg.click("#fH3")
            v = pg.input_value("#editor")
            assert v.split("\n\n") == ["앞 문장이 끝난다.", "### 2-1 설치", "첫 문장이다."], repr(v)
            # 선택 없이 줄 전체
            pg.evaluate("() => { const e = document.getElementById('editor'); e.setSelectionRange(0, 0); }")
            pg.click("#fH4")
            assert pg.input_value("#editor").startswith("#### 앞 문장이 끝난다."), pg.input_value("#editor")
            pg.click("#fP")
            # 쪽 목록·목차
            pg.click("#pageList"); txt = pg.inner_text("#pgListBody")
            assert "책 2P (캡처 4)" in txt and "챕터 시작: 1장 시작" in txt and "뺀 쪽" in txt, txt
            pg.click("#pgListClose")
            br.close()

        cfg = json.loads((out / "책_장설정.json").read_text(encoding="utf-8"))
        assert [c["capture"] for c in cfg["chapters"]] == [3, 6] and cfg["skip_pages"] == [7]
        assert cfg["page_fixes"] == [{"capture": 9, "page": 8}], cfg
        assert cfg["chapters"][1]["split"] == "topic" and cfg["chapters"][1]["part"] == "Part 1. 기초"
        print("편집기 시험 통과")
    finally:
        srv.terminate()


if __name__ == "__main__":
    main()
