#!/usr/bin/env python3
"""
장 설정(책이름_장설정.json)과 책 쪽 번호 계산 — 교정 편집기(ebook_review.py)와 내보내기(ebook_export.py)가 함께 씁니다.
================================================================================================================

도구 안의 쪽 번호(캡처 순번, page_0001.png, <!-- p.N -->, 제외 영역, 확인 표시)는 바꾸지 않습니다.
'책 쪽 번호'(사람이 책에서 보는 쪽 번호)는 이 설정에서 화면 표시와 내보내기 때만 계산합니다.

설정 파일 예
    {
      "chapters":   [{"capture": 311, "page": 291, "title": "3장 에이전트 설계", "split": "chapter", "exclude": false}],
      "page_fixes": [{"capture": 340, "page": 321}],
      "skip_pages": [312]
    }

  chapters    챕터 시작 쪽. capture = 캡처 쪽 번호, page = 그 쪽의 책 쪽 번호,
              split = "chapter"(챕터만) | "topic"(대주제까지 나눔), exclude = 이 챕터 전체를 내보내기·교정에서 뺌
  page_fixes  쪽 번호 교정. 그 캡처 쪽부터 다음 설정이 나올 때까지 이 책 쪽 번호에서 이어집니다
  skip_pages  이 쪽 빼기. 그 쪽의 글만 내보내기에서 빼고, 쪽 번호는 그대로 차지합니다

책 쪽 번호 = (캡처 c 이하에서 가장 가까운 설정의 page) + (c - 그 설정의 capture).
앞에 설정이 하나도 없으면 앞부분이라 '앞' + 캡처 번호(예: 앞3).
"""

from __future__ import annotations

import json
from pathlib import Path

SPLITS = ("chapter", "topic")


def config_path(out_dir: Path, title: str) -> Path:
    return out_dir / f"{title}_장설정.json"


def empty_config() -> dict:
    return {"chapters": [], "page_fixes": [], "skip_pages": []}


def _int(v, what: str) -> int:
    if isinstance(v, bool):
        raise ValueError(f"{what}: 정수가 아닙니다")
    try:
        if isinstance(v, str):
            v = v.strip()
        return int(v)
    except (TypeError, ValueError):
        raise ValueError(f"{what}: 정수가 아닙니다 ({v!r})") from None


def clean_config(d) -> dict:
    """읽어 온(또는 화면이 보낸) 설정을 검사해 정리한다. 잘못되면 ValueError."""
    if not isinstance(d, dict):
        raise ValueError("설정이 올바른 형식이 아닙니다")
    chapters: dict[int, dict] = {}
    for c in d.get("chapters", []) or []:
        cap = _int(c.get("capture"), "챕터 캡처 쪽")
        if cap < 1:
            raise ValueError("캡처 쪽 번호는 1 이상이어야 합니다")
        title = str(c.get("title", "")).strip()
        if not title:
            raise ValueError(f"캡처 {cap}쪽 챕터 제목이 비어 있습니다")
        split = c.get("split", "chapter")
        if split not in SPLITS:
            raise ValueError(f"캡처 {cap}쪽 나누기 값이 잘못됐습니다: {split!r}")
        chapters[cap] = {"capture": cap, "page": _int(c.get("page"), f"캡처 {cap}쪽 책 쪽 번호"),
                         "title": title, "split": split, "exclude": bool(c.get("exclude", False))}
    fixes: dict[int, dict] = {}
    for f in d.get("page_fixes", []) or []:
        cap = _int(f.get("capture"), "쪽 번호 교정 캡처 쪽")
        if cap < 1:
            raise ValueError("캡처 쪽 번호는 1 이상이어야 합니다")
        if cap not in chapters:  # 챕터 시작 쪽의 번호는 챕터 설정이 정한다
            fixes[cap] = {"capture": cap, "page": _int(f.get("page"), f"캡처 {cap}쪽 책 쪽 번호")}
    skips = sorted({_int(x, "뺄 쪽") for x in d.get("skip_pages", []) or []})
    return {"chapters": [chapters[k] for k in sorted(chapters)],
            "page_fixes": [fixes[k] for k in sorted(fixes)], "skip_pages": skips}


def load_config(path: Path) -> dict | None:
    """설정 파일이 없으면 None (예전 책: 지금까지와 같게 동작). 파일이 깨졌으면 ValueError."""
    try:
        raw = path.read_bytes().decode("utf-8-sig")
    except OSError:
        return None
    try:
        return clean_config(json.loads(raw))
    except json.JSONDecodeError as e:
        raise ValueError(f"{path.name} 를 읽을 수 없습니다: {e}") from None


def save_config(path: Path, cfg: dict) -> dict:
    cfg = clean_config(cfg)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_bytes(json.dumps(cfg, ensure_ascii=False, indent=1).encode("utf-8"))
    tmp.replace(path)
    return cfg


class BookPages:
    """캡처 쪽 번호 → 책 쪽 번호."""

    def __init__(self, cfg: dict | None):
        cfg = cfg or empty_config()
        anchors: dict[int, int] = {f["capture"]: f["page"] for f in cfg["page_fixes"]}
        anchors.update({c["capture"]: c["page"] for c in cfg["chapters"]})  # 같은 쪽이면 챕터 설정이 우선
        self.anchors = sorted(anchors.items())

    def number(self, c: int) -> int | None:
        base = None
        for cap, page in self.anchors:
            if cap <= c:
                base = (cap, page)
            else:
                break
        return None if base is None else base[1] + (c - base[0])

    def label(self, c: int) -> str:
        n = self.number(c)
        return f"앞{c}" if n is None else str(n)


IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}  # ebook_ocr.py 와 같게 유지


def count_pages(folder: Path) -> int:
    try:
        return sum(1 for f in folder.iterdir()
                   if f.is_file() and f.suffix.lower() in IMAGE_EXTS and not f.stem.startswith("test_"))
    except OSError:
        return 0
