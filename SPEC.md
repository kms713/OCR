# 시험지 OCR · 전자책 OCR — 서비스 기술 명세

이 문서는 다른 개발자(사람·AI)가 이 저장소를 이어서 개발할 때 읽는 기준 문서입니다.
코드와 이 문서가 다르면 **코드가 맞습니다**. 고친 사람은 이 문서도 함께 고칩니다.

| 문서 | 내용 |
|---|---|
| `SPEC.md` (이 문서) | 무엇을, 어떻게 만들었는가. 구조·알고리즘·인터페이스·검증 방법 |
| `OCR/ExamOCR_build/CLAUDE.md` | 고칠 때 지킬 규칙 (원칙, 파일 형식, 보고 방식) |
| `작업현황.md` | 시험 결과 기록, 결정 이력, 남긴 과제 |
| `README.md` | 판별 필요한 파일 목록 |

---

## 1. 서비스 개요

### 1.1 시험지 OCR (주 제품)
- **사용자**: 학원 선생님. 코드를 다루지 않으며, 설치 파일을 실행하고 버튼만 누릅니다.
- **입력**: 스캔한 시험지 PDF 또는 사진(`.pdf .png .jpg .jpeg .bmp .tif .tiff .webp`). 한글 경로 지원.
- **출력**: 원본과 같은 폴더에 `원본이름_OCR.hwpx` (한글 문서). 같은 이름이 있으면 `원본이름_OCR(2).hwpx` …
- **주요 기능**
  - 두 단 편집 시험지를 왼쪽 단 → 오른쪽 단 순서로 읽기
  - 뒷면 비침·연한 연필 자국 걸러내기
  - 신뢰도가 낮은 글자 뒤에 `[?]` 표시 (선택)
  - 테두리가 있는 표·박스(`<보기>`, 지문, 조건 등)를 HWPX에서 **칸 하나짜리 표**로 감싸기
  - 원본 쪽마다 새 쪽에서 시작
- **범위 밖 (의도적으로 하지 않음)**: 표의 칸 구조 복원, 손글씨·원문자(①~⑤, ⓐ~ⓚ) 인식 보정, 수식 인식, 모델 재학습.

### 1.2 전자책 OCR (부가 도구)
- LD플레이어(안드로이드 에뮬레이터)로 연 전자책을 ADB로 한 쪽씩 넘기며 캡처 → 글자만 뽑아 Markdown 한 파일로.
- 용도: 개인 학습용. 결과 `책이름.md`를 NotebookLM·Claude 등 AI 지식 도구에 넣어 요약.
- 교정·그림 삽입(2026-11 추가): 원본 쪽 이미지와 OCR 글을 브라우저에서 나란히 보며 고치고, 결과물 2종을 만든다 (§11.1).

---

## 2. 요구사항과 원칙 (반드시 지킬 것)

| # | 원칙 | 확인 방법 |
|---|---|---|
| P1 | 레이아웃 보정·새 기능은 **기존 샘플 결과를 한 글자라도 바꾸면 채택하지 않는다** | 고치기 전후 결과를 글자 단위로 대조 (§12) |
| P2 | 정확도가 떨어지는 속도 개선은 하지 않는다 | 같은 시험지로 글자 대조 |
| P3 | 글자는 항상 **원본 이미지**에서 읽는다. 전처리 이미지는 판정에만 쓴다 | 코드 리뷰 |
| P4 | 표 기능은 HWPX에서 감싸기만 한다. txt 결과와 읽는 순서는 표 기능과 무관하게 같다 | `--no-table` 결과와 대조 |
| P5 | 원문자·손글씨·낙서는 제어하지 않는다. 나오는 대로 두고 사용법에 안내한다 | — |
| P6 | 시험지 PDF·이미지와 그 변환 결과는 저장소에 올리지 않는다 (학교 저작물, 저장소 공개) | `.gitignore`의 `gpu_test/`, `books/` |

**검증 기준 (새 기능·새 판을 받아들이는 조건)**
- 저사양판·그래픽카드판: 일반판 결과와 글자 일치율 99% 이상, 빠진 줄 0.
- 처음 보는 시험지 검증(미실시): 빠진 줄 0, 읽는 순서가 맞는 쪽 95% 이상.

---

## 3. 저장소 구조

