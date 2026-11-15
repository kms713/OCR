#!/usr/bin/env python3
"""
교정한 전자책 글 내보내기 — 결과물 2종
=====================================

ebook_review.py 로 고친 '책이름_교정.md' 하나에서 두 파일을 만듭니다.

    책이름_완성본.docx   사람이 보는 문서. 그림이 글 사이에 이미지로 들어갑니다. (Word·한글·구글 문서에서 열기)
    책이름_AI용.md       AI 지식(NotebookLM·Claude 프로젝트 등)에 넣는 글. 이미지는 없습니다.
                         그림이 있던 자리는 사용자가 쓴 설명 글('> [그림] 설명')로 바뀝니다.

Markdown 은 그림을 '파일 링크'로만 가리킬 뿐 그림을 품지 못하고, AI 지식 도구는 이 링크를 읽지 못하거나
잡음으로 취급합니다. 그래서 AI용에는 링크를 넣지 않고 설명 글로 대신합니다.

사용 예 (Windows 에서는 python 대신 py -3.12)
    python ebook_export.py books\\책이름                 # 두 파일 모두
    python ebook_export.py books\\책이름 --only ai       # AI용 글만
    python ebook_export.py books\\책이름 --only docx     # 완성본 Word 만
    python ebook_export.py books\\책이름 --no-page-marks # AI용에서 '[p.12]' 쪽 표시를 뺌 (기본은 넣음: 인용 검사용 출처 표시)
    python ebook_export.py books\\책이름 --no-caption    # Word 에 그림 설명 캡션을 넣지 않음

그림 줄은 교정 글 안의  ![설명](figures/p0012_01.png)  한 줄입니다. 설명이 비어 있는 그림은 끝에 알려 줍니다.

제목 단계: 책 제목·파트·챕터·쪽은 제목 표시가 아니라 파일 머리 정보(--- 블록)로 들어갑니다.
교정 글의 제목은 챕터 안의 구조만 '#'(챕터 바로 아래, 1.1)부터 '######'까지 쓰고, 단계를 바꾸지 않고 그대로 내보냅니다.
(옛 교정 파일 첫 줄의 '# 책제목' 은 책 제목으로 보고 건너뜁니다.) Word: # → 제목 1 … ##### ·###### → 제목 5.

파일 머리 (나눈 파일마다, 제목 표시 # 없이)
    ---
    책: 책이름
    파트: Part 1. 도구의 이해        (파트가 있을 때만)
    챕터: 1장. ...                  (앞부분 파일은 '앞부분')
    대주제: 1.1 ...                 (대주제로 나눈 파일만)
    쪽: p.8–p.15                    (인쇄 쪽 번호 없음이면 끝에 '(캡처 번호)')
    ---

챕터 설정(편집기의 [챕터 시작] 등, 책이름_장설정.json)이 있으면
    · 쪽 표시와 머리의 쪽 범위는 '책 쪽 번호'로 씁니다 (표시 [p.291], 앞부분 [p.앞3])
    · AI용 나눔은 챕터 단위로 나눕니다: 책이름.앞부분.md, 책이름.챕터01.md, (대주제까지 나눈 챕터는 '#' 줄마다) 책이름.챕터03.대주제01.md
    · 제외한 챕터는 파일을 만들지 않고, 뺀 쪽의 글은 쓰지 않습니다 (번호는 그 쪽이 차지)
    · 목차 창에서 입력한 목차 쪽은 OCR 글 대신 '**목차**' + 들여쓴 목록으로 씁니다
설정이 없으면 예전처럼 제목(--split-level)으로 나누고 쪽 번호는 캡처 번호를 그대로 씁니다.
"""

from __future__ import annotations

import argparse
import re
import sys
from bisect import bisect_right
from dataclasses import dataclass, field
from pathlib import Path

import ebook_chapters as chap

PAGE_MARK = re.compile(r"^<!--\s*p\.(\d+)(\s*이어짐)?\s*-->\s*$")  # 이어짐: 앞 쪽 마지막 문단과 이어 붙임
FIGURE = re.compile(r"^!\[([^\]]*)\]\(([^)\s]+)\)\s*$")
HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")  # # ~ ###### 챕터 안의 제목 단계 (# = 챕터 바로 아래)
# 글 속 서식 (겹쳐도 됨, 순서 상관없음): ***굵게+기울임***, **굵게**, *기울임*, <u>밑줄</u>
# 기울임 *…* 은 앞뒤가 영문·숫자면 제외 (2*3*4 같은 곱셈). 한글 조사가 바로 붙어도(*집단 지성*의) 인식
FMT_PATTERNS = [  # (정규식, 붙는 서식). 같은 자리에서 시작하면 앞의 것(긴 표시)이 우선
    (re.compile(r"\*\*\*(?!\s)(.+?)(?<!\s)\*\*\*"), "bi"),
    (re.compile(r"\*\*(?!\s)(.+?)(?<!\s)\*\*"), "b"),
    (re.compile(r"<u>(.+?)</u>"), "u"),
    (re.compile(r"(?<![*A-Za-z0-9])\*(?![\s*])(.+?)(?<![\s*])\*(?![*A-Za-z0-9])"), "i"),
]


