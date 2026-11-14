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
    python ebook_suggest.py books\\책이름 --model gemini-3.8-flash --thinking low --timeout 300   # 느린 모델
    python ebook_suggest.py books\\책이름 --limit 5      # 처음 5덩어리만 (시험용)
    python ebook_suggest.py --check                     # 연결만 점검 (짧은 글 한 번)
    python ebook_suggest.py --check --no-proxy          # 프록시를 거치지 않고 점검

동작
    · 답은 조각으로 받아(stream) 받는 글자 수를 보여 줍니다. --timeout 은 조각 사이 대기 제한입니다.
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
DEFAULT_MODEL = "gemini-3.5-flash-lite"  # 3.8-flash 는 2026-11-07 시험에서 "hello" 한 마디에 54초·503 혼잡
API_BASE = os.environ.get("GEMINI_API_BASE", "https://generativelanguage.googleapis.com/v1beta")
# OpenAI 형식(chat/completions) 서비스. --service nvidia 는 NVIDIA build, openai 는 --base-url 로 지정 (예: Ollama http://localhost:11434/v1)
MAX_ATTEMPTS = 5  # 한 모델에 다시 보내는 횟수 (자동 모드에서 다음 모델이 있으면 2)
MODELS_FILE = Path(os.environ.get("AI_MODELS_FILE") or Path(__file__).resolve().parent / "ai_models.txt")
SERVICES = {
    "nvidia": {"base": os.environ.get("NVIDIA_API_BASE", "https://integrate.api.nvidia.com/v1"), "key_file": "nvidia_key.txt",
               "key_env": "NVIDIA_API_KEY", "model": "google/gemma-4-31b-it"},  # 2026-11-10 사용자 키 목록에 있는 다국어 모델
    "openai": {"base": os.environ.get("OPENAI_API_BASE", "http://localhost:11434/v1"), "key_file": "openai_key.txt",
               "key_env": "OPENAI_API_KEY", "model": ""},
}
SOFT = "⁠"
PAGE_MARK = re.compile(r"^<!--.*-->$")
FIGURE = re.compile(r"^!\[")

