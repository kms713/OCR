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
    python ebook_export.py books\\책이름 --page-marks    # AI용에 '[p.12]' 쪽 표시를 남김 (출처 표시용)
    python ebook_export.py books\\책이름 --no-caption    # Word 에 그림 설명 캡션을 넣지 않음

그림 줄은 교정 글 안의  ![설명](figures/p0012_01.png)  한 줄입니다. 설명이 비어 있는 그림은 끝에 알려 줍니다.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

PAGE_MARK = re.compile(r"^<!--\s*p\.(\d+)\s*-->\s*$")
FIGURE = re.compile(r"^!\[([^\]]*)\]\(([^)\s]+)\)\s*$")
HEADING = re.compile(r"^(#{1,4})\s+(.*\S)\s*$")  # # 제목, ## 대주제, ### 중주제, #### 소주제
# 글 속 서식: **굵게**, *기울임*, <u>밑줄</u> (편집기 버튼이 쓰는 형식)
# 기울임 *…* 은 앞뒤가 영문·숫자일 때만 제외 (2*3*4 같은 곱셈). 한글 조사가 바로 붙어도(*집단 지성*의) 인식
INLINE = re.compile(r"\*\*(.+?)\*\*|(?<![*A-Za-z0-9])\*(?!\s)(.+?)(?<!\s)\*(?![*A-Za-z0-9])|<u>(.+?)</u>")


def inline_runs(text: str) -> list[tuple[str, str]]:
    """'가 **나** <u>다</u>' → [('가 ', ''), ('나', 'b'), (' ', ''), ('다', 'u')]. 서식은 겹치지 않는 한 단계만."""
    out, k = [], 0
    for m in INLINE.finditer(text):
        if m.start() > k:
            out.append((text[k:m.start()], ""))
        if m.group(1) is not None:
            out.append((m.group(1), "b"))
        elif m.group(2) is not None:
            out.append((m.group(2), "i"))
        else:
            out.append((m.group(3), "u"))
        k = m.end()
    if k < len(text):
        out.append((text[k:], ""))
    return out


def ai_inline(text: str) -> str:
    """AI용 글: 굵게·기울임은 마크다운 그대로, 밑줄 태그는 지운다."""
    return re.sub(r"</?u>", "", text)


def add_inline(p, text: str, size=None, color=None, italic=None):
    """Word 문단에 서식 있는 글 넣기."""
    for t, f in inline_runs(text):
        r = p.add_run(t)
        r.bold = True if f == "b" else None
        r.italic = True if f == "i" else italic
        r.underline = True if f == "u" else None
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
    kind: str  # title | heading | note | figure | para | page
    text: str = ""
    level: int = 1
    page: int = 0
    src: str = ""  # figure 파일 경로


@dataclass
class Parsed:
    blocks: list[Block] = field(default_factory=list)
    missing_alt: list[int] = field(default_factory=list)  # 설명 없는 그림이 있는 쪽
    missing_file: list[str] = field(default_factory=list)


def parse_markdown(text: str, base: Path) -> Parsed:
    out = Parsed()
    page = 0
    first_h1 = True
    for raw in text.replace("\r\n", "\n").replace(SOFT, "").split("\n"):
        line = raw.rstrip()
        if not line.strip():
            continue
        m = PAGE_MARK.match(line.strip())
        if m:
            page = int(m.group(1))
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
            continue
        m = HEADING.match(line.strip())
        if m:
            level = len(m.group(1))
            if level == 1 and first_h1:
                out.blocks.append(Block("title", m.group(2)))
                first_h1 = False
            else:
                out.blocks.append(Block("heading", m.group(2), level=max(1, level - 1) if level > 1 else 1, page=page))
            continue
        m = NOTE.match(line.strip())
        if m:
            out.blocks.append(Block("note", m.group(1).strip(), page=page))
            continue
        out.blocks.append(Block("para", line.strip(), page=page))
    return out