```
README.md                  판별 필요한 파일
SPEC.md                    이 문서
작업현황.md                 시험 결과·결정 이력·남은 과제
.gitignore                 빌드 산출물, 모델, 로그, gpu_test/ 제외
OCR/ExamOCR_build/         ← 시험지 OCR. 모든 판의 코드가 여기 하나
  ocr_paddle.py            엔진·처리 파이프라인·저장 (명령줄 겸용). 전자책 OCR도 이 파일을 import
  ocr_gui.py               tkinter 화면, 자가 점검(--check), CPU 사양 판정
  ExamOCR.spec / .iss      일반판 PyInstaller 설정 / Inno Setup 설치 스크립트
  ExamOCR_Lite.spec / .iss 저사양판(ONNX) 설정
  build_windows.bat        일반판 빌드 (venv → 설치 → 모델 → exe → 점검 → 설치 파일)
  build_lite.bat           저사양판 빌드
  onnx_test.py             공식 ONNX 모델 받기(fetch_onnx). build_lite.bat이 사용
  설치_GPU.bat / GPU_실행.bat  그래픽카드판 (설치 파일 없이 폴더에서 실행)
  requirements*.txt        버전 고정 목록
  사용법.txt               선생님용 안내 (UTF-8 BOM + CRLF)
  CLAUDE.md                작업 규칙
EbookOCR/                  ← 전자책 OCR
  ebook_capture.py         ADB 캡처
  ebook_ocr.py             이미지 폴더 → Markdown
  ebook_review.py/.html    교정 편집기 (브라우저, 표준 라이브러리 서버)
  ebook_export.py          교정 글 → 완성본 docx + AI용 md
  ebook_suggest.py         Gemini 맞춤법·OCR 교정 제안 (선택, 원문 불변)
  bookdir.py               책 폴더 위치: 책폴더.txt(PC별, git 제외)가 있으면 'books\\X' → 그 경로\\X. 결과 폴더 X_OCR (3_OCR_GPU.bat도 2026-11-10부터 같은 곳). 예전 판이 만든 X_OCR_GPU만 있으면(또는 그쪽에만 교정 중 파일) 그쪽
  설치_교정용.bat          OCR 없는 가벼운 설치(pillow, python-docx: requirements_edit.txt)
  책폴더_설정.bat          bookdir.py 실행 (경로 입력·확인)
  표 넣기(편집기): 캐시 `boxes`(줄로 묶기 전 글상자, 2026-11-10부터 저장. 없으면 rows 사용)를 고른 영역에서 가로로 겹치면(간격 0.3h) 같은 열, 세로로 겹치거나 행 나누기 기준(0.15/0.5/1.0h) 안이면 같은 행으로 묶어 마크다운 표 초안. 칸 안 여러 줄은 기본 빈칸으로, '칸 안 줄바꿈 살리기'면 `<br>`(Word는 칸 안 줄바꿈, AI용은 `<br>` 그대로). 본문 문단 중 글자 80% 이상이 표 칸 글이면 지우고 그 자리에 표. 내보내기: `| … |` 줄 묶음 → Word 표(Table Grid, 머리 행 굵게)·AI용 md 표. ebook_suggest 는 표 줄을 보내지 않음
  교정 도우미(편집기, 2026-11-10): 쪽 확인 완료(`책이름_확인.json` {pages}, GET/POST /api/checked)·진행률·다음 미확인 쪽, 커서 → 원본 줄 강조(커서 앞뒤 글자 조각을 줄 글에서 찾음),
    빠진 줄 의심(줄 글의 5글자 조각 60% 이상이 처음 교정용 글(GET /api/source)에는 있는데 지금 글 전체에는 없음), 미리보기(마크다운 → HTML, 그림은 /figures/),
    바꾸기 미리보기(쪽 표시 줄 안 제외, 고른 곳만), 각주 표시 기호 색칠, 점검표(GET /api/rowtexts 로 전체 쪽 OCR 줄).
  머리말·꼬리말(ebook_ocr.strip_headers, 2026-11-10): 가장자리 줄 = 이미지 위·아래 band 안 또는 글 영역 맨 위·아래 두 줄(쪽당 4줄 이상일 때).
    숫자뿐인 줄·반복 줄(숫자 무시 비교, 20%·3쪽 이상)은 빼고, FOOTER 모양(쪽 번호+짧은 글)은 제목 크기(본문 1.3배 초과)가 아니고 본문과 1.2줄 이상 떨어졌을 때만 뺌(장마다 바뀌는 꼬리말도 반복 없이 빠짐).
    편집기 '머리말·꼬리말 정리': 캐시 OCR 줄의 쪽별 맨 위·아래 두 줄 중 20% 이상 반복되는 것, 또는 맨 위·아래 한 줄로 3쪽 이상 나오고 쪽 번호가 붙은 것(장별 꼬리말) → 숫자는 \d{1,4}, 글자 사이 빈칸 허용 정규식으로 지금 글에서 찾아 골라 지움, 숫자뿐인 줄 별도.
  편집기 키: PageUp/PageDown 쪽 넘기기, Shift+Enter `<br>`(내보내기 Word 문단·표 칸 안 줄바꿈).
  fix_page_split.py / 쪽나누기_고치기.bat  예전 판 교정 글에서 앞 쪽에 붙은 다음 쪽 글을 제 쪽으로 (캐시로 build_paragraphs(merge=False) 다시 계산, 띄어쓰기·서식 무시하고 첫머리 14→9→5자 맞춤, 고치기 전 .쪽나누기전 백업)
  make_sample.py / 샘플책_만들기.bat  교정기 시험용 3쪽 샘플(쪽 이미지·cache 줄 상자·교정용.md 일부러 넣은 잘못·제안 3건)
  설치.bat, 1_캡처점검.bat, 2_캡처.bat, 3_OCR.bat, 4_교정.bat, 5_내보내기.bat, 설치_GPU.bat, 3_OCR_GPU.bat
```

빌드 때 생기는 `.venv*`, `models/`, `models_onnx/`, `build*/`, `dist/`, `installer*/`는 저장소에 넣지 않습니다.

---

## 4. 판(edition) 구성과 엔진 선택

| 판 | 대상 | 계산 엔진 | 모델 폴더 | 배포 |
|---|---|---|---|---|
| 일반판 | AVX 지원 CPU | PaddlePaddle 3.2.2 (CPU, oneDNN) | `models/` | `installer\ExamOCR_Setup.exe` |
| 저사양판 | AVX 없는 CPU | ONNX Runtime 1.29 (PaddlePaddle 미포함) | `models_onnx/` | `installer_lite\ExamOCR_Lite_Setup.exe` |
| 그래픽카드판 | NVIDIA GPU PC | paddlepaddle-gpu 3.2.2 (CUDA 12.6) | `models/` 또는 자동 다운로드 | `GPU_실행.bat` (`.venv_gpu`) |
| 전자책 OCR | 개인 PC | 위 엔진 공유, `--device gpu` 가능 | 자동 다운로드 캐시 | 배치 파일 |

