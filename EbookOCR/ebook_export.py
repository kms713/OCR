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
    python ebook_export.py books\\책이름 --no-page-marks # AI용에 '[p.N]' 쪽 표시를 넣지 않음 (기본은 책 쪽 번호로 넣음)
    python ebook_export.py books\\책이름 --no-caption    # Word 에 그림 설명 캡션을 넣지 않음

그림 줄은 교정 글 안의  ![설명](figures/p0012_01.png)  한 줄입니다. 설명이 비어 있는 그림은 끝에 알려 줍니다.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from bookpages import BookPages, count_pages, empty_config, config_path, load_config, toc_pages

PAGE_MARK = re.compile(r"^<!--\s*p\.(\d+)(\s*이어짐)?\s*-->\s*$")  # 이어짐: 앞 쪽 마지막 문단과 이어 붙임
FIGURE = re.compile(r"^!\[([^\]]*)\]\(([^)\s]+)\)\s*$")
HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")  # # 책 제목(자동), ## 챕터(자동), ### 사용자 1단계 … ###### 4단계
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


def parse_markdown(text: str, base: Path, skip_pages=frozenset(), text_off=frozenset()) -> Parsed:
    """교정 글 → 블록 목록. 제목 단계는 # 개수 그대로(## 챕터, ### 사용자 1단계 … ###### 4단계).
    파일 첫 줄의 '# 책제목'은 건너뛴다(책 제목은 폴더 이름·--title 에서 가져옴). skip_pages: 글을 뺄 캡처 쪽 번호. text_off: 글을 다른 것(저장한 목차)으로 바꿀 쪽 — 쪽 표시만 남기고 글은 버림."""
    out = Parsed()
    page = 0
    first = True
    join_next = False  # '<!-- p.N 이어짐 -->' 다음 첫 본문은 앞 쪽 마지막 본문 문단에 이어 붙인다

    def close_table():
        if out.blocks and out.blocks[-1].kind == "table":
            out.blocks[-1].closed = True

    for raw in text.replace("\r\n", "\n").replace(SOFT, "").split("\n"):
        line = raw.rstrip()
        s = line.strip()
        if not s:
            close_table()  # 빈 줄 = 표 끝
            continue
        was_first, first = first, False
        m = PAGE_MARK.match(s)
        if m:
            close_table()
            page = int(m.group(1))
            join_next = bool(m.group(2)) and page not in skip_pages
            if page not in skip_pages:
                out.blocks.append(Block("page", page=page))
            continue
        if page in text_off:
            close_table()
            continue
        if page in skip_pages:  # 뺀 쪽: 글도 그림도 쓰지 않는다 (쪽 번호는 그대로 차지)
            close_table()
            continue
        if was_first:
            mh = HEADING.match(s)
            if mh and len(mh.group(1)) == 1:
                continue  # 예전 교정 파일의 첫 줄 '# 책제목'
        if TABLE_LINE.match(s):  # 표 줄: 이어진 표 줄을 한 표로 모은다
            last = out.blocks[-1] if out.blocks else None
            if last is not None and last.kind == "table" and not last.closed:
                if TABLE_SEP.match(s) and len(last.rows) == 1:
                    last.head = True
                elif not TABLE_SEP.match(s):
                    last.rows.append(table_cells(s))
            elif not TABLE_SEP.match(s):
                out.blocks.append(Block("table", page=page, rows=[table_cells(s)], closed=False))
            join_next = False
            continue
        close_table()  # 빈 줄이 아닌 다른 줄이 오면 표 끝
        if s.startswith("<!--") and s.endswith("-->"):
            continue  # 그 밖의 주석은 버림
        m = FIGURE.match(s)
        if m:
            alt, src = m.group(1).strip(), m.group(2)
            if not alt:
                out.missing_alt.append(page)
            if not (base / src).is_file():
                out.missing_file.append(src)
            out.blocks.append(Block("figure", alt, page=page, src=src))
            continue  # 그림은 이어 붙이기 대상이 아니므로 join_next 를 그대로 둔다 (그림 뒤 본문을 앞 문단에 붙임)
        m = HEADING.match(s)
        if m:
            out.blocks.append(Block("heading", m.group(2), level=max(2, len(m.group(1))), page=page))  # 글 속 # 는 책 제목 자리라 ## 로 본다
            join_next = False  # 제목이 오면 이어지지 않음
            continue
        m = NOTE.match(s)
        if m:
            out.blocks.append(Block("note", m.group(1).strip(), page=page))
            continue
        if join_next:  # 앞 쪽 마지막 본문 문단 찾기 (사이의 쪽 표시·각주·그림은 건너뜀)
            prev = next((b for b in reversed(out.blocks) if b.kind not in ("page", "note", "figure")), None)
            join_next = False
            if prev is not None and prev.kind == "para":
                prev.text = prev.text[:-1] + s if re.search(r"[A-Za-z]-$", prev.text) and re.match(r"[a-z]", s) else f"{prev.text} {s}"
                continue
        out.blocks.append(Block("para", s, page=page))
    return out


