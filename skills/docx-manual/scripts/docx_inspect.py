#!/usr/bin/env python3
"""Dump the body structure of a .docx: one line per element, plus optional figure list.

Use this first whenever you need to patch an existing manual — the printed
index and text prefixes are exactly what ``docx_extract.py`` specs and
``find_prefix()`` take as ``start``/``end`` anchors.

Examples::

    python docx_inspect.py manual.docx
    python docx_inspect.py manual.docx --grep '[NEW 2.3]'
    python docx_inspect.py manual.docx --figures
    python docx_inspect.py manual.docx --figures --json > figures.json
"""

from __future__ import annotations

import argparse
import json
import sys

import docx
from docx.oxml.ns import qn

sys.path.insert(0, __file__.rsplit('/', 1)[0])
from docxkit import (  # noqa: E402
    body_elements, figures, has_image, has_sdt, is_hr, is_pagebreak, ptext,
    style_id,
)


def describe(doc):
    """Yield ``(index, flags, style, text)`` for every body element."""
    for i, el in enumerate(body_elements(doc)):
        tag = el.tag.split('}')[-1]
        if tag == 'p':
            flags = []
            if has_image(el):
                flags.append('IMG')
            if is_hr(el):
                flags.append('HR')
            if is_pagebreak(el):
                flags.append('PAGEBREAK')
            if has_sdt(el):
                flags.append('SDT')
            yield i, flags, style_id(el) or 'normal', ptext(el).replace('\n', ' ')
        elif tag == 'tbl':
            t = docx.table.Table(el, doc)
            head = t.rows[0].cells[0].text.strip() if t.rows else ''
            yield i, ['TABLE %dx%d' % (len(t.rows), len(t.columns))], style_id(el) or 'table', head
        else:
            yield i, [tag], '', ''


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('docx', help='path to the .docx to inspect')
    ap.add_argument('--figures', action='store_true',
                    help='list pictures (media name, size, md5, caption)')
    ap.add_argument('--json', action='store_true', help='emit JSON instead of text')
    ap.add_argument('--grep', metavar='TEXT',
                    help='only show elements whose text contains TEXT')
    ap.add_argument('--width', type=int, default=110, help='text truncation width')
    args = ap.parse_args(argv)

    doc = docx.Document(args.docx)
    figs = figures(doc) if args.figures else []

    if args.json:
        rows = [{'index': i, 'flags': f, 'style': s, 'text': t}
                for i, f, s, t in describe(doc)
                if (not args.grep or args.grep in t)]
        out = {'body': rows}
        if args.figures:
            out['figures'] = figs
        json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
        print()
        return 0

    shown = 0
    for i, flags, style, text in describe(doc):
        if args.grep and args.grep not in text:
            continue
        if not text and not flags:
            continue
        mark = ''.join(' [%s]' % f for f in flags)
        print('%04d [%s]%s %s' % (i, style, mark, text[:args.width]))
        shown += 1
    print('-- %d element(s) shown' % shown)

    if args.figures:
        print()
        print('-- %d figure(s)' % len(figs))
        for n, f in enumerate(figs, 1):
            size = '%sx%s' % (f['width'], f['height']) if f['width'] else '?'
            print('%3d  %-14s %-11s %s  %s'
                  % (n, f['media_name'], size, f['md5'][:10], f['caption'][:60]))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