**모델**: 검출 `PP-OCRv5_server_det`, 인식 `korean_PP-OCRv5_mobile_rec` (PaddleOCR 공식, 재학습 없음).
`--fast`를 주면 검출이 `PP-OCRv5_mobile_det` (비권장).

**엔진 결정 순서**
1. `ocr_gui.engine_name()`: 실행 폴더(또는 `_MEIPASS`)에 `models_onnx/`만 있고 `models/`가 없으면 `"onnx"`, 아니면 `"paddle"`.
2. `ocr_paddle.build_ocr(args)`:
   - `engine == "onnx"` → `engine="onnxruntime"`, `device="cpu"` 고정. 모델이 없으면 `RuntimeError`.
   - 그 외 → `args.device`가 `auto`면 환경변수 `EXAMOCR_DEVICE`(그래픽카드판 bat이 `gpu`로 지정)를 따름.
3. 모델 위치 `find_bundled_models()`: 환경변수 `OCR_MODEL_DIR` → exe 옆 → `_MEIPASS` → 스크립트 옆. 없으면 PaddleX가 인터넷에서 받아 `~/.paddlex/official_models`에 캐시.
4. 경로에 한글이 있으면 `_ascii_safe()`가 `C:\Users\Public\ExamOCR\models`에 한 번 복사해서 씀 (Paddle의 비ASCII 경로 문제 회피).

**CPU 사양 판정** (일반판만 해당)
- 설치 단계(`ExamOCR.iss` `InitializeSetup`): AVX 없으면 설치를 막고 안내 창.
- 실행 단계(`ocr_gui.low_spec_problem`): AVX 없음 → 안내 후 종료. AVX는 있고 AVX2 없음 → 별도 프로세스로 엔진을 한 번 불러 보고(`--engine-probe`) 결과를 `cpu_check.txt`에 기억.
- 판정 불가(오래된 Windows 등)면 막지 않음.

---

## 5. 처리 파이프라인 (`ocr_paddle.py`)

해상도 기준 `REF_WIDTH = 3035`(A4 300dpi 폭). 형태 연산의 크기는 모두 `s = 쪽 폭 / REF_WIDTH`에 비례합니다.

| 단계 | 함수 | 내용과 주요 값 |
|---|---|---|
| 1 입력 | `render_pdf(path, dpi=300)`, `load_image` | pypdfium2로 렌더, BGR 배열. 이미지는 바이트로 읽어 한글 경로 대응 |
| 2 판정용 그림 | `flatten(img)` | 회색조 ÷ (dilate → medianBlur 배경) × 255. 글자 어둡게, 종이 255 근처 |
| 3 단 나누기 | `plan_regions(norm, layout)` | `layout=single`이면 쪽 통째로 |
| 3a 글줄 덩어리 | `text_line_blobs` | 밝기 < 140, 가로로 닫기, 높이 20s~120s |
| 3b 단 경계 | `find_gutter` | 폭 35~65% 구간에서 가로지르는 상자가 가장 적은 x. 양쪽에 각 20% 이상, 가로지름 5% 이하일 때만 두 단 |
| 3c 세로 구분선 | `find_vertical_rule` | 밝기 < 200, 세로 열기 60s. 쪽 높이 40% 이상 이어져야 인정. 선이 있는 높이만 두 단, 위(제목)·아래(꼬리말)는 통째 |
| 3d 경계 다듬기 | `_shrink_by_side_rows` | 구분선 밖이라도 좌우 글줄이 나란하면 단으로 읽게 확장 |
| 4 구간 자르기 | `prepare_crop` | 진한 잉크(<160) 50px 미만이면 건너뜀. 가로세로비 8 초과면 흰 여백 덧댐(`MAX_ASPECT=8`) |
| 5 인식 | `ocr.predict(crop)` → `to_items` | 글상자 좌표를 쪽 좌표로 되돌림. `--min-score` 미만 버림(기본 0) |
| 6 비침 걸러내기 | `ink_ratio(norm, box, level=180)` | 상자 안 잉크 중 180보다 진한 잉크 비율 < 0.25이면 `dropped` |
| 7 표·박스 찾기 | `find_boxes(norm)` | §5.1 |
| 8 줄 묶기 | `group_rows` | cy 기준 정렬, 같은 줄 조건 `|cy − 줄 평균 cy| ≤ 0.5 × min(줄 평균 높이, 상자 높이)`. 줄 안은 x 순 |
| 9 줄 글자 | `row_text(row, mark_low)` | 상자 사이 간격 > 1.5 × 글자 높이면 탭, 아니면 공백. 신뢰도 < mark_low면 `[?]` |
| 10 줄의 표 번호 | `box_of` | 줄의 모든 상자가 같은 박스 안일 때만 그 표의 줄 |
| 11 저장 | `write_hwpx` / `write_txt` / `write_json` | §7 |

구간(region) 사이에는 빈 줄 하나가 들어갑니다. 쪽 결과는 `PageResult`(§6)입니다.