# ----------------------------------------------------------------------------
# 챕터 나누기 (챕터 설정 + 설정이 없을 때 교정 글 속 '## 제목')
# ----------------------------------------------------------------------------
@dataclass
class Chapter:
    num: int  # 0 = 앞부분, 1~ = 챕터 번호 (제외한 챕터도 번호를 차지한다)
    title: str
    part: str
    split: int  # 0 = 챕터만, N = ### … (## 아래 N단계)까지 나눔 (설정의 '대주제까지' = 1)
    exclude: bool
    start: int  # 시작 캡처 쪽
    blocks: list = field(default_factory=list)  # 쪽 표시 블록 + 본문 블록 (챕터명·파트는 머리에서 따로 씀)


@dataclass
class Plan:
    chapters: list[Chapter]
    skipped: list[int]  # 뺀 쪽 (캡처 번호)
    labels: BookPages


def _norm(t: str) -> str:
    return re.sub(r"^#+|\*+|</?u>|<br\s*/?>|\s+", "", t)


def build_plan(parsed: Parsed, cfg: dict | None, n_pages: int, legacy_split: int = 0) -> Plan:
    """블록을 챕터로 나누고 쪽 표시 블록에 책 쪽 번호(text)를 단다.
    cfg 가 None(설정 파일 없음)이면 교정 글에 직접 쓴 '## 제목' 줄을 챕터로 보고(나누기는 챕터만), 앞부분은 legacy_split 단계까지 나눈다."""
    has_cfg = cfg is not None
    cfg = cfg or empty_config()
    bp = BookPages(cfg)
    chap_at = {c["capture"]: c for c in cfg["chapters"]}
    skip = set(cfg["skip_pages"])
    toc_at = {t["capture"]: [(i["level"], i["text"]) for i in t["items"]] for t in cfg.get("toc", [])}
    chapters = [Chapter(0, "앞부분", "", 0 if has_cfg else legacy_split, False, 1)]
    st = {"cur": chapters[0], "page": 0, "drop": set()}

    def new_chapter(title, part, split, exclude, start):
        st["cur"] = Chapter(len(chapters), title, part, split, exclude, start)
        chapters.append(st["cur"])

    def enter(c: int):
        st["page"], st["drop"] = c, set()
        ch = chap_at.get(c)
        if ch:
            new_chapter(ch["title"], ch.get("part", ""), 1 if ch["split"] == "topic" else 0, ch["exclude"], c)
            st["drop"] = {x for x in (_norm(ch["title"]), _norm(ch.get("part", ""))) if x}
        if c in skip:  # 글만 뺀다: 쪽 표시는 쓰지 않고, 챕터 설정은 살아 있다
            return
        st["cur"].blocks.append(Block("page", bp.label(c), page=c))  # 새 챕터가 쪽 맨 위에서 시작하면 쪽 표시도 새 챕터 것
        if c in toc_at:  # 저장한 목차: 이 쪽의 OCR 글 대신 (제목이 아니라서 나누기·제목 겹침 처리에 안 잡힘)
            st["cur"].blocks.append(Block("toc", page=c, rows=toc_at[c]))

    last = 0
    for b in parsed.blocks:
        if b.kind == "page":
            if b.page > last:
                for c in range(last + 1, b.page + 1):  # 글이 없어 쪽 표시가 없는 쪽도 차례로 지난다
                    enter(c)
                last = b.page
            continue
        cur = st["cur"]
        if b.kind in ("heading", "para") and st["drop"] and _norm(b.text) in st["drop"]:
            st["drop"].discard(_norm(b.text))  # 챕터 시작 쪽에 있던 챕터명·파트명 줄: 머리에 한 번만 나오게
            continue
        if b.kind == "heading" and b.level == 2 and not has_cfg:  # 설정 없이 글에 직접 쓴 '## 제목' = 챕터
            moved = cur.blocks.pop() if cur.blocks and cur.blocks[-1].kind == "page" and cur.blocks[-1].page == st["page"] else None
            new_chapter(b.text, "", 0, False, st["page"])
            if moved:
                st["cur"].blocks.append(moved)
            continue
        cur.blocks.append(b)
    if last:
        for c in range(last + 1, n_pages + 1):
            enter(c)
    return Plan(chapters, sorted(skip), bp)


