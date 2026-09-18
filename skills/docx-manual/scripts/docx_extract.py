#!/usr/bin/env python3
"""Assemble a derived .docx (a "what changed" document) out of one or more manuals.

You give a JSON spec that names a *package* document — it supplies the styles,
headers/footers and page setup, and becomes the output — plus any number of
*source* documents to pull ranges of body elements from.  New headings,
paragraphs, tables, rules and page breaks are cloned from the package, so the
result looks like it was written in the same manual.

Spec format::

    {
      "package": "ops.docx",
      "sources": {"ops": "ops.docx", "scn": "scenarios.docx"},
      "title": "Release notes",
      "templates": {"h1": "text prefix picking the H1 template"},
      "fixes": [["詳見第三節", "詳見下文"]],
      "parts": [
        {"heading": [1, "Release notes"]},
        {"para": "Screenshots taken on dev.", "bold_prefix": "Environment: "},
        {"hr": true},
        {"pagebreak": true},
        {"table": [["System", "New"], ["HQ", "Feedback"]]},
        {"range": {"from": "ops", "start": "1. Login", "end": "Figure 4:",
                   "after": "HQ console"}},
        {"one":   {"from": "ops", "start": "Menu"}},
        {"figure":{"from": "ops", "caption": "Figure 10-1:"}}
      ]
    }

``range``/``one``/``figure`` select by **text prefix**, which survives edits far
better than element indexes; use ``docx_inspect.py`` to find the prefixes, and
``after`` to disambiguate a prefix that occurs more than once.

After assembly the script applies the ``fixes`` text replacements (asserting
none of them was split across runs, which would silently leave stale
cross-references), renumbers every figure caption into one 1..N sequence, makes
``wp:docPr`` ids unique, and prunes image parts the body no longer references.

Example::

    python docx_extract.py --spec extract_spec.json --out release-notes.docx
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys

import docx
from docx.oxml.ns import qn

sys.path.insert(0, __file__.rsplit('/', 1)[0])
from docxkit import (  # noqa: E402
    FIGURE_FORMAT, FIGURE_PATTERN, Importer, TemplateSet, append_elements,
    clear_body, clone_heading, clone_hr, clone_pagebreak, clone_para,
    clone_table, find_prefix, find_range, has_image, human_size,
    prune_unused_images, ptext, renumber_figures, unique_docpr_ids,
)


class Extractor:
    """Turns a spec dict into a list of body elements for the package document."""

    def __init__(self, spec, base_dir='.'):
        self.spec = spec
        self.base = base_dir
        pkg_path = self._path(spec['package'])
        self.package = docx.Document(pkg_path)
        self.templates = TemplateSet.from_doc(self.package,
                                              overrides=spec.get('templates'))
        # Detach templates before the body is cleared, so cloning still works.
        for field in TemplateSet.FIELDS:
            el = getattr(self.templates, field)
            setattr(self.templates, field, copy.deepcopy(el) if el is not None else None)

        self.sources = {}     # name -> (Document, [elements], Importer)
        for name, path in spec.get('sources', {}).items():
            full = self._path(path)
            doc = self.package if os.path.abspath(full) == os.path.abspath(pkg_path) \
                else docx.Document(full)
            els = list(doc.element.body.iterchildren())
            self.sources[name] = (doc, els, Importer(doc, self.package))
        self.out = []

    def _path(self, p):
        return p if os.path.isabs(p) else os.path.join(self.base, p)

    def _src(self, name):
        if name not in self.sources:
            raise SystemExit('unknown source %r (have: %s)'
                             % (name, ', '.join(sorted(self.sources))))
        return self.sources[name]

    # -- part kinds --------------------------------------------------------
    def part(self, part):
        if 'heading' in part:
            level, text = part['heading']
            tpl = getattr(self.templates, 'h%d' % level)
            if tpl is None:
                raise SystemExit('package has no H%d template' % level)
            self.out.append(clone_heading(tpl, text))
        elif 'para' in part:
            self.templates.require('body')
            self.out.append(clone_para(self.templates.body, part['para'],
                                       part.get('bold_prefix')))
        elif 'hr' in part:
            self.out.append(clone_hr(self.templates.hr))
        elif 'pagebreak' in part:
            self.out.append(clone_pagebreak(self.templates.pagebreak))
        elif 'table' in part:
            self.templates.require('table')
            self.out.append(clone_table(self.templates.table, part['table']))
        elif 'range' in part:
            self.out.extend(self._range(part['range']))
        elif 'one' in part:
            self.out.extend(self._one(part['one']))
        elif 'figure' in part:
            self.out.extend(self._figure(part['figure']))
        else:
            raise SystemExit('unknown part: %r' % part)

    def _start_at(self, els, sel):
        after = sel.get('after')
        return find_prefix(els, after) if after else 0

    def _range(self, sel):
        _, els, imp = self._src(sel['from'])
        start = self._start_at(els, sel)
        got = find_range(els, sel['start'], sel['end'], start)
        return [imp.copy(e) for e in got]

    def _one(self, sel):
        _, els, imp = self._src(sel['from'])
        start = self._start_at(els, sel)
        return [imp.copy(els[find_prefix(els, sel['start'], start)])]

    def _figure(self, sel):
        """A picture paragraph plus its caption, selected by the caption prefix."""
        _, els, imp = self._src(sel['from'])
        start = self._start_at(els, sel)
        i = find_prefix(els, sel['caption'], start)
        if i == 0 or not has_image(els[i - 1]):
            raise SystemExit('no picture paragraph before caption %r' % sel['caption'])
        return [imp.copy(els[i - 1]), imp.copy(els[i])]

    # -- assembly ----------------------------------------------------------
    def build(self):
        for part in self.spec.get('parts', []):
            self.part(part)
        self.apply_fixes()
        return self.out

    def apply_fixes(self):
        """Replace stale cross-references; fail if a phrase is split across runs.

        A phrase broken over two ``w:r`` elements would silently survive a
        naive replace, so the assertion is the point of this step.
        """
        fixes = [tuple(f) for f in self.spec.get('fixes', [])]
        if not fixes:
            return
        for el in self.out:
            for t in el.iter(qn('w:t')):
                if not t.text:
                    continue
                for a, b in fixes:
                    if a in t.text:
                        t.text = t.text.replace(a, b)
        for el in self.out:
            txt = ptext(el)
            for a, _ in fixes:
                if a in txt:
                    raise SystemExit('fix %r is split across runs in: %s' % (a, txt[:70]))

    def finish(self, out_path):
        doc = self.package
        clear_body(doc)
        append_elements(doc, self.out)
        n_figs = renumber_figures(
            self.out,
            self.spec.get('figure_pattern', FIGURE_PATTERN),
            self.spec.get('figure_format', FIGURE_FORMAT))
        unique_docpr_ids(self.out)
        dropped = prune_unused_images(doc)
        if self.spec.get('title'):
            doc.core_properties.title = self.spec['title']
        doc.save(out_path)
        return n_figs, dropped


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--spec', required=True, help='JSON spec file')
    ap.add_argument('--out', required=True, help='output .docx')
    ap.add_argument('--base-dir',
                    help='directory relative paths in the spec resolve against '
                         '(default: the spec file’s directory)')
    args = ap.parse_args(argv)

    with open(args.spec, encoding='utf-8') as fh:
        spec = json.load(fh)
    base = args.base_dir or os.path.dirname(os.path.abspath(args.spec))

    ex = Extractor(spec, base)
    els = ex.build()
    n_figs, dropped = ex.finish(args.out)
    print('-- %s: %d element(s), %d figure(s), %d unused image part(s) pruned, %s'
          % (args.out, len(els), n_figs, dropped, human_size(args.out)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