### 5.1 표·박스 찾기 `find_boxes`
1. 선 후보: `norm < 180` (뒷면 비침 판정 기준과 같은 값. 160이면 얇은 회색 테두리를 놓쳐 2026-11-05에 바꿈)
2. 가로선: 가로 열기 `max(15, 80s)` → 닫기 `(15s, 5s)`. 세로선: 세로 열기 `max(15, 60s)` → 닫기 `(5s, 15s)`
3. 세로선 조각 중 길이 ≥ 70s만 사용 (`_segments`)
4. 세로선 두 개마다 후보 사각형: 폭 ≥ 150s, 두 선의 길이 겹침 ≥ 80%, 높이 ≤ 쪽 높이 60% (쪽·단 테두리 제외)
5. 위·아래 가로선 덮임 비율(`coverage`, 기울기 반영, 허용 두께 ±15s): 한쪽 ≥ 95%, 다른 쪽 ≥ 40% → 위가 뚫린 `<보기>` 박스도 잡힘
6. 큰 것부터 채택, 이미 채택한 것과 겹치면 버림 (칸 나뉜 표 = 바깥 사각형 하나)

`box_of`: 상자 가로 중심이 박스 안이고 세로 중심이 박스 안. 단, 위 테두리에 걸친 글(`<보기>` 제목)은 상자 아래가 테두리보다 아래이고 중심이 테두리 위 반 글자 높이 이내일 때만 포함.

---

## 6. 자료 구조

```python
@dataclass
class Item:            # 글상자 하나
    text: str
    score: float       # 인식 신뢰도 0~1
    box: list[int]     # [x1, y1, x2, y2] 쪽 전체 좌표
    region: int = 0    # 읽은 구간 번호 (읽는 순서)
    ink: float | None  # 진한 잉크 비율
    dropped: bool      # 비침으로 판정해 뺐는지

@dataclass
class PageResult:
    page: int                       # 1부터
    items: list[Item]               # 걸러낸 것 포함 전체
    lines: list[str]                # 출력 줄
    line_boxes: list[int | None]    # lines와 같은 길이. 그 줄이 든 표 번호, 표 밖이면 None
```

**전자책 쪽에서 쓰는 공개 함수** (모양을 바꾸면 `EbookOCR/ebook_ocr.py`도 고칠 것):
`to_items`, `group_rows`, `build_ocr`, `default_options`, `load_image`, `Item`.

---

## 7. 출력 형식

### 7.1 HWPX (`write_hwpx`, python-hwpx 6.8.0)
- 새 문서의 기본 빈 문단을 첫 줄로 씀. 여러 쪽이면 각 쪽 첫 문단에 `pageBreak="1"`, 제목 줄 `===== N 페이지 =====`.
- `table_runs`로 같은 표 번호가 이어지는 줄(구간 사이 빈 줄 하나는 건너뜀)을 묶어 `doc.add_table(1, 1)` + `set_cell_text(…, split_paragraphs=True)`.
- 줄 안의 탭은 HWPX에서 `<hp:tab/>` 요소가 됨.
- 알려진 모양: 한 쪽짜리 문서가 표로 시작하면 맨 위에 빈 문단 하나가 생김.

### 7.2 txt / json (명령줄 전용)
- txt: 쪽 제목 + 줄, 쪽 사이 빈 줄. 글자는 HWPX와 같음.
- json(`--json`): 쪽별 평균 신뢰도, 줄, 글상자(글자·신뢰도·좌표·구간·잉크·제외 여부).

### 7.3 HWPX에서 글자 뽑기 (검증용)
`Contents/section*.xml`의 `<hp:p>`마다 `<hp:t>` 글자 + 자식 `<hp:tab/>`은 탭 + 각 자식의 `tail`을 이어 붙입니다. 표를 품은 문단은 건너뛰고 표 안 문단을 읽습니다.

---

## 8. 명령줄 (`python ocr_paddle.py 입력… [옵션]`)

| 옵션 | 기본 | 뜻 |
|---|---|---|
| `-o, --output` | `ocr_output` | 결과 폴더 (명령줄은 `원본이름.hwpx`로 저장, 화면과 다름) |
| `-r, --recursive` | 끔 | 폴더 하위까지 |
| `--format` | `hwpx,txt` | 저장 형식 |
| `--json`, `--vis` | 끔 | 상세 JSON, 구간별 인식 영역 그림 |
| `--device` | `auto` | `cpu`, `gpu`, `gpu:0` … (`auto`면 `EXAMOCR_DEVICE`) |
| `--engine` | `paddle` | `onnx`면 `models_onnx` 필요 |
| `--fast` | 끔 | 가벼운 검출 모델 |
| `--no-mkldnn` | 끔 | oneDNN 끄기 (PaddlePaddle 3.3.x 오류 회피용) |
| `--rotate`, `--unwarp` | 끔 | 방향 보정, 휜 문서 펴기 |
| `--pdf-dpi` | 300 | PDF 렌더 해상도 |
| `--layout` | `auto` | `single`이면 두 단 분리 끔 |
| `--no-filter`, `--filter-level 180`, `--filter-ratio 0.25` | | 비침 걸러내기 |
| `--no-table` | 표 켬 | 표 감싸기 끄기 |
| `--show-dropped` | 끔 | 걸러낸 글상자를 쪽 끝에 적기 |
| `--min-score` | 0 | 이 신뢰도 미만 버림 |
| `--mark-low` | 0 | 이 신뢰도 미만 `[?]` (화면은 0.6) |

---

## 9. 화면 프로그램 (`ocr_gui.py`)