def has_content(blocks: list[Block]) -> bool:
    return any(b.kind != "page" for b in blocks)


def partition(ch: Chapter) -> list[list[Block]]:
    """챕터 글을 ### (사용자 1단계) 앞에서 나눈다(split 이 2 이상이면 #### 까지). 새 덩어리는 그 쪽의 쪽 표시로 시작한다
    (제목이 쪽 맨 위에서 시작하면 쪽 표시를 새 덩어리로 옮기고, 쪽 중간이면 같은 쪽 표시를 하나 더 둔다)."""
    if not ch.split:
        return [list(ch.blocks)]
    groups: list[list[Block]] = [[]]
    last_page = None
    for b in ch.blocks:
        if b.kind == "page":
            last_page = b
        if b.kind == "heading" and 3 <= b.level <= ch.split + 2:
            g = groups[-1]
            if last_page is not None and g and g[-1] is last_page:
                pb = g.pop()
            else:
                pb = Block("page", last_page.text, page=last_page.page) if last_page is not None else None
            groups.append(([pb] if pb else []) + [b])
            continue
        groups[-1].append(b)
    return groups


# ----------------------------------------------------------------------------
# AI용 Markdown
# ----------------------------------------------------------------------------
def render_blocks(blocks: list[Block], page_marks: bool) -> list[str]:
    """제목은 교정 글의 # 표시를 그대로 쓴다(## 챕터, ### …)."""
    lines: list[str] = []
    for b in blocks:
        if b.kind == "heading":
            lines += ["#" * b.level + f" {ai_inline(b.text)}", ""]
        elif b.kind == "note":
            lines += [f"> {ai_inline(b.text)}", ""]
        elif b.kind == "figure":
            desc = b.text or (f"(설명 없음 — 캡처 {b.page}쪽)" if b.page else NO_ALT)
            lines += [f"> [그림] {desc}", ""]
        elif b.kind == "table":
            n = max(len(r) for r in b.rows)
            cells = [[ai_inline(c).replace("|", "\\|") for c in r] + [""] * (n - len(r)) for r in b.rows]
            tl = ["| " + " | ".join(r) + " |" for r in cells]
            if b.head:
                tl.insert(1, "|" + "|".join(["---"] * n) + "|")
            lines += tl + [""]
        elif b.kind == "toc":
            lines += ["**목차**", ""] + ["  " * lv + "- " + ai_inline(t) for lv, t in b.rows] + [""]
        elif b.kind == "page":
            if page_marks:
                lines += [f"[p.{b.text}]", ""]  # b.text = 책 쪽 번호 (앞부분은 '앞3')
        else:
            lines += [ai_inline(b.text), ""]
    return lines


