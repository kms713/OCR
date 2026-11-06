# 시험지 OCR · 전자책 OCR

스캔한 시험지(PDF·사진)를 한글 파일(`원본이름_OCR.hwpx`)로, 전자책 화면을 Markdown으로 바꾸는 프로그램입니다.
구조·알고리즘·검증 방법은 `SPEC.md`, 진행 상황과 시험 결과는 `작업현황.md`, 고칠 때 지킬 규칙은 `OCR/ExamOCR_build/CLAUDE.md`에 있습니다.

## 판별 파일

글자 인식 엔진은 `OCR/ExamOCR_build/ocr_paddle.py` 하나를 모든 판이 함께 씁니다.

### 시험지 OCR (`OCR/ExamOCR_build/`)

| 판 | 쓰는 곳 | 만드는·실행하는 파일 | 필요한 파일 |
|---|---|---|---|
| 일반판 | 선생님 PC (AVX 있는 CPU) | `build_windows.bat` → `installer\ExamOCR_Setup.exe` | `ocr_gui.py`, `ocr_paddle.py`, `ExamOCR.spec`, `ExamOCR.iss`, `requirements.txt`, `사용법.txt` |
| 저사양판 | 구형 PC (AVX 없는 CPU) | `build_lite.bat` → `installer_lite\ExamOCR_Lite_Setup.exe` | 위 공통 파일 + `ExamOCR_Lite.spec`, `ExamOCR_Lite.iss`, `requirements_lite.txt`, `onnx_test.py`(ONNX 모델 받기) |
| 그래픽카드판 | NVIDIA 그래픽카드 PC (집 PC 대량 변환) | `설치_GPU.bat`(처음 한 번) → `GPU_실행.bat` | `ocr_gui.py`, `ocr_paddle.py` (`models` 폴더가 없으면 처음 실행 때 모델을 내려받음) |

- 일반판·저사양판은 설치 파일로 나눠 주고, 그래픽카드판은 설치 파일 없이 폴더에서 바로 실행합니다.
- 빌드하면 생기는 `.venv*`, `models*`, `build*`, `dist`, `installer*` 폴더는 저장소에 넣지 않습니다.

### 전자책 OCR (`EbookOCR/`)

| 판 | 실행 순서 | 결과 |
|---|---|---|
| 기본(CPU) | `설치.bat` → `1_캡처점검.bat` → `2_캡처.bat` → `3_OCR.bat` | `books\책이름_OCR\` |
| 그래픽카드 | `설치_GPU.bat`(처음 한 번) → 캡처 후 `3_OCR_GPU.bat` | `books\책이름_OCR_GPU\` |

- 저장소 그대로의 폴더 구조로 두면 `OCR/ExamOCR_build/ocr_paddle.py`를 자동으로 찾아 씁니다.
- 결과 폴더의 `처리시간.txt`에 쪽당 인식 시간이 남습니다.
- 교정·내보내기: `4_교정.bat`(원본 이미지와 글을 나란히 보며 고치기, 그림 넣기) → `5_내보내기.bat`(사람용 `책이름_완성본.docx` + AI용 `책이름_AI용.md`).

## 저장소에 올리지 않는 것

- 시험지 PDF·이미지와 그 변환 결과 (저장소가 공개라서). `gpu_test/`, `books/` 폴더는 자동으로 빠집니다.