- 창 제목: `시험지 OCR 변환`, 저사양판이면 `(저사양용)`, `EXAMOCR_DEVICE=gpu`면 `(그래픽카드)`.
- 버튼: 파일 추가 / 선택 비우기 / 목록 비우기 / 변환 시작(변환 중에는 **중지**). 체크박스 "확인이 필요한 글자에 [?] 표시"(기준 `MARK_LOW = 0.6`).
- 변환은 `Worker` 스레드 하나가 모델 불러오기와 변환을 차례로 처리. 완료 파일은 목록에서 사라지고 실패는 "실패"로 남음.
- 저장: `next_free_path(원본 폴더, "원본이름_OCR", ".hwpx")`. 화면에서는 HWPX만 저장.
- **로그 폴더**: 프로그램 폴더에 쓸 수 있으면 거기, 아니면 `%LOCALAPPDATA%\ExamOCR`.
  - `ocr_log.txt`(회전, 쪽별 시간), `ocr_crash.txt`(faulthandler), `ocr_console.txt`(창 모드 표준 출력)
  - `ocr_running.flag`: 변환 중에만 존재. 다음 실행 때 남아 있으면 비정상 종료로 보고 `ocr_safe_mode.txt`를 만들어 **자동으로 안전 모드**로 전환 (일반판만)
  - `ocr_safe_mode.txt`: 있으면 oneDNN을 끈 안전 모드(느림). 관리자가 지우면 빠른 모드로 복귀
  - `cpu_check.txt`: AVX만 있는 CPU의 엔진 시험 결과
- **자가 점검** `ExamOCR.exe --check`: CPU, 라이브러리, 한글 경로 PDF, HWPX 저장, 모델 찾기·불러오기, 글자 인식("Hello OCR 2025"), 결과 저장 → `ocr_check.txt`, 첫 줄 `RESULT: PASS`. 빌드 bat이 이 결과로 성공 여부를 판단.

---

## 10. 빌드와 배포 (Windows, 파이썬 3.12 64비트)

**고정 버전과 이유**
- `paddlepaddle==3.2.2`: 3.3.x는 CPU에서 `ConvertPirAttribute2RuntimeAttribute not support` 오류.
- `paddleocr==3.7.0`, `paddlex==3.7.2`, `onnxruntime==1.29.0`, `python-hwpx==6.8.0`, `pyinstaller==6.22.3`.

**`build_windows.bat` (일반판)**: `.venv` 생성 → 설치 → 모델을 받아 `models/`로 복사 → PyInstaller(`ExamOCR.spec`) → `dist\ExamOCR\ExamOCR.exe --check` 통과 확인 → Inno Setup(`ExamOCR.iss`) → `installer\ExamOCR_Setup.exe`.

**`build_lite.bat` (저사양판)**: `.venv_lite`(PaddlePaddle이 설치돼 있으면 실패 처리) → `onnx_test.fetch_onnx()`로 공식 ONNX 모델을 `models_onnx/`에 → PyInstaller(`ExamOCR_Lite.spec`, `paddle` 제외) → 점검(ONNX 엔진으로 돌았는지까지 확인) → `installer_lite\ExamOCR_Lite_Setup.exe`.
- ONNX 모델은 paddle2onnx로 직접 변환하지 않음 (Windows판이 3.2.2와 DLL 충돌).

**설치 파일**
- 일반판 `AppId {0AB9C8CC-…}`, 설치 위치 `C:\Program Files\ExamOCR`. 저사양판 `AppId {41EDF31A-…}`, `ExamOCR_Lite`. **AppId는 바꾸지 말 것** (덮어 설치 유지). 두 판은 함께 설치 가능.
- 설치 파일에 파이썬·라이브러리·모델이 모두 들어 있어 대상 PC는 인터넷·파이썬 불필요.
- 버전 `1.0.0` (각 `.iss`의 `#define AppVersion`). 설치 파일 이름에 날짜가 없어 공유 폴더에서 혼동한 적 있음(§13).

**그래픽카드판**: `설치_GPU.bat`이 `nvidia-smi` 확인 → `.venv_gpu` → `paddleocr python-hwpx` → `paddlepaddle-gpu==3.2.2 -i https://www.paddlepaddle.org.cn/packages/stable/cu126/` → `paddle.utils.run_check()`. `GPU_실행.bat`은 `EXAMOCR_DEVICE=gpu`로 `ocr_gui.py`를 `pythonw`로 실행.

---

## 11. 전자책 OCR (`EbookOCR/`)

**캡처 `ebook_capture.py`**
- 화면 가져오기 `--source auto|adb|window`. auto는 ADB 스크린샷이 검은 화면(뷰어의 캡처 차단)이면 Windows 창 캡처로 전환. 넘기기는 항상 ADB(`--turn tap|key|swipe`).
- 넘긴 뒤 화면이 바뀌고 멈출 때까지 기다려 저장(`--interval`, `--settle`, `--timeout`). 화면이 그대로면 `--end-retries`번 더 넘겨 보고 끝으로 판단.
- 출력 `page_0001.png …`. 같은 폴더로 다시 실행하면 이어서 번호.

**변환 `ebook_ocr.py 폴더 [-o 결과]`**
- 엔진: `ocr_paddle.py`를 저장소 경로(`../OCR/ExamOCR_build`)에서 먼저 찾고, 없을 때만 자기 폴더의 복사본을 씀.
- 처리: 그림 영역 제외(`picture_regions`, `--picture-fill 0.12`) → 줄 묶기(`ocr_paddle.group_rows`) → 머리말·꼬리말·쪽 번호 제거(`strip_headers`, 위·아래 10%) → 문단 복원(`build_paragraphs`: 줄바꿈 잇기, 들여쓰기·줄 간격·문장 끝, 쪽 넘김 문장 잇기) → 큰 글자 줄은 `##` 제목, 작은 글자 줄은 `> 주:` 각주 → Kiwi 띄어쓰기 보충(`fix_spacing`, 있던 띄어쓰기는 지우지 않음).
- 쪽별 결과 캐시 `결과/cache/*.json` (이어 하기). `--redo`로 무시.
- 출력: `책이름.md`, `책이름.txt`(쪽별 원문), `책이름_교정용.md`(같은 문단에 `<!-- p.N -->` 쪽 표시), `처리시간.txt`(장치, 쪽 수, 쪽당 인식 시간).
- 주의: kiwipiepy가 없으면 띄어쓰기 교정을 조용히 건너뜀(알림만 출력). 설치가 오래된 PC에서 띄어쓰기가 붙어 나온 사례 있음 → `설치.bat` 재실행.

