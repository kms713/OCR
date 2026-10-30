# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 설정 — build_windows.bat 이 사용합니다. (직접 실행: pyinstaller --noconfirm ExamOCR.spec)
#
# 결과: dist\ExamOCR\ExamOCR.exe  (폴더째 배포, 모델 포함)

import importlib.metadata as md
import os

from PyInstaller.utils.hooks import collect_all, copy_metadata

MODELS = ["PP-OCRv5_server_det", "korean_PP-OCRv5_mobile_rec"]
missing = [m for m in MODELS if not os.path.isdir(os.path.join("models", m))]
if missing:
    raise SystemExit(f"models 폴더에 모델이 없습니다: {missing}  (build_windows.bat 이 자동으로 준비합니다)")

datas = [(os.path.join("models", m), os.path.join("models", m)) for m in MODELS]
binaries, hiddenimports = [], ["ocr_paddle"]

# 딥러닝 엔진·문서 라이브러리는 동적으로 불러오는 모듈과 설정 파일이 많아 통째로 넣는다
for pkg in ["paddle", "paddlex", "paddleocr", "hwpx", "pypdfium2", "pypdfium2_raw"]:
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# PaddleX는 실행 중에 '설치된 패키지 목록(메타데이터)'으로 의존성을 확인한다 → 전부 포함
seen = set()
for dist in md.distributions():
    name = dist.metadata["Name"]
    if not name or name.lower() in seen:
        continue
    seen.add(name.lower())
    try:
        datas += copy_metadata(name)
    except Exception:
        pass

a = Analysis(
    ["ocr_gui.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["matplotlib", "IPython", "jupyter", "notebook", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ExamOCR",
    console=False,  # 검은 콘솔 창 없이 실행
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="ExamOCR", upx=False)
