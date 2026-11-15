"""편집기 시험 (요청서 v3 3절 기대 결과 1~3, 그리고 편집기로 만든 결과를 내보내 4~8 한 번 더).
Playwright(Chromium) 필요.  실행: python tests/test_editor.py"""
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
    md = out / "책_교정.md"
    md.write_text(md.read_text(encoding="utf-8").replace("<!-- p.1 -->\n\n", ""), encoding="utf-8")  # 옛 파일: 글 없는 1쪽에 쪽 표시 없음
    srv = subprocess.Popen([sys.executable, str(ROOT / "ebook_review.py"), str(book), "--port", str(PORT), "--no-browser"],
                           cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        for _ in range(50):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{PORT}/", timeout=1); break
            except Exception:
                time.sleep(0.2)
        with sync_playwright() as pw:
            try:
                br = pw.chromium.launch()
            except Exception:  # 브라우저가 따로 깔린 환경 (Playwright 판이 달라 기본 경로에 없을 때)
                br = pw.chromium.launch(executable_path="/opt/pw-browsers/chromium")
            pg = br.new_page()
            answer = {"v": None}
            pg.on("dialog", lambda d: d.accept(answer["v"]) if answer["v"] is not None else d.dismiss())
            pg.goto(f"http://127.0.0.1:{PORT}/")
            pg.wait_for_function("document.getElementById('status').textContent === '준비됨'")
            ed = lambda: pg.input_value("#editor")  # noqa: E731

            def go(n):
                pg.fill("#pageNo", str(n)); pg.press("#pageNo", "Enter")
                pg.wait_for_function(f"document.getElementById('imgTitle').textContent.includes('{n}')")
                pg.wait_for_function(f"(() => {{ const i = document.getElementById('pageImg'); return i.src.endsWith('/img/{n}') && i.complete && i.naturalWidth > 0; }})()")
                pg.wait_for_timeout(50)  # 이미지가 뜬 뒤 글 칸 맞춤(커서 맨 앞)이 끝나게

            def saved():
                pg.click("#saveNow"); pg.wait_for_function("document.getElementById('status').textContent.startsWith('저장됨')")

            # 설정 없는 책은 예전 이름 그대로
            go(4); assert pg.inner_text("#imgTitle").startswith("4쪽"), pg.inner_text("#imgTitle")
            # 버튼은 # ~ ###### 여섯 개, 범례에 '## 챕터' 없음
            assert [pg.inner_text(f"#fH{n}") for n in range(1, 7)] == ["#" * n for n in range(1, 7)]
            assert "챕터" not in pg.inner_text(".legend")

            # 쪽 표시가 없던 글 없는 쪽(1)에도 글을 쓸 수 있다
            go(1); assert not pg.eval_on_selector("#editor", "e => e.readOnly")
            pg.fill("#editor", "표지 글"); saved()
            t = md.read_text(encoding="utf-8")
            assert "<!-- p.1 -->\n\n표지 글\n\n<!-- p.2 -->" in t, t[:80]

            # 목차 창 (캡처 2): OCR 글로 채워짐 → Enter 로 나누고 Tab 으로 단계
            go(2); pg.click("#tocInput")
            pre = pg.input_value("#tocText").split("\n")
            assert pre[:4] == ["Part 1. 기초", "1장 시작", "1.1 개요", "2장 도구"] and "차례" not in pre, pre
            pg.fill("#tocText", "Part 1. 기초\n1장 시작\n1.1 개요\n2장 도구 2.1 설치")
            pg.evaluate("""() => { const e = document.getElementById('tocText'); const k = e.value.indexOf('2.1 설치');
                e.focus(); e.setSelectionRange(k, k); }""")
            pg.keyboard.press("Enter")
            v = pg.input_value("#tocText")

            def sel_lines(a, b):  # a 줄 ~ b 줄 고르기 (0부터)
                pg.evaluate(f"""() => {{ const e = document.getElementById('tocText'), L = e.value.split('\\n');
                    let s = 0; for (let i = 0; i < {a}; i++) s += L[i].length + 1;
                    let t = s; for (let i = {a}; i <= {b}; i++) t += L[i].length + (i < {b} ? 1 : 0);
                    e.focus(); e.setSelectionRange(s, t); }}""")
            sel_lines(1, 4); pg.keyboard.press("Tab")
            sel_lines(2, 2); pg.keyboard.press("Tab")
            sel_lines(4, 4); pg.keyboard.press("Tab"); pg.keyboard.press("Tab"); pg.keyboard.press("Shift+Tab")
            v = pg.input_value("#tocText")
            assert [x.rstrip() for x in v.split("\n")] == ["Part 1. 기초", "  1장 시작", "    1.1 개요", "  2장 도구", "    2.1 설치"], repr(v)
            pg.click("#tocOk"); pg.wait_for_function("!document.getElementById('tocDlg').open")

            # 1) 글 없는 3쪽에서 [챕터 시작] — 챕터명을 목차에서 고르면 파트가 채워짐
            go(3)
            pg.click("#chapStart")
            opts = pg.eval_on_selector_all("#chNameList option", "os => os.map(o => o.value)")
            assert "1장 시작" in opts and "2장 도구" in opts, opts
            pg.fill("#chName", "1장 시작")
            assert pg.input_value("#chPart") == "Part 1. 기초", pg.input_value("#chPart")
            pg.fill("#chPage", "1")
            pg.click("#chOk"); pg.wait_for_function("!document.getElementById('chapDlg').open")
            go(6)
            pg.click("#chapStart")
            assert pg.input_value("#chPart") == "Part 1. 기초", pg.input_value("#chPart")   # 앞 챕터의 파트가 미리 채워짐
            assert "2장 도구" in pg.eval_on_selector_all("#chNameList option", "os => os.map(o => o.value)")
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
            go(2); assert pg.inner_text("#imgTitle").startswith("책 앞2") and "목차" in pg.inner_text("#imgTitle"), pg.inner_text("#imgTitle")
            assert "뺀" in pg.inner_text("#progress")

            # 3-가) [제목 구조] → 일괄 정리: '1.1 개요' 를 # 로. '2장 도구' 는 체크가 미리 빠져 있음
            answer["v"] = ""  # confirm 은 확인
            pg.click("#headBtn")
            rows = pg.eval_on_selector_all("#headList .hr", "rs => rs.map(r => [r.querySelector('input').checked, r.innerText])")
            assert rows and not any(on for on, _ in rows), rows  # 처음에는 모두 체크 해제
            two = [(on, t) for on, t in rows if "2장 도구" in t]
            assert len(two) == 2 and all("⚠" in t for _, t in two), two
            pg.select_option("#hdPat", "n2")  # 거르기로 고른 줄만 체크
            rows = pg.eval_on_selector_all("#headList .hr", "rs => rs.map(r => [r.querySelector('input').checked, r.innerText])")
            assert len(rows) == 1 and "1.1 개요" in rows[0][1] and rows[0][0], rows
            pg.select_option("#hdPat", "")  # 거르기 '모두' → 다시 모두 해제
            assert not any(pg.eval_on_selector_all("#headList .hr input", "is => is.map(i => i.checked)"))
            pg.select_option("#hdPat", "n2")
            pg.click("#hdSuggest")  # 자동 제안: 제안이 있고 단계가 다른 줄만 체크
            assert "→ #" in pg.inner_text("#headList")
            pg.select_option("#hdTo", "1"); pg.click("#hdApply")
            pg.click("#hdUndo")  # 되돌리기 → 다시
            assert "\n## 1.1 개요" in pg.evaluate("() => full"), "되돌리기 실패"
            pg.select_option("#hdTo", "1"); pg.click("#hdApply")
            assert "\n# 1.1 개요" in pg.evaluate("() => full")
            pg.click("#headClose")
            go(4); assert ed().startswith("# 1.1 개요"), ed()

            # 3-나) 8쪽에서 '2.1 설치' 를 골라 [#]
            go(8)
            pg.evaluate("""() => { const e = document.getElementById('editor'); const k = e.value.indexOf('2.1 설치');
                e.focus(); e.setSelectionRange(k, k + '2.1 설치'.length); }""")
            pg.click("#fH1")
            assert ed().split("\n\n") == ["앞 문장이 끝난다.", "# 2.1 설치", "첫 문장이다."], repr(ed())
            # 선택 없이 줄 전체
            pg.evaluate("() => { const e = document.getElementById('editor'); e.setSelectionRange(0, 0); }")
            pg.click("#fH2"); assert ed().startswith("## 앞 문장이 끝난다."), ed()
            pg.click("#fP"); assert ed().startswith("앞 문장이 끝난다."), ed()

            # 본문 목록 줄에서 Tab/Shift+Tab, 목록 줄이 아니면 그대로
            go(5); orig = ed()
            pg.fill("#editor", "- 가\n- 나")
            pg.evaluate("() => { const e = document.getElementById('editor'); e.focus(); e.setSelectionRange(e.value.length, e.value.length); }")
            pg.keyboard.press("Tab"); assert ed() == "- 가\n  - 나", repr(ed())
            pg.keyboard.press("Shift+Tab"); assert ed() == "- 가\n- 나", repr(ed())
            pg.fill("#editor", orig)

            # 쪽 목록
            pg.click("#pageList"); txt = pg.inner_text("#pgListBody")
            assert "책 2P (캡처 4)" in txt and "챕터 시작: 1장 시작" in txt and "뺀 쪽" in txt and "📑 목차" in txt, txt
            pg.click("#pgListClose")
            saved()
            br.close()

        cfg = json.loads((out / "책_장설정.json").read_text(encoding="utf-8"))
        assert [c["capture"] for c in cfg["chapters"]] == [3, 6] and cfg["skip_pages"] == [7]
        assert cfg["page_fixes"] == [{"capture": 9, "page": 8}], cfg
        assert cfg["chapters"][1]["split"] == "topic" and cfg["chapters"][1]["part"] == "Part 1. 기초"
        assert [(i["level"], i["text"]) for i in cfg["toc"][0]["items"]] == [
            (0, "Part 1. 기초"), (1, "1장 시작"), (2, "1.1 개요"), (1, "2장 도구"), (2, "2.1 설치")], cfg["toc"]

        # 편집기로 만든 결과를 내보내기 (4~8)
        r = subprocess.run([sys.executable, str(ROOT / "ebook_export.py"), str(book)], capture_output=True, text=True,
                           encoding="utf-8", cwd=ROOT)
        assert r.returncode == 0, r.stdout + r.stderr
        d = out / "책_AI용_나눔"
        fs = {p.name: p.read_text(encoding="utf-8") for p in d.glob("*.md")}
        assert sorted(fs) == ["책.앞부분.md", "책.챕터01.md", "책.챕터02.md", "책.챕터02.대주제01.md"], sorted(fs)
        c1 = [x for x in fs["책.챕터01.md"].split("\n") if x.strip()]
        assert c1[:9] == ["---", "책: 책", "파트: Part 1. 기초", "챕터: 1장 시작", "쪽: p.1–p.3", "---", "[p.1]", "[p.2]", "# 1.1 개요"], c1
        assert "**목차**" in fs["책.앞부분.md"] and "    - 1.1 개요" in fs["책.앞부분.md"], fs["책.앞부분.md"]
        assert "대주제: 2.1 설치" in fs["책.챕터02.대주제01.md"]
        print("편집기 시험 통과")
    finally:
        srv.terminate()


if __name__ == "__main__":
    main()
