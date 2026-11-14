#!/usr/bin/env python3
"""교정 편집기 화면 시험. 견본 책을 임시 폴더에 만들고 편집기를 띄운 뒤 node + Playwright(test_editor.js)로
챕터 시작(글 없는 쪽)·쪽 이름·고른 글을 제목으로 떼기·이 쪽 빼기를 눌러 본다. 필요: node, playwright(npm)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_chapters as tc  # noqa: E402


def main() -> int:
    with tempfile.TemporaryDirectory() as t:
        root = Path(t)
        folder = tc.make_book(root, False)
        port = 8791
        srv = subprocess.Popen([sys.executable, str(HERE.parent / "ebook_review.py"), str(folder), "--port", str(port), "--no-browser"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        try:
            time.sleep(1.5)
            env = dict(os.environ, NODE_PATH=os.environ.get("NODE_PATH") or "/opt/node-tools/node_modules")
            rc = subprocess.run(["node", str(HERE / "test_editor.js"), f"http://127.0.0.1:{port}/"], env=env).returncode
        finally:
            srv.terminate()
        if rc:
            return 1
        cfg = json.loads((root / "책_OCR" / "책_장설정.json").read_text(encoding="utf-8"))
        ok = len(cfg["chapters"]) == 2 and cfg["skip_pages"] == [7] and cfg["page_fixes"] == [{"capture": 9, "page": 8}]
        md = (root / "책_OCR" / "책_교정.md").read_text(encoding="utf-8")
        ok2 = "<!-- p.9 -->" in md and "<!-- p.8 -->" in md and "## 대주제B" in md and "…끝난다.\n\n## 대주제B\n\n첫 문장…" in md
        print(("  통과 " if ok else "  실패 ") + "설정 파일 저장", "" if ok else cfg)
        print(("  통과 " if ok2 else "  실패 ") + "교정 글에 쪽 번호 그대로, 제목 떼기 저장")
        return 0 if ok and ok2 else 1


if __name__ == "__main__":
    sys.exit(main())
