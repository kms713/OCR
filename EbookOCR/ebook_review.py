#!/usr/bin/env python3
"""
전자책 OCR 교정 편집기 — 왼쪽 책 이미지, 오른쪽 OCR 글을 나란히 보며 고치기
=======================================================================

ebook_ocr.py 가 만든 결과 폴더(책이름_OCR)의 '책이름_교정용.md' 를 브라우저에서 고칩니다.
  · 오른쪽 글에서 커서를 옮기면 왼쪽에 그 글이 있는 원본 쪽이 나옵니다.
  · 이미지 위에 OCR 이 읽은 줄을 표시하고, 신뢰도가 낮은 줄은 색을 다르게 합니다.
  · 이미지에서 영역을 끌어 지정하면 원본에서 잘라 figures 폴더에 저장하고, 글 사이에 그림 줄을 넣습니다.
    그림 줄의 설명은 AI용 텍스트에서는 그림을 대신하는 글이 됩니다.

사용 예 (Windows 에서는 python 대신 py -3.12)
    python ebook_review.py books\\책이름            # 결과 폴더는 books\\책이름_OCR
    python ebook_review.py books\\책이름 --port 9000 --no-browser

교정 내용은 '책이름_교정.md' 에 저장됩니다 (처음 열 때 '책이름_교정용.md' 를 복사해 만듦).
ebook_ocr.py 를 다시 돌려도 이 파일은 덮어쓰지 않습니다. 다 고친 뒤 ebook_export.py 로 내보냅니다.

서버는 이 PC(127.0.0.1)에서만 접속됩니다. 끝낼 때는 명령창에서 Ctrl+C.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import shutil
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

HERE = Path(__file__).resolve().parent
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}  # ebook_ocr.py 와 같게 유지
LOW_SCORE = 0.8  # 이 신뢰도 미만 줄은 '의심 줄'
MAX_BODY = 20 * 1024 * 1024
ALLOWED_HOSTS = {"127.0.0.1", "localhost"}
EDITOR_VERSION = "2026-11-10.3"  # ebook_review.html 의 EDITOR_VERSION 과 같게 (업데이트 뒤 편집기를 다시 켰는지 확인용)

FIG_LINK = re.compile(r"!\[([^\]\n]*)\]\((figures/[^)\s]+)\)")


def natural_key(f: Path):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", f.stem)]


def collect_pages(folder: Path) -> list[Path]:
    """ebook_ocr.collect_pages 와 같은 순서·같은 대상 (쪽 번호가 어긋나면 안 된다)."""
    files = [f for f in folder.iterdir()
             if f.is_file() and f.suffix.lower() in IMAGE_EXTS and not f.stem.startswith("test_")]
    return sorted(files, key=natural_key)


def clean_alt(text: str) -> str:
    """Markdown 그림 설명에 넣을 수 있게 줄바꿈·대괄호를 정리."""
    text = re.sub(r"\s+", " ", text or "").strip()
    return text.replace("[", "(").replace("]", ")")


class Book:
    def __init__(self, folder: Path, out_dir: Path, title: str):
        self.folder, self.out_dir, self.title = folder, out_dir, title
        self.files = collect_pages(folder)
        self.work = out_dir / f"{title}_교정.md"
        self.source = out_dir / f"{title}_교정용.md"
        self.figures = out_dir / "figures"
        self.suggest = out_dir / f"{title}_제안.json"  # ebook_suggest.py 가 만든 AI 교정 제안
        self.checked_file = out_dir / f"{title}_확인.json"  # 사람이 '확인 완료'한 쪽 (여러 PC 에서 이어서)
        self.exclude_file = out_dir / f"{title}_제외영역.json"  # 영역 지우기: 다시 OCR 할 때도 빼는 영역 (ebook_ocr 가 읽음)
        self.lock = threading.Lock()

    # -- 작업 파일 --------------------------------------------------------
    def ensure_work_file(self) -> None:
        if self.work.is_file():
            return
        if not self.source.is_file():
            raise FileNotFoundError(
                f"{self.source.name} 가 없습니다. 먼저 3_OCR.bat 로 변환하세요 (예전 버전으로 변환했다면 --redo 없이 다시 실행하면 만들어집니다).")
        shutil.copyfile(self.source, self.work)

    def read_md(self) -> str:
        return self.work.read_bytes().decode("utf-8")

    def write_md(self, text: str) -> None:
        with self.lock:
            if self.work.is_file():
                shutil.copyfile(self.work, self.work.with_suffix(".md.bak"))
            tmp = self.work.with_suffix(".md.tmp")
            tmp.write_bytes(text.replace("\r\n", "\n").encode("utf-8"))
            tmp.replace(self.work)

    # -- 쪽 ---------------------------------------------------------------
    def page_file(self, no: int) -> Path | None:
        return self.files[no - 1] if 1 <= no <= len(self.files) else None

    def cache_json(self, no: int) -> dict:
        f = self.page_file(no)
        if f is None:
            return {}
        cf = self.out_dir / "cache" / f"{f.stem}.json"
        try:
            return json.loads(cf.read_bytes().decode("utf-8"))
        except (OSError, ValueError):
            return {}

    def page_info(self) -> list[dict]:
        out = []
        for i, f in enumerate(self.files, start=1):
            d = self.cache_json(i)
            out.append({"no": i, "name": f.name, "width": d.get("width"), "height": d.get("height")})
        return out

    def rows(self, no: int) -> dict:
        d = self.cache_json(no)
        return {"rows": [{"text": r["text"], "box": r["box"], "score": r.get("score", 1.0)} for r in d.get("rows", [])],
                "pictures": d.get("pictures", []), "width": d.get("width"), "height": d.get("height"),
                "boxes": [{"text": b["text"], "box": b["box"]} for b in d.get("boxes", [])]}  # 표 넣기용 글상자

    # -- 쪽 확인 완료 -----------------------------------------------------
    def checked(self) -> list[int]:
        try:
            d = json.loads(self.checked_file.read_bytes().decode("utf-8"))
            return sorted({int(x) for x in d.get("pages", [])})
        except (OSError, ValueError):
            return []

    def set_checked(self, page: int, done: bool) -> list[int]:
        with self.lock:
            cur = set(self.checked())
            (cur.add if done else cur.discard)(page)
            tmp = self.checked_file.with_suffix(".json.tmp")
            tmp.write_bytes(json.dumps({"pages": sorted(cur)}, ensure_ascii=False).encode("utf-8"))
            tmp.replace(self.checked_file)
            return sorted(cur)

    def source_md(self) -> str:
        """OCR 이 처음 만든 교정용 글 (빠진 글 경고의 기준)."""
        try:
            return self.source.read_bytes().decode("utf-8")
        except OSError:
            return ""

    def row_boxes(self) -> list[dict]:
        """쪽마다 OCR 줄 글과 위치 (영역 지우기 미리보기용)."""
        out = []
        for i in range(1, len(self.files) + 1):
            d = self.cache_json(i)
            out.append({"w": d.get("width"), "h": d.get("height"),
                        "rows": [{"text": r["text"], "box": r["box"]} for r in d.get("rows", [])]})
        return out

    def add_exclude(self, region: dict) -> int:
        with self.lock:
            try:
                d = json.loads(self.exclude_file.read_bytes().decode("utf-8"))
            except (OSError, ValueError):
                d = {"regions": []}
            box = [min(max(float(v), 0.0), 1.0) for v in region["box"]]
            d["regions"].append({"box": box, "scope": str(region.get("scope", "all")),
                                 "from": int(region.get("from", 1)), "to": int(region.get("to", 99999))})
            tmp = self.exclude_file.with_suffix(".json.tmp")
            tmp.write_bytes(json.dumps(d, ensure_ascii=False, indent=1).encode("utf-8"))
            tmp.replace(self.exclude_file)
            return len(d["regions"])

    def row_texts(self) -> list[list[str]]:
        """쪽마다 OCR 줄 글 (점검표·빠진 글 경고용)."""
        return [[r["text"] for r in self.cache_json(i).get("rows", [])] for i in range(1, len(self.files) + 1)]

    def suspects(self) -> list[dict]:
        out = []
        for i in range(1, len(self.files) + 1):
            for j, r in enumerate(self.cache_json(i).get("rows", [])):
                if r.get("score", 1.0) < LOW_SCORE:
                    out.append({"page": i, "row": j, "text": r["text"], "score": round(r["score"], 3)})
        return out

    # -- AI 교정 제안 (원문은 건드리지 않고 사용자가 수락할 때만 글에 반영) --------
    def _load_suggest(self) -> dict:
        try:
            d = json.loads(self.suggest.read_bytes().decode("utf-8"))
            return d if isinstance(d, dict) and "items" in d else {"items": {}}
        except (OSError, ValueError):
            return {"items": {}}

    def suggestions(self) -> list[dict]:
        return [{"orig": v["orig"], "sug": v["sug"], "flags": v.get("flags", [])}
                for v in self._load_suggest()["items"].values() if v.get("status", "new") == "new"]

    def set_suggest_status(self, orig: str, status: str) -> None:
        self.set_suggest_status_many([(orig, status)])

    def set_suggest_status_many(self, pairs: list[tuple[str, str]]) -> None:
        """여러 제안의 상태를 한 번에 (책 전체 일괄 수락용)."""
        if any(st not in ("accepted", "rejected", "stale") for _, st in pairs):  # stale: 글이 바뀌어 맞출 수 없어 정리함
            raise ValueError("잘못된 상태")
        want = dict(pairs)
        with self.lock:
            d = self._load_suggest()
            for v in d["items"].values():
                if v["orig"] in want:
                    v["status"] = want[v["orig"]]
            tmp = self.suggest.with_suffix(".json.tmp")
            tmp.write_bytes(json.dumps(d, ensure_ascii=False, indent=1).encode("utf-8"))
            tmp.replace(self.suggest)

    # -- 그림 오려내기 ----------------------------------------------------
    def crop(self, no: int, box: list[float]) -> str:
        from PIL import Image

        f = self.page_file(no)
        if f is None:
            raise ValueError("없는 쪽입니다")
        img = Image.open(io.BytesIO(f.read_bytes()))
        img.load()
        w, h = img.size
        x1, y1, x2, y2 = (int(round(v)) for v in box)
        x1, x2 = sorted((max(0, min(w, x1)), max(0, min(w, x2))))
        y1, y2 = sorted((max(0, min(h, y1)), max(0, min(h, y2))))
        if x2 - x1 < 8 or y2 - y1 < 8:
            raise ValueError("영역이 너무 작습니다")
        crop = img.crop((x1, y1, x2, y2))
        if crop.mode not in ("RGB", "RGBA", "L"):
            crop = crop.convert("RGB")
        self.figures.mkdir(parents=True, exist_ok=True)
        with self.lock:
            k = 1
            while (self.figures / f"p{no:04d}_{k:02d}.png").exists():
                k += 1
            name = f"p{no:04d}_{k:02d}.png"
            buf = io.BytesIO()
            crop.save(buf, "PNG")
            (self.figures / name).write_bytes(buf.getvalue())
        return f"figures/{name}"


def make_handler(book: Book):
    html_path = HERE / "ebook_review.html"

    class Handler(BaseHTTPRequestHandler):
        server_version = "EbookReview"

        def log_message(self, fmt, *args):  # 조용히
            pass

        # -- 보조 ---------------------------------------------------------
        def _host_ok(self) -> bool:
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
            return host in ALLOWED_HOSTS  # DNS rebinding 방지

        def _send(self, code: int, body: bytes, ctype: str, cache: bool = False) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "max-age=3600" if cache else "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code: int = 200) -> None:
            self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def _body(self) -> bytes:
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                raise ValueError("요청이 너무 큽니다")
            return self.rfile.read(n)

        def _file(self, path: Path | None) -> None:
            if path is None or not path.is_file():
                return self._json({"error": "없음"}, 404)
            ctype = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                     ".bmp": "image/bmp", ".webp": "image/webp"}.get(path.suffix.lower(), "application/octet-stream")
            self._send(200, path.read_bytes(), ctype)  # 캐시 안 함: 다시 캡처·샘플 재생성 뒤 예전 그림이 보이지 않게 (내 PC 안이라 느리지 않음)

        # -- GET ----------------------------------------------------------
        def do_GET(self):
            if not self._host_ok():
                return self._json({"error": "허용되지 않은 접속"}, 403)
            path = unquote(urlparse(self.path).path)
            try:
                if path == "/":
                    return self._send(200, html_path.read_bytes(), "text/html; charset=utf-8")
                if path == "/api/book":
                    return self._json({"title": book.title, "pages": book.page_info(), "md": book.read_md(),
                                       "low_score": LOW_SCORE})
                if path == "/api/suggestions":
                    return self._json(book.suggestions())
                if path == "/api/version":
                    return self._json({"version": EDITOR_VERSION})
                if path == "/api/checked":
                    return self._json(book.checked())
                if path == "/api/source":
                    return self._json({"md": book.source_md()})
                if path == "/api/exclude":
                    try:
                        return self._json(json.loads(book.exclude_file.read_bytes().decode("utf-8")).get("regions", []))
                    except (OSError, ValueError):
                        return self._json([])
                if path == "/api/rowboxes":
                    return self._json(book.row_boxes())
                if path == "/api/rowtexts":
                    return self._json(book.row_texts())
                if path == "/api/suspects":
                    return self._json(book.suspects())
                m = re.fullmatch(r"/api/rows/(\d+)", path)
                if m:
                    return self._json(book.rows(int(m.group(1))))
                m = re.fullmatch(r"/img/(\d+)", path)
                if m:
                    return self._file(book.page_file(int(m.group(1))))
                m = re.fullmatch(r"/figures/([\w.\-]+)", path)  # 이름만 허용: 경로 이탈 불가
                if m:
                    return self._file(book.figures / m.group(1))
                return self._json({"error": "없음"}, 404)
            except Exception as e:  # noqa: BLE001
                return self._json({"error": str(e)}, 500)

        # -- PUT / POST ---------------------------------------------------
        def _write_ok(self) -> bool:
            # 다른 사이트가 이 서버로 쓰기 요청을 보내지 못하게, 우리 화면만 붙이는 머리글을 요구
            return self._host_ok() and self.headers.get("X-Ebook-Review") == "1"

        def do_PUT(self):
            if not self._write_ok():
                return self._json({"error": "허용되지 않은 요청"}, 403)
            try:
                if urlparse(self.path).path == "/api/md":
                    book.write_md(self._body().decode("utf-8"))
                    return self._json({"ok": True})
                return self._json({"error": "없음"}, 404)
            except Exception as e:  # noqa: BLE001
                return self._json({"error": str(e)}, 500)

        def do_POST(self):
            if not self._write_ok():
                return self._json({"error": "허용되지 않은 요청"}, 403)
            try:
                if urlparse(self.path).path == "/api/crop":
                    req = json.loads(self._body().decode("utf-8"))
                    rel = book.crop(int(req["page"]), [float(v) for v in req["box"]])
                    return self._json({"path": rel})
                if urlparse(self.path).path == "/api/exclude":
                    req = json.loads(self._body().decode("utf-8"))
                    return self._json({"count": book.add_exclude(req)})
                if urlparse(self.path).path == "/api/checked":
                    req = json.loads(self._body().decode("utf-8"))
                    return self._json(book.set_checked(int(req["page"]), bool(req["done"])))
                if urlparse(self.path).path == "/api/suggest/status-many":
                    req = json.loads(self._body().decode("utf-8"))
                    book.set_suggest_status_many([(str(x["orig"]), str(x["status"])) for x in req["items"]])
                    return self._json({"ok": True})
                if urlparse(self.path).path == "/api/backup":  # 일괄 수락 전 교정 글 한 벌 (덮어씀)
                    if book.work.is_file():
                        shutil.copyfile(book.work, book.work.with_name(book.work.name + ".일괄수락전"))
                    return self._json({"ok": True, "name": book.work.name + ".일괄수락전"})
                if urlparse(self.path).path == "/api/suggest/status":
                    req = json.loads(self._body().decode("utf-8"))
                    book.set_suggest_status(str(req["orig"]), str(req["status"]))
                    return self._json({"ok": True})
                return self._json({"error": "없음"}, 404)
            except ValueError as e:
                return self._json({"error": str(e)}, 400)
            except Exception as e:  # noqa: BLE001
                return self._json({"error": str(e)}, 500)

    return Handler


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="전자책 OCR 교정 편집기 (브라우저)")
    ap.add_argument("folder", help="page_0001.png ... 가 들어 있는 폴더")
    ap.add_argument("-o", "--output", help="OCR 결과 폴더 (기본: <폴더>_OCR)")
    ap.add_argument("--title", help="책 제목 (기본: 폴더 이름, ebook_ocr.py 와 같게)")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true", help="브라우저를 자동으로 열지 않음")
    args = ap.parse_args(argv)

    from bookdir import resolve, result_dir
    folder = resolve(args.folder)
    if not folder.is_dir():
        print(f"[오류] 폴더가 없습니다: {folder}")
        return 1
    out_dir = result_dir(folder, args.output, args.title)
    if not out_dir.is_dir():
        print(f"[오류] OCR 결과 폴더가 없습니다: {out_dir}\n  먼저 3_OCR.bat 로 변환하세요.")
        return 1
    book = Book(folder, out_dir, args.title or folder.name)
    if not book.files:
        print(f"[오류] 이미지가 없습니다: {folder}")
        return 1
    try:
        book.ensure_work_file()
    except FileNotFoundError as e:
        print(f"[오류] {e}")
        return 1

    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(book))
    except OSError:
        print(f"[오류] 포트 {args.port} 를 이미 쓰고 있습니다. 다른 교정 창이 열려 있지 않은지 확인하거나 --port 로 바꾸세요.")
        return 1
    url = f"http://127.0.0.1:{args.port}/"
    print(f"교정 편집기: {url}")
    print(f"  교정 파일: {book.work.resolve()}")
    print("  끝내려면 이 창에서 Ctrl+C (고친 내용은 자동 저장됩니다)")
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n종료합니다.")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