def inline_runs(text: str, fmt: str = "") -> list[tuple[str, str]]:
    """'가 **나** <u>*다*</u>' → [('가 ', ''), ('나', 'b'), (' ', ''), ('다', 'ui')]. 서식은 겹쳐서 쌓인다."""
    out: list[tuple[str, str]] = []
    k = 0
    while k < len(text):
        best = None
        for rx, f in FMT_PATTERNS:
            m = rx.search(text, k)
            if m and (best is None or m.start() < best[0].start()):
                best = (m, f)
        if best is None:
            break
        m, f = best
        if m.start() > k:
            out.append((text[k:m.start()], fmt))
        out += inline_runs(m.group(1), "".join(sorted(set(fmt + f))))
        k = m.end()
    if k < len(text):
        out.append((text[k:], fmt))
    return out


def ai_inline(text: str) -> str:
    """AI용 글: 굵게·기울임은 마크다운 그대로, 밑줄 태그는 지운다."""
    return re.sub(r"</?u>", "", text)


def add_inline(p, text: str, size=None, color=None, italic=None):
    """Word 문단에 서식 있는 글 넣기. <br> 은 문단 안 줄바꿈."""
    parts = re.split(r"<br\s*/?>", text, flags=re.I)
    if len(parts) > 1:
        for k, part in enumerate(parts):
            if k:
                p.add_run().add_break()
            add_inline(p, part.strip(), size, color, italic)
        return p
    for t, f in inline_runs(text):
        r = p.add_run(t)
        r.bold = True if "b" in f else None
        r.italic = True if "i" in f else italic
        r.underline = True if "u" in f else None
        if size:
            r.font.size = size
        if color is not None:
            r.font.color.rgb = color
    return p
NOTE = re.compile(r"^>\s?(.*)$")
SOFT = "⁠"  # ebook_ocr.py 가 줄 경계에 쓰는 보이지 않는 표시 (저장 때 지우지만 혹시 남았으면 제거)
NO_ALT = "(설명 없음)"


@dataclass
class Block:
    kind: str  # title | heading | note | figure | para | page | table
    text: str = ""
    level: int = 1
    page: int = 0
    src: str = ""  # figure 파일 경로
    rows: list = field(default_factory=list)  # table: [[칸 글, ...], ...]
    head: bool = False  # table: 첫 행이 머리 행 (둘째 줄이 |---| 구분선)
    closed: bool = True  # table: 읽는 중 표가 끝났는지 (빈 줄·다른 줄이 오면 끝)


@dataclass
class Parsed:
    blocks: list[Block] = field(default_factory=list)
    missing_alt: list[int] = field(default_factory=list)  # 설명 없는 그림이 있는 쪽
    missing_file: list[str] = field(default_factory=list)


TABLE_LINE = re.compile(r"^\|.*\|$")
TABLE_SEP = re.compile(r"^\|[\s:|-]+\|$")


def table_cells(line: str) -> list[str]:
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", line.strip()[1:-1])]


