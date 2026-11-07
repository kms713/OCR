#!/usr/bin/env python3
"""
AI 교정 제안 만들기 (Gemini API, 선택 기능)
==========================================

'책이름_교정.md' 의 문단을 나눠 Gemini API 로 보내 맞춤법·오탈자·OCR 오인식 수정안을 받아
'책이름_제안.json' 에 저장합니다. **원문(교정.md)은 건드리지 않습니다.**
제안은 교정 편집기(ebook_review.py) 아래쪽에 원문과 나란히 나타나고, 사용자가 '수락'한 것만 글에 반영됩니다.

준비: API 키를 환경변수 GEMINI_API_KEY 로 지정하거나, 이 폴더에 gemini_key.txt (키 한 줄) 를 둡니다.
      gemini_key.txt 는 git 에 올라가지 않습니다.

사용 예 (Windows 에서는 python 대신 py -3.12)
    python ebook_suggest.py books\\책이름
    python ebook_suggest.py books\\책이름 --model gemini-3.8-flash --rpm 15 --thinking low
    python ebook_suggest.py books\\책이름 --limit 5      # 처음 5덩어리만 (시험용)

동작
    · 문단 경계에서만 약 4000자씩 묶어 보냅니다. 분당 호출 수(--rpm)를 넘기지 않게 간격을 둡니다.
    · 이미 검사한 문단은 다시 보내지 않습니다 (이어 하기). 하루 한도에 걸리면 멈추고 다음에 이어서 합니다.
    · 너무 많이 바뀐 제안(--max-change, 기본 15%)은 버립니다. 숫자·영문이 바뀐 제안은 '주의' 표시를 붙입니다.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_MODEL = "gemini-3.8-flash"
API_BASE = os.environ.get("GEMINI_API_BASE", "https://generativelanguage.googleapis.com/v1beta")
SOFT = "⁠"
PAGE_MARK = re.compile(r"^<!--.*-->$")
FIGURE = re.compile(r"^!\[")

PROMPT = """너는 한국어 책 OCR 결과의 교정자다. 아래 문단들에서 **명백한 오류만** 고친다.
고칠 것: 맞춤법, 오탈자, 띄어쓰기, 비슷하게 생긴 글자를 잘못 읽은 OCR 오류(예: 하엿다→하였다).
절대 하지 말 것: 문장을 다듬거나 바꿔 쓰기, 요약, 내용 추가·삭제, 숫자·연도·고유명사·영문·기호 변경, 문체 통일.
확실하지 않으면 고치지 말고 그대로 둔다.
입력은 `[번호] 문단` 형식이다. 고친 문단만 JSON 배열로 답한다: [{"id":"번호","text":"고친 문단 전체"}].
고칠 것이 없으면 [] 만 답한다. JSON 외의 글은 쓰지 않는다.

