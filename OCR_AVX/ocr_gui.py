#!/usr/bin/env python3
"""
시험지 OCR 변환 — 화면 프로그램

    · [파일 추가]로 PDF·사진을 고르고 [변환 시작]을 누르면
      원본과 같은 폴더에 '원본이름_OCR.hwpx'로 저장합니다. (같은 이름이 있으면 _OCR(2) ...)
    · 목록에서 파일을 눌러 □를 ▣로 만든 뒤 [선택 비우기]를 누르면 그 파일만 목록에서 지웁니다.
    · 변환이 끝나면 완료된 파일은 목록에서 사라지고, 실패한 파일은 '실패'로 남습니다.
    · 오류 내용은 화면이 아니라 로그 파일(ocr_log.txt)에 남깁니다.

관리자용 점검:  ExamOCR.exe --check   (또는 python ocr_gui.py --check)
    → 로그 폴더에 ocr_check.txt 를 만들고 엔진·모델·HWPX 저장을 점검합니다.
"""

from __future__ import annotations

import logging
import os
import queue
import sys
import threading
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path

APP_TITLE = "시험지 OCR 변환"
SUPPORTED = (".pdf", ".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp")
MARK_LOW = 0.6  # [?] 표시 기준 (신뢰도)

CHECK_OFF, CHECK_ON = "□", "▣"  # 한글 표준 글꼴(맑은 고딕)에 있는 기호
ST_WAIT, ST_RUN, ST_DONE, ST_FAIL = "대기", "변환 중…", "완료", "실패"


# ----------------------------------------------------------------------------
# 로그
# ----------------------------------------------------------------------------
def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def log_dir() -> Path:
    """프로그램 폴더에 쓸 수 있으면 거기, 아니면 %LOCALAPPDATA%\\ExamOCR."""
    d = app_dir()
    try:
        probe = d / ".write_test"
        probe.write_text("x", encoding="utf-8")
        probe.unlink()
        return d
    except OSError:
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
        d = base / "ExamOCR"
        d.mkdir(parents=True, exist_ok=True)
        return d


def RUNNING_FLAG() -> Path:
    """변환 중에만 존재하는 표시 파일. 다음 실행 때 남아 있으면 지난번에 비정상 종료된 것."""
    return log_dir() / "ocr_running.flag"


def SAFE_FLAG() -> Path:
    """있으면 안전 모드(CPU 가속 끔)로 실행. 관리자가 지우면 빠른 모드로 복귀."""
    return log_dir() / "ocr_safe_mode.txt"


_crash_file = None  # faulthandler가 쓰는 파일 (프로그램이 끝날 때까지 열어 둬야 함)


def enable_crash_log():
    """엔진(C++)이 통째로 죽을 때도 어디서 죽었는지 ocr_crash.txt에 남긴다."""
    global _crash_file
    import faulthandler

    try:
        _crash_file = open(log_dir() / "ocr_crash.txt", "a", encoding="utf-8")
        faulthandler.enable(file=_crash_file, all_threads=True)
    except Exception:
        pass


