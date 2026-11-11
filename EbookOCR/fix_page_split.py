#!/usr/bin/env python3
"""
쪽 나누기 고치기 (이미 교정 중인 책용)
=====================================

예전 판 OCR 은 쪽 끝 문장이 마침표 없이 끝나면 다음 쪽 첫 문단을 앞 쪽 마지막 문단에 붙였습니다.
그래서 교정 편집기에서 한 쪽을 보면 다음 쪽 글이 섞여 보입니다 (표·상자처럼 마침표 없이 끝나는 쪽에서 특히).

이 도구는 '책이름_교정.md'(그동안 고친 내용 그대로)에서 붙어 있던 다음 쪽 글을 찾아 제 쪽으로 돌려놓고
'<!-- p.N 이어짐 -->' 표시를 남깁니다. 내보낼 때(ebook_export.py)는 이 표시를 보고 다시 한 문단으로 이어 붙입니다.

어디서 나누는지는 OCR 캐시(쪽별 인식 결과)로 다시 계산합니다. 글자를 고친 곳 때문에 찾지 못한 쪽은 목록으로
알려 주니 편집기에서 손으로 옮기세요 (잘라내기 → 다음 쪽 → 맨 위에 붙여넣기).

사용: python fix_page_split.py books\\책이름        (쪽나누기_고치기.bat)
      먼저 바뀔 쪽을 보여 주고, y 를 눌러야 고칩니다. 고치기 전 파일은 '책이름_교정.md.쪽나누기전' 으로 남깁니다.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

from bookdir import resolve, result_dir

SKIP = {" ", "\t", "\n", "\r", "⁠", "*"}  # 맞춰 볼 때 무시하는 글자 (띄어쓰기·줄 경계 표시·굵게 기울임 표시)
MARK = re.compile(r"<!-- p\.(\d+)( 이어짐)? -->")


def squeeze(s: str, base: int = 0) -> tuple[str, list[int]]:
    """띄어쓰기·서식 표시를 뺀 글자와, 각 글자의 원래 위치."""
    out, pos, i = [], [], 0
    while i < len(s):
        if s.startswith("<u>", i):
            i += 3
            continue
        if s.startswith("</u>", i):
            i += 4
            continue
        if s[i] not in SKIP:
            out.append(s[i])
            pos.append(base + i)
        i += 1
    return "".join(out), pos


def continuations(folder: Path, out_dir: Path) -> list[tuple[int, str]]:
    """(쪽 번호, 그 쪽 첫 문단 글) — 앞 쪽 마지막 문단에서 이어진다고 OCR 이 판단한 쪽들."""
    import ebook_ocr as eo

    files = eo.collect_pages(folder)
    pages = []
    for f in files:
        cf = out_dir / "cache" / f"{f.stem}.json"
        if not cf.is_file():
            raise FileNotFoundError(f"OCR 캐시가 없습니다: {cf}")
        pages.append(eo.page_from_json(json.loads(cf.read_bytes().decode("utf-8"))))
    eo.drop_screenshots(pages)
    eo.apply_exclusions(pages, out_dir, folder.name)
    eo.strip_headers(pages, 0.1)  # ebook_ocr 기본값과 같게
    paras = eo.build_paragraphs(pages, merge=False)
    return [(x.page, x.text) for x in paras if x.cont]


def split_pages(text: str, conts: list[tuple[int, str]]) -> tuple[str, list[int], list[int]]:
    fixed, failed = [], []
    for no, first in conts:
        if f"<!-- p.{no} 이어짐 -->" in text:
            continue
        ms = list(MARK.finditer(text))
        start = max((m.end() for m in ms if int(m.group(1)) < no), default=0)
        own = next((m for m in ms if int(m.group(1)) == no and not m.group(2)), None)
        later = [m.start() for m in ms if int(m.group(1)) > no and m.start() > start]
        end = own.start() if own else (min(later) if later else len(text))
        win, pos = squeeze(text[start:end], start)
        key_src, _ = squeeze(first)
        at = -1
        for n in (14, 9, 5):  # 고친 글자 때문에 못 찾으면 짧게 다시
            key = key_src[:n]
            if len(key) < 4:
                break
            k = win.rfind(key)
            if k >= 0:
                at = pos[k]
                break
        if at < 0:
            failed.append(no)
            continue
        while at > 0 and (text[at - 1] == "*" or text.endswith("<u>", 0, at)):  # 붙어 있는 여는 서식 표시는 뒤 글과 함께
            at -= 3 if text.endswith("<u>", 0, at) else 1
        before, after = text[:at].rstrip(" \t"), text[at:].lstrip(" \t")
        text = before + f"\n\n<!-- p.{no} 이어짐 -->\n\n" + after
        if own is not None:  # 예전 쪽 표시는 이제 필요 없음 (그 쪽 글은 새 표시 뒤에 이어 있음)
            k = text.find(f"<!-- p.{no} -->", len(before))
            if k >= 0:
                text = text[:k] + text[k + len(f"<!-- p.{no} -->"):]
        fixed.append(no)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text, fixed, failed


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="교정 글에서 앞 쪽에 붙어 있던 다음 쪽 글을 제 쪽으로 돌려놓기")
    ap.add_argument("folder", help="쪽 이미지 폴더 (books\\책이름)")
    ap.add_argument("-o", "--output")
    ap.add_argument("--title")
    ap.add_argument("--yes", action="store_true", help="묻지 않고 고침")
    args = ap.parse_args(argv)
    folder = resolve(args.folder)
    out_dir = result_dir(folder, args.output, args.title)
    title = args.title or folder.name
    work = out_dir / f"{title}_교정.md"
    if not work.is_file():
        work = out_dir / f"{title}_교정용.md"  # 아직 편집기를 한 번도 안 열었으면 교정용을 고친다
    if not work.is_file():
        print(f"[오류] 교정 파일이 없습니다: {out_dir}")
        return 1
    try:
        conts = continuations(folder, out_dir)
    except (OSError, ValueError) as e:
        print(f"[오류] {e}")
        return 1
    text = work.read_bytes().decode("utf-8").replace("\r\n", "\n")
    new, fixed, failed = split_pages(text, conts)
    print(f"파일: {work}")
    print(f"앞 쪽에 붙어 있던 쪽: {len(conts)}곳 → 돌려놓을 수 있음 {len(fixed)}곳, 못 찾음 {len(failed)}곳")
    if fixed:
        print("  돌려놓을 쪽:", ", ".join(map(str, fixed)))
    if failed:
        print("  못 찾은 쪽 (편집기에서 손으로 옮기세요):", ", ".join(map(str, failed)))
    if not fixed:
        print("고칠 것이 없습니다.")
        return 0
    if not args.yes and input("고칠까요? [y/N] ").strip().lower() != "y":
        print("그대로 두었습니다.")
        return 0
    backup = work.with_name(work.name + ".쪽나누기전")
    if not backup.exists():
        shutil.copyfile(work, backup)
    tmp = work.with_suffix(".md.tmp")
    tmp.write_bytes(new.encode("utf-8"))
    tmp.replace(work)
    print(f"고쳤습니다. 고치기 전 파일: {backup.name}")
    print("편집기(4_교정.bat)를 다시 여세요. 나뉜 문단의 AI 제안은 6_AI교정제안.bat 를 다시 실행하면 새로 받습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