### 11.1 교정·내보내기 (2026-11 추가)
**흐름**: `3_OCR.bat` → `4_교정.bat`(`ebook_review.py`) → `5_내보내기.bat`(`ebook_export.py`).

**교정 편집기** (`ebook_review.py` + `ebook_review.html`)
- `EDITOR_VERSION`을 `.py`·`.html` 둘 다에 두고 열 때 비교: 다르면(업데이트 뒤 서버를 다시 켜지 않음) 경고. **서버 API를 바꾸면 두 곳의 값을 함께 올릴 것.**
- `http.server`, `127.0.0.1`만, Host 검사(DNS rebinding 방지), 쓰기(PUT/POST)는 `X-Ebook-Review: 1` 머리글 필요. 외부 CDN 없음.
- 작업 파일 `책이름_교정.md`: 처음 열 때 `_교정용.md`를 복사해 만들고 이후 **절대 덮어쓰지 않음**(OCR 재실행에도). 저장 때 `.md.bak` 한 벌.
- 쪽 번호 = 정렬된 이미지의 1부터 순번 (`ebook_ocr.collect_pages`와 같은 규칙. 바꾸면 둘 다 고칠 것). 글 칸은 `<!-- p.N -->`로 나눈 그 쪽 글만 보임. 쪽을 넘어 이어 붙은 문단은 시작 쪽에 들어 있음.
- 이미지 위 줄 상자·신뢰도(<0.8 강조)·그림 후보는 `cache/*.json`의 `rows`·`pictures` 사용. 줄을 누르면 글에서 부분 문자열 검색.
- API: `GET /api/book`, `/api/suspects`, `/api/rows/N`, `/img/N`, `/figures/이름`, `PUT /api/md`, `POST /api/crop {page, box}`. 그림은 **원본 이미지**에서 잘라 `책이름_OCR/figures/pNNNN_KK.png`.
- 그림 줄: `![설명](figures/…png)` 한 줄. 문단 끝(다음 빈 줄 앞)에 삽입.
- 내보내기 서식: 제목 `#`(문서 제목)·`##`/`###`/`####` → Word 제목 1/2/3. 글 속 `***굵게+기울임***`·`**굵게**`·`*기울임*`(앞뒤 영문·숫자면 제외)·`<u>밑줄</u>`을 겹쳐서도 읽어(`inline_runs`, 편집기 색칠 `hlInline`과 같은 규칙) Word 서식으로 적용, AI용 md는 굵게·기울임 유지하고 `<u>` 태그만 지움.