def parse_markdown(text: str, base: Path, skip_pages=(), no_join_pages=()) -> Parsed:
    """교정 글 → 블록. 제목 블록의 level 은 글에 쓴 # 개수 그대로(1 = #, … 6 = ######).
    옛 교정 파일 호환: 파일 첫 줄(쪽 표시보다 앞)의 '# 책제목' 은 title 블록으로 보고 본문 제목으로 쓰지 않는다.
    skip_pages: 뺀 쪽(그 쪽 글에 앞 쪽 문단을 이어 붙이지 않음), no_join_pages: 챕터 시작 쪽(앞 챕터 글에 이어 붙이지 않음)."""
    out = Parsed()
    page = 0
    first_line = True
    join_next = False  # '<!-- p.N 이어짐 -->' 다음 첫 본문은 앞 쪽 마지막 본문 문단에 이어 붙인다
    for raw in text.replace("\r\n", "\n").replace(SOFT, "").split("\n"):
        line = raw.rstrip()
        if not line.strip():
            if out.blocks and out.blocks[-1].kind == "table":
                out.blocks[-1].closed = True  # 빈 줄 = 표 끝
            continue
        was_first, first_line = first_line, False
        if TABLE_LINE.match(line.strip()):  # 표 줄: 이어진 표 줄을 한 표로 모은다
            t = line.strip()
            last = out.blocks[-1] if out.blocks else None
            if last is not None and last.kind == "table" and not last.closed:
                if TABLE_SEP.match(t) and len(last.rows) == 1:
                    last.head = True
                elif not TABLE_SEP.match(t):
                    last.rows.append(table_cells(t))
            elif not TABLE_SEP.match(t):
                out.blocks.append(Block("table", page=page, rows=[table_cells(t)], closed=False))
            join_next = False
            continue
        if out.blocks and out.blocks[-1].kind == "table":
            out.blocks[-1].closed = True  # 빈 줄이 아닌 다른 줄이 오면 표 끝
        m = PAGE_MARK.match(line.strip())
        if m:
            page = int(m.group(1))
            join_next = bool(m.group(2)) and page not in no_join_pages and page not in skip_pages
            out.blocks.append(Block("page", page=page))
            continue
        if line.strip().startswith("<!--") and line.strip().endswith("-->"):
            continue  # 그 밖의 주석은 버림
        m = FIGURE.match(line.strip())
        if m:
            alt, src = m.group(1).strip(), m.group(2)
            if not alt:
                out.missing_alt.append(page)
            if not (base / src).is_file():
                out.missing_file.append(src)
            out.blocks.append(Block("figure", alt, page=page, src=src))
            continue  # 그림은 이어 붙이기 대상이 아니므로 join_next 를 그대로 둔다 (그림 뒤 본문을 앞 문단에 붙임)
        m = HEADING.match(line.strip())
        if m:
            level = len(m.group(1))
            if level == 1 and was_first and page == 0:  # 옛 교정 파일 첫 줄의 '# 책제목'
                out.blocks.append(Block("title", m.group(2)))
            else:
                out.blocks.append(Block("heading", m.group(2), level=level, page=page))
            join_next = False  # 제목이 오면 이어지지 않음
            continue
        m = NOTE.match(line.strip())
        if m:
            out.blocks.append(Block("note", m.group(1).strip(), page=page))
            continue
        if join_next:  # 앞 쪽 마지막 본문 문단 찾기 (사이의 쪽 표시·각주·그림은 건너뜀)
            prev = next((b for b in reversed(out.blocks) if b.kind not in ("page", "note", "figure")), None)
            join_next = False
            if prev is not None and prev.kind == "para" and prev.page not in skip_pages:
                t = line.strip()
                prev.text = prev.text[:-1] + t if re.search(r"[A-Za-z]-$", prev.text) and re.match(r"[a-z]", t) else f"{prev.text} {t}"
                continue
        out.blocks.append(Block("para", line.strip(), page=page))
    return out


def apply_toc(blocks: list[Block], toc: dict[int, list]) -> list[Block]:
    """목차를 저장한 쪽은 그 쪽 글(그림·표 포함) 대신 목차 블록 하나로 바꾼다. 쪽 표시가 없는 쪽이면 쪽 표시도 만든다.
    여러 쪽에 걸친 목차는 쪽 순서대로 잇고, 첫 쪽에만 '**목차**' 머리를 단다 (Block.head)."""
    if not toc:
        return blocks
    first = min(toc)
    out: list[Block] = []
    done: set[int] = set()

    def add(cap: int) -> None:
        out.append(Block("toc", page=cap, rows=toc[cap], head=cap == first))
        done.add(cap)

    for b in blocks:
        for cap in sorted(c for c in toc if c not in done and 0 < c < b.page and b.kind == "page"):  # 쪽 표시가 없던 목차 쪽
            out.append(Block("page", page=cap)); add(cap)
        if b.kind != "title" and b.page in toc and b.kind != "page":
            continue  # 목차 쪽의 원래 글은 쓰지 않음
        out.append(b)
        if b.kind == "page" and b.page in toc and b.page not in done:
            add(b.page)
    for cap in sorted(c for c in toc if c not in done):
        out.append(Block("page", page=cap)); add(cap)
    return out


# ----------------------------------------------------------------------------
# AI용 Markdown
# ----------------------------------------------------------------------------
def toc_lines(b: Block) -> list[str]:
    lines = ["**목차**", ""] if b.head else []
    lines += ["  " * it["level"] + "- " + ai_inline(it["text"]) for it in b.rows]
    return lines + [""]


def blocks_to_lines(blocks: list[Block], cfg: dict, page_marks: bool) -> list[str]:
    """블록 → AI용 글 줄 (각 줄 뒤에 빈 줄). 쪽 표시는 책 쪽 번호로 쓴다."""
    lines: list[str] = []
    for b in blocks:
        if b.kind == "title":
            continue  # 책 제목은 파일 머리(---)에만
        elif b.kind == "heading":
            lines += ["#" * b.level + f" {ai_inline(b.text)}", ""]
        elif b.kind == "note":
            lines += [f"> {ai_inline(b.text)}", ""]
        elif b.kind == "figure":
            where = (f"책 p.{chap.page_label(b.page, cfg)}" if chap.has_page_numbers(cfg) else f"원본 {b.page}쪽")
            desc = b.text or (f"(설명 없음 — {where})" if b.page else NO_ALT)
            lines += [f"> [그림] {desc}", ""]
        elif b.kind == "table":
            n = max(len(r) for r in b.rows)
            cells = [[ai_inline(c).replace("|", "\\|") for c in r] + [""] * (n - len(r)) for r in b.rows]
            tl = ["| " + " | ".join(r) + " |" for r in cells]
            if b.head:
                tl.insert(1, "|" + "|".join(["---"] * n) + "|")
            lines += tl + [""]
        elif b.kind == "toc":
            lines += toc_lines(b)
        elif b.kind == "page":
            if page_marks:
                lines += [f"[p.{chap.page_label(b.page, cfg)}]", ""]
        else:
            lines += [ai_inline(b.text), ""]
    return lines


