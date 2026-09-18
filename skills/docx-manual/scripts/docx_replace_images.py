#!/usr/bin/env python3
"""Replace screenshots inside an existing .docx without touching anything else.

The media bytes are swapped by rewriting the zip entry, so the document XML,
styles, numbering and every other picture stay byte-identical — far safer than
re-generating the document when all you did was re-shoot a screen.

Targets (``KEY``) can be:

* a media name — ``image50.png`` (see ``docx_inspect.py --figures``);
* ``caption:<substring>`` — the picture whose caption contains that text.
  Add ``#0`` / ``#1`` when two pictures share one caption (left/right layout),
  e.g. ``caption:圖 12：登入頁#1``.

By default the new PNG is resampled to the **old pixel size**, so the picture
occupies exactly the same box on the page.  With ``--no-resize`` the bytes go in
untouched and the drawing's ``wp:extent``/``a:ext`` are rescaled instead, which
keeps the displayed width and adopts the new image's aspect ratio.

Examples::

    python docx_replace_images.py manual.docx --set image50.png=shots/login.png
    python docx_replace_images.py manual.docx --set 'caption:圖 12：登入頁=shots/login.png'
    python docx_replace_images.py manual.docx --map replace_map.json --no-resize
"""

from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import sys
import zipfile

import docx
from docx.oxml.ns import qn
from PIL import Image

sys.path.insert(0, __file__.rsplit('/', 1)[0])
from docxkit import backup_path, figures, human_size  # noqa: E402


def resolve(figs, key):
    """Map one KEY to a figure dict, or raise ``SystemExit`` explaining the miss."""
    if not key.startswith('caption:'):
        hits = [f for f in figs if f['media_name'] == key]
        if not hits:
            names = sorted({f['media_name'] for f in figs})
            raise SystemExit('KEY %r matches no media. Known: %s' % (key, ', '.join(names)))
        return hits[0]

    spec = key[len('caption:'):]
    pick = None
    if '#' in spec:
        spec, _, idx = spec.rpartition('#')
        if not idx.isdigit():
            raise SystemExit('KEY %r: expected #<number> after the caption' % key)
        pick = int(idx)
    hits = [f for f in figs if spec in f['caption']]
    if not hits:
        raise SystemExit('KEY %r matches no caption' % key)
    captions = sorted({f['caption'] for f in hits})
    if len(captions) > 1:
        raise SystemExit('KEY %r matches %d captions:\n  %s'
                         % (key, len(captions), '\n  '.join(c[:70] for c in captions)))
    if pick is None:
        if len(hits) > 1:
            raise SystemExit('KEY %r matches %d pictures under one caption; '
                             'add #0..#%d' % (key, len(hits), len(hits) - 1))
        return hits[0]
    if pick >= len(hits):
        raise SystemExit('KEY %r: only %d picture(s) under that caption' % (key, len(hits)))
    return hits[pick]


def resized_png(src, size):
    """New image bytes resampled to `size` (LANCZOS), as optimised PNG."""
    with Image.open(src) as im:
        im = im.convert('RGB').resize(size, Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, 'PNG', optimize=True)
        return buf.getvalue()


def rescale_extent(doc, rid, new_size):
    """Keep the displayed width, adopt the new aspect ratio, for the drawing using `rid`.

    ``wp:extent`` (the layout box) and ``pic:spPr/a:xfrm/a:ext`` (the picture's
    own frame) are both in EMU and must stay consistent, or Word squashes the
    image.
    """
    nw, nh = new_size
    for blip in doc.element.body.iter(qn('a:blip')):
        if blip.get(qn('r:embed')) != rid:
            continue
        anchor = blip
        while anchor is not None and anchor.tag not in (qn('wp:inline'), qn('wp:anchor')):
            anchor = anchor.getparent()
        if anchor is None:
            continue
        ext = anchor.find(qn('wp:extent'))
        if ext is None:
            continue
        cx = int(ext.get('cx'))
        cy = int(round(cx * nh / float(nw)))
        ext.set('cy', str(cy))
        for aext in anchor.iter(qn('a:ext')):
            aext.set('cx', str(cx))
            aext.set('cy', str(cy))
        return True
    return False


def rewrite_zip(src_path, dst_path, media):
    """Copy the zip `src_path` to `dst_path`, substituting ``word/media`` entries.

    `media` maps a media base name to the replacement bytes.
    """
    tmp = dst_path + '.tmp'
    with zipfile.ZipFile(src_path) as zin, \
            zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            base = item.filename.split('/')[-1]
            if item.filename.startswith('word/media/') and base in media:
                data = media[base]
            zout.writestr(item, data)
    os.replace(tmp, dst_path)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('docx', help='document to patch')
    ap.add_argument('--set', action='append', default=[], metavar='KEY=PNG',
                    help='replacement; repeatable')
    ap.add_argument('--map', metavar='JSON', help='JSON file of {KEY: PNG} replacements')
    ap.add_argument('--out', metavar='OUT', help='write here instead of in place')
    ap.add_argument('--no-backup', action='store_true', help='do not write a .bak.docx')
    ap.add_argument('--no-resize', action='store_true',
                    help='keep the new image size and rescale the drawing instead')
    ap.add_argument('--backup-tag', help='extra tag in the backup file name')
    args = ap.parse_args(argv)

    pairs = {}
    if args.map:
        with open(args.map, encoding='utf-8') as fh:
            pairs.update(json.load(fh))
    for item in args.set:
        key, sep, png = item.partition('=')
        if not sep:
            raise SystemExit('--set expects KEY=PNG, got %r' % item)
        pairs[key] = png
    if not pairs:
        raise SystemExit('nothing to do: pass --set or --map')

    missing = [p for p in pairs.values() if not os.path.exists(p)]
    if missing:
        raise SystemExit('missing replacement image(s):\n  ' + '\n  '.join(missing))

    doc = docx.Document(args.docx)
    figs = figures(doc)

    plan = []  # (figure, png path)
    seen = {}
    for key, png in pairs.items():
        fig = resolve(figs, key)
        if fig['media_name'] in seen:
            raise SystemExit('KEY %r and %r both target %s'
                             % (key, seen[fig['media_name']], fig['media_name']))
        seen[fig['media_name']] = key
        plan.append((key, fig, png))

    out = args.out or args.docx
    if not args.no_backup:
        bak = backup_path(args.docx, args.backup_tag)
        shutil.copy2(args.docx, bak)
        print('backup: %s' % bak)

    media = {}
    for key, fig, png in plan:
        old_size = (fig['width'], fig['height'])
        if args.no_resize:
            with open(png, 'rb') as fh:
                data = fh.read()
            with Image.open(png) as im:
                new_size = im.size
            rescale_extent(doc, fig['rid'], new_size)
            note = '%dx%d -> %dx%d (drawing rescaled)' % (old_size + new_size)
        else:
            data = resized_png(png, old_size)
            note = '%dx%d kept' % old_size
        media[fig['media_name']] = data
        print('%-14s %-22s <- %s (%d KB)  [%s]'
              % (fig['media_name'], fig['caption'][:22] or '-', os.path.basename(png),
                 len(data) // 1024, note))

    src = args.docx
    if args.no_resize:
        # the XML changed, so round-trip through python-docx before the zip swap
        src = out + '.xmltmp'
        doc.save(src)
    rewrite_zip(src, out, media)
    if src != args.docx:
        os.remove(src)

    docx.Document(out)  # fails loudly if the result is not a valid package
    print('-- %d image(s) replaced, %s -> %s' % (len(plan), human_size(out), out))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