**AI 교정 제안** (`ebook_suggest.py`, 선택. Gemini REST `models/<모델>:streamGenerateContent?alt=sse`(조각 받기), 표준 라이브러리만)
- 키: 환경변수 `GEMINI_API_KEY` 또는 `EbookOCR/gemini_key.txt`(.gitignore). 모델 기본 `gemini-3.5-flash-lite`(`--model`/`GEMINI_MODEL`), 사고 수준 `--thinking`(기본 none = 보내지 않음, 지정했는데 모델이 400으로 거부하면 빼고 재시도. PowerShell은 `""`를 넘기지 않아 `none`을 둠), 분당 호출 `--rpm`(기본 15), 한 번에 `--chunk-chars`(기본 4000, 문단 경계). 시험용으로 `GEMINI_API_BASE` 지정 가능. `--timeout`(기본 90초, 조각 사이 대기) 초과·연결 실패는 화면에 이유를 표시하고 5번까지 재시도. temperature는 기본으로 보내지 않음(Gemini 3 계열은 1.0 미만에서 되풀이 루프 위험, `--temperature`로 지정 가능), `maxOutputTokens` = `--max-tokens` 또는 자동(보낸 글자×2+2048, 최소 4096). 답이 `MAX_TOKENS`·차단·JSON 오류면 그 덩어리는 '검사함'으로 표시하지 않고 다음 실행에 재시도. `--redo`는 검사함 표시를 무시하고 다시 보내되, 진행을 `redo {model, done}`에 기록해 같은 모델로 다시 `--redo` 하면 이어서 함(끝까지 마치면 지움). `--check`는 짧은 글 한 번으로 연결·속도 점검(프록시 표시), `--no-proxy`는 Windows 인터넷 옵션 프록시를 거치지 않음. 429에 `limit: 0`이면 그 모델은 키로 못 씀으로 안내. 실제 Gemini 연결 점검(`--check`)은 2026-11-07 `gemini-3.5-flash-lite`로 성공(6초). 2026-11-08 책 한 권(문단 1500개) 전체 제안 성공. 형식 깨진 답은 앞 군더더기를 건너뛰고 배열을 찾고, 그래도 못 쓰면 같은 실행에서 한 번 재시도.
- 본문 문단(제목·각주·그림·쪽 표시 제외)을 `[id] 문단`으로 보내 고친 문단만 JSON으로 받음. **원문은 건드리지 않고** `책이름_제안.json`에 `{orig, sug, flags, status}` 저장, 검사한 문단은 `checked`에 기록(이어 하기). 429 중 "PerDay"는 중단(내일 이어 하기), 그 외 429·5xx는 대기 후 재시도.
- 걸러내기: 원문 대비 변경 비율 > `--max-change`(0.15)이면 버림, 숫자·영문 열이 달라지면 `flags`에 표시.
- 편집기 화면(2026-11-08): 글 칸은 지금 쪽 글만 보임(`pageRange`: 쪽 표시 다음 줄 ~ 다음 쪽 표시 앞, 끝 빈 줄 제외). 책 전체는 `full`에 두고 입력할 때마다 그 범위만 교체, 저장은 `full` 전체. 쪽 표시 줄은 화면에 안 나와 지울 수 없음. 쪽을 넘는 문단: OCR이 교정용 글에서는 붙이지 않고(`build_paragraphs(merge=False)`) 다음 쪽 표시를 `<!-- p.N 이어짐 -->`으로 씀(AI용 최종본 `책이름.md`는 예전처럼 붙임). 편집기는 제목에 '(첫 문단은 앞 쪽에서 이어짐)'과 켜고 끄는 버튼, 내보내기는 이어짐 다음 첫 본문을 앞 쪽 마지막 본문 문단에 이어 붙임(사이의 각주·그림은 건너뜀, 제목이 오면 취소).
  마크다운 색칠: 투명한 textarea 뒤에 같은 글꼴·줄바꿈의 `<pre id=hl>`를 깔고 색·바탕만 칠함(굵기·크기는 바꾸지 않아 줄 위치가 같음). 제목·인용(> 주)·그림·**굵게**·[?]·목록·AI 제안 있는 문단.
  서식 버튼: `**굵게**`·`*기울임*`·`<u>밑줄</u>`. 겹침 허용 — 고른 글 바깥의 짝 맞는 표시를 모두 읽어 하나를 켜고/끈 뒤 `<u>` + `***`/`**`/`*` 순서로 다시 씀(어떤 순서로 켜고 꺼도 꼬이지 않음, 표시까지 통째로 골라도 됨), 줄 단계 `##`/`###`/`####`/본문, 각주(고른 글 → 그 문단 뒤 `> 주:` 문단, 앞 기호 ▸●• 등 제거), 문단 위·아래 이동(빈 줄 단위, 같은 쪽 안). 바뀐 부분만 `execCommand("insertText")`로 넣어 Ctrl+Z 가능.
  찾기·모두 바꾸기는 책 전체 대상(쪽 표시 문자열은 바꾸기 거부). 제안은 지금 쪽 것만, '이 쪽 모두 수락/거절', '다음 제안 쪽'. 제안 카드의 고친 곳(바뀐 글자가 이어진 덩어리)마다 눌러서 넣기/빼기, '고른 N곳만 수락'. 남은 제안 수는 원문 문단이 지금 글에 그대로 있는 것만 셈, 나머지는 '맞출 수 없는 제안 정리'(status `stale`). '책 전체 모두 수락'(⚠ 제외 기본): `POST /api/backup`(교정.md.일괄수락전) 뒤 책 전체에서 원문 줄과 똑같은 줄을 바꾸고 `POST /api/suggest/status-many`. 문단 이동·각주 버튼 뒤에는 선택을 풀어 다음 서식 버튼이 문단 전체에 걸리지 않게 함.
- 편집기: `GET /api/suggestions`, `POST /api/suggest/status`. 제안은 현재 쪽 문단 아래에 글자 단위 차이로 표시, 수락 시 해당 문단만 교체. 문단은 원문 문자열 일치로 찾으므로 그 사이 원문을 고쳤으면 적용되지 않음.
- 무료 등급 한도는 자주 바뀜(분당 횟수보다 하루 요청 수가 먼저 걸릴 수 있음) → 설정값으로 둠. 실제 API 호출은 가짜 서버로만 시험함.

**내보내기** (`ebook_export.py`) — 교정 글 하나에서 2종
| | `책이름_완성본.docx` (python-docx) | `책이름_AI용.md` |
|---|---|---|
| 그림 | 이미지 삽입(최대 14cm) + 설명 캡션(`--no-caption`) | 이미지·링크 없음. `> [그림] 설명`, 설명이 없으면 `> [그림] (설명 없음 — 원본 N쪽)` |
| 쪽 표시 | 없음 | 기본 없음, `--page-marks`면 `[p.N]` 줄 |
- Markdown은 그림을 링크로만 가리키고 AI 지식 도구는 이를 읽지 못하므로 AI용에는 넣지 않음. 설명 없는 그림·없는 파일은 끝에 경고.
- docx: A4, 맑은 고딕(East-Asian 지정), 제목/제목1~3, `> 주:`는 작은 회색 들여쓰기. 줄바꿈된 줄은 각각 문단.
- 한계: 한글(HWPX) 직접 저장은 안 함(python-hwpx 그림 삽입 미확인). 한글은 docx를 열어 저장. Windows·한글·Word에서 열어 본 확인은 아직 없음.

---

## 12. 검증 방법

### 12.1 리눅스에서 할 수 있는 것 (Windows·한글 프로그램 없이)
- PaddleOCR 없이 `opencv-python-headless numpy pillow python-hwpx==6.8.0`만으로:
  - 합성 시험지(PIL로 글자·박스 그림) → `find_boxes`, `box_of` 판정 시험
  - `PageResult`를 직접 만들어 `write_hwpx` → 글자 추출(§7.3)로 저장 결과 확인
  - 실제 PDF는 `render_pdf` + `flatten` + `find_boxes`로 박스 찾기만 시험 (빨간 네모를 그린 확인용 그림)