def page_span(blocks: list[Block], with_capture: bool = False) -> str:
    """'쪽: p.21–p.48'. with_capture(인쇄 쪽 번호 없는 책)면 끝에 '(캡처 21–48)'."""
    pgs = [b for b in blocks if b.kind == "page"]
    if not pgs:
        return ""
    a, z = pgs[0], pgs[-1]
    out = f"쪽: p.{a.text}" + (f"–p.{z.text}" if z.text != a.text else "")
    if with_capture:
        out += f" (캡처 {a.page}" + (f"–{z.page}" if z.page != a.page else "") + ")"
    return out


def file_head(title: str, ch: Chapter, blocks: list[Block], with_capture: bool = False) -> list[str]:
    """파일 머리: 책 제목 / 파트(있을 때) / 쪽 범위 / ## 챕터명. 파일만 보고 어느 책·파트·챕터·쪽인지 알게 한다."""
    head = [f"# {title}"]
    if ch.part:
        head.append(f"파트: {ch.part}")
    if page_span(blocks):
        head.append(page_span(blocks, with_capture))
    head.append(f"## {ai_inline(ch.title)}")
    return head + [""]


def build_chapter_file(title: str, ch: Chapter, blocks: list[Block], page_marks: bool, with_capture: bool = False) -> str:
    return "\n".join(file_head(title, ch, blocks, with_capture) + render_blocks(blocks, page_marks)).rstrip() + "\n"


def build_whole_ai(plan: Plan, title: str, page_marks: bool) -> str:
    """책 전체 한 파일: # 책제목, 쪽 범위, 그리고 챕터마다 (파트가 바뀌면 파트 줄) ## 챕터명 + 글."""
    kept = [c for c in plan.chapters if not c.exclude]
    allblocks = [b for c in kept for b in c.blocks]
    lines = [f"# {title}"] + ([page_span(allblocks, plan.labels.no_print)] if page_span(allblocks) else []) + [""]
    multi = len([c for c in kept if c.num]) > 0
    last_part = ""
    for c in kept:
        if c.num == 0 and not (has_content(c.blocks) and multi):
            if c.num == 0 and has_content(c.blocks):
                lines += render_blocks(c.blocks, page_marks)  # 챕터가 하나도 없는 책: 제목 줄 없이 그대로
            continue
        if c.part and c.part != last_part:
            lines += [f"파트: {c.part}"]
            last_part = c.part
        lines += [f"## {ai_inline(c.title)}", ""] + render_blocks(c.blocks, page_marks)
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


def build_docx(blocks: list[Block], title: str, base: Path, path: Path, captions: bool) -> int:
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
    _set_font(st["Title"], LATIN_FONT, BODY_FONT, 24, True, RGBColor(0x1D, 0x23, 0x30))
    for i, size in ((1, 16), (2, 13), (3, 11.5), (4, 10.5), (5, 10.5)):
        _set_font(st[f"Heading {i}"], LATIN_FONT, BODY_FONT, size, True, RGBColor(0x1D, 0x23, 0x30))

    doc.add_paragraph(title, style="Title")

    n_fig = 0
    for b in blocks:
        if b.kind == "heading":
            h = doc.add_heading("", level=min(5, max(1, b.level - 1)))  # ## → 제목 1, ### → 제목 2 …
            add_inline(h, b.text)
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
        elif b.kind == "toc":
            tp = doc.add_paragraph()
            tp.add_run("목차").bold = True
            for lv, t in b.rows:
                p2 = doc.add_paragraph()
                p2.paragraph_format.left_indent = Cm(0.6 * (lv + 1))
                p2.paragraph_format.space_after = Pt(2)
                add_inline(p2, "• " + t)
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
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    return n_fig


