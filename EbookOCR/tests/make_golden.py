"""옛 방식(설정 파일 없음) 골든 파일 다시 만들기. 내보내기 동작을 일부러 바꿨을 때만 실행하고, 바뀐 내용을 눈으로 확인한 뒤 올린다.
실행: python tests/make_golden.py"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, SAMPLE, make_book  # noqa: E402

gold = SAMPLE / "golden_legacy"
shutil.rmtree(gold, ignore_errors=True)
for lvl in (1, 2):
    book, out = make_book(with_config=False, edited=False)
    subprocess.run([sys.executable, str(ROOT / "ebook_export.py"), str(book), "--no-page-marks", "--split-level", str(lvl), "--only", "ai"],
                   check=True, cwd=ROOT, capture_output=True)
    shutil.copytree(out / "책_AI용_나눔", gold / f"split{lvl}")
shutil.copy(out / "책_AI용.md", gold / "AI용.md")
print("골든 파일을 다시 만들었습니다:", gold)
