# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 설정 — 저사양판(ONNX 엔진). build_lite.bat 이 사용합니다.
#
# 결과: dist\ExamOCR_Lite\ExamOCR.exe  (PaddlePaddle 없이 ONNX Runtime으로 계산, AVX 없는 CPU에서도 동작)

import importlib.metadata as md
import os

from PyInstaller.utils.hooks import collect_all, copy_metadata

MODELS = ["PP-OCRv5_server_det", "korean_PP-OCRv5_mobile_rec"]
missing = [m for m in MODELS if not os.path.isfile(os.path.join("models_onnx", m, "inference.onnx"))]
if missing:
    raise SystemExit(f"models_onnx 폴더에 ONNX 모델이 없습니다: {missing}  (build_lite.bat 이 자동으로 준비합니다)")

# 저사양판은 models 폴더 없이 models_onnx 만 넣는다 → 프로그램이 이를 보고 ONNX 엔진을 고른다
datas = [(os.path.join("models_onnx", m), os.path.join("models_onnx", m)) for m in MODELS]
binaries, hiddenimports = [], ["ocr_paddle"]

for pkg in ["paddlex", "paddleocr", "hwpx", "pypdfium2", "pypdfium2_raw", "onnxruntime"]:
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
    # PaddlePaddle은 넣지 않는다 (들어가면 AVX 없는 CPU에서 죽는다)
    excludes=["paddle", "paddlepaddle", "matplotlib", "IPython", "jupyter", "notebook", "pytest", "torch"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ExamOCR",
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="ExamOCR_Lite", upx=False)