- 전체 OCR은 모델 다운로드 호스트(`paddle-model-ecology.bj.bcebos.com`, `huggingface.co` 등)가 막혀 있으면 불가. 그때는 사용자가 Windows에서 돌린 결과 파일을 받아 대조.

### 12.2 대조 방법
- 글자 일치율: `difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()`. 차이 위치를 함께 보고 원본과 맞춰 판단.
- 표 수: `section0.xml`의 `<hp:tbl ` 개수. 표 안 내용 비교는 표마다 문단 목록 비교.
- `[?]`는 판에 따라 개수가 조금 다를 수 있음(신뢰도 경계 글자) → 글자 비교 때는 지우고 비교.

### 12.3 기준 결과 (2026-11, 실제 시험지 3종: TEST, 20261015152455, 20261015152518)
| 비교 | 결과 |
|---|---|
| 표 기능 추가 전 ↔ 후 | 글자 차이 0 (297·322·401줄), 표 21→23, 8→23, 8→19 |
| 저사양판 ↔ 일반판 | TEST·152518 완전 동일, 152455 99.98% (손글씨 2곳) |
| 그래픽카드 ↔ CPU | 99.91~99.95%, 종당 10~12곳(띄어쓰기·기호) |
| 같은 입력 반복 | CPU·그래픽카드 각각 완전 동일 |
| 속도 | 일반판 쪽당 약 74초(i5-1335U), 그래픽카드 시험지 4쪽 약 5초·전자책 쪽당 0.35초(RTX 4070 Ti) |

시험지 원본·기준 텍스트는 저장소에 없습니다 (P6). 필요하면 사용자에게 받습니다.

---

## 13. 알려진 한계

- 사이가 좁은(약 100px 미만) 나란한 박스 두 개는 표 하나로 묶임. 같은 줄에 두 박스 글이 있으면 나눠도 표에 못 넣어 그대로 둠.
- 위·아래 선이 모두 여러 곳 끊긴 박스, 낙서로 많이 그어진 박스, 아주 흐린 박스는 못 잡음 → 줄글로 나옴.
- 쪽 아래 "확인" 도장 칸도 표로 잡힘.
- 한 쪽짜리 문서가 표로 시작하면 맨 위 빈 문단 하나.
- 손글씨·원문자 인식은 품질 보장 없음 (P5).
- AVX만 있고 AVX2 없는 CPU는 실행 시 엔진 시험으로 판정 (§4).

---

## 14. 남은 과제 (우선순위 높은 순)

| 과제 | 내용 | 비고 |
|---|---|---|
| 자동 회귀 검사 | 합성 시험지 + 기준 결과로 "글자 차이 0"을 자동 대조하는 스크립트 | P1을 사람 손 없이 지키기. 실제 시험지는 저장소 밖에 둘 것 |
| 처음 보는 시험지 검증 | 다른 출판사·형식 10~20종 | 판정 기준 §2 |
| 통합 설치 파일 | AVX 자동 판정으로 일반·저사양 중 맞는 판 설치, VC++ 런타임 동봉, 파일 이름에 날짜·버전 | 현재 두 판 따로 |
| 화면 편의 | 파일 끌어다 놓기, 중지한 작업 이어하기 (중지 버튼은 있음) | |
| 검수 화면 | `[?]` 글자를 원본 조각 옆에 보여 주고 바로 고치기 | 시험지 쪽. 전자책 쪽은 §11.1로 구현 |
| 문항 단위 구조화 | 문항 번호·지문·보기를 나눠 저장 | 별도 프로젝트 규모 |

---

## 15. 개발할 때 주의

- **파일 형식**: `.bat` CRLF + 첫머리 `chcp 65001`, `.iss`·`사용법.txt` UTF-8 BOM + CRLF, `.py`·`.spec`·`.md` UTF-8(BOM 없음) LF. 고친 뒤 `file`로 확인. 파이썬으로 bat을 고치면 줄 끝이 LF로 바뀌기 쉬우니 주의.
- **bat 안 `if (...)` 블록**에서 `rem`이나 `echo`에 괄호를 쓰면 블록이 깨짐 (`^)`로 이스케이프하거나 블록 밖으로).
- **한글 경로**: 이미지는 `np.fromfile`+`imdecode`, 모델은 `_ascii_safe`. 새 입출력 코드도 한글 경로로 시험.
- **사용자 안내**: 사용자는 코드를 짜지 않음. "어느 파일을 어디에 두고 무엇을 두 번 누르는지" 수준으로 안내. 보고는 한국어, TL;DR 먼저, 확인한 것과 추정을 구분.
- **브랜치**: main에는 사용자 허락 후 합침. 강제 푸시·브랜치 삭제는 명시적 허락이 있을 때만.
- **설치 파일 혼동**: 다른 날 만든 설치 파일을 잘못 설치해 "표 0개" 결과가 나온 적 있음. 결과가 이상하면 설치된 `ExamOCR.exe` 날짜부터 확인.

---

## 16. 용어

| 용어 | 뜻 |
|---|---|
| 구간(region) | 읽는 단위로 자른 쪽의 일부. 두 단이면 왼쪽 단·오른쪽 단·가로지르는 띠 |
| 글상자(Item) | OCR이 찾은 글자 덩어리 하나와 그 좌표·신뢰도 |
| 비침 | 뒷면 인쇄가 비쳐 보이는 연한 글자 |
| `[?]` | 신뢰도가 기준보다 낮은 글자 뒤 표시 |
| 일반판 / 저사양판 / 그래픽카드판 | §4 |
| AVX | CPU 명령어 확장. PaddlePaddle CPU 엔진이 필요로 함 |
