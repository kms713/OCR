#!/usr/bin/env python3
"""
챕터 설정(책이름_장설정.json)과 책 쪽 번호 계산 — 편집기(ebook_review.py)와 내보내기(ebook_export.py)가 함께 씀
===============================================================================================

도구 안의 쪽 번호는 '캡처 순번'(page_0001.png 의 1, 교정 글의 <!-- p.N -->)입니다. 이 번호는 바꾸지 않습니다.
사람이 책에서 보는 쪽 번호('책 쪽')는 이 파일의 설정으로만 계산해 화면 표시와 내보내기에서 씁니다.

설정 파일 예
    {
      "chapters":   [{"capture": 311, "page": 291, "title": "3장 에이전트 설계", "part": "Part 2. 설계의 기술",
                      "split": "chapter", "exclude": false}],
      "page_fixes": [{"capture": 340, "page": 321}],
      "skip_pages": [312]
    }
  chapters    챕터 시작 쪽. capture = 캡처 쪽 번호, page = 그 쪽의 책 쪽 번호, split = "chapter"(챕터만) | "topic"(### 까지),
              exclude = 이 챕터 전체를 교정·내보내기에서 뺌
  page_fixes  쪽 번호 교정. 그 쪽부터 책 쪽 번호를 새로 시작
  skip_pages  글만 내보내기에서 뺀 쪽 (쪽 번호는 그 쪽이 그대로 차지)

책 쪽 번호 = c 이하에서 가장 가까운 설정(챕터 시작 또는 쪽 번호 교정)의 page + (c - 그 설정의 capture).
앞에 설정이 하나도 없으면 앞부분이며 '앞' + 캡처 번호(예: 앞3)로 표시합니다.
챕터·쪽 번호 교정이 하나도 없는 책(설정 파일이 없거나 skip_pages 뿐)은 캡처 번호를 그대로 책 쪽으로 씁니다.
"""

from __future__ import annotations

import json
from bisect import bisect_right
from pathlib import Path

CONFIG_SUFFIX = "_장설정.json"
SPLIT_CHAPTER = "chapter"
SPLIT_TOPIC = "topic"
_TOPIC_NAMES = {"topic", "subtopic", "section", "h3", "대주제", "대주제까지"}


def config_path(out_dir: Path, title: str) -> Path:
    return out_dir / f"{title}{CONFIG_SUFFIX}"


def empty() -> dict:
    return {"chapters": [], "page_fixes": [], "skip_pages": []}


def _int(v):
    try:
        if isinstance(v, bool):
            return None
        n = int(str(v).strip()) if not isinstance(v, int) else v
        return n
    except (TypeError, ValueError):
        return None


def normalize(data) -> dict:
    """읽은 JSON 을 쓸 수 있는 꼴로 정리 (잘못된 항목은 건너뜀, 같은 캡처 번호는 뒤의 것, 캡처 순으로 정렬)."""
    out = empty()
    if not isinstance(data, dict):
        return out
    chapters: dict[int, dict] = {}
    for c in data.get("chapters") or []:
        if not isinstance(c, dict):
            continue
        cap, page, title = _int(c.get("capture")), _int(c.get("page")), str(c.get("title") or "").strip()
        if cap is None or cap < 1 or page is None or not title:
            continue
        split = SPLIT_TOPIC if str(c.get("split") or "").strip().lower() in _TOPIC_NAMES else SPLIT_CHAPTER
        chapters[cap] = {"capture": cap, "page": page, "title": title, "part": str(c.get("part") or "").strip(),
                         "split": split, "exclude": bool(c.get("exclude"))}
    out["chapters"] = [chapters[k] for k in sorted(chapters)]
    fixes: dict[int, int] = {}
    for f in data.get("page_fixes") or []:
        if not isinstance(f, dict):
            continue
        cap, page = _int(f.get("capture")), _int(f.get("page"))
        if cap is not None and cap >= 1 and page is not None:
            fixes[cap] = page
    out["page_fixes"] = [{"capture": k, "page": fixes[k]} for k in sorted(fixes)]
    out["skip_pages"] = sorted({n for n in (_int(x) for x in data.get("skip_pages") or []) if n is not None and n >= 1})
    return out


def load(path: Path) -> dict:
    try:
        return normalize(json.loads(path.read_bytes().decode("utf-8-sig")))
    except (OSError, ValueError):
        return empty()


def save(path: Path, data: dict) -> dict:
    data = normalize(data)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_bytes((json.dumps(data, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
    tmp.replace(path)
    return data


# ---- 책 쪽 번호 -----------------------------------------------------------------
def has_page_numbers(cfg: dict) -> bool:
    return bool(cfg["chapters"] or cfg["page_fixes"])


def anchors(cfg: dict) -> list[tuple[int, int]]:
    """[(캡처, 책 쪽)] 캡처 순. 같은 캡처에 챕터 시작과 쪽 번호 교정이 함께 있으면 쪽 번호 교정이 우선."""
    d = {c["capture"]: c["page"] for c in cfg["chapters"]}
    d.update({f["capture"]: f["page"] for f in cfg["page_fixes"]})
    return sorted(d.items())


def book_page(c: int, cfg: dict) -> int | None:
    """캡처 쪽 c 의 책 쪽 번호. 앞에 설정이 없으면 None(앞부분)."""
    an = anchors(cfg)
    i = bisect_right([a for a, _ in an], c) - 1
    if i < 0:
        return None
    cap, page = an[i]
    return page + (c - cap)


def page_label(c: int, cfg: dict) -> str:
    """쪽 표시에 쓰는 글: '291', 앞부분은 '앞3'. 쪽 번호 설정이 없는 책은 캡처 번호 그대로."""
    if not has_page_numbers(cfg):
        return str(c)
    n = book_page(c, cfg)
    return f"앞{c}" if n is None else str(n)


def chapter_of(c: int, cfg: dict) -> int | None:
    """캡처 쪽 c 가 속한 챕터 번호(1부터). 첫 챕터 앞이면 None."""
    k = bisect_right([ch["capture"] for ch in cfg["chapters"]], c)
    return k or None


def excluded_pages(cfg: dict, n_pages: int) -> set[int]:
    """교정 진행률·다음 쪽·AI 교정 제안에서 빼는 쪽: 뺀 쪽 + 제외한 챕터의 모든 쪽."""
    out = set(cfg["skip_pages"])
    if n_pages <= 0:
        return out
    chs = cfg["chapters"]
    for i, ch in enumerate(chs):
        if ch["exclude"]:
            end = chs[i + 1]["capture"] - 1 if i + 1 < len(chs) else n_pages
            out.update(range(ch["capture"], end + 1))
    return {n for n in out if 1 <= n <= n_pages}