def front_matter(fields: list[tuple[str, str]]) -> list[str]:
    """파일 머리 정보. 제목 표시(#)를 쓰지 않고 '---' 블록으로 (파일 하나만 떼어 써도 어느 책·어느 위치인지 알게)."""
    return ["---"] + [f"{k}: {v}" for k, v in fields if v] + ["---", ""]


def build_ai_markdown(parsed: Parsed, title: str, page_marks: bool, cfg: dict | None = None,
                      chapter: str = "", topic: str = "") -> str:
    """챕터 설정이 없을 때의 AI용 글 (책 전체, 또는 예전 방식으로 나눈 한 덩어리)."""
    cfg = cfg or chap.empty()
    rng = page_range(parsed.blocks, None, cfg)
    head = front_matter([("책", title), ("챕터", chapter), ("대주제", topic), ("쪽", rng)])
    return "\n".join(head + blocks_to_lines(parsed.blocks, cfg, page_marks)).rstrip() + "\n"


# ----------------------------------------------------------------------------
# 챕터 설정에 따른 정리·나누기
# ----------------------------------------------------------------------------
@dataclass
class Section:
    kind: str  # front(앞부분) | chapter
    index: int  # 챕터 번호(1부터, 제외한 챕터도 번호를 차지). 앞부분은 0
    name: str
    part: str
    split: str
    exclude: bool
    start: int  # 시작하는 캡처 쪽 (앞부분은 0)
    blocks: list[Block] = field(default_factory=list)


def norm_title(t: str) -> str:
    """제목 겹침 비교용: 제목 표시·빈칸·서식 기호를 없애고 소문자로."""
    t = re.sub(r"^#{1,6}\s+", "", t.strip())
    t = re.sub(r"\*+|</?u>|<br\s*/?>", "", t, flags=re.I)
    return re.sub(r"\s+", "", t).casefold()


def drop_skipped(blocks: list[Block], skip: set[int]) -> list[Block]:
    return [b for b in blocks if b.kind == "title" or b.page not in skip]


def make_sections(parsed: Parsed, cfg: dict, warnings: list[str] | None = None) -> list[Section]:
    """블록을 앞부분과 챕터로 나눈다 (블록이 속한 쪽 = 마지막으로 읽은 쪽 표시의 캡처 번호).
    뺀 쪽의 글은 버리고, 챕터 시작 쪽과 그다음 쪽에서 챕터명·파트명과 같은 줄은 버린다 (파일 머리에만 나오게).
    그 밖의 쪽에 챕터명·파트명과 같은 제목 줄이 있으면 warnings 에 적는다."""
    chs = cfg["chapters"]
    starts = [c["capture"] for c in chs]
    secs = [Section("front", 0, "앞부분", "", chap.SPLIT_CHAPTER, False, 0)]
    for i, c in enumerate(chs, start=1):
        secs.append(Section("chapter", i, c["title"], c["part"], c["split"], c["exclude"], c["capture"]))
    skip = set(cfg["skip_pages"])
    for b in drop_skipped(parsed.blocks, skip):
        if b.kind == "title":
            continue
        secs[bisect_right(starts, b.page)].blocks.append(b)
    names = {norm_title(c["title"]): c["title"] for c in chs} | {norm_title(c["part"]): c["part"] for c in chs if c["part"]}
    for sec in secs:
        if sec.kind == "chapter":
            same = {norm_title(sec.name)} | ({norm_title(sec.part)} if sec.part else set())
            near = {sec.start, sec.start + 1}
            sec.blocks = [b for b in sec.blocks
                          if not (b.page in near and b.kind in ("para", "heading") and norm_title(b.text) in same)]
        if warnings is not None and not sec.exclude:
            for b in sec.blocks:
                if b.kind == "heading" and norm_title(b.text) in names:
                    warnings.append(f"캡처 {b.page}(책 p.{chap.page_label(b.page, cfg)}): 챕터·파트 이름과 같은 제목 줄이 "
                                    f"챕터 시작 쪽 밖에 있습니다 — '{b.text}'")
    return secs


def has_content(blocks: list[Block]) -> bool:
    return any(b.kind != "page" for b in blocks)


def has_body(blocks: list[Block]) -> bool:
    """제목·쪽 표시 말고 본문이 있는지."""
    return any(b.kind not in ("page", "heading") for b in blocks)


TOPIC_LEVEL = 1  # '대주제까지' 나눌 때의 제목 단계 (#)