def setup_logging() -> logging.Logger:
    log = logging.getLogger("examocr")
    if not log.handlers:
        h = RotatingFileHandler(log_dir() / "ocr_log.txt", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        log.addHandler(h)
        log.setLevel(logging.INFO)
    return log


# ----------------------------------------------------------------------------
# 작업 스레드: 모델 불러오기와 변환을 한 스레드에서 차례로 처리
# ----------------------------------------------------------------------------
class Worker(threading.Thread):
    def __init__(self, events: queue.Queue, log: logging.Logger):
        super().__init__(daemon=True)
        self.events = events  # 화면으로 보내는 알림
        self.jobs: queue.Queue = queue.Queue()
        self.stop_flag = threading.Event()
        self.log = log
        self.ocr = None

    def emit(self, *msg):
        self.events.put(msg)

    def run(self):
        import ocr_paddle as op

        # 지난번 변환 도중 프로그램이 통째로 죽었다면(표시 파일이 남아 있으면) 안전 모드로 전환:
        # CPU 가속(oneDNN)을 끄면 느려지지만 즉석 생성 코드에서의 충돌을 피할 수 있다.
        if RUNNING_FLAG().exists():
            SAFE_FLAG().write_text("변환 도중 프로그램이 비정상 종료되어 안전 모드로 전환함.\n"
                                   "이 파일을 지우면 다음 실행부터 빠른 모드로 돌아갑니다.\n", encoding="utf-8")
            RUNNING_FLAG().unlink(missing_ok=True)
            self.log.warning("지난 실행이 변환 도중 비정상 종료됨 → 안전 모드(CPU 가속 끔)로 전환")
        self.safe_mode = SAFE_FLAG().exists()
        try:
            self.log.info("모델 불러오기 시작 (%s)", "안전 모드" if self.safe_mode else "빠른 모드")
            self.ocr = op.build_ocr(op.default_options(no_mkldnn=self.safe_mode))
            self.log.info("모델 불러오기 완료")
            self.emit("ready")
        except Exception:
            self.log.error("모델 불러오기 실패\n%s", traceback.format_exc())
            self.emit("load_failed")
            return

        while True:
            job = self.jobs.get()
            if job is None:
                return
            self.convert(job)

    def convert(self, job):
        """job = (항목 목록 [(iid, 경로, 쪽수)], [?] 표시 여부)"""
        import ocr_paddle as op

        items, mark = job
        args = op.default_options(mark_low=MARK_LOW if mark else 0.0, formats={"hwpx"})
        total = sum(max(1, p) for _, _, p in items)
        done_pages = 0
        self.stop_flag.clear()
        RUNNING_FLAG().write_text("변환 중\n", encoding="utf-8")  # 정상 종료하면 지움
        for iid, path, pages in items:
            if self.stop_flag.is_set():
                break
            self.emit("file_start", iid, path.name)
            self.log.info("시작: %s (%s쪽)", path, pages or "?")

            def on_page(i, n, base=done_pages, name=path.name):
                self.log.info("  %s %d/%d쪽 완료", name, i, n)
                self.emit("progress", base + i, total, name, i, n)

            try:
                result = op.ocr_file(self.ocr, path, args, None, on_page=on_page, should_stop=self.stop_flag.is_set)
                out = op.next_free_path(path.parent, f"{path.stem}_OCR", ".hwpx")
                op.write_hwpx(result, out)
                self.log.info("완료: %s → %s", path, out)
                self.emit("file_done", iid, str(out))
            except op.Stopped:
                self.log.info("중지: %s", path)
                self.emit("file_stopped", iid)
                break
            except Exception:
                self.log.error("실패: %s\n%s", path, traceback.format_exc())
                self.emit("file_failed", iid)
            done_pages += max(1, pages)
        RUNNING_FLAG().unlink(missing_ok=True)
        self.emit("batch_end", self.stop_flag.is_set())


# ----------------------------------------------------------------------------
# 화면
# ----------------------------------------------------------------------------
class App:
    def __init__(self, root, worker_factory=Worker):
        import tkinter as tk
        from tkinter import ttk

        self.tk, self.ttk = tk, ttk
        self.root = root
        self.log = setup_logging()
        self.events: queue.Queue = queue.Queue()
        self.items: dict[str, dict] = {}  # iid → {path, pages, checked, status}
        self.running = False
        self.ready = False

        root.title(APP_TITLE)
        root.geometry("660x660")
        root.minsize(600, 600)
        self._setup_style()

        pad = {"padx": 12}
        top = ttk.Frame(root)
        top.pack(fill="x", pady=(12, 6), **pad)
        self.btn_add = ttk.Button(top, text="파일 추가", command=self.add_files)
        self.btn_del_sel = ttk.Button(top, text="선택 비우기", command=self.remove_checked)
        self.btn_clear = ttk.Button(top, text="목록 비우기", command=self.clear_list)
        for b in (self.btn_add, self.btn_del_sel, self.btn_clear):
            b.pack(side="left", padx=(0, 6))

        box = ttk.Frame(root)
        box.pack(fill="both", expand=True, **pad)
        cols = ("check", "name", "pages", "status")
        self.tree = ttk.Treeview(box, columns=cols, show="headings", selectmode="none", height=8)
        for c, title, w, anchor, stretch in [("check", "", 36, "center", False), ("name", "파일", 360, "w", True),
                                             ("pages", "쪽수", 60, "center", False), ("status", "상태", 90, "center", False)]:
            self.tree.heading(c, text=title)
            self.tree.column(c, width=w, anchor=anchor, stretch=stretch)
        sb = ttk.Scrollbar(box, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<Button-1>", self.on_click)
        self.tree.tag_configure("fail", foreground="#c62828")

        self.hint = ttk.Label(root, style="Hint.TLabel",
                              text="[파일 추가]를 눌러 변환할 시험지(PDF·사진)를 고르세요. "
                                   "목록에서 파일을 누르면 □가 ▣로 바뀌고, [선택 비우기]로 그 파일만 지울 수 있습니다.")
        self.hint.pack(fill="x", pady=(4, 8), **pad)

        opt = ttk.Frame(root)
        opt.pack(fill="x", **pad)
        self.var_mark = tk.BooleanVar(value=True)
        ttk.Checkbutton(opt, text="확인이 필요한 글자에 [?] 표시", variable=self.var_mark).pack(anchor="w")
        ttk.Label(opt, style="Hint.TLabel",
                  text="프로그램이 자신 없게 읽은 글자 뒤에 [?]가 붙습니다. "
                       "한글에서 Ctrl+F로 [?]를 찾아 원본과 비교해 고치세요.").pack(anchor="w", padx=(22, 0))

        self.btn_run = ttk.Button(root, text="변환 시작", style="Big.TButton", command=self.on_run)
        self.btn_run.pack(fill="x", pady=(14, 8), **pad)
        self.bar = ttk.Progressbar(root, mode="determinate", maximum=1, value=0)
        self.bar.pack(fill="x", **pad)
        self.status = ttk.Label(root, text="", style="Status.TLabel")
        self.status.pack(fill="x", pady=(6, 0), **pad)
        ttk.Label(root, style="Hint.TLabel",
                  text="결과는 원본 파일과 같은 폴더에 '원본이름_OCR.hwpx'로 저장됩니다.").pack(fill="x", pady=(4, 12), **pad)

        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.worker = worker_factory(self.events, self.log)
        self.set_status("준비 중입니다… (처음 실행할 때는 1분 정도 걸릴 수 있습니다)")
        self.update_buttons()
        self.worker.start()
        self._after = root.after(100, self.poll)

    # --- 모양 --------------------------------------------------------------
    def _setup_style(self):
        from tkinter import font as tkfont

        style = self.ttk.Style(self.root)
        families = set(tkfont.families(self.root))
        family = next((f for f in ("맑은 고딕", "Malgun Gothic", "Noto Sans CJK KR") if f in families), None)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        base = tkfont.nametofont("TkDefaultFont")
        if family:
            base.configure(family=family, size=10)
            for name in ("TkTextFont", "TkHeadingFont", "TkMenuFont"):
                try:
                    tkfont.nametofont(name).configure(family=family)
                except Exception:
                    pass
        fam = base.actual("family")
        style.configure("Treeview", rowheight=26)
        style.configure("Hint.TLabel", foreground="#666666", wraplength=620)
        style.configure("Status.TLabel", font=(fam, 10, "bold"))
        style.configure("Big.TButton", font=(fam, 12, "bold"), padding=8)

    # --- 목록 --------------------------------------------------------------
    def add_files(self):
        from tkinter import filedialog

        paths = filedialog.askopenfilenames(
            title="변환할 시험지 고르기",
            filetypes=[("PDF·사진", " ".join(f"*{e}" for e in SUPPORTED)), ("모든 파일", "*.*")],
        )
        self.add_paths(paths)

    def add_paths(self, paths):
        import ocr_paddle as op

        have = {str(v["path"].resolve()).lower() for v in self.items.values()}
        for p in map(Path, paths):
            if p.suffix.lower() not in SUPPORTED or str(p.resolve()).lower() in have:
                continue
            try:
                pages = op.page_count(p)
            except Exception:
                self.log.warning("쪽수 확인 실패: %s\n%s", p, traceback.format_exc())
                pages = 0
            iid = self.tree.insert("", "end", values=(CHECK_OFF, p.name, pages or "?", ST_WAIT))
            self.items[iid] = {"path": p, "pages": pages, "checked": False, "status": ST_WAIT}
            have.add(str(p.resolve()).lower())
        self.update_buttons()

    def on_click(self, event):
        if self.running or self.tree.identify_region(event.x, event.y) != "cell":
            return
        iid = self.tree.identify_row(event.y)
        if iid in self.items:
            it = self.items[iid]
            it["checked"] = not it["checked"]
            self.tree.set(iid, "check", CHECK_ON if it["checked"] else CHECK_OFF)
            self.update_buttons()

    def remove_items(self, iids):
        for iid in iids:
            self.tree.delete(iid)
            self.items.pop(iid, None)
        self.update_buttons()

    def remove_checked(self):
        self.remove_items([i for i, v in self.items.items() if v["checked"]])

    def clear_list(self):
        self.remove_items(list(self.items))

    def set_item_status(self, iid, status):
        if iid in self.items:
            self.items[iid]["status"] = status
            self.tree.set(iid, "status", status)
            self.tree.item(iid, tags=("fail",) if status == ST_FAIL else ())

    # --- 실행 --------------------------------------------------------------
    def update_buttons(self):
        idle = not self.running
        has_items = bool(self.items)
        self.btn_add.state(["!disabled"] if idle else ["disabled"])
        self.btn_clear.state(["!disabled"] if idle and has_items else ["disabled"])
        any_checked = any(v["checked"] for v in self.items.values())
        self.btn_del_sel.state(["!disabled"] if idle and any_checked else ["disabled"])
        if self.running:
            self.btn_run.configure(text="중지")
        else:
            self.btn_run.configure(text="변환 시작")
            self.btn_run.state(["!disabled"] if self.ready and has_items else ["disabled"])

    def set_status(self, text):
        self.status.configure(text=text)

    def on_run(self):
        if self.running:
            self.worker.stop_flag.set()
            self.btn_run.configure(text="중지하는 중…")
            self.btn_run.state(["disabled"])
            self.set_status("지금 쪽을 마치고 멈춥니다…")
            return
        todo = [(iid, v["path"], v["pages"]) for iid, v in self.items.items()]
        if not todo:
            return
        for iid, _, _ in todo:
            self.set_item_status(iid, ST_WAIT)
        self.running = True
        self.bar.configure(maximum=sum(max(1, p) for _, _, p in todo), value=0)
        self.set_status("변환을 시작합니다…")
        self.update_buttons()
        self.worker.jobs.put((todo, self.var_mark.get()))

    def poll(self):
        try:
            while True:
                self.handle(*self.events.get_nowait())
        except queue.Empty:
            pass
        self._after = self.root.after(100, self.poll)

    def handle(self, kind, *a):
        if kind == "ready":
            self.ready = True
            self.set_status("")
            self.update_buttons()
        elif kind == "load_failed":
            self.set_status("프로그램을 준비하지 못했습니다. 관리자에게 ocr_log.txt 파일을 보내 주세요.")
        elif kind == "file_start":
            self.set_item_status(a[0], ST_RUN)
        elif kind == "progress":
            done, total, name, i, n = a
            self.bar.configure(maximum=total, value=done)
            self.set_status(f"변환 중: {name} ({i}/{n}쪽)")
        elif kind == "file_done":
            self.set_item_status(a[0], ST_DONE)
        elif kind == "file_failed":
            self.set_item_status(a[0], ST_FAIL)
        elif kind == "file_stopped":
            self.set_item_status(a[0], ST_WAIT)
        elif kind == "batch_end":
            stopped = a[0]
            self.running = False
            self.remove_items([i for i, v in self.items.items() if v["status"] == ST_DONE])
            failed = sum(1 for v in self.items.values() if v["status"] == ST_FAIL)
            if stopped:
                self.set_status("중지했습니다. 남은 파일은 목록에 있습니다.")
            elif failed:
                self.set_status(f"작업 완료 (실패 {failed}개는 목록에 남겨 두었습니다)")
            else:
                self.set_status("작업 완료")
                self.bar.configure(value=self.bar.cget("maximum"))
            self.update_buttons()

    def on_close(self):
        from tkinter import messagebox

        if self.running and not messagebox.askyesno(
                APP_TITLE, "변환 중입니다.\n지금 끄면 변환 중인 파일은 저장되지 않습니다.\n종료할까요?"):
            return
        self.worker.stop_flag.set()
        RUNNING_FLAG().unlink(missing_ok=True)  # 사용자가 직접 끈 것은 비정상 종료가 아님
        try:
            self.root.after_cancel(self._after)
        except Exception:
            pass
        self.root.destroy()


# ----------------------------------------------------------------------------
# 관리자용 점검 (--check)
# ----------------------------------------------------------------------------
def self_check() -> int:
    """엔진·모델·HWPX 저장을 점검하고 결과를 ocr_check.txt로 남긴다."""
    import tempfile
    import time

    lines, ok = [], True

    def step(name, fn):
        nonlocal ok
        t = time.perf_counter()
        try:
            info = fn()
            lines.append(f"[통과] {name} ({time.perf_counter() - t:.1f}초) {info or ''}")
            return True
        except Exception:
            ok = False
            lines.append(f"[실패] {name}\n{traceback.format_exc()}")
            return False

    state = {}

    def imports():
        import cv2
        import hwpx
        import paddle
        import paddleocr
        import pypdfium2

        from importlib.metadata import version

        return (f"paddle {paddle.__version__}, paddleocr {paddleocr.__version__}, hwpx {hwpx.__version__}, "
                f"pypdfium2 {version('pypdfium2')}, cv2 {cv2.__version__}")

    def models():
        import ocr_paddle as op

        found = op.find_bundled_models(op.DET_MODEL_ACCURATE, op.REC_MODEL)
        if found is None:
            raise RuntimeError("동봉된 models 폴더를 찾지 못했습니다 (인터넷에서 받으려 시도하게 됩니다)")
        return " / ".join(map(str, found))

    def load():
        import ocr_paddle as op

        state["ocr"] = op.build_ocr(op.default_options())

    def recognize():
        import cv2
        import numpy as np

        import ocr_paddle as op

        img = np.full((200, 900, 3), 255, np.uint8)
        cv2.putText(img, "Hello OCR 2025", (30, 120), cv2.FONT_HERSHEY_SIMPLEX, 2.2, (0, 0, 0), 4)
        page = op.ocr_page(state["ocr"], img, op.default_options(), None, 1)
        text = " ".join(page.lines)
        if "OCR" not in text.upper():
            raise RuntimeError(f"시험 글자를 못 읽음: {text!r}")
        state["page"] = page
        return repr(text)

    def pdf():
        import pypdfium2 as pdfium

        import ocr_paddle as op

        p = Path(tempfile.mkdtemp(prefix="한글경로_")) / "점검.pdf"
        doc = pdfium.PdfDocument.new()
        doc.new_page(595, 842)
        doc.save(str(p))
        doc.close()
        imgs = op.render_pdf(p, 300)
        return f"{len(imgs)}쪽, {imgs[0].shape[1]}x{imgs[0].shape[0]}"

    def save(page=None):
        import ocr_paddle as op
        from hwpx import HwpxDocument

        page = page or op.PageResult(page=1, lines=["점검 문장 ① calm\t② editor[?]"])
        p = Path(tempfile.mkdtemp()) / "점검_OCR.hwpx"
        op.write_hwpx([page], p)
        rep = HwpxDocument.open(str(p)).validate()
        if rep.issues:
            raise RuntimeError(str(rep.issues))
        return str(p)

    def cpu():
        flags = cpu_flags()
        if flags is None:
            raise RuntimeError("CPU 기능을 확인하지 못했습니다 (실행 시 사양 확인이 동작하지 않음)")
        return f"{cpu_name()} / AVX={flags[0]}, AVX2={flags[1]}"

    step("CPU 사양 확인", cpu)
    step("라이브러리 불러오기", imports)
    step("한글 경로 PDF 열기", pdf)
    step("HWPX 저장", save)
    step("동봉 모델 찾기", models)
    if step("모델 불러오기", load):
        if step("글자 인식", recognize):
            step("인식 결과 HWPX 저장", lambda: save(state["page"]))
    out = log_dir() / "ocr_check.txt"
    out.write_text(("RESULT: " + ("PASS" if ok else "FAIL") + "\n점검 결과: " + ("모두 통과" if ok else "실패 있음")
                    + "\n\n" + "\n".join(lines) + "\n"), encoding="utf-8")
    print(out.read_text(encoding="utf-8"))
    return 0 if ok else 1


# ----------------------------------------------------------------------------
# PC 사양 확인: 딥러닝 엔진(PaddlePaddle)은 AVX 명령이 없는 CPU에서 실행하자마자 죽는다.
# 아무 말 없이 꺼지는 대신, 처음에 확인해서 안내 창을 띄운다.
# ----------------------------------------------------------------------------
LOW_SPEC_MESSAGE = (
    "이 컴퓨터는 CPU 사양이 낮아 '시험지 OCR 변환'을 사용할 수 없습니다.\n"
    "다른 컴퓨터를 이용해 주세요.\n\n"
    "CPU: {cpu}"
)


def cpu_name() -> str:
    if sys.platform.startswith("win"):
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
                return str(winreg.QueryValueEx(k, "ProcessorNameString")[0]).strip()
        except Exception:
            pass
    return os.environ.get("PROCESSOR_IDENTIFIER", "") or "알 수 없음"


def cpu_flags() -> tuple[bool, bool] | None:
    """(AVX 있음, AVX2 있음). 판단할 수 없으면 None (그때는 막지 않는다)."""
    if sys.platform.startswith("win"):
        try:
            import ctypes

            k = ctypes.windll.kernel32
            # 이 기능 번호들은 Windows 10 2004 이후에만 알아듣는다. 오래된 Windows는 무조건 '없음'(0)을 돌려주므로,
            # 거의 모든 CPU에 있는 SSE4.2(38번)가 '있음'으로 나올 때만 결과를 믿는다.
            if k.IsProcessorFeaturePresent(38):
                return bool(k.IsProcessorFeaturePresent(39)), bool(k.IsProcessorFeaturePresent(40))
        except Exception:
            pass
    try:
        import numpy as np  # numpy는 실행 중에 CPU 기능을 직접 확인해 둔다

        try:
            feats = np._core._multiarray_umath.__cpu_features__
        except AttributeError:
            feats = np.core._multiarray_umath.__cpu_features__
        return bool(feats.get("AVX")), bool(feats.get("AVX2"))
    except Exception:
        return None


def _engine_probe_ok(log: logging.Logger) -> bool:
    """엔진을 별도 프로세스로 한 번 불러와 본다. 죽으면 False. (AVX는 있고 AVX2는 없는 CPU에서만 사용)"""
    import subprocess

    cmd = [sys.executable, "--engine-probe"] if getattr(sys, "frozen", False) else [sys.executable, __file__, "--engine-probe"]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=300,
                           creationflags=0x08000000 if sys.platform.startswith("win") else 0)
        log.info("엔진 시험 실행 결과 코드: %s", r.returncode)
        return r.returncode == 0
    except subprocess.TimeoutExpired:
        log.warning("엔진 시험 실행이 시간 안에 끝나지 않음 → 막지 않음")
        return True
    except Exception:
        log.warning("엔진 시험 실행 실패 → 막지 않음\n%s", traceback.format_exc())
        return True


def low_spec_problem(log: logging.Logger) -> str | None:
    """이 PC에서 엔진을 쓸 수 없으면 안내 문구, 쓸 수 있으면(또는 판단 불가면) None."""
    name = cpu_name()
    flags = cpu_flags()
    log.info("CPU: %s / AVX·AVX2: %s", name, flags)
    if flags is None:
        return None
    avx, avx2 = flags
    if not avx:
        return LOW_SPEC_MESSAGE.format(cpu=name)
    if avx2:
        return None
    # AVX만 있고 AVX2가 없는 CPU(2011~2013년 무렵): 엔진이 도는지 실제로 한 번 확인하고 결과를 기억한다
    cache = log_dir() / "cpu_check.txt"
    try:
        saved = cache.read_text(encoding="utf-8").splitlines()
        if len(saved) == 2 and saved[0] == name:
            return None if saved[1] == "ok" else LOW_SPEC_MESSAGE.format(cpu=name)
    except OSError:
        pass
    ok = _engine_probe_ok(log)
    try:
        cache.write_text(f"{name}\n{'ok' if ok else 'fail'}\n", encoding="utf-8")
    except OSError:
        pass
    return None if ok else LOW_SPEC_MESSAGE.format(cpu=name)


def _fix_std_streams():
    """창 모드로 패키징하면 sys.stdout/stderr가 None이라, 무언가를 출력하는 라이브러리가 죽는다.
    출력을 로그 폴더의 ocr_console.txt로 돌린다."""
    if sys.stdout is None or sys.stderr is None:
        try:
            f = open(log_dir() / "ocr_console.txt", "a", encoding="utf-8", buffering=1)
        except OSError:
            f = open(os.devnull, "w", encoding="utf-8")
        if sys.stdout is None:
            sys.stdout = f
        if sys.stderr is None:
            sys.stderr = f


def main():
    if "--engine-probe" in sys.argv:  # 사양 확인용: 엔진만 불러 보고 끝낸다
        _fix_std_streams()
        import paddle  # noqa: F401

        sys.exit(0)
    _fix_std_streams()
    if "--check" in sys.argv:
        sys.exit(self_check())
    if sys.platform.startswith("win"):
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # 고해상도 화면에서 글자가 흐리지 않게
        except Exception:
            pass
    import tkinter as tk

    enable_crash_log()
    problem = low_spec_problem(setup_logging())
    if problem:
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(APP_TITLE, problem)
        root.destroy()
        return
    # 작업 스레드의 스택을 넉넉히: Windows 기본(약 1MB)으로는 딥러닝 엔진이 공간 부족으로 죽을 수 있다
    threading.stack_size(64 * 1024 * 1024)
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