# ----------------------------------------------------------------------------
def safe_name(t: str) -> str:
    return re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", t).strip() or "책"


def split_files(plan: Plan, title: str, page_marks: bool) -> list[tuple[str, str]]:
    """장별 AI용 파일 [(파일 이름, 내용)]. 제외한 챕터는 만들지 않고, 챕터 번호는 건너뛰지 않는다.
    파일 이름: 책.앞부분.md / 책.챕터01.md / (대주제까지 나눈 챕터) 책.챕터03.md + 책.챕터03.대주제01.md"""
    name = safe_name(title)
    out: list[tuple[str, str]] = []
    for ch in plan.chapters:
        if ch.exclude:
            continue
        stem = f"{name}.앞부분" if ch.num == 0 else f"{name}.챕터{ch.num:02d}"
        groups = partition(ch)
        if has_content(groups[0]):
            out.append((f"{stem}.md", build_chapter_file(title, ch, groups[0], page_marks, plan.labels.no_print)))
        for k, g in enumerate(groups[1:], start=1):
            out.append((f"{stem}.대주제{k:02d}.md", build_chapter_file(title, ch, g, page_marks, plan.labels.no_print)))
    return out


def docx_blocks(plan: Plan) -> list[Block]:
    """Word 용: 챕터마다 (파트가 바뀌면 파트 줄) ## 챕터명 + 글. 쪽 표시는 넣지 않는다."""
    kept = [c for c in plan.chapters if not c.exclude]
    multi = any(c.num for c in kept)
    out: list[Block] = []
    last_part = ""
    for c in kept:
        if c.num == 0 and not multi:
            out += c.blocks
            continue
        if c.num == 0 and not has_content(c.blocks):
            continue
        if c.part and c.part != last_part:
            out.append(Block("para", f"파트: {c.part}"))
            last_part = c.part
        out.append(Block("heading", c.title, level=2, page=c.start))
        out += c.blocks
    return out


def page_range(ch: Chapter) -> str:
    labs = [b.text for b in ch.blocks if b.kind == "page"]
    return f"책 {labs[0]}~{labs[-1]}쪽" if len(labs) > 1 else (f"책 {labs[0]}쪽" if labs else "쪽 없음")


