"""저사양 PC용 엔진(ONNX Runtime) 시험 — 변환 + 정확도 비교 + 속도 비교.

사용: onnx_test.bat 위에 비교할 PDF 파일들을 끌어다 놓는다.
  1) PaddlePaddle 공식 ONNX 모델을 받아 models_onnx\\ 에 저장 (이미 있으면 건너뜀)
  2) 같은 입력으로 두 엔진의 모델 출력값을 직접 비교 (수치 검사)
  3) PDF마다 기본 엔진(paddle)과 ONNX 엔진으로 각각 변환해 글자 단위로 비교
  4) 결과를 onnx_report.txt 에 적는다 (첫 줄: RESULT: GO / NO-GO)

판정 기준(합의): 전체 글자 일치율 99% 이상, 빠진 줄 0.
"""

from __future__ import annotations

import difflib
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

import ocr_paddle as op  # noqa: E402

MODELS = [op.DET_MODEL_ACCURATE, op.REC_MODEL]
SRC = HERE / "models"
DST = HERE / "models_onnx"
CACHE = HERE / "onnx_test_cache"
OUT = HERE / "onnx_test_out"
REPORT = HERE / "onnx_report.txt"
SIM_GO = 0.99


def log(msg: str):
    print(msg, flush=True)


# ----------------------------------------------------------------------------
# 1) 공식 ONNX 모델 받기
#    (Windows용 변환 도구 paddle2onnx는 특정 PaddlePaddle 개발판에만 맞게 만들어져 있어
#     지금 버전에서는 실행되지 않는다. 대신 PaddlePaddle이 공식으로 변환해 배포하는 ONNX 모델을 받는다.)
# ----------------------------------------------------------------------------
def fetch_onnx():
    import shutil

    from paddlex.inference.utils.official_models import official_models

    for name in MODELS:
        dst = DST / name
        if (dst / "inference.onnx").is_file() and (dst / "inference.yml").is_file():
            log(f"  {name}: 이미 받아 둠")
            continue
        log(f"  {name}: 공식 ONNX 모델 받는 중...")
        src = Path(official_models.get_model_path(name, model_formats=["onnx"]))
        if not (src / "inference.onnx").is_file():
            raise SystemExit(f"[실패] {src} 에 inference.onnx 가 없습니다")
        dst.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dst, dirs_exist_ok=True)
        log(f"    → {dst}")


# ----------------------------------------------------------------------------
# 2) 수치 검사: 같은 입력 → 두 엔진의 모델 출력 비교
# ----------------------------------------------------------------------------
def numeric_check() -> list[str]:
    import onnxruntime as ort
    from paddle import inference as pi

    lines = []
    rng = np.random.default_rng(0)
    tests = {op.DET_MODEL_ACCURATE: [(1, 3, 960, 736), (1, 3, 1600, 1216)],
             op.REC_MODEL: [(1, 3, 48, 320), (6, 3, 48, 800)]}
    for name, shapes in tests.items():
        src, dst = SRC / name, DST / name
        cfg = pi.Config(str(src / "inference.json"), str(src / "inference.pdiparams"))
        cfg.disable_gpu()
        cfg.enable_mkldnn()
        pred = pi.create_predictor(cfg)
        sess = ort.InferenceSession(str(dst / "inference.onnx"), providers=["CPUExecutionProvider"])
        for sh in shapes:
            x = rng.uniform(-2, 2, sh).astype(np.float32)
            h = pred.get_input_handle(pred.get_input_names()[0])
            h.reshape(list(sh))
            h.copy_from_cpu(x)
            pred.run()
            a = pred.get_output_handle(pred.get_output_names()[0]).copy_to_cpu()
            b = sess.run(None, {sess.get_inputs()[0].name: x})[0]
            if name == op.REC_MODEL:
                agree = float(np.mean(a.argmax(-1) == b.argmax(-1)))
                kind = "글자 선택 일치"
            else:
                agree = float(np.mean((a > 0.3) == (b > 0.3)))
                kind = "글자 영역 일치"
            lines.append(f"  {name} {sh}: 최대 차이 {np.abs(a - b).max():.2e}, {kind} {agree * 100:.4f}%")
    return lines


# ----------------------------------------------------------------------------
# 3) 실제 시험지 비교
# ----------------------------------------------------------------------------
def run_engine(ocr, imgs, opts) -> tuple[list[list[str]], list[float]]:
    pages, times = [], []
    for i, img in enumerate(imgs, 1):
        t = time.perf_counter()
        res = op.ocr_page(ocr, img, opts, None, i)
        times.append(time.perf_counter() - t)
        pages.append(res.lines)
        log(f"    {i}/{len(imgs)}쪽 {times[-1]:.0f}초")
    return pages, times