PROMPT = """너는 한국어 책 OCR 결과의 교정자다. 아래 문단들에서 **명백한 오류만** 고친다.
고칠 것: 맞춤법, 오탈자, 띄어쓰기, 비슷하게 생긴 글자를 잘못 읽은 OCR 오류(예: 하엿다→하였다),
OCR 이 빠뜨린 문장 끝 마침표(예: "달렸습니다 하지만" → "달렸습니다. 하지만"),
낱말 가운데가 잘못 띄어진 것(예: "체 그의" → "체그의", "1 주당" → "1주당").
같은 잘못이 문단 안에 여러 번 있으면 모두 고친다.
절대 하지 말 것: 문장을 다듬거나 바꿔 쓰기, 요약, 내용 추가·삭제, 숫자·연도·고유명사·영문 변경,
마침표 외의 기호 추가·변경, 문체 통일.
서식 기호 **, *, <u>, </u>, <br> 는 마크다운 강조·밑줄·줄바꿈 표시다. 오타가 아니니 지우거나 옮기거나 새로 넣지 말고 그대로 둔다.
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
        if not t or t.startswith(("#", ">", "|")) or PAGE_MARK.match(t) or FIGURE.match(t):  # | : 표 줄은 보내지 않음
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
    s = MARKUP.sub(" ", s) if "MARKUP" in globals() else s
    return re.findall(r"\d+(?:[.,]\d+)*", s)


def latin(s: str) -> list[str]:
    s = MARKUP.sub(" ", s) if "MARKUP" in globals() else s  # <u>, <br> 의 글자는 영문으로 세지 않음
    return re.findall(r"[A-Za-z]+", s)


MARKUP = re.compile(r"\*+|</?u>|<br\s*/?>", re.I)  # 서식 기호 (굵게·기울임·밑줄·줄바꿈)
MARKUP_ONLY = re.compile(r"(?:\s*(?:\*+|</?u>|<br\s*/?>)\s*)+", re.I)


def keep_markup(orig: str, sug: str) -> str:
    """제안에서 서식 기호를 지우거나 새로 넣은 곳만 원문대로 되돌린다 (나머지 수정은 살림).
    모델이 강조 표시 ** 를 오타로 보고 지우는 경우가 있어서."""
    if MARKUP.findall(orig) == MARKUP.findall(sug):
        return sug
    out = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, orig, sug, autojunk=False).get_opcodes():
        a, b = orig[i1:i2], sug[j1:j2]
        if tag == "equal":
            out.append(a)
        elif tag == "delete":
            out.append(a if MARKUP.search(a) else "")  # 서식 기호를 지운 곳은 되살림
        elif tag == "insert":
            out.append("" if MARKUP_ONLY.fullmatch(b) else MARKUP.sub("", b))  # 새로 넣은 서식 기호는 뺌
        else:  # replace: 원문 쪽 서식 기호는 남기고 글자만 제안대로
            if MARKUP_ONLY.fullmatch(a):  # 서식 기호만 있던 자리: 기호는 남기고, 빈칸이 아닌 글이 들어왔으면 그 글도
                out.append(a + ("" if not b.strip() else MARKUP.sub("", b)))
            elif MARKUP.search(a):
                lead = re.match(r"^(?:\*+|</?u>|<br\s*/?>)*", a, re.I).group(0)
                rest = a[len(lead):]
                tail = re.search(r"(?:\*+|</?u>|<br\s*/?>)*$", rest, re.I).group(0)
                out.append(lead + MARKUP.sub("", b) + tail)
            else:
                out.append(MARKUP.sub("", b))
    return "".join(out)


def check_suggestion(orig: str, sug: str, max_change: float) -> tuple[bool, list[str], str]:
    """(채택 여부, 주의 표시, 다듬은 제안). 서식 기호는 원문대로 두고, 너무 많이 바뀌면 버리고, 숫자·영문이 바뀌면 주의 표시."""
    sug = keep_markup(orig, sug.replace(SOFT, "").strip())
    if not sug or sug == orig:
        return False, [], sug
    if 1 - difflib.SequenceMatcher(None, orig, sug, autojunk=False).ratio() > max_change:
        return False, [], sug
    flags = []
    if MARKUP.findall(orig) != MARKUP.findall(sug):
        flags.append("서식 변경")
    if numbers(orig) != numbers(sug):
        flags.append("숫자 변경")
    if latin(orig) != latin(sug):
        flags.append("영문 변경")
    return True, flags, sug


class QuotaDaily(Exception):
    pass


class BadReply(Exception):
    """응답은 왔지만 쓸 수 없음 (출력 한도 초과·차단·JSON 형식 오류). 이 덩어리는 '검사함'으로 표시하지 않는다."""


def make_opener(no_proxy: bool):
    # Windows 에서 urllib 은 인터넷 옵션(레지스트리)의 프록시를 자동으로 쓴다. curl.exe 는 쓰지 않는다.
    # 그래서 curl 은 되는데 파이썬만 멈추는 경우 --no-proxy 로 프록시를 거치지 않게 한다.
    if no_proxy:
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener()


def build_body(text: str, thinking: str, max_tokens: int, temperature: float | None) -> dict:
    cfg: dict = {"responseMimeType": "application/json", "maxOutputTokens": max_tokens}
    # Gemini 3 계열은 temperature 를 1.0 아래로 낮추면 같은 말을 되풀이(루프)하다 출력 한도까지 가는 일이 있어
    # 기본은 보내지 않는다 (모델 기본값 사용).
    if temperature is not None:
        cfg["temperature"] = temperature
    if thinking:  # 사고 수준: 맞춤법 교정에는 낮춰도 충분 (모델이 지원하지 않으면 빼고 다시 시도)
        cfg["thinkingConfig"] = {"thinkingLevel": thinking}
    return {"contents": [{"role": "user", "parts": [{"text": text}]}], "generationConfig": cfg}


def stream_once(opener, url: str, key: str, body: dict, timeout: int, show: bool) -> tuple[str, str, dict]:
    """streamGenerateContent(SSE) 로 한 번 호출. (글, 끝난 이유, 사용량). timeout 은 '조각 사이' 대기 제한."""
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json", "x-goog-api-key": key})
    parts, finish, usage = [], "", {}
    t0 = time.monotonic()
    first = None
    with opener.open(req, timeout=timeout) as r:
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            try:
                ev = json.loads(line[5:].strip())
            except ValueError:
                continue
            if "error" in ev:
                raise RuntimeError(f"API 오류: {json.dumps(ev['error'], ensure_ascii=False)[:300]}")
            usage = ev.get("usageMetadata", usage)
            for c in ev.get("candidates", [])[:1]:
                for p in c.get("content", {}).get("parts", []):
                    if p.get("text") and not p.get("thought"):
                        parts.append(p["text"])
                finish = c.get("finishReason", finish)
            if ev.get("promptFeedback", {}).get("blockReason"):
                finish = "BLOCKED:" + ev["promptFeedback"]["blockReason"]
            if parts and first is None:
                first = time.monotonic() - t0
            if show:
                got = sum(len(x) for x in parts)
                print(f"\r    받는 중: {got}자 ({time.monotonic() - t0:.0f}초)" + " " * 40, end="", flush=True)
    usage = dict(usage, _first_sec=first, _total_sec=time.monotonic() - t0)
    return "".join(parts), finish, usage


def call_raw(key: str, model: str, text: str, thinking: str = "", timeout: int = 90, max_tokens: int = 8192,
             temperature: float | None = None, no_proxy: bool = False, show: bool = True) -> tuple[str, str, dict]:
    body = build_body(text, thinking, max_tokens, temperature)
    url = f"{API_BASE}/models/{model}:streamGenerateContent?alt=sse"
    opener = make_opener(no_proxy)
    for attempt in range(MAX_ATTEMPTS):
        t0 = time.monotonic()
        try:
            return stream_once(opener, url, key, body, timeout, show)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            if e.code == 429:
                if re.search(r"PerDay|per day|daily", detail, re.I):
                    raise QuotaDaily(detail[:300])
                if re.search(r"limit: 0\b", detail):
                    raise RuntimeError(f"이 키로는 모델 {model} 을 쓸 수 없습니다 (한도 0). --model 로 다른 모델을 지정하세요.\n  {detail[:300]}")
                wait = 20 * (attempt + 1)
                print(f"\n  호출 한도 초과 — {wait}초 기다립니다")
                time.sleep(wait)
                continue
            if e.code == 400 and "thinkingConfig" in body["generationConfig"] and "think" in detail.lower():
                print("\n  이 모델은 사고 수준 설정을 받지 않아 빼고 다시 보냅니다 (--thinking 없이)")
                del body["generationConfig"]["thinkingConfig"]
                continue
            if e.code == 400 and "responseMimeType" in body["generationConfig"] and re.search(r"json|mime", detail, re.I):
                print("\n  이 모델은 JSON 전용 답 설정을 받지 않아 빼고 다시 보냅니다 (Gemma 등)")
                del body["generationConfig"]["responseMimeType"]
                continue
            if e.code in (500, 502, 503, 504):
                wait = 10 * (attempt + 1)
                print(f"\n  서버 혼잡·일시 오류 ({e.code}) — {wait}초 뒤 다시 시도합니다 ({attempt + 1}/{MAX_ATTEMPTS})", flush=True)
                if attempt == MAX_ATTEMPTS - 1:
                    raise RuntimeError(f"서버가 계속 바쁩니다 ({e.code}). 잠시 뒤 다시 하거나 --model 로 다른 모델을 쓰세요.")
                time.sleep(wait)
                continue
            raise RuntimeError(f"API 오류 {e.code}: {detail[:300]}")
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            why = getattr(e, "reason", e)
            print(f"\n  응답 실패 ({time.monotonic() - t0:.0f}초 후): {why} — 다시 시도합니다 ({attempt + 1}/{MAX_ATTEMPTS})", flush=True)
            if attempt == MAX_ATTEMPTS - 1:
                hint = "" if no_proxy else "\n  curl 은 되는데 이렇게 멈추면 --no-proxy 를 붙여 보세요. 먼저 --check 로 점검할 수 있습니다."
                raise RuntimeError(f"연결 실패: {why}{hint}")
            time.sleep(5 * (attempt + 1))
    raise RuntimeError("API 호출이 계속 실패했습니다")


def call_raw_oai(base: str, key: str, model: str, text: str, timeout: int = 90, max_tokens: int = 8192,
                 temperature: float | None = None, no_proxy: bool = False, show: bool = True) -> tuple[str, str, dict]:
    """OpenAI 형식 chat/completions (stream). 끝난 이유는 Gemini 와 같은 이름으로 바꿔 돌려준다 (length → MAX_TOKENS)."""
    body = {"model": model, "messages": [{"role": "user", "content": text}], "max_tokens": max_tokens, "stream": True,
            "temperature": 0.2 if temperature is None else temperature}  # 교정은 낮은 온도가 안전 (Gemini 3 와 달리 루프 문제 없음)
    url = base.rstrip("/") + "/chat/completions"
    opener = make_opener(no_proxy)
    for attempt in range(MAX_ATTEMPTS):
        t0 = time.monotonic()
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                     headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}",
                                              "Accept": "text/event-stream"})
        try:
            parts, finish, usage, first = [], "", {}, None
            with opener.open(req, timeout=timeout) as r:
                for raw in r:
                    line = raw.decode("utf-8", "replace").strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        ev = json.loads(data)
                    except ValueError:
                        continue
                    if "error" in ev:
                        raise RuntimeError(f"API 오류: {json.dumps(ev['error'], ensure_ascii=False)[:300]}")
                    usage = ev.get("usage") or usage
                    for c in ev.get("choices", [])[:1]:
                        t = (c.get("delta") or {}).get("content") or ""
                        if t:
                            parts.append(t)
                            if first is None:
                                first = time.monotonic() - t0
                        finish = c.get("finish_reason") or finish
                    if show:
                        print(f"\r    받는 중: {sum(len(x) for x in parts)}자 ({time.monotonic() - t0:.0f}초)" + " " * 40, end="", flush=True)
            finish = {"length": "MAX_TOKENS", "content_filter": "SAFETY", "stop": "STOP"}.get(finish, finish.upper())
            return "".join(parts), finish, dict(promptTokenCount=usage.get("prompt_tokens", "?"),
                                                candidatesTokenCount=usage.get("completion_tokens", "?"),
                                                _first_sec=first, _total_sec=time.monotonic() - t0)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            if e.code in (401, 403):
                raise RuntimeError(f"키가 맞지 않거나 이 모델을 쓸 권한이 없습니다 ({e.code}): {detail[:300]}")
            if e.code in (404, 410):  # 410: 서비스가 끝난 모델
                why = "서비스가 끝났습니다" if e.code == 410 else "을 찾지 못했습니다"
                raise RuntimeError(f"모델 '{model}' {why}. --list-models 로 쓸 수 있는 이름을 확인하고 --model 로 지정하세요.\n  {detail[:200]}")
            if e.code == 429:
                if re.search(r"per day|daily|quota|credit", detail, re.I):
                    raise QuotaDaily(detail[:300])
                wait = 20 * (attempt + 1)
                print(f"\n  호출 한도 초과 — {wait}초 기다립니다")
                time.sleep(wait)
                continue
            if e.code in (500, 502, 503, 504):
                wait = 10 * (attempt + 1)
                print(f"\n  서버 혼잡·일시 오류 ({e.code}) — {wait}초 뒤 다시 시도합니다 ({attempt + 1}/{MAX_ATTEMPTS})", flush=True)
                if attempt == MAX_ATTEMPTS - 1:
                    raise RuntimeError(f"서버가 계속 바쁩니다 ({e.code}). 잠시 뒤 다시 하거나 --model 로 다른 모델을 쓰세요.")
                time.sleep(wait)
                continue
            raise RuntimeError(f"API 오류 {e.code}: {detail[:300]}")
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            why = getattr(e, "reason", e)
            print(f"\n  응답 실패 ({time.monotonic() - t0:.0f}초 후): {why} — 다시 시도합니다 ({attempt + 1}/{MAX_ATTEMPTS})", flush=True)
            if attempt == MAX_ATTEMPTS - 1:
                raise RuntimeError(f"연결 실패: {why}")
            time.sleep(5 * (attempt + 1))
    raise RuntimeError("API 호출이 계속 실패했습니다")


def ask_model(args, key: str, text: str, max_tokens: int, timeout: int, show: bool = True) -> tuple[str, str, dict]:
    if args.service == "gemini":
        return call_raw(key, args.model, text, args.thinking, timeout, max_tokens, args.temperature, args.no_proxy, show)
    return call_raw_oai(args.base_url, key, args.model, text, timeout, max_tokens, args.temperature, args.no_proxy, show)


def call_gemini(key: str, model: str, text: str, thinking: str = "", timeout: int = 90, max_tokens: int = 8192,
                temperature: float | None = None, no_proxy: bool = False, args=None) -> list[dict]:
    if args is not None:
        txt, finish, _ = ask_model(args, key, PROMPT + text, max_tokens, timeout)
    else:
        txt, finish, _ = call_raw(key, model, PROMPT + text, thinking, timeout, max_tokens, temperature, no_proxy)
    txt = re.sub(r"<think>.*?</think>", "", txt, flags=re.S)  # 생각 과정을 글로 내놓는 모델 (DeepSeek-R1 등)
    if finish == "MAX_TOKENS":
        raise BadReply("답이 출력 한도에서 잘렸습니다 (같은 말 되풀이 가능성). --chunk-chars 를 줄이거나 --max-tokens 를 늘리세요.")
    if finish.startswith("BLOCKED") or finish in ("SAFETY", "RECITATION", "PROHIBITED_CONTENT", "OTHER"):
        raise BadReply(f"모델이 답을 거부했습니다 ({finish})")
    txt = re.sub(r"^```(?:json)?\s*|\s*```$", "", txt.strip())
    res = parse_reply(txt)
    if res is None:
        raise BadReply(f"답이 JSON 형식이 아닙니다: {txt[:120]!r}")
    return res


def parse_reply(txt: str) -> list[dict] | None:
    """답에서 [{"id":..,"text":..}, ...] 배열을 찾는다. 앞에 군더더기가 붙은 답도 살린다. 못 찾으면 None."""
    if not txt:
        return []
    dec = json.JSONDecoder()
    for m in re.finditer(r"\[", txt):
        try:
            res, _ = dec.raw_decode(txt, m.start())
        except ValueError:
            continue
        if isinstance(res, list) and (not res or all(isinstance(x, dict) for x in res)):
            if res and not any("id" in x and "text" in x for x in res):
                continue
            return [x for x in res if "id" in x and "text" in x]
    return None


def run_check(key: str, args) -> int:
    """연결 점검: 프록시 설정을 보여 주고, 짧은 글로 실제 호출을 해 본다."""
    px = {k: v for k, v in urllib.request.getproxies().items() if k in ("http", "https")}
    print("[점검] 파이썬이 쓰는 프록시:", px or "없음",
          "(--no-proxy 사용)" if args.no_proxy else "")
    base = API_BASE if args.service == "gemini" else args.base_url
    print(f"[점검] 서비스 {args.service}  주소 {base}  모델 {args.model}" + (f"  사고 수준 {args.thinking or '보내지 않음'}" if args.service == "gemini" else ""))
    try:
        txt, finish, u = ask_model(args, key, 'JSON 으로만 답하라: {"ok": true}', 256, min(args.timeout, 60))
    except (RuntimeError, QuotaDaily) as e:
        print(f"\n[점검 실패] {e}")
        return 1
    first = u.get("_first_sec")
    print(f"\n[점검 성공] 첫 글자까지 {first:.1f}초, 전체 {u['_total_sec']:.1f}초, 끝난 이유 {finish or '?'}"
          if first is not None else f"\n[점검] 글 없이 끝남 ({u['_total_sec']:.1f}초, 끝난 이유 {finish or '?'})")
    print(f"  답: {txt.strip()[:100]!r}")
    print(f"  토큰: 입력 {u.get('promptTokenCount', '?')}, 출력 {u.get('candidatesTokenCount', '?')}, 사고 {u.get('thoughtsTokenCount', 0)}")
    return 0 if txt.strip() else 1


def list_models(args, key: str) -> int:
    """이 키로 쓸 수 있는 모델 이름 목록 (--model 에 넣을 이름)."""
    if args.service == "gemini":
        url, hdr = f"{API_BASE}/models?pageSize=1000", {"x-goog-api-key": key}
    else:
        url, hdr = args.base_url.rstrip("/") + "/models", {"Authorization": f"Bearer {key}"}
    try:
        with make_opener(args.no_proxy).open(urllib.request.Request(url, headers=hdr), timeout=60) as r:
            d = json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as e:
        print(f"[오류] 모델 목록을 받지 못했습니다: {getattr(e, 'reason', e)}")
        return 1
    if args.service == "gemini":
        names = [m["name"].split("/", 1)[-1] for m in d.get("models", []) if "generateContent" in m.get("supportedGenerationMethods", [])]
    else:
        names = [m.get("id", "") for m in d.get("data", [])]
    flt = (args.model_filter or "").lower()
    names = sorted(n for n in names if n and flt in n.lower())
    print(f"{args.service} 모델 {len(names)}개" + (f" ('{flt}' 포함)" if flt else "") + ":")
    for n in names:
        print("  " + n)
    return 0


def load_key(service: str = "gemini") -> str | None:
    if service != "gemini":
        cfg = SERVICES[service]
        k = os.environ.get(cfg["key_env"], "").strip()
        f = HERE / cfg["key_file"]
        if not k and f.is_file():
            lines = f.read_bytes().decode("utf-8-sig").strip().splitlines()
            k = lines[0].strip() if lines else ""
        return k or ("none" if service == "openai" else None)  # Ollama 등 내 PC 서비스는 키가 없어도 됨
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


def load_model_list() -> list[dict]:
    """ai_models.txt → [{service, model, note}]."""
    out = []
    try:
        lines = MODELS_FILE.read_bytes().decode("utf-8-sig").splitlines()
    except OSError:
        lines = ["nvidia google/gemma-4-31b-it", f"gemini {DEFAULT_MODEL}"]
    for line in lines:
        t = line.strip()
        if not t or t.startswith("#"):
            continue
        parts = t.split(None, 2)
        if len(parts) >= 2 and parts[0] in ("nvidia", "gemini", "openai"):
            out.append({"service": parts[0], "model": parts[1], "note": parts[2] if len(parts) > 2 else ""})
    return out


def use_model(args, m: dict, rpm_user: float | None) -> None:
    """args 를 이 모델로 바꾼다 (서비스·주소·분당 호출 수)."""
    args.service, args.model = m["service"], m["model"]
    if args.service != "gemini":
        args.base_url = args.base_url_user or SERVICES[args.service]["base"]
    args.rpm = rpm_user or {"gemini": 15, "nvidia": 30}.get(args.service, 60)


def pick_menu(models: list[dict]) -> str:
    print("AI 교정 제안 — 쓸 모델을 고르세요 (ai_models.txt 에서 바꿀 수 있음)")
    for i, m in enumerate(models, start=1):
        ok = "" if load_key(m["service"]) else "  [키 없음]"
        print(f"  {i}. {m['model']:<38} {m['note']}{ok}")
    print("  A. 자동 — 위에서부터 쓰다가 막히면 다음 모델로 (기본)")
    print("  C. 모든 모델 점검 — 지금 되는 모델·막힌 모델 확인")
    try:
        return input("번호 또는 A / C (그냥 Enter = A): ").strip().upper() or "A"
    except EOFError:
        return "A"


def check_all(args, models: list[dict], rpm_user) -> int:
    global MAX_ATTEMPTS
    MAX_ATTEMPTS = 1
    print("모든 모델 점검 (모델마다 짧은 글 한 번, 최대 40초):")
    for m in models:
        key = load_key(m["service"])
        if not key:
            print(f"  ✗ {m['model']:<38} 키 없음")
            continue
        use_model(args, m, rpm_user)
        try:
            txt, finish, u = ask_model(args, key, 'JSON 으로만 답하라: {"ok": true}', 256, 40, show=False)
            sec = u.get("_total_sec", 0)
            print(f"  {'✓' if txt.strip() else '?'} {m['model']:<38} {sec:.1f}초" + ("" if txt.strip() else " (빈 답)"))
        except (RuntimeError, QuotaDaily) as e:
            print(f"  ✗ {m['model']:<38} {str(e).splitlines()[0][:90]}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Gemini 로 맞춤법·OCR 교정 '제안' 만들기 (원문은 그대로)")
    ap.add_argument("folder", nargs="?", help="page_0001.png ... 가 들어 있는 폴더 (결과 폴더는 <폴더>_OCR)")
    ap.add_argument("-o", "--output", help="OCR 결과 폴더")
    ap.add_argument("--title")
    ap.add_argument("--menu", action="store_true", help="ai_models.txt 의 모델 목록에서 골라 쓰기 (6_AI교정제안.bat)")
    ap.add_argument("--auto", action="store_true", help="ai_models.txt 의 모델을 위에서부터 쓰다가 막히면 다음 모델로")
    ap.add_argument("--check-all", action="store_true", help="ai_models.txt 의 모든 모델을 짧게 불러 되는지 확인")
    ap.add_argument("--service", default="gemini", choices=["gemini", "nvidia", "openai"],
                    help="AI 서비스: gemini(기본) / nvidia (NVIDIA build, 키는 nvidia_key.txt) / openai (OpenAI 형식, --base-url)")
    ap.add_argument("--base-url", help="openai 서비스 주소 (예: Ollama http://localhost:11434/v1)")
    ap.add_argument("--model", default=None, help=f"모델 이름 (gemini 기본 {DEFAULT_MODEL}, nvidia 기본 {SERVICES['nvidia']['model']})")
    ap.add_argument("--list-models", nargs="?", const="", default=None, metavar="찾을말", dest="model_filter",
                    help="이 키로 쓸 수 있는 모델 목록만 보여 줌 (예: --list-models qwen)")
    ap.add_argument("--thinking", default="none", choices=["", "none", "minimal", "low", "medium", "high"],
                    help="사고 수준 (기본 none = 보내지 않음). 모델이 받지 않으면 자동으로 뺌")
    ap.add_argument("--timeout", type=int, default=90, help="응답 조각 사이 대기 제한(초, 기본 90)")
    ap.add_argument("--max-tokens", type=int, default=0, help="한 번 답의 최대 토큰 (0 = 보낸 글자 수에 맞춰 자동)")
    ap.add_argument("--temperature", type=float, default=None, help="온도 (기본: 보내지 않음 = 모델 기본값)")
    ap.add_argument("--no-proxy", action="store_true", help="Windows 인터넷 옵션의 프록시를 거치지 않음")
    ap.add_argument("--check", action="store_true", help="연결만 점검 (짧은 글 한 번 호출)")
    ap.add_argument("--rpm", type=float, default=None, help="분당 최대 호출 수 (기본: gemini 15, nvidia 30 — NVIDIA 무료 한도 분당 40 아래로)")
    ap.add_argument("--chunk-chars", type=int, default=4000, help="한 번에 보낼 글자 수 (기본 4000)")
    ap.add_argument("--max-change", type=float, default=0.15, help="이보다 많이 바뀐 제안은 버림 (기본 0.15)")
    ap.add_argument("--limit", type=int, default=0, help="이번에 보낼 덩어리 수 상한 (0 = 끝까지)")
    ap.add_argument("--redo", action="store_true",
                    help="이미 검사한 문단도 다시 보냄. 중간에 멈췄다면 같은 명령(같은 모델)으로 다시 실행하면 이어서 함")
    args = ap.parse_args(argv)
    if args.thinking == "none":  # PowerShell 은 빈 "" 를 넘기지 않으므로 none 으로도 받는다
        args.thinking = ""
    rpm_user = args.rpm
    args.base_url_user = args.base_url
    models = load_model_list()
    chain: list[dict] = []
    if args.menu:
        c = pick_menu(models)
        if c == "C":
            args.check_all = True
        elif c == "A":
            args.auto = True
        elif c.isdigit() and 1 <= int(c) <= len(models):
            chain = [models[int(c) - 1]]
        else:
            print("잘못 고르셨습니다.")
            return 1
    if args.check_all:
        return check_all(args, models, rpm_user)
    if args.auto:
        chain = [m for m in models if load_key(m["service"])]
        if not chain:
            print("[오류] 키가 있는 모델이 없습니다. nvidia_key.txt 또는 gemini_key.txt 를 만드세요.")
            return 1
    if chain:
        use_model(args, chain[0], rpm_user)
    if args.rpm is None:
        args.rpm = {"gemini": 15, "nvidia": 30}.get(args.service, 60)
    if args.service == "gemini":
        args.model = args.model or os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)
    else:
        args.base_url = args.base_url or SERVICES[args.service]["base"]
        args.model = args.model or SERVICES[args.service]["model"]
        if not args.model and args.model_filter is None:
            ap.error("--model 로 모델 이름을 지정하세요 (목록: --list-models)")

    if not args.folder and not args.check and args.model_filter is None and not args.check_all:
        ap.error("책 폴더를 지정하세요 (연결 점검만 할 때는 --check, 모델 목록은 --list-models)")
    from bookdir import resolve, result_dir
    folder = resolve(args.folder or "books/_")
    out_dir = result_dir(folder, args.output, args.title)
    title = args.title or folder.name
    src = out_dir / f"{title}_교정.md"
    key = load_key(args.service)
    if not key:
        kf = "gemini_key.txt" if args.service == "gemini" else SERVICES[args.service]["key_file"]
        print(f"[오류] API 키가 없습니다. 이 폴더({HERE})에 {kf} (키 한 줄)를 만드세요.")
        return 1
    if args.model_filter is not None:
        return list_models(args, key)
    if args.check:
        return run_check(key, args)
    if not src.is_file():
        print(f"[오류] 교정 파일이 없습니다: {src}\n  먼저 4_교정.bat 로 교정 편집기를 한 번 여세요.")
        return 1

    store_path = out_dir / f"{title}_제안.json"
    store = load_store(store_path)
    label = "자동" if len(chain) > 1 else args.model
    if args.redo:  # 다시 검사: 같은 모델(자동이면 '자동')로 하던 다시 검사가 멈춰 있으면 거기서 이어서
        redo = store.get("redo")
        if redo and redo.get("model") == label and redo.get("done"):
            print(f"멈췄던 다시 검사({label})를 이어서 합니다 — 이미 끝낸 문단 {len(redo['done'])}개는 건너뜁니다")
        else:
            redo = store["redo"] = {"model": label, "done": []}
        done = set(redo["done"])
    else:
        done = set(store["checked"])
    paras = [p for p in read_paragraphs(src.read_bytes().decode("utf-8")) if para_id(p) not in done]
    chunks = chunk(paras, args.chunk_chars)
    n_all = len(chunks)
    if args.limit:
        chunks = chunks[:args.limit]
    if not chunks:
        if args.redo:
            store.pop("redo", None)
            save_store(store_path, store)
        print("검사할 새 문단이 없습니다.")
        return 0
    global MAX_ATTEMPTS
    ci = 0  # 자동 모드: 지금 쓰는 모델 번호
    dead: set[int] = set()  # 이번 실행에서 다시 쓰지 않을 모델 (하루 한도·서비스 종료·권한 없음)
    rest_until: dict[int, int] = {}  # 잠깐 막힌 모델 → 이 덩어리 번호부터 다시 써 봄

    def pick(i_chunk: int) -> int:  # 지금 쓸 모델: 위에서부터, 완전히 막혔거나 쉬는 중인 것은 건너뜀
        for k in range(len(chain)):
            if k not in dead and rest_until.get(k, 0) <= i_chunk:
                return k
        return -1
    if len(chain) > 1:
        MAX_ATTEMPTS = 2  # 막히면 오래 붙잡지 말고 다음 모델로
        print("자동: " + " → ".join(m["model"] for m in chain))
    print(f"{args.service} · 모델 {args.model} · 문단 {len(paras)}개를 {len(chunks)}번에 나눠 보냅니다 (분당 {args.rpm:g}회 이하)")
    gap = 60.0 / max(0.1, args.rpm)
    last = 0.0
    n_sug = n_drop = n_bad = 0
    # 한글은 대략 1자 ≈ 1토큰. 고친 문단 전체를 돌려받으므로 보낸 양의 2배 + 사고 여유분.
    max_tokens = args.max_tokens or max(4096, args.chunk_chars * 2 + 2048)
    for i, ch in enumerate(chunks, start=1):
        wait = gap - (time.monotonic() - last)
        if wait > 0 and last:
            time.sleep(wait)
        last = time.monotonic()
        ids = {para_id(p): p for p in ch}
        text = "\n".join(f"[{k}] {p}" for k, p in ids.items())
        print(f"\r  {i}/{len(chunks)} 덩어리 보내는 중... (응답이 올 때까지 최대 {args.timeout}초)", end="", flush=True)
        t_call = time.monotonic()
        if len(chain) > 1:  # 자동: 쉬던 앞 모델이 다시 쓸 수 있게 됐으면 돌아감
            k = pick(i)
            if k >= 0 and k != ci:
                ci = k
                use_model(args, chain[ci], rpm_user)
                if args.service == "gemini":
                    args.thinking = ""
                key = load_key(args.service)
                gap = 60.0 / max(0.1, args.rpm)
                print(f"\n  → {chain[ci]['model']} 로 돌아갑니다", flush=True)
        try:
            while True:
                try:
                    try:
                        res = call_gemini(key, args.model, text, args.thinking, args.timeout, max_tokens,
                                          args.temperature, args.no_proxy, args)
                    except BadReply as e:  # 작은 모델은 가끔 형식이 깨진 답을 보냄 → 한 번 더
                        print(f"\n  {i}번째 덩어리 답을 못 써서 한 번 더 보냅니다 ({str(e)[:60]})", flush=True)
                        time.sleep(gap)
                        last = time.monotonic()
                        res = call_gemini(key, args.model, text, args.thinking, args.timeout, max_tokens,
                                          args.temperature, args.no_proxy, args)
                    break
                except (RuntimeError, QuotaDaily) as e:
                    if len(chain) <= 1:
                        raise
                    msg = str(e)
                    hard = isinstance(e, QuotaDaily) or re.search(r"서비스가 끝났|찾지 못했|키가 맞지|권한|한도 0|API 오류 4", msg)
                    if hard:
                        dead.add(ci)
                    else:
                        rest_until[ci] = i + 5  # 잠깐 막힘: 5덩어리 쉬었다가 다시
                    k = pick(i)
                    if k < 0:
                        raise
                    why = "이번 실행에서 다시 쓰지 않음" if hard else "5덩어리 뒤 다시 써 봄"
                    print(f"\n  [{args.model}] 막힘 ({why}): {msg.splitlines()[0][:80]}\n  → {chain[k]['model']} 로 같은 덩어리를 다시 보냅니다", flush=True)
                    ci = k
                    use_model(args, chain[ci], rpm_user)
                    if args.service == "gemini":
                        args.thinking = ""
                    key = load_key(args.service)
                    gap = 60.0 / max(0.1, args.rpm)
        except BadReply as e:
            print(f"\n  [건너뜀] {i}번째 덩어리: {e}  (검사 안 한 것으로 남겨 다음에 다시 보냅니다)")
            n_bad += 1
            continue
        except QuotaDaily as e:
            save_store(store_path, store)
            print(f"\n[중단] 사용 한도에 도달했습니다. 나중에 다시 실행하면 이어서 합니다.\n"
                  f"  기다리기 싫으면 6_AI교정제안.bat 에서 다른 모델이나 '자동'을 고르세요 (검사한 문단은 건너뜀).\n  {e}")
            return 2
        except RuntimeError as e:
            save_store(store_path, store)
            print(f"\n[오류] {e}\n  지금까지 결과는 저장했습니다. 다시 실행하면 이어서 합니다."
                  + ("" if len(chain) > 1 else " 6_AI교정제안.bat 에서 다른 모델이나 '자동'을 골라도 됩니다."))
            return 1
        for r in res:
            orig = ids.get(str(r["id"]).strip("[] "))
            if orig is None:
                continue
            ok, flags, sug = check_suggestion(orig, str(r["text"]), args.max_change)
            if ok:
                store["items"][para_id(orig)] = {"orig": orig, "sug": sug,
                                                  "flags": flags, "status": "new"}
                n_sug += 1
            else:
                n_drop += 1
        store["checked"] = sorted(set(store["checked"]) | set(ids))
        if args.redo:
            store["redo"]["done"] = sorted(set(store["redo"]["done"]) | set(ids))
        save_store(store_path, store)
        print(f"\r  {i}/{len(chunks)} 덩어리 완료 ({time.monotonic() - t_call:.0f}초) — 제안 {n_sug}개          ", flush=True)
    if args.redo and n_bad == 0 and len(chunks) == n_all:
        store.pop("redo", None)  # 다시 검사를 끝까지 함 → 다음 --redo 는 처음부터
    elif args.redo:
        print("\n  다시 검사가 아직 남았습니다. 같은 명령(--redo 포함)을 다시 실행하면 이어서 합니다.")
    save_store(store_path, store)
    print(f"\n완료: 제안 {n_sug}개 (너무 많이 바뀌어 버린 것 {n_drop}개)"
          + (f", 답을 못 쓴 덩어리 {n_bad}개 (다시 실행하면 재시도)" if n_bad else ""))
    print(f"  저장: {store_path.resolve()}")
    print("  4_교정.bat 로 교정 편집기를 열면 아래쪽에 제안이 나타납니다.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n[멈춤] Ctrl+C 로 멈췄습니다. 다시 실행하면 검사하지 않은 문단부터 이어서 합니다.")
        sys.exit(130)
