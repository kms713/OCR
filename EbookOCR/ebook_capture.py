#!/usr/bin/env python3
"""
전자책 자동 캡처 — LD플레이어(안드로이드 에뮬레이터) 화면을 ADB로 한 쪽씩 넘기며 저장
=====================================================================================

준비
    1) LD플레이어 설정 → 기타 설정 → ADB 디버깅: '로컬 연결 열기'
    2) LD플레이어 해상도는 세로형 고해상도 권장 (예: 1600x2560, DPI 320)
    3) 뷰어: 흰 바탕·검은 글씨, 한 화면에 한 쪽, 글자 약간 크게, 페이지 넘김 효과 끄기(가능하면)
    4) 전자책을 열고 '처음 캡처할 쪽'을 화면에 띄워 둡니다.

사용 예 (Windows에서는 python 대신 py -3.12)
    python ebook_capture.py --test                         # 한 장만 찍어 test_screen.png 저장 (검은 화면인지 점검)
    python ebook_capture.py -o 책이름                       # 오른쪽 끝을 눌러 넘기며 끝까지 캡처
    python ebook_capture.py -o 책이름 --crop 0,120,1600,2440  # 뷰어 상·하단 영역 잘라내고 저장
    python ebook_capture.py -o 책이름 --turn key            # 오른쪽 방향키로 넘기기
    python ebook_capture.py -o 책이름 --turn swipe          # 왼쪽으로 쓸어 넘기기
    python ebook_capture.py -o 책이름 --max-pages 50        # 50쪽만

동작
    · 넘긴 뒤 화면이 바뀌고 '멈출 때까지'(넘김 효과가 끝날 때까지) 기다렸다가 저장합니다.
    · 넘겨도 화면이 그대로면 한 번 더 넘겨 보고, 그래도 같으면 마지막 쪽으로 보고 끝냅니다.
    · 같은 폴더로 다시 실행하면 이어서 번호를 붙입니다 (중간에 멈췄을 때 이어 찍기).
    · Ctrl+C 로 언제든 멈출 수 있습니다. 그때까지 찍은 쪽은 남아 있습니다.

출력
    <폴더>/page_0001.png, page_0002.png, ...   → 그대로 ebook_ocr.py 에 넣으면 됩니다.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

# LD플레이어에 함께 들어 있는 adb.exe 를 찾을 위치 (PATH 의 adb 보다 먼저 봄: 버전이 맞아 충돌이 없음)
LDPLAYER_DIRS = [
    r"C:\LDPlayer\LDPlayer9", r"C:\LDPlayer\LDPlayer4.0", r"C:\LDPlayer\LDPlayer64",
    r"D:\LDPlayer\LDPlayer9", r"D:\LDPlayer\LDPlayer4.0", r"D:\LDPlayer\LDPlayer64",
    r"C:\Program Files\LDPlayer\LDPlayer9", r"C:\Program Files\LDPlayer9",
    r"C:\XuanZhi\LDPlayer9", r"C:\XuanZhi9",
]
LDPLAYER_PORTS = [5555, 5557, 5559]  # 첫 번째·두 번째·세 번째 LD플레이어 창

KEYCODE_DPAD_RIGHT = 22
COMPARE_WIDTH = 240  # 화면 비교용 축소 폭
DIFF_THRESHOLD = 1.0  # 축소 흑백 이미지 평균 밝기 차이(0~255)가 이보다 크면 '화면이 바뀜'


# ----------------------------------------------------------------------------
# ADB
# ----------------------------------------------------------------------------
class AdbError(RuntimeError):
    pass


def find_adb(explicit: str | None) -> str:
    if explicit:
        return explicit
    for d in LDPLAYER_DIRS:
        p = Path(d) / "adb.exe"
        if p.is_file():
            return str(p)
    found = shutil.which("adb")
    if found:
        return found
    raise AdbError("adb 를 찾지 못했습니다. --adb \"C:\\LDPlayer\\LDPlayer9\\adb.exe\" 처럼 위치를 알려 주세요.")


class Adb:
    def __init__(self, exe: str, serial: str | None):
        self.exe = exe
        self.serial = serial

    def _run(self, args: list[str], timeout: float = 20) -> bytes:
        cmd = [self.exe] + (["-s", self.serial] if self.serial else []) + args
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        r = subprocess.run(cmd, capture_output=True, timeout=timeout, creationflags=flags)
        if r.returncode != 0:
            raise AdbError(f"adb {' '.join(args)} 실패: {r.stderr.decode(errors='replace').strip()}")
        return r.stdout

    def devices(self) -> list[str]:
        out = Adb(self.exe, None)._run(["devices"]).decode(errors="replace")
        return [ln.split("\t")[0] for ln in out.splitlines()[1:] if ln.strip().endswith("\tdevice")]

    def connect(self) -> str:
        """연결된 기기를 고르고, 없으면 LD플레이어 기본 포트로 연결을 시도한다."""
        if self.serial:
            if ":" in self.serial and self.serial not in self.devices():
                Adb(self.exe, None)._run(["connect", self.serial])
            return self.serial
        devs = self.devices()
        if not devs:
            for port in LDPLAYER_PORTS:
                try:
                    Adb(self.exe, None)._run(["connect", f"127.0.0.1:{port}"], timeout=5)
                except (AdbError, subprocess.TimeoutExpired):
                    continue
                devs = self.devices()
                if devs:
                    break
        if not devs:
            raise AdbError("LD플레이어에 연결하지 못했습니다. LD플레이어가 켜져 있고 'ADB 디버깅'이 켜져 있는지 확인하세요.")
        if len(devs) > 1:
            print(f"[알림] 연결된 기기가 여러 개입니다: {', '.join(devs)} → {devs[0]} 사용 (다른 기기는 --serial 로 지정)")
        self.serial = devs[0]
        return self.serial

    def screenshot(self) -> np.ndarray:
        import cv2

        data = self._run(["exec-out", "screencap", "-p"])
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise AdbError("스크린샷을 읽지 못했습니다 (adb 응답이 PNG가 아님)")
        return img

    def key(self, code: int) -> None:
        self._run(["shell", "input", "keyevent", str(code)])

    def tap(self, x: int, y: int) -> None:
        self._run(["shell", "input", "tap", str(x), str(y)])

    def swipe(self, x1: int, y1: int, x2: int, y2: int, ms: int = 200) -> None:
        self._run(["shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(ms)])


# ----------------------------------------------------------------------------
# 화면 처리
# ----------------------------------------------------------------------------
def parse_box(text: str | None) -> tuple[int, int, int, int] | None:
    if not text:
        return None
    try:
        x1, y1, x2, y2 = (int(v) for v in text.split(","))
    except ValueError:
        raise SystemExit(f"--crop 형식은 x1,y1,x2,y2 (예: 0,120,1600,2440) 입니다: {text}")
    if x2 <= x1 or y2 <= y1:
        raise SystemExit(f"--crop 의 x2·y2 는 x1·y1 보다 커야 합니다: {text}")
    return x1, y1, x2, y2


def crop(img: np.ndarray, box: tuple[int, int, int, int] | None) -> np.ndarray:
    if box is None:
        return img
    h, w = img.shape[:2]
    x1, y1, x2, y2 = box
    return img[max(0, y1):min(h, y2), max(0, x1):min(w, x2)]


def signature(img: np.ndarray) -> np.ndarray:
    """화면 비교용 축소 흑백 이미지. 시계·배터리가 바뀌는 맨 위·아래 4% 는 뺀다."""
    import cv2

    h, w = img.shape[:2]
    m = int(h * 0.04)
    g = cv2.cvtColor(img[m:h - m], cv2.COLOR_BGR2GRAY)
    nh = max(1, int(g.shape[0] * COMPARE_WIDTH / w))
    return cv2.resize(g, (COMPARE_WIDTH, nh), interpolation=cv2.INTER_AREA).astype(np.float32)


def differs(a: np.ndarray, b: np.ndarray) -> bool:
    return a.shape != b.shape or float(np.abs(a - b).mean()) > DIFF_THRESHOLD


def looks_blank(img: np.ndarray) -> bool:
    """캡처 차단(보안 화면)이면 전부 검은색이 나온다."""
    g = img.mean(axis=2)
    return float(g.mean()) < 8 and float(g.std()) < 4


def save_png(img: np.ndarray, path: Path) -> None:
    """한글 경로에서도 저장되도록 인코딩 후 바이트로 쓴다."""
    import cv2

    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise RuntimeError(f"PNG 인코딩 실패: {path}")
    buf.tofile(str(path))


def existing_pages(folder: Path) -> list[Path]:
    return sorted(folder.glob("page_[0-9][0-9][0-9][0-9].png"))


# ----------------------------------------------------------------------------
# 넘기기 / 캡처
# ----------------------------------------------------------------------------
def make_turner(adb: Adb, args, width: int, height: int):
    if args.turn == "key":
        return lambda: adb.key(args.key)
    if args.turn == "swipe":
        y = height // 2
        return lambda: adb.swipe(int(width * 0.8), y, int(width * 0.2), y, 200)
    if args.tap:
        x, y = (int(v) for v in args.tap.split(","))
    else:
        x, y = int(width * 0.92), height // 2  # 화면 오른쪽 끝 가운데
    return lambda: adb.tap(x, y)


def settle(adb: Adb, first: np.ndarray, args) -> np.ndarray:
    """넘김 효과가 끝날 때까지(연속 두 장이 같을 때까지) 기다린 화면."""
    cur = first
    for _ in range(10):
        time.sleep(args.settle)
        nxt = adb.screenshot()
        if not differs(signature(cur), signature(nxt)):
            return nxt
        cur = nxt
    return cur


def wait_change(adb: Adb, prev_sig: np.ndarray, sig, args) -> np.ndarray | None:
    """본문(sig 로 본 화면)이 prev 와 달라지면 안정된 화면을, timeout 안에 안 바뀌면 None."""
    end = time.monotonic() + args.timeout
    while time.monotonic() < end:
        time.sleep(args.interval)
        img = adb.screenshot()
        if differs(prev_sig, sig(img)):
            return settle(adb, img, args)
    return None


def run_test(adb: Adb, out: Path, box) -> int:
    img = adb.screenshot()
    h, w = img.shape[:2]
    out.mkdir(parents=True, exist_ok=True)
    full = out / "test_screen.png"
    save_png(img, full)
    print(f"화면 크기: {w} x {h}")
    print(f"저장: {full.resolve()}")
    if box is not None:
        save_png(crop(img, box), out / "test_crop.png")
        print(f"잘라낸 결과: {(out / 'test_crop.png').resolve()}")
    if looks_blank(img):
        print("[주의] 화면이 거의 검은색입니다. 뷰어가 화면 캡처를 막고 있을 수 있습니다.")
        print("       뷰어에서 책을 연 상태인지 확인하고, 그래도 검으면 이 방식으로는 캡처할 수 없습니다.")
        return 2
    print("정상: 화면이 찍힙니다. 그림판으로 열어 잘라낼 영역(--crop x1,y1,x2,y2) 좌표를 확인하세요.")
    return 0


def run_capture(adb: Adb, out: Path, args) -> int:
    box = parse_box(args.crop)
    out.mkdir(parents=True, exist_ok=True)
    done = existing_pages(out)
    num = int(done[-1].stem.split("_")[1]) if done else 0

    img = adb.screenshot()
    if looks_blank(img):
        print("[중단] 화면이 검은색입니다 (캡처 차단 가능성). --test 로 먼저 확인하세요.")
        return 2
    h, w = img.shape[:2]
    turn = make_turner(adb, args, w, h)
    page_sig = lambda im: signature(crop(im, box) if box else im)  # noqa: E731

    if done:
        import cv2

        last = cv2.imdecode(np.fromfile(str(done[-1]), np.uint8), cv2.IMREAD_COLOR)
        print(f"이어 찍기: 이미 {len(done)}장 있음 (마지막 {done[-1].name}).")
        if last is not None and not differs(signature(last), page_sig(img)):
            print("  지금 화면이 마지막 저장 쪽과 같아서 한 쪽 넘기고 시작합니다.")
            turn()
            img = wait_change(adb, page_sig(img), page_sig, args)
            if img is None:
                print("넘어가지 않습니다. 이미 마지막 쪽입니다.")
                return 0

    print(f"캡처 시작 → {out.resolve()}   (멈추려면 Ctrl+C)")
    started = time.monotonic()
    saved = 0
    try:
        while True:
            num += 1
            path = out / f"page_{num:04d}.png"
            save_png(crop(img, box), path)
            saved += 1
            print(f"\r  {path.name} 저장 ({saved}장, {time.monotonic() - started:.0f}초)", end="", flush=True)
            if args.max_pages and saved >= args.max_pages:
                print(f"\n--max-pages {args.max_pages} 에 도달해 멈춥니다.")
                break

            prev = page_sig(img)
            nxt = None
            for attempt in range(1 + args.end_retries):
                turn()
                got = wait_change(adb, prev, page_sig, args)
                # 넘김 효과 도중에 바뀌었다가 같은 쪽으로 되돌아온 경우는 '안 넘어감'으로 본다
                if got is not None and differs(prev, page_sig(got)):
                    nxt = got
                    break
            if nxt is None:
                print(f"\n넘겨도 화면이 바뀌지 않아 마지막 쪽으로 판단하고 끝냅니다. (총 {saved}장)")
                break
            if looks_blank(nxt):
                print("\n[중단] 화면이 검은색으로 바뀌었습니다 (캡처 차단 또는 뷰어 종료).")
                break
            img = nxt
    except KeyboardInterrupt:
        print(f"\n사용자가 멈췄습니다. (이번에 {saved}장 저장, 다시 실행하면 이어 찍습니다)")
    return 0


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="LD플레이어 전자책 뷰어를 한 쪽씩 넘기며 스크린샷 저장")
    ap.add_argument("-o", "--output", default="ebook_pages", help="저장 폴더 (기본: ebook_pages)")
    ap.add_argument("--test", action="store_true", help="한 장만 찍어 test_screen.png 로 저장하고 끝 (캡처 가능 여부 점검)")
    ap.add_argument("--adb", help="adb.exe 위치 (기본: LD플레이어 설치 폴더에서 자동으로 찾음)")
    ap.add_argument("--serial", help="기기 이름 (예: emulator-5554, 127.0.0.1:5555). 기본: 첫 번째 기기")
    ap.add_argument("--crop", help="저장할 영역 x1,y1,x2,y2 (픽셀). 뷰어 상단바·쪽번호를 잘라낼 때")
    ap.add_argument("--turn", choices=["tap", "key", "swipe"], default="tap",
                    help="넘기는 방법: tap(기본, 화면 오른쪽 끝 누르기) | key(방향키) | swipe(쓸어 넘기기)")
    ap.add_argument("--tap", help="tap 위치 x,y (기본: 화면 오른쪽 끝 가운데)")
    ap.add_argument("--key", type=int, default=KEYCODE_DPAD_RIGHT,
                    help="key 방식의 안드로이드 키코드 (기본 22=오른쪽, 93=PageDown, 62=Space)")
    ap.add_argument("--interval", type=float, default=0.3, help="넘긴 뒤 화면 확인 간격(초, 기본 0.3)")
    ap.add_argument("--settle", type=float, default=0.3, help="넘김 효과가 끝났는지 다시 확인하는 간격(초, 기본 0.3)")
    ap.add_argument("--timeout", type=float, default=4.0, help="넘긴 뒤 화면이 바뀌길 기다리는 최대 시간(초, 기본 4)")
    ap.add_argument("--end-retries", type=int, default=1, help="안 넘어갈 때 다시 넘겨 볼 횟수 (기본 1)")
    ap.add_argument("--max-pages", type=int, default=0, help="이번 실행에서 저장할 최대 쪽수 (기본 0=끝까지)")
    return ap.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        adb = Adb(find_adb(args.adb), args.serial)
        print(f"연결: {adb.connect()}  (adb: {adb.exe})")
        out = Path(args.output)
        if args.test:
            return run_test(adb, out, parse_box(args.crop))
        return run_capture(adb, out, args)
    except (AdbError, subprocess.TimeoutExpired) as e:
        print(f"[오류] {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