def split_topics(blocks: list[Block]) -> list[list[Block]]:
    """# 줄마다 새 덩어리. # 앞의 글(첫 덩어리)은 챕터 파일에 남는다.
    # 가 쪽 맨 위에서 시작하면 그 쪽 표시도 새 덩어리로 옮긴다 (쪽 중간이면 앞 덩어리에도 남는다)."""
    groups: list[list[Block]] = [[]]
    for b in blocks:
        if b.kind == "heading" and b.level == TOPIC_LEVEL:
            moved: list[Block] = []
            g = groups[-1]
            if g and g[-1].kind == "page" and g[-1].page == b.page:
                moved = [g.pop()]
            groups.append(moved)
        groups[-1].append(b)
    return groups


def page_range(blocks: list[Block], start: int | None, cfg: dict) -> str:
    pages = [b.page for b in blocks if b.page > 0]
    if start:
        pages.append(start)
    if not pages:
        return ""
    a, z = chap.page_label(min(pages), cfg), chap.page_label(max(pages), cfg)
    rng = f"p.{a}" if a == z else f"p.{a}–p.{z}"
    return rng + (" (캡처 번호)" if cfg.get("no_print_pages") else "")


def with_start_mark(blocks: list[Block], start: int | None) -> list[Block]:
    """그 파일이 시작하는 쪽 표시를 맨 앞에 (쪽 중간에서 나뉘면 앞 파일에도 남아 있음)."""
    if start and not (blocks and blocks[0].kind == "page" and blocks[0].page == start):
        return [Block("page", page=start)] + blocks
    return blocks


def section_fields(title: str, sec: Section, rng: str, topic: str = "") -> list[tuple[str, str]]:
    return [("책", title), ("파트", sec.part), ("챕터", sec.name), ("대주제", topic), ("쪽", rng)]


def file_text(title: str, sec: Section, blocks: list[Block], start: int | None, cfg: dict, page_marks: bool,
              topic: str = "") -> str:
    """나눈 파일 하나: 머리(---: 책·파트·챕터·대주제·쪽) + 빈 줄 + 그 파일이 시작하는 쪽 표시 + 글."""
    blocks = with_start_mark(blocks, start)
    head = front_matter(section_fields(title, sec, page_range(blocks, start, cfg), topic))
    return "\n".join(head + blocks_to_lines(blocks, cfg, page_marks)).rstrip() + "\n"


def safe_name(title: str) -> str:
    return re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", title).strip() or "책"


def split_by_chapters(secs: list[Section], title: str, cfg: dict, page_marks: bool, warnings: list[str] | None = None):
    """챕터 설정대로 나눈 AI용 파일. ([(파일 이름, 내용)], [챕터 요약 줄], [내용이 없어 건너뛴 챕터])."""
    base = safe_name(title)
    warnings = warnings if warnings is not None else []
    files: list[tuple[str, str]] = []
    info: list[str] = []
    empty_ch: list[str] = []
    for sec in secs:
        if sec.exclude or not has_content(sec.blocks):
            if sec.kind == "chapter" and not sec.exclude:
                empty_ch.append(f"챕터{sec.index:02d} {sec.name}")
            continue
        if sec.kind == "front":
            files.append((f"{base}.앞부분.md", file_text(title, sec, sec.blocks, None, cfg, page_marks)))
            info.append(f"앞부분: {page_range(sec.blocks, None, cfg)}")
            continue
        name = f"{base}.챕터{sec.index:02d}"
        groups = split_topics(sec.blocks) if sec.split == chap.SPLIT_TOPIC else [sec.blocks]
        n_files = 0
        for k, g in enumerate(groups):
            if k == 0:
                if not has_content(g):
                    continue
                if not has_body(g):
                    warnings.append(f"{name}.md: 본문 없이 제목·쪽 표시만 있습니다 "
                                    f"({page_range(g, sec.start, cfg)})")
                files.append((f"{name}.md", file_text(title, sec, g, sec.start, cfg, page_marks)))
            else:
                head = next(b for b in g if b.kind == "heading")
                files.append((f"{name}.대주제{k:02d}.md", file_text(title, sec, g, head.page, cfg, page_marks, topic=head.text)))
            n_files += 1
        info.append(f"챕터{sec.index:02d} {sec.name}: {page_range(sec.blocks, sec.start, cfg)} (파일 {n_files}개)")
    return files, info, empty_ch


def build_chapter_markdown(secs: list[Section], title: str, cfg: dict, page_marks: bool) -> str:
    """책 전체 AI용 글: 맨 앞 머리(책·쪽) + 앞부분·챕터마다 머리(파트·챕터·쪽) + 쪽 표시·글."""
    kept = [s for s in secs if not s.exclude and has_content(s.blocks)]
    all_blocks = [b for s in kept for b in s.blocks] + [Block("page", page=s.start) for s in kept if s.start]
    lines = front_matter([("책", title), ("쪽", page_range(all_blocks, None, cfg))])
    for sec in kept:
        start = sec.start if sec.kind == "chapter" else None
        blocks = with_start_mark(sec.blocks, start)
        lines += front_matter([("파트", sec.part), ("챕터", sec.name), ("쪽", page_range(blocks, start, cfg))])
        lines += blocks_to_lines(blocks, cfg, page_marks)
    return "\n".join(lines).rstrip() + "\n"


