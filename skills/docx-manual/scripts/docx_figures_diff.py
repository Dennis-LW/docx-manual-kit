#!/usr/bin/env python3
"""Compare the figures of two manual revisions and report NEW / RESHOT / REMOVED.

Figures are matched by **caption title** — the text after the figure number and
colon — not by position or media name, because both shift between revisions
(``image50.png`` is not the same picture in two different .docx files, and
inserting one screenshot renumbers everything after it).

Example::

    python docx_figures_diff.py manual-v1.docx manual-v2.docx
    python docx_figures_diff.py old.docx new.docx --caption-pattern '^Figure\\s*[\\d.-]+\\s*[:：]'
"""

from __future__ import annotations

import argparse
import re
import sys

import docx

sys.path.insert(0, __file__.rsplit('/', 1)[0])
from docxkit import FIGURE_PATTERN, figures  # noqa: E402


def collect(path, rx):
    """``{caption title: (label, [md5, ..])}`` for one document.

    Two pictures sharing one caption (a left/right pair) become one entry with
    two hashes, so a reshot of either side is reported once.
    """
    doc = docx.Document(path)
    out = {}
    for f in figures(doc):
        cap = f['caption']
        if not cap or not rx.match(cap):
            continue
        label = rx.match(cap).group(0).strip()
        title = cap[rx.match(cap).end():].strip()
        entry = out.setdefault(title, [label, []])
        entry[1].append(f['md5'][:10])
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('old', help='previous revision (.docx)')
    ap.add_argument('new', help='current revision (.docx)')
    ap.add_argument('--caption-pattern', default=FIGURE_PATTERN,
                    help='regex matching the figure number prefix of a caption')
    ap.add_argument('--show-same', action='store_true', help='also list unchanged figures')
    args = ap.parse_args(argv)

    rx = re.compile(args.caption_pattern)
    old, new = collect(args.old, rx), collect(args.new, rx)

    counts = {'NEW': 0, 'RESHOT': 0, 'REMOVED': 0, 'SAME': 0}
    for title, (label, hashes) in new.items():
        if title not in old:
            status = 'NEW'
        elif old[title][1] != hashes:
            status = 'RESHOT'
        else:
            status = 'SAME'
        counts[status] += 1
        if status != 'SAME' or args.show_same:
            print('%-8s %-10s %s' % (status, label, title[:60]))
    for title, (label, _) in old.items():
        if title not in new:
            counts['REMOVED'] += 1
            print('%-8s %-10s %s' % ('REMOVED', label, title[:60]))

    print('-- old %d, new %d | new %d, reshot %d, removed %d, same %d'
          % (len(old), len(new), counts['NEW'], counts['RESHOT'],
             counts['REMOVED'], counts['SAME']))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