"""


def para_id(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]


def read_paragraphs(md: str) -> list[str]:
    """교정 글에서 본문 문단만 뽑는다 (제목·쪽 표시·그림·각주 줄 제외). 같은 문단은 한 번만."""
    out, seen = [], set()
    for raw in md.replace("\r\n", "\n").replace(SOFT, "").split("\n"):
        t = raw.strip()
        if not t or t.startswith("#") or t.startswith(">") or PAGE_MARK.match(t) or FIGURE.match(t):
            continue
        if len(re.findall(r"[가-힣A-Za-z]", t)) < 4 or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def chunk(paras: list[str], max_chars: int) -> list[list[str]]:
    chunks, cur, size = [], [], 0
    for p in paras:
        if cur and size + len(p) > max_chars:
            chunks.append(cur)
            cur, size = [], 0
        cur.append(p)
        size += len(p)
    if cur:
        chunks.append(cur)
    return chunks


def numbers(s: str) -> list[str]:
    return re.findall(r"\d+(?:[.,]\d+)*", s)


def latin(s: str) -> list[str]:
    return re.findall(r"[A-Za-z]+", s)


def check_suggestion(orig: str, sug: str, max_change: float) -> tuple[bool, list[str]]:
    """(채택 여부, 주의 표시). 너무 많이 바뀌면 버리고, 숫자·영문이 바뀌면 주의 표시."""
    sug = sug.replace(SOFT, "").strip()
    if not sug or sug == orig:
        return False, []
    if 1 - difflib.SequenceMatcher(None, orig, sug, autojunk=False).ratio() > max_change:
        return False, []
    flags = []
    if numbers(orig) != numbers(sug):
        flags.append("숫자 변경")
    if latin(orig) != latin(sug):
        flags.append("영문 변경")
    return True, flags


class QuotaDaily(Exception):
    pass


def call_gemini(key: str, model: str, text: str, thinking: str = "") -> list[dict]:
    body = {"contents": [{"role": "user", "parts": [{"text": PROMPT + text}]}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json"}}
    if thinking:  # 사고 수준: 맞춤법 교정에는 낮춰도 충분 (모델이 지원하지 않으면 아래에서 빼고 다시 시도)
        body["generationConfig"]["thinkingConfig"] = {"thinkingLevel": thinking}
    url = f"{API_BASE}/models/{model}:generateContent"
    for attempt in range(5):
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                     headers={"Content-Type": "application/json", "x-goog-api-key": key})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                data = json.loads(r.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            if e.code == 429:
                if re.search(r"PerDay|per day|daily", detail, re.I):
                    raise QuotaDaily(detail[:300])
                wait = 20 * (attempt + 1)
                print(f"\n  호출 한도 초과 — {wait}초 기다립니다")
                time.sleep(wait)
                continue
            if e.code == 400 and "thinkingConfig" in body["generationConfig"] and "think" in detail.lower():
                print("\n  이 모델은 사고 수준 설정을 받지 않아 빼고 다시 보냅니다 (--thinking 없이)")
                del body["generationConfig"]["thinkingConfig"]
                continue
            if e.code in (500, 502, 503, 504):
                time.sleep(5 * (attempt + 1))
                continue
            raise RuntimeError(f"API 오류 {e.code}: {detail[:300]}")
        except (urllib.error.URLError, TimeoutError) as e:
            time.sleep(5 * (attempt + 1))
            if attempt == 4:
                raise RuntimeError(f"연결 실패: {e}")
    else:
        raise RuntimeError("API 호출이 계속 실패했습니다")
    try:
        parts = data["candidates"][0]["content"]["parts"]
        txt = "".join(p.get("text", "") for p in parts).strip()
        txt = re.sub(r"^```(?:json)?\s*|\s*```$", "", txt)
        res = json.loads(txt) if txt else []
    except (KeyError, IndexError, ValueError):
        return []  # 차단·형식 오류는 이 덩어리를 '제안 없음'으로 보지 않고 다시 시도하도록 예외로 올릴 수도 있으나, 일단 건너뜀
    return [x for x in res if isinstance(x, dict) and "id" in x and "text" in x] if isinstance(res, list) else []


def load_key() -> str | None:
    k = os.environ.get("GEMINI_API_KEY", "").strip()
    if k:
        return k
    f = HERE / "gemini_key.txt"
    if f.is_file():
        k = f.read_bytes().decode("utf-8-sig").strip().splitlines()
        return k[0].strip() if k else None
    return None


def load_store(path: Path) -> dict:
    try:
        d = json.loads(path.read_bytes().decode("utf-8"))
        if d.get("version") == 1:
            return d
    except (OSError, ValueError):
        pass
    return {"version": 1, "items": {}, "checked": []}


def save_store(path: Path, store: dict) -> None:
    tmp = path.with_suffix(".json.tmp")
    tmp.write_bytes(json.dumps(store, ensure_ascii=False, indent=1).encode("utf-8"))
    tmp.replace(path)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Gemini 로 맞춤법·OCR 교정 '제안' 만들기 (원문은 그대로)")
    ap.add_argument("folder", help="page_0001.png ... 가 들어 있는 폴더 (결과 폴더는 <폴더>_OCR)")
    ap.add_argument("-o", "--output", help="OCR 결과 폴더")
    ap.add_argument("--title")
    ap.add_argument("--model", default=os.environ.get("GEMINI_MODEL", DEFAULT_MODEL), help=f"모델 이름 (기본 {DEFAULT_MODEL})")
    ap.add_argument("--thinking", default="low", choices=["", "minimal", "low", "medium", "high"],
                    help="사고 수준 (기본 low. 빈 값이면 보내지 않음). 모델이 받지 않으면 자동으로 뺌")
    ap.add_argument("--rpm", type=float, default=15, help="분당 최대 호출 수 (기본 15)")
    ap.add_argument("--chunk-chars", type=int, default=4000, help="한 번에 보낼 글자 수 (기본 4000)")
    ap.add_argument("--max-change", type=float, default=0.15, help="이보다 많이 바뀐 제안은 버림 (기본 0.15)")
    ap.add_argument("--limit", type=int, default=0, help="이번에 보낼 덩어리 수 상한 (0 = 끝까지)")
    ap.add_argument("--redo", action="store_true", help="이미 검사한 문단도 다시 보냄")
    args = ap.parse_args(argv)

    folder = Path(args.folder)
    out_dir = Path(args.output) if args.output else folder.with_name(folder.name + "_OCR")
    title = args.title or folder.name
    src = out_dir / f"{title}_교정.md"
    if not src.is_file():
        print(f"[오류] 교정 파일이 없습니다: {src}\n  먼저 4_교정.bat 로 교정 편집기를 한 번 여세요.")
        return 1
    key = load_key()
    if not key:
        print("[오류] API 키가 없습니다. 환경변수 GEMINI_API_KEY 를 지정하거나 이 폴더에 gemini_key.txt 를 만드세요.")
        return 1

    store_path = out_dir / f"{title}_제안.json"
    store = load_store(store_path)
    done = set(store["checked"]) if not args.redo else set()
    paras = [p for p in read_paragraphs(src.read_bytes().decode("utf-8")) if para_id(p) not in done]
    chunks = chunk(paras, args.chunk_chars)
    if args.limit:
        chunks = chunks[:args.limit]
    if not chunks:
        print("검사할 새 문단이 없습니다.")
        return 0
    print(f"모델 {args.model} · 문단 {len(paras)}개를 {len(chunks)}번에 나눠 보냅니다 (분당 {args.rpm:g}회 이하)")
    gap = 60.0 / max(0.1, args.rpm)
    last = 0.0
    n_sug = n_drop = 0
    for i, ch in enumerate(chunks, start=1):
        wait = gap - (time.monotonic() - last)
        if wait > 0 and last:
            time.sleep(wait)
        last = time.monotonic()
        ids = {para_id(p): p for p in ch}
        text = "\n".join(f"[{k}] {p}" for k, p in ids.items())
        try:
            res = call_gemini(key, args.model, text, args.thinking)
        except QuotaDaily as e:
            save_store(store_path, store)
            print(f"\n[중단] 하루 사용 한도에 도달했습니다. 내일 같은 명령을 다시 실행하면 이어서 합니다.\n  {e}")
            return 2
        except RuntimeError as e:
            save_store(store_path, store)
            print(f"\n[오류] {e}\n  지금까지 결과는 저장했습니다. 다시 실행하면 이어서 합니다.")
            return 1
        for r in res:
            orig = ids.get(str(r["id"]).strip("[] "))
            if orig is None:
                continue
            ok, flags = check_suggestion(orig, str(r["text"]), args.max_change)
            if ok:
                store["items"][para_id(orig)] = {"orig": orig, "sug": str(r["text"]).replace(SOFT, "").strip(),
                                                  "flags": flags, "status": "new"}
                n_sug += 1
            else:
                n_drop += 1
        store["checked"] = sorted(set(store["checked"]) | set(ids))
        save_store(store_path, store)
        print(f"\r  {i}/{len(chunks)} 덩어리 — 제안 {n_sug}개", end="", flush=True)
    print(f"\n완료: 제안 {n_sug}개 (너무 많이 바뀌어 버린 것 {n_drop}개)")
    print(f"  저장: {store_path.resolve()}")
    print("  4_교정.bat 로 교정 편집기를 열면 아래쪽에 제안이 나타납니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