# ----------------------------------------------------------------------------
# Word(.docx)
# ----------------------------------------------------------------------------
BODY_FONT = "맑은 고딕"
LATIN_FONT = "Calibri"


def _set_font(style, name: str, east_asia: str, size_pt: float | None = None, bold: bool | None = None, color=None) -> None:
    from docx.oxml.ns import qn
    from docx.shared import Pt

    style.font.name = name
    if size_pt:
        style.font.size = Pt(size_pt)
    if bold is not None:
        style.font.bold = bold
    if color is not None:
        style.font.color.rgb = color
    rpr = style.element.get_or_add_rPr()
    fonts = rpr.find(qn("w:rFonts"))
    if fonts is None:
        from docx.oxml import OxmlElement
        fonts = OxmlElement("w:rFonts")
        rpr.append(fonts)
    for attr in ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme", "w:cstheme"):  # 테마 글꼴이 우선하지 않게
        if fonts.get(qn(attr)) is not None:
            del fonts.attrib[qn(attr)]
    for attr in ("w:ascii", "w:hAnsi"):
        fonts.set(qn(attr), name)
    fonts.set(qn("w:eastAsia"), east_asia)


def build_docx(parsed: Parsed, title: str, base: Path, path: Path, captions: bool, secs: list[Section] | None = None,
               cfg: dict | None = None) -> int:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm, Pt, RGBColor

    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
    for side in ("left_margin", "right_margin"):
        setattr(sec, side, Cm(2.5))
    sec.top_margin = sec.bottom_margin = Cm(2.5)
    content_cm = 16.0
    st = doc.styles
    _set_font(st["Normal"], LATIN_FONT, BODY_FONT, 10.5)
    st["Normal"].paragraph_format.line_spacing = 1.5
    st["Normal"].paragraph_format.space_after = Pt(6)
    for i, size in ((1, 16), (2, 13), (3, 11.5), (4, 11), (5, 10.5)):  # # → 제목 1, ## → 제목 2 … #####·###### → 제목 5
        _set_font(st[f"Heading {i}"], LATIN_FONT, BODY_FONT, size, True, RGBColor(0x1D, 0x23, 0x30))
    from docx.enum.style import WD_STYLE_TYPE
    head_st = {}  # 머리 문단(책·파트·챕터): 제목 스타일이 아니라 Word 목차·탐색 창의 제목 단계와 섞이지 않음
    for key, name, size, color in (("책", "머리 책", 20, RGBColor(0x1D, 0x23, 0x30)), ("파트", "머리 파트", 12, RGBColor(0x66, 0x70, 0x85)),
                                   ("챕터", "머리 챕터", 18, RGBColor(0x1F, 0x5F, 0xD1)), ("쪽", "머리 쪽", 9, RGBColor(0x66, 0x70, 0x85))):
        hs = st.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        hs.base_style = st["Normal"]
        _set_font(hs, LATIN_FONT, BODY_FONT, size, key != "쪽", color)
        hs.paragraph_format.keep_with_next = True
        head_st[key] = hs

    def head_paras(fields: list[tuple[str, str]], new_page: bool) -> None:
        first = True
        for k, v in fields:
            if not v:
                continue
            p = doc.add_paragraph(v if k in ("책", "챕터") else f"{k}: {v}", style=head_st[k])
            if first and new_page:
                p.paragraph_format.page_break_before = True
            first = False

    n_fig = 0

    def render(b: Block) -> None:
        nonlocal n_fig
        if b.kind == "title":
            return  # 책 제목은 머리 문단으로
        elif b.kind == "heading":
            h = doc.add_heading("", level=min(5, max(1, b.level)))
            add_inline(h, b.text)
        elif b.kind == "toc":
            if b.head:
                add_inline(doc.add_paragraph(), "**목차**")
            for it in b.rows:
                p = doc.add_paragraph()
                add_inline(p, it["text"])
                p.paragraph_format.left_indent = Cm(0.8 * it["level"])
                p.paragraph_format.space_after = Pt(2)
        elif b.kind == "note":
            p = doc.add_paragraph()
            add_inline(p, "주  " + re.sub(r"^주\s*[:：]\s*", "", b.text), Pt(9), RGBColor(0x66, 0x70, 0x85))
            p.paragraph_format.left_indent = Cm(0.8)
        elif b.kind == "figure":
            f = base / b.src
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.keep_with_next = bool(captions and b.text)
            if f.is_file():
                from PIL import Image

                with Image.open(f) as im:
                    px = im.size[0]
                width_cm = min(14.0, content_cm, max(3.0, px / 150 * 2.54))  # 150dpi 크기, 최대 14cm
                p.add_run().add_picture(str(f), width=Cm(width_cm))
                n_fig += 1
            else:
                r = p.add_run(f"(그림 파일 없음: {b.src})")
                r.font.color.rgb = RGBColor(0xE5, 0x48, 0x4D)
            if captions and b.text:
                c = doc.add_paragraph()
                c.alignment = WD_ALIGN_PARAGRAPH.CENTER
                r = c.add_run(b.text)
                r.font.size = Pt(9)
                r.font.italic = True
                r.font.color.rgb = RGBColor(0x66, 0x70, 0x85)
        elif b.kind == "para":
            add_inline(doc.add_paragraph(), b.text)
        elif b.kind == "table":
            n = max(len(r) for r in b.rows)
            t = doc.add_table(rows=len(b.rows), cols=n)
            t.style = "Table Grid"
            for i, r in enumerate(b.rows):
                for j in range(n):
                    c = t.cell(i, j)
                    para = c.paragraphs[0]
                    parts = re.split(r"<br\s*/?>", r[j] if j < len(r) else "", flags=re.I)  # 칸 안 줄바꿈
                    for k, part in enumerate(parts):
                        if k:
                            para.add_run().add_break()
                        add_inline(para, part.strip(), Pt(9.5))
                    if i == 0 and b.head:
                        for run in para.runs:
                            run.bold = True
            doc.add_paragraph()  # 표 다음 문단과 띄우기
        # page 표시는 완성본에 넣지 않음

    head_paras([("책", title)], False)  # 문서 맨 앞: 책 (머리 문단)
    if secs is None:
        for b in parsed.blocks:
            render(b)
    else:  # 챕터 설정이 있으면: 앞부분 → 챕터마다 머리 문단(파트·챕터·쪽, 새 쪽에서) → 글. 제외한 챕터는 쓰지 않음
        for chapter in secs:
            if chapter.exclude or not has_content(chapter.blocks):
                continue
            if chapter.kind == "chapter":
                head_paras([("파트", chapter.part), ("챕터", chapter.name),
                            ("쪽", page_range(chapter.blocks, chapter.start, cfg or chap.empty()))], True)
            for b in chapter.blocks:
                render(b)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    return n_fig