# ----------------------------------------------------------------------------
# AI용 Markdown
# ----------------------------------------------------------------------------
def build_ai_markdown(parsed: Parsed, title: str, page_marks: bool) -> str:
    lines: list[str] = []
    has_title = any(b.kind == "title" for b in parsed.blocks)
    if not has_title:
        lines += [f"# {title}", ""]
    for b in parsed.blocks:
        if b.kind == "title":
            lines += [f"# {b.text}", ""]
        elif b.kind == "heading":
            lines += ["#" * (b.level + 1) + f" {ai_inline(b.text)}", ""]
        elif b.kind == "note":
            lines += [f"> {ai_inline(b.text)}", ""]
        elif b.kind == "figure":
            desc = b.text or (f"(설명 없음 — 원본 {b.page}쪽)" if b.page else NO_ALT)
            lines += [f"> [그림] {desc}", ""]
        elif b.kind == "page":
            if page_marks:
                lines += [f"[p.{b.page}]", ""]
        else:
            lines += [ai_inline(b.text), ""]
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


def build_docx(parsed: Parsed, title: str, base: Path, path: Path, captions: bool) -> int:
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
    for i, size in ((1, 16), (2, 13), (3, 11.5)):
        _set_font(st[f"Heading {i}"], LATIN_FONT, BODY_FONT, size, True, RGBColor(0x1D, 0x23, 0x30))

    has_title = any(b.kind == "title" for b in parsed.blocks)
    if not has_title:
        doc.add_paragraph(title, style="Title")

    n_fig = 0
    for b in parsed.blocks:
        if b.kind == "title":
            doc.add_paragraph(b.text, style="Title")
        elif b.kind == "heading":
            h = doc.add_heading("", level=min(3, b.level))
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
        elif b.kind == "para":
            add_inline(doc.add_paragraph(), b.text)
        # page 표시는 완성본에 넣지 않음
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    return n_fig


# ----------------------------------------------------------------------------
def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="교정한 글 → 사람용 Word(.docx) + AI용 Markdown")
    ap.add_argument("folder", help="page_0001.png ... 가 들어 있는 폴더 (결과 폴더는 <폴더>_OCR)")
    ap.add_argument("-o", "--output", help="OCR 결과 폴더 (기본: <폴더>_OCR)")
    ap.add_argument("--title", help="책 제목 (기본: 폴더 이름)")
    ap.add_argument("--only", choices=["docx", "ai"], help="한 가지만 만들기")
    ap.add_argument("--page-marks", action="store_true", help="AI용 글에 [p.N] 쪽 표시를 남김")
    ap.add_argument("--no-caption", action="store_true", help="Word 에 그림 설명 캡션을 넣지 않음")
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
    parsed = parse_markdown(src.read_bytes().decode("utf-8"), out_dir)
    figs = [b for b in parsed.blocks if b.kind == "figure"]

    made = []
    if args.only in (None, "ai"):
        p = out_dir / f"{title}_AI용.md"
        p.write_bytes(build_ai_markdown(parsed, title, args.page_marks).encode("utf-8"))
        made.append(("AI용 글", p))
    if args.only in (None, "docx"):
        try:
            import docx  # noqa: F401
        except ImportError:
            print("[오류] python-docx 가 없어 Word 파일을 만들 수 없습니다. 설치.bat 를 다시 실행하세요.")
            return 1
        p = out_dir / f"{title}_완성본.docx"
        build_docx(parsed, title, out_dir, p, not args.no_caption)
        made.append(("완성본(Word)", p))

    print(f"완료: 그림 {len(figs)}개")
    for label, p in made:
        print(f"  {label}: {p.resolve()}")
    if parsed.missing_alt:
        pages = ", ".join(f"{n}쪽" if n else "쪽 미상" for n in parsed.missing_alt)
        print(f"[주의] 설명이 없는 그림 {len(parsed.missing_alt)}개 ({pages}) — AI용 글에는 '설명 없음'으로 들어갑니다."
              "\n       4_교정.bat 의 '그림 목록'에서 찾아 설명을 쓴 뒤 다시 내보내세요.")
    if parsed.missing_file:
        print(f"[주의] 그림 파일을 찾지 못함: {', '.join(parsed.missing_file)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