def print_summary(plan: Plan, files: list) -> None:
    print(f"나눈 파일 {len(files)}개")
    for ch in plan.chapters:
        if ch.num == 0 and not has_content(ch.blocks):
            continue
        nm = "앞부분" if ch.num == 0 else f"챕터{ch.num:02d} {ch.title}"
        print(f"  {nm}: {page_range(ch)}" + (" — 제외" if ch.exclude else "") + (" (대주제까지 나눔)" if ch.split and not ch.exclude else ""))
    if plan.skipped:
        print("뺀 쪽: " + ", ".join(f"캡처 {c}(책 {plan.labels.label(c)}쪽)" for c in plan.skipped))
    ex = [f"챕터{c.num:02d} {c.title}" for c in plan.chapters if c.exclude]
    if ex:
        print("제외한 챕터: " + ", ".join(ex))


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="교정한 글 → 사람용 Word(.docx) + AI용 Markdown")
    ap.add_argument("folder", help="page_0001.png ... 가 들어 있는 폴더 (결과 폴더는 <폴더>_OCR)")
    ap.add_argument("-o", "--output", help="OCR 결과 폴더 (기본: <폴더>_OCR)")
    ap.add_argument("--title", help="책 제목 (기본: 폴더 이름)")
    ap.add_argument("--only", choices=["docx", "ai"], help="한 가지만 만들기")
    ap.add_argument("--page-marks", action="store_true", help="(예전 옵션, 이제 기본으로 켜져 있음)")
    ap.add_argument("--no-page-marks", action="store_true", help="AI용 글에 [p.N] 쪽 표시를 넣지 않음")
    ap.add_argument("--no-caption", action="store_true", help="Word 에 그림 설명 캡션을 넣지 않음")
    ap.add_argument("--split-level", type=int, default=1, choices=[0, 1, 2, 3],
                    help="장 설정 파일이 없을 때만: 앞부분을 나눌 제목 단계 1 = ###(기본), 2 = ####까지, 3 = #####까지, 0 = 나누지 않음")
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
    try:
        cfg = load_config(config_path(out_dir, title))
    except ValueError as e:
        print(f"[오류] {e}")
        return 1
    parsed = parse_markdown(src.read_bytes().decode("utf-8"), out_dir, set(cfg["skip_pages"]) if cfg else frozenset(),
                            toc_pages(cfg) - set(cfg["skip_pages"]) if cfg else frozenset())
    plan = build_plan(parsed, cfg, count_pages(folder), args.split_level)
    kept = [c for c in plan.chapters if not c.exclude]
    figs = [b for c in kept for b in c.blocks if b.kind == "figure"]
    page_marks = not args.no_page_marks
    print(f"장 설정: {'있음 (' + str(len(cfg['chapters'])) + '개 챕터)' if cfg else '없음 (교정 글의 ## 제목을 챕터로 봄)'}")

    made = []
    files: list = []
    if args.only in (None, "ai"):
        p = out_dir / f"{title}_AI용.md"
        p.write_bytes(build_whole_ai(plan, title, page_marks).encode("utf-8"))
        made.append(("AI용 글", p))
        d = out_dir / f"{title}_AI용_나눔"
        d.mkdir(exist_ok=True)
        for old in d.glob("*.md"):  # 예전에 나눈 파일 지우기 (이 폴더는 내보내기 전용)
            old.unlink()
        files = split_files(plan, title, page_marks)
        for name, text in files:
            (d / name).write_bytes(text.encode("utf-8"))
        made.append((f"AI용 나눔 ({len(files)}개 파일)", d))
    if args.only in (None, "docx"):
        try:
            import docx  # noqa: F401
        except ImportError:
            print("[오류] python-docx 가 없어 Word 파일을 만들 수 없습니다. 설치.bat 를 다시 실행하세요.")
            return 1
        p = out_dir / f"{title}_완성본.docx"
        build_docx(docx_blocks(plan), title, out_dir, p, not args.no_caption)
        made.append(("완성본(Word)", p))

    print(f"완료: 그림 {len(figs)}개")
    for label, p in made:
        print(f"  {label}: {p.resolve()}")
    print_summary(plan, files)
    if cfg:  # 챕터 설정이 있는 책에 남은 # · ## 줄 (OCR이 큰 글자 줄에 붙인 ## 등. 챕터명·파트명과 같아 지워진 줄은 제외)
        stray = [b for c in kept for b in c.blocks if b.kind == "heading" and b.level <= 2]
        if stray:
            print(f"[주의] 본문에 # 또는 ## 줄이 {len(stray)}개 남아 있습니다 (챕터는 [챕터 시작]으로 정하므로 ### 이하로 바꾸거나 지우세요):")
            for b in stray[:30]:
                print(f"       책 {plan.labels.label(b.page)}쪽 (캡처 {b.page}): {'#' * b.level} {b.text}")
            if len(stray) > 30:
                print(f"       … 외 {len(stray) - 30}개")
    if parsed.missing_alt:
        pages = ", ".join(f"캡처 {n}쪽" if n else "쪽 미상" for n in parsed.missing_alt)
        print(f"[주의] 설명이 없는 그림 {len(parsed.missing_alt)}개 ({pages}) — AI용 글에는 '설명 없음'으로 들어갑니다."
              "\n       4_교정.bat 의 '그림 목록'에서 찾아 설명을 쓴 뒤 다시 내보내세요.")
    if parsed.missing_file:
        print(f"[주의] 그림 파일을 찾지 못함: {', '.join(parsed.missing_file)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