# ----------------------------------------------------------------------------
def split_ai(parsed: Parsed, title: str, level: int, page_marks: bool, cfg: dict | None = None) -> list[tuple[str, str]]:
    """챕터 설정이 없을 때만 쓰는 예전 방식: 제목 단계로 나눈다 (level 1 = ## 까지, 2 = ### 까지 …; # 는 늘 나눔).
    [(파일 이름, 내용)]. 각 파일 맨 위에 머리(---: 책·챕터·쪽)를 둔다."""
    groups: list[tuple[str, list[Block]]] = [("앞부분", [])]
    for b in parsed.blocks:
        if b.kind == "title":
            continue
        if b.kind == "heading" and b.level - 1 <= level:
            moved: list[Block] = []
            g = groups[-1][1]
            if g and g[-1].kind == "page" and g[-1].page == b.page:  # 쪽 맨 위에서 시작하면 그 쪽 표시도 새 파일로
                moved = [g.pop()]
            groups.append((b.text, moved + [b]))
        else:
            groups[-1][1].append(b)
    out = []
    n = 0
    last_page = 0
    for name, blocks in groups:
        start = last_page
        pages = [b.page for b in blocks if b.kind == "page"]
        last_page = pages[-1] if pages else last_page
        if not any(b.kind not in ("page",) for b in blocks):
            continue  # 쪽 표시뿐인 덩어리(제목 앞 빈 부분)는 건너뜀
        if start and not (blocks and blocks[0].kind == "page"):
            blocks = [Block("page", page=start)] + blocks  # 쪽 중간에서 나뉘면 그 쪽 표시를 새 파일 첫머리에도
        part = Parsed()
        part.blocks = blocks
        safe = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", re.sub(r"\*+|</?u>|<br\s*/?>", "", name)).strip()[:40] or "제목없음"
        out.append((f"{n:02d}_{safe}.md", build_ai_markdown(part, title, page_marks, cfg, chapter=name)))
        n += 1
    return out


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="교정한 글 → 사람용 Word(.docx) + AI용 Markdown")
    ap.add_argument("folder", help="page_0001.png ... 가 들어 있는 폴더 (결과 폴더는 <폴더>_OCR)")
    ap.add_argument("-o", "--output", help="OCR 결과 폴더 (기본: <폴더>_OCR)")
    ap.add_argument("--title", help="책 제목 (기본: 폴더 이름)")
    ap.add_argument("--only", choices=["docx", "ai"], help="한 가지만 만들기")
    ap.add_argument("--page-marks", action="store_true", help="(기본값이라 안 써도 됨) AI용 글에 [p.N] 쪽 표시를 남김")
    ap.add_argument("--no-page-marks", action="store_true", help="AI용 글에서 [p.N] 쪽 표시를 뺌")
    ap.add_argument("--no-caption", action="store_true", help="Word 에 그림 설명 캡션을 넣지 않음")
    ap.add_argument("--split-level", type=int, default=1, choices=[0, 1, 2, 3],
                    help="챕터 설정이 없을 때만: AI용 글을 나눌 제목 단계 1 = ##(기본), 2 = ###까지, 3 = ####까지, 0 = 나누지 않음")
    return ap.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    from bookdir import resolve, result_dir
    folder = resolve(args.folder)
    out_dir = result_dir(folder, args.output, args.title)
    title = args.title or folder.name
    src = out_dir / f"{title}_교정.md"
    if not src.is_file():
        print(f"[오류] 교정 파일이 없습니다: {src}\n  먼저 4_교정.bat 로 교정 편집기를 한 번 여세요.")
        return 1
    cfg = chap.load(chap.config_path(out_dir, title))
    page_marks = not args.no_page_marks
    chapter_mode = bool(cfg["chapters"])
    skip = set(cfg["skip_pages"])
    starts = {c["capture"] for c in cfg["chapters"]}
    toc = {k: v for k, v in chap.toc_map(cfg).items() if k not in skip}
    parsed = parse_markdown(src.read_bytes().decode("utf-8"), out_dir, skip_pages=skip | set(toc), no_join_pages=starts)
    parsed.blocks = apply_toc(drop_skipped(parsed.blocks, skip), toc)
    warnings: list[str] = []
    secs = make_sections(parsed, cfg, warnings) if chapter_mode else None
    kept = [b for sec in secs for b in sec.blocks] if secs is not None else parsed.blocks
    parsed.missing_alt = [b.page for b in kept if b.kind == "figure" and not b.text]
    figs = [b for b in kept if b.kind == "figure"]

    made = []
    parts: list = []
    notes: list[str] = []
    if args.only in (None, "ai"):
        p = out_dir / f"{title}_AI용.md"
        text = build_chapter_markdown(secs, title, cfg, page_marks) if secs is not None else build_ai_markdown(parsed, title, page_marks, cfg)
        p.write_bytes(text.encode("utf-8"))
        made.append(("AI용 글", p))
        if chapter_mode or args.split_level:
            d = out_dir / f"{title}_AI용_나눔"
            d.mkdir(exist_ok=True)
            for old in d.glob("*.md"):  # 예전에 나눈 파일 지우기 (이 폴더는 내보내기 전용)
                old.unlink()
            if chapter_mode:
                parts, info, empty_ch = split_by_chapters(secs, title, cfg, page_marks, warnings)
                label = f"AI용 나눔 ({len(parts)}개 파일, 챕터 설정대로)"
                notes += [f"  {line}" for line in info]
                if empty_ch:
                    notes.append("  [참고] 내용이 없어 파일을 만들지 않은 챕터: " + ", ".join(empty_ch))
            else:
                parts = split_ai(parsed, title, args.split_level, page_marks, cfg)
                label = f"AI용 나눔 ({len(parts)}개 파일, 제목 단계 {args.split_level})"
            for name, text in parts:
                (d / name).write_bytes(text.encode("utf-8"))
            made.append((label, d))
    if args.only in (None, "docx"):
        try:
            import docx  # noqa: F401
        except ImportError:
            print("[오류] python-docx 가 없어 Word 파일을 만들 수 없습니다. 설치.bat 를 다시 실행하세요.")
            return 1
        p = out_dir / f"{title}_완성본.docx"
        build_docx(parsed, title, out_dir, p, not args.no_caption, secs, cfg)
        made.append(("완성본(Word)", p))

    n_parts = sum(1 for label, _ in made if label.startswith("AI용 나눔"))
    print(f"완료: 그림 {len(figs)}개" + (f", 나눈 파일 {len(parts)}개" if n_parts else ""))
    for label, p in made:
        print(f"  {label}: {p.resolve()}")
    for line in notes:
        print(line)
    if cfg["skip_pages"]:
        print("  뺀 쪽: " + ", ".join(f"캡처 {n}(책 p.{chap.page_label(n, cfg)})" for n in cfg["skip_pages"]))
    ex = [f"챕터{i:02d} {c['title']}" for i, c in enumerate(cfg["chapters"], start=1) if c["exclude"]]
    if ex:
        print("  제외한 챕터: " + ", ".join(ex))
    if parsed.missing_alt:
        pages = ", ".join(f"{n}쪽" if n else "쪽 미상" for n in parsed.missing_alt)
        print(f"[주의] 설명이 없는 그림 {len(parsed.missing_alt)}개 ({pages}) — AI용 글에는 '설명 없음'으로 들어갑니다."
              "\n       4_교정.bat 의 '그림 목록'에서 찾아 설명을 쓴 뒤 다시 내보내세요.")
    if parsed.missing_file:
        print(f"[주의] 그림 파일을 찾지 못함: {', '.join(parsed.missing_file)}")
    if warnings:
        print(f"[경고] {len(warnings)}건 (내보내기는 끝났습니다. 확인 후 필요하면 고쳐서 다시 내보내세요)")
        for w in warnings:
            print("  " + w)
    return 0


if __name__ == "__main__":
    sys.exit(main())