def compare_page(a_lines: list[str], b_lines: list[str]) -> dict:
    a, b = "\n".join(a_lines), "\n".join(b_lines)
    sim = difflib.SequenceMatcher(None, a, b, autojunk=False).ratio() if (a or b) else 1.0
    a_set = [x for x in a_lines if x.strip()]
    b_set = [x for x in b_lines if x.strip()]

    def unmatched(src, other):
        out = []
        for line in src:
            best = max((difflib.SequenceMatcher(None, line, o, autojunk=False).ratio() for o in other), default=0.0)
            if best < 0.5:
                out.append(line)
        return out

    return {"sim": sim, "identical": a == b, "missing": unmatched(a_set, b_set),
            "extra": unmatched(b_set, a_set), "chars": len(a)}


def main(argv: list[str]) -> int:
    files = [Path(p) for p in argv if Path(p).is_file()]
    if not files:
        print("비교할 PDF 파일을 onnx_test.bat 위에 끌어다 놓으세요.")
        return 1

    log("[2/4] 공식 ONNX 모델 받기")
    fetch_onnx()
    log("[3/4] 모델 출력값 직접 비교 (수치 검사)")
    numeric = numeric_check()
    for line in numeric:
        log(line)

    log("[4/4] 시험지 비교 (기본 엔진 결과는 저장해 두고 다시 쓰므로, 두 번째부터는 빨라집니다)")
    CACHE.mkdir(exist_ok=True)
    OUT.mkdir(exist_ok=True)
    opts_p = op.default_options(engine="paddle")
    opts_o = op.default_options(engine="onnx")
    ocr_p = None
    log("  ONNX 엔진 불러오는 중...")
    t = time.perf_counter()
    ocr_o = op.build_ocr(opts_o)
    load_o = time.perf_counter() - t

    rows, all_a, all_b, total_missing = [], [], [], 0
    t_p_all, t_o_all, n_pages = 0.0, 0.0, 0
    for f in files:
        log(f"  {f.name}")
        imgs = op.render_pdf(f, opts_p.pdf_dpi) if f.suffix.lower() == ".pdf" else [op.load_image(f)]
        cache = CACHE / (f.stem + ".json")
        if cache.is_file():
            data = json.loads(cache.read_text(encoding="utf-8"))
            pages_p, times_p = data["pages"], data["times"]
            log("   기본 엔진: 저장된 결과 사용")
        else:
            if ocr_p is None:
                log("   기본 엔진 불러오는 중...")
                ocr_p = op.build_ocr(opts_p)
            log("   기본 엔진(paddle) 변환")
            pages_p, times_p = run_engine(ocr_p, imgs, opts_p)
            cache.write_text(json.dumps({"pages": pages_p, "times": times_p}, ensure_ascii=False), encoding="utf-8")
        log("   ONNX 엔진 변환")
        pages_o, times_o = run_engine(ocr_o, imgs, opts_o)
        (OUT / (f.stem + "_ONNX.txt")).write_text(
            "\n".join(f"===== {i} 페이지 =====\n" + "\n".join(p) for i, p in enumerate(pages_o, 1)), encoding="utf-8")
        for i, (a, b) in enumerate(zip(pages_p, pages_o), 1):
            c = compare_page(a, b)
            total_missing += len(c["missing"])
            all_a.append("\n".join(a))
            all_b.append("\n".join(b))
            rows.append((f.name, i, c, times_p[i - 1], times_o[i - 1]))
        t_p_all += sum(times_p)
        t_o_all += sum(times_o)
        n_pages += len(pages_o)

    total_a, total_b = "\n".join(all_a), "\n".join(all_b)
    overall = difflib.SequenceMatcher(None, total_a, total_b, autojunk=False).ratio() if (total_a or total_b) else 1.0
    go = overall >= SIM_GO and total_missing == 0

    out = [f"RESULT: {'GO' if go else 'NO-GO'}",
           f"전체 글자 일치율 {overall * 100:.2f}% (기준 99% 이상) / 빠진 줄 {total_missing}개 (기준 0)",
           f"쪽당 평균 시간: 기본 엔진 {t_p_all / max(n_pages, 1):.0f}초, ONNX 엔진 {t_o_all / max(n_pages, 1):.0f}초"
           f" (ONNX 엔진 불러오기 {load_o:.0f}초)",
           "", "[모델 출력값 직접 비교]", *numeric, "", "[쪽별 결과]"]
    for name, i, c, tp, to in rows:
        out.append(f"  {name} {i}쪽: 일치 {c['sim'] * 100:.2f}%{' (완전히 같음)' if c['identical'] else ''}"
                   f", 빠진 줄 {len(c['missing'])}, 새로 생긴 줄 {len(c['extra'])}, 시간 {tp:.0f}초 → {to:.0f}초")
        for line in c["missing"]:
            out.append(f"      - 빠짐: {line}")
        for line in c["extra"]:
            out.append(f"      + 새로 생김: {line}")
    out += ["", f"ONNX 엔진 결과 전문: {OUT}"]
    REPORT.write_text("\n".join(out) + "\n", encoding="utf-8")
    log("")
    log("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
