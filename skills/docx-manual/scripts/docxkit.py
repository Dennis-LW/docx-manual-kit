"""docxkit — a small toolkit for building and patching .docx operation manuals.

This module is both an importable library and the shared base for the sibling
scripts (``docx_inspect.py``, ``docx_build.py``, ``docx_extract.py``,
``docx_replace_images.py``, ``docx_figures_diff.py``).

Why it exists: python-docx's convenience API is not enough for real manuals.
The recurring problems this module solves, and the gotcha behind each one:

* **Google-Docs-exported headings wrap their runs in ``w:sdt``**, so
  ``paragraph.text`` comes back empty.  Always read text with :func:`ptext`.
* **Media names are per-file.**  ``image50.png`` in one manual is not the same
  screenshot as ``image50.png`` in another.  Address figures by caption
  (:func:`figures`) when you work across documents.
* **Word refuses to open a file with duplicate ``wp:docPr`` ids**, which is
  exactly what you get after deep-copying picture paragraphs.  Call
  :func:`unique_docpr_ids` before saving.
* **Unreferenced image parts are not dropped automatically**, so a document
  derived from a 40 MB manual stays 40 MB.  Call :func:`prune_unused_images`.
* **Numbering and table styles live outside the element you copy.**  Use
  :class:`Importer` to carry them across documents.

Everything here works on lxml elements (``CT_P`` / ``CT_Tbl``) rather than
python-docx proxy objects, because cloning and splicing raw elements is the
only way to reuse an existing manual's look as a template.
"""

from __future__ import annotations

import copy
import datetime as _dt
import hashlib
import io
import os
import re

import docx
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Cm

try:  # Pillow is optional for the pure-XML helpers
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None

XML_SPACE = '{http://www.w3.org/XML/1998/namespace}space'
VML_IMAGEDATA = '{urn:schemas-microsoft-com:vml}imagedata'

__all__ = [
    'ptext', 'body_elements', 'find_prefix', 'find_range',
    'element_kind', 'has_image', 'is_hr', 'is_pagebreak', 'has_sdt', 'style_id',
    'set_text', 'clone_para', 'clone_para_runs', 'clone_heading', 'clone_table',
    'clone_hr', 'clone_pagebreak', 'TemplateSet', 'Importer', 'add_figure',
    'renumber_figures', 'unique_docpr_ids', 'prune_unused_images', 'clear_body',
    'append_elements', 'figures', 'backup_path',
    'FIGURE_PATTERN', 'FIGURE_FORMAT',
]

FIGURE_PATTERN = r'^(圖|Figure|Fig\.)\s*[\d\-\.]+\s*[：:]'
FIGURE_FORMAT = '圖 {n}：'


# --------------------------------------------------------------------------
# reading
# --------------------------------------------------------------------------

def ptext(el):
    """All text of an element, joined and stripped.

    Gotcha: Google Docs wraps heading runs in ``w:sdt``, which makes
    ``python-docx``'s ``Paragraph.text`` return ``''``.  Walking every ``w:t``
    descendant is the only reliable way to read a paragraph's text.
    """
    return ''.join(t.text or '' for t in el.iter(qn('w:t'))).strip()


def body_elements(doc):
    """Top-level body children of a document, in order (paragraphs, tables, sectPr)."""
    return list(doc.element.body.iterchildren())


def find_prefix(els, prefix, start=0):
    """Index of the first paragraph/table at or after `start` whose text starts with `prefix`.

    Raises ``KeyError`` with the prefix so failures point at the missing text.
    """
    for i in range(start, len(els)):
        if els[i].tag in (qn('w:p'), qn('w:tbl')) and ptext(els[i]).startswith(prefix):
            return i
    raise KeyError(prefix)


def find_range(els, start_prefix, end_prefix, start=0):
    """Inclusive slice of `els` from `start_prefix` to the following `end_prefix`."""
    s = find_prefix(els, start_prefix, start)
    e = find_prefix(els, end_prefix, s)
    return els[s:e + 1]


def element_kind(el):
    """``'p'``, ``'tbl'``, ``'sectPr'`` or the raw local tag name."""
    tag = el.tag.split('}')[-1]
    return tag if tag in ('p', 'tbl', 'sectPr') else tag


def has_image(el):
    """True if the element contains a DrawingML picture."""
    return bool(el.findall('.//' + qn('w:drawing')))


def is_hr(el):
    """True for a horizontal rule.

    Two shapes count: the ``w:pict`` line Google Docs exports, and the empty
    paragraph carrying only a bottom border that Word (and this kit's fallback)
    produces.
    """
    if el.findall('.//' + qn('w:pict')):
        return True
    if el.tag != qn('w:p') or ptext(el) or has_image(el):
        return False
    ppr = el.find(qn('w:pPr'))
    if ppr is None:
        return False
    bdr = ppr.find(qn('w:pBdr'))
    return bdr is not None and bdr.find(qn('w:bottom')) is not None


def is_pagebreak(el):
    """True if the element carries an explicit page break."""
    return any(b.get(qn('w:type')) == 'page' for b in el.iter(qn('w:br')))


def has_sdt(el):
    """True if the element wraps content in a structured-document tag."""
    return el.find('.//' + qn('w:sdt')) is not None


def style_id(el):
    """The ``w:pStyle``/``w:tblStyle`` id of an element, or ``''``."""
    if el.tag == qn('w:tbl'):
        ts = el.find('.//' + qn('w:tblStyle'))
        return ts.get(qn('w:val')) if ts is not None else ''
    ppr = el.find(qn('w:pPr'))
    if ppr is None:
        return ''
    st = ppr.find(qn('w:pStyle'))
    return st.get(qn('w:val')) if st is not None else ''


def _norm_style(name):
    """'Heading 1', 'heading1', 'Heading1' → 'heading1' so style lookups can be loose."""
    return re.sub(r'[\s_-]+', '', (name or '')).lower()


def _has_numpr(el):
    return el.find('.//' + qn('w:numPr')) is not None


def _has_hyperlink(el):
    return el.find('.//' + qn('w:hyperlink')) is not None


# --------------------------------------------------------------------------
# writing / cloning
# --------------------------------------------------------------------------

def set_text(p, text):
    """Replace all text of paragraph `p` with `text`, keeping its formatting.

    Keeps the first ``w:t`` (so the run's ``w:rPr`` and any sdt wrapper survive)
    and removes the rest.  This is what makes sdt-wrapped Google Docs headings
    editable at all.
    """
    ts = list(p.iter(qn('w:t')))
    if not ts:
        r = p.makeelement(qn('w:r'), {})
        t = p.makeelement(qn('w:t'), {})
        r.append(t)
        p.append(r)
        ts = [t]
    ts[0].text = text
    ts[0].set(XML_SPACE, 'preserve')
    for t in ts[1:]:
        t.getparent().remove(t)
    return p


#: Run properties that belong to a hyperlink rather than to body text.
#: Keeping them would paint every new run blue and underlined.
_HYPERLINK_RPR = ('w:rStyle', 'w:color', 'w:u')


def _rpr_specimen(p):
    """A clean ``w:rPr`` to base new runs on, taken from anywhere inside `p`.

    Real template paragraphs are rarely a tidy ``w:p > w:r``: the run carrying
    the house font may sit inside a ``w:hyperlink`` or an ``w:sdt`` wrapper.
    So search every descendant run, prefer one that actually has text, and
    strip the hyperlink-only properties off the copy.
    """
    runs = list(p.iter(qn('w:r')))
    chosen = next((r for r in runs if r.find(qn('w:t')) is not None), None)
    if chosen is None:
        chosen = runs[0] if runs else None
    if chosen is None:
        return None
    rpr = chosen.find(qn('w:rPr'))
    if rpr is None:
        return None
    rpr = copy.deepcopy(rpr)
    if any(a.tag == qn('w:hyperlink') for a in chosen.iterancestors()):
        for tag in _HYPERLINK_RPR:
            for e in rpr.findall(qn(tag)):
                rpr.remove(e)
    return rpr


def clone_para_runs(template_p, parts):
    """Clone `template_p` and fill it with `parts` = ``[(text, {'bold':..,'italic':..}), ..]``.

    Everything except ``w:pPr`` is discarded and the runs are rebuilt from one
    run-properties specimen, so the paragraph keeps its style, indentation and
    list numbering while its text is exactly what you passed.

    Gotcha this guards against: a template paragraph holds far more than plain
    ``w:r`` children — ``w:hyperlink`` (with runs of its own),
    ``w:bookmarkStart``/``w:bookmarkEnd``, ``w:proofErr``, ``w:fldSimple``, an
    ``w:sdt`` wrapper.  Removing only the direct ``w:r`` children leaves that
    text behind, and a cloned bullet comes out as ``https://…/your new text``.
    """
    p = copy.deepcopy(template_p)
    specimen = _rpr_specimen(p)
    for child in list(p):
        if child.tag != qn('w:pPr'):
            p.remove(child)

    for text, fmt in parts:
        r = p.makeelement(qn('w:r'), {})
        rpr = copy.deepcopy(specimen) if specimen is not None \
            else r.makeelement(qn('w:rPr'), {})
        for tag in ('w:b', 'w:bCs', 'w:i', 'w:iCs'):
            for e in rpr.findall(qn(tag)):
                rpr.remove(e)
        if fmt.get('bold'):
            for tag in ('w:b', 'w:bCs'):
                rpr.insert(0, rpr.makeelement(qn(tag), {qn('w:val'): '1'}))
        if fmt.get('italic'):
            for tag in ('w:i', 'w:iCs'):
                rpr.insert(0, rpr.makeelement(qn(tag), {qn('w:val'): '1'}))
        r.append(rpr)
        t = r.makeelement(qn('w:t'), {})
        t.text = text
        t.set(XML_SPACE, 'preserve')
        r.append(t)
        p.append(r)
    return p


def clone_para(template_p, text, bold_prefix=None):
    """Clone a body paragraph, optionally with a bold label in front of `text`."""
    parts = []
    if bold_prefix:
        parts.append((bold_prefix, {'bold': True}))
    parts.append((text, {}))
    return clone_para_runs(template_p, parts)


def clone_heading(template_p, text):
    """Clone a heading paragraph (sdt-safe) and set its text."""
    return set_text(copy.deepcopy(template_p), text)


def clone_hr(template_p):
    """Clone a horizontal-rule paragraph, or synthesise one when `template_p` is None."""
    if template_p is None:
        return new_hr()
    return copy.deepcopy(template_p)


def clone_pagebreak(template_p):
    """Clone a page-break paragraph, or synthesise one when `template_p` is None."""
    if template_p is None:
        return new_pagebreak()
    return copy.deepcopy(template_p)


def new_hr():
    """A detached empty paragraph with a bottom border — the portable rule."""
    return parse_xml(
        '<w:p %s><w:pPr><w:pBdr>'
        '<w:bottom w:val="single" w:sz="6" w:space="1" w:color="auto"/>'
        '</w:pBdr></w:pPr></w:p>' % nsdecls('w'))


def new_pagebreak():
    """A detached paragraph carrying an explicit page break."""
    return parse_xml(
        '<w:p %s><w:r><w:br w:type="page"/></w:r></w:p>' % nsdecls('w'))


def _set_cell(tc, text):
    """Put a single line of `text` into a ``w:tc``, keeping the first run's formatting."""
    ps = tc.findall(qn('w:p'))
    if not ps:
        p = tc.makeelement(qn('w:p'), {})
        tc.append(p)
        ps = [p]
    for p in ps[1:]:
        tc.remove(p)
    p = ps[0]
    runs = p.findall(qn('w:r'))
    for r in runs[1:]:
        p.remove(r)
    if runs:
        r = runs[0]
        for t in r.findall(qn('w:t')):
            r.remove(t)
    else:
        r = p.makeelement(qn('w:r'), {})
        p.append(r)
    t = r.makeelement(qn('w:t'), {})
    t.text = text
    t.set(XML_SPACE, 'preserve')
    r.append(t)


def clone_table(template_tbl, rows):
    """Clone `template_tbl` and refill it with `rows` (first row = header).

    Columns come from the template, so pass rows with the template's column
    count; extra values are dropped and missing ones leave the cell blank.
    """
    tbl = copy.deepcopy(template_tbl)
    trs = tbl.findall(qn('w:tr'))
    if not trs:
        raise ValueError('table template has no rows')
    body_tpl = trs[1] if len(trs) > 1 else trs[0]
    body_tpl = copy.deepcopy(body_tpl)
    for tr in trs[1:]:
        tbl.remove(tr)

    def fill(tr, vals):
        for tc, v in zip(tr.findall(qn('w:tc')), vals):
            _set_cell(tc, v)

    fill(trs[0], list(rows[0]))
    for vals in rows[1:]:
        tr = copy.deepcopy(body_tpl)
        fill(tr, list(vals))
        tbl.append(tr)
    return tbl


# --------------------------------------------------------------------------
# template discovery
# --------------------------------------------------------------------------

class TemplateSet:
    """Template elements discovered in an existing manual.

    Attributes (any may be ``None`` when the document has no such element):
    ``h1``/``h2``/``h3``, ``body``, ``caption``, ``hr``, ``pagebreak``,
    ``table``, ``bullet``, ``number``.
    """

    FIELDS = ('h1', 'h2', 'h3', 'body', 'caption', 'hr', 'pagebreak', 'table',
              'bullet', 'number')

    def __init__(self, **kw):
        for f in self.FIELDS:
            setattr(self, f, kw.get(f))

    @classmethod
    def from_doc(cls, doc, overrides=None, style_overrides=None):
        """Auto-discover templates in `doc`.

        `overrides` maps a field name to a text prefix ("use *this* paragraph").
        `style_overrides` maps a field name to a style id.  Both win over the
        heuristics below.
        """
        els = body_elements(doc)
        found = {}
        candidates = {}

        heading_styles = {'heading1': 'h1', 'heading2': 'h2', 'heading3': 'h3',
                          'title': 'h1', 'subtitle': 'h2'}
        prev_was_image = False
        for el in els:
            if el.tag == qn('w:tbl'):
                found.setdefault('table', el)
                prev_was_image = False
                continue
            if el.tag != qn('w:p'):
                continue
            sid = _norm_style(style_id(el))
            txt = ptext(el)
            img = has_image(el)

            if sid in heading_styles:
                found.setdefault(heading_styles[sid], el)
            if is_hr(el):
                found.setdefault('hr', el)
            if is_pagebreak(el):
                found.setdefault('pagebreak', el)
            if sid == 'listbullet':
                candidates.setdefault('bullet', []).append(el)
            if sid == 'listnumber':
                candidates.setdefault('number', []).append(el)
            if prev_was_image and txt and not img:
                found.setdefault('caption', el)
            if (txt and not img and sid not in heading_styles
                    and not is_hr(el) and not _has_numpr(el)):
                found.setdefault('body', el)
            prev_was_image = img

        # Among list paragraphs, prefer a plain one: a bullet holding a
        # hyperlink or a picture carries structure that is only noise once the
        # paragraph is reused as a text template.
        for field, cands in candidates.items():
            plain = next((e for e in cands
                          if not _has_hyperlink(e) and not has_image(e)), None)
            found.setdefault(field, plain if plain is not None else cands[0])

        # A caption paragraph doubles as the fallback body paragraph and vice
        # versa; a numbered paragraph is the fallback for both list kinds.
        if found.get('body') is None:
            found['body'] = found.get('caption')
        if found.get('caption') is None:
            found['caption'] = found.get('body')
        numbered = next((e for e in els if e.tag == qn('w:p') and _has_numpr(e)
                         and not _has_hyperlink(e) and not has_image(e)), None)
        if numbered is None:
            numbered = next((e for e in els if e.tag == qn('w:p') and _has_numpr(e)), None)
        found.setdefault('bullet', numbered)
        found.setdefault('number', numbered)

        for field, sid in (style_overrides or {}).items():
            want = _norm_style(sid)
            el = next((e for e in els if _norm_style(style_id(e)) == want), None)
            if el is None:
                raise KeyError('no element with style %r for template %r' % (sid, field))
            found[field] = el
        for field, prefix in (overrides or {}).items():
            found[field] = els[find_prefix(els, prefix)]

        return cls(**found)

    def require(self, *fields):
        """Raise if any of `fields` was not discovered (clear error beats an AttributeError)."""
        missing = [f for f in fields if getattr(self, f) is None]
        if missing:
            raise KeyError('template document lacks: %s' % ', '.join(missing))
        return self


# --------------------------------------------------------------------------
# cross-document import
# --------------------------------------------------------------------------

class Importer:
    """Deep-copies elements from one document into another, carrying their parts.

    A ``w:p`` does not own its pictures, numbering or table style: those live in
    the source package.  Copying the XML alone gives you a document Word
    refuses to open (dangling rIds) or one that renumbers your lists.  ``copy()``
    rewrites, per element:

    * ``a:blip/@r:embed`` — image bytes re-added to the destination part;
    * ``w:numPr/w:numId`` — numbering definitions imported with an id offset so
      they cannot collide with the destination's own lists;
    * ``w:tblStyle`` — the table style definition copied under a prefixed id;
    * ``w:hyperlink/@r:id`` — external targets re-related.
    """

    def __init__(self, src_doc, dst_doc, num_offset=100, style_prefix='Imp'):
        self.src = src_doc
        self.dst = dst_doc
        self.num_offset = num_offset
        self.style_prefix = style_prefix
        self._numbering_done = False
        self._styles = {}

    # -- numbering ---------------------------------------------------------
    def _import_numbering(self):
        if self._numbering_done:
            return
        self._numbering_done = True
        try:
            src = self.src.part.numbering_part.element
        except (KeyError, NotImplementedError, AttributeError):
            return
        dst = self.dst.part.numbering_part.element
        abstracts = dst.findall(qn('w:abstractNum'))
        anchor = abstracts[-1] if abstracts else None
        for a in src.findall(qn('w:abstractNum')):
            a2 = copy.deepcopy(a)
            a2.set(qn('w:abstractNumId'),
                   str(int(a.get(qn('w:abstractNumId'))) + self.num_offset))
            if anchor is None:
                dst.insert(0, a2)
            else:
                anchor.addnext(a2)
            anchor = a2
        for n in src.findall(qn('w:num')):
            n2 = copy.deepcopy(n)
            n2.set(qn('w:numId'), str(int(n.get(qn('w:numId'))) + self.num_offset))
            ref = n2.find(qn('w:abstractNumId'))
            if ref is not None:
                ref.set(qn('w:val'), str(int(ref.get(qn('w:val'))) + self.num_offset))
            dst.append(n2)

    # -- table styles ------------------------------------------------------
    def _import_table_style(self, sid):
        if sid in self._styles:
            return self._styles[sid]
        new_id = self.style_prefix + sid
        src = [s for s in self.src.styles.element.findall(qn('w:style'))
               if s.get(qn('w:type')) == 'table' and s.get(qn('w:styleId')) == sid]
        if src:
            s2 = copy.deepcopy(src[-1])
            s2.set(qn('w:styleId'), new_id)
            nm = s2.find(qn('w:name'))
            if nm is not None:
                nm.set(qn('w:val'), new_id)
            self.dst.styles.element.append(s2)
        else:
            new_id = sid  # nothing to import; hope the destination has it
        self._styles[sid] = new_id
        return new_id

    # -- public ------------------------------------------------------------
    def copy(self, el):
        """Return a deep copy of `el` that is valid inside the destination document."""
        if self.src is self.dst:
            return copy.deepcopy(el)
        el = copy.deepcopy(el)
        for blip in el.iter(qn('a:blip')):
            rid = blip.get(qn('r:embed'))
            if not rid:
                continue
            part = self.src.part.related_parts[rid]
            new_rid, _ = self.dst.part.get_or_add_image(io.BytesIO(part.blob))
            blip.set(qn('r:embed'), new_rid)
        for numpr in el.iter(qn('w:numPr')):
            nid = numpr.find(qn('w:numId'))
            if nid is not None and nid.get(qn('w:val')):
                self._import_numbering()
                nid.set(qn('w:val'), str(int(nid.get(qn('w:val'))) + self.num_offset))
        for ts in el.iter(qn('w:tblStyle')):
            ts.set(qn('w:val'), self._import_table_style(ts.get(qn('w:val'))))
        for hl in el.iter(qn('w:hyperlink')):
            rid = hl.get(qn('r:id'))
            if rid:
                target = self.src.part.rels[rid].target_ref
                hl.set(qn('r:id'),
                       self.dst.part.relate_to(target, RT.HYPERLINK, is_external=True))
        return el


# --------------------------------------------------------------------------
# figures
# --------------------------------------------------------------------------

def add_figure(doc, image_path, caption, width_cm=None, caption_template=None,
               side_by_side_paths=None):
    """Append a centred picture paragraph plus its caption; return both elements.

    With `side_by_side_paths` (exactly two paths) both pictures go into the one
    centred paragraph at half width each, which is how manuals show a
    before/after or left/right pair under a single caption.
    """
    paths = list(side_by_side_paths) if side_by_side_paths else [image_path]
    if len(paths) == 2:
        total = width_cm if width_cm else 15.0
        each = (total - 0.3) / 2.0
        widths = [Cm(each), Cm(each)]
    else:
        widths = [Cm(width_cm) if width_cm else None]

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for i, (path, w) in enumerate(zip(paths, widths)):
        if i:
            p.add_run(' ')
        p.add_run().add_picture(path, width=w)

    if caption_template is not None:
        cap_el = clone_para(caption_template, caption)
        append_elements(doc, [cap_el])
    else:
        cap = doc.add_paragraph()
        cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = cap.add_run(caption)
        run.italic = True
        cap_el = cap._p
    return [p._p, cap_el]


def renumber_figures(elements, pattern=FIGURE_PATTERN, fmt=FIGURE_FORMAT):
    """Rewrite figure captions in `elements` to a single 1..N sequence; return N.

    Source manuals use section-scoped numbers ("圖 10-1："), which are wrong the
    moment you extract a subset of sections into a derived document.
    """
    rx = re.compile(pattern)
    n = 0
    for el in elements:
        if el.tag != qn('w:p'):
            continue
        txt = ptext(el)
        if not rx.match(txt):
            continue
        n += 1
        full = ''.join(t.text or '' for t in el.iter(qn('w:t')))
        full = rx.sub(fmt.format(n=n), full, count=1)
        set_text(el, full)
    return n


def unique_docpr_ids(elements, start=1):
    """Give every ``wp:docPr`` a unique id; return the next free id.

    Word reports a corrupt file when two drawings share a docPr id, which always
    happens after deep-copying picture paragraphs.
    """
    i = start
    for el in elements:
        for dp in el.iter(qn('wp:docPr')):
            dp.set('id', str(i))
            i += 1
    return i


def prune_unused_images(doc):
    """Drop image relationships the body no longer references; return the count.

    Without this, a document derived from a big manual keeps every screenshot of
    the original, even the ones it does not show.
    """
    body = doc.element.body
    used = {b.get(qn('r:embed')) for b in body.iter(qn('a:blip'))}
    used |= {b.get(qn('r:link')) for b in body.iter(qn('a:blip'))}
    # VML (``v:imagedata``) is how Google Docs exports horizontal rules and a
    # few legacy pictures; python-docx has no 'v' prefix, hence the literal URI.
    used |= {d.get(qn('r:id')) for d in body.iter(VML_IMAGEDATA)}
    dropped = 0
    for rid, rel in list(doc.part.rels.items()):
        if rel.reltype == RT.IMAGE and rid not in used:
            del doc.part.rels[rid]
            dropped += 1
    return dropped


def clear_body(doc):
    """Remove every body element except the final ``w:sectPr``.

    Keeping the sectPr keeps page size, margins, headers and footers, which is
    the whole point of using an existing manual as a style template.
    """
    body = doc.element.body
    sect = body.find(qn('w:sectPr'))
    for child in list(body):
        if child is not sect:
            body.remove(child)
    return doc


def append_elements(doc, elements):
    """Append elements to the body, before the ``sectPr`` if there is one."""
    body = doc.element.body
    sect = body.find(qn('w:sectPr'))
    for el in elements:
        if sect is not None:
            sect.addprevious(el)
        else:
            body.append(el)
    return doc


def figures(doc):
    """List every picture in the body as a dict.

    Keys: ``index`` (body element index), ``media_name`` (``imageNN.png``),
    ``rid``, ``md5``, ``width``, ``height``, ``caption``.  The caption is the
    next non-empty paragraph within two elements — two pictures in a left/right
    layout therefore share one caption, which is intentional.
    """
    els = body_elements(doc)
    out = []
    for i, el in enumerate(els):
        if el.tag != qn('w:p'):
            continue
        blips = el.findall('.//' + qn('a:blip'))
        if not blips:
            continue
        caption = ''
        for nxt in els[i + 1:i + 3]:
            if nxt.tag == qn('w:p') and ptext(nxt):
                caption = ptext(nxt)
                break
        for blip in blips:
            rid = blip.get(qn('r:embed'))
            if not rid:
                continue
            part = doc.part.related_parts[rid]
            blob = part.blob
            w = h = None
            if Image is not None:
                try:
                    with Image.open(io.BytesIO(blob)) as im:
                        w, h = im.size
                except Exception:  # pragma: no cover - unreadable media
                    pass
            out.append({
                'index': i,
                'media_name': os.path.basename(str(part.partname)),
                'rid': rid,
                'md5': hashlib.md5(blob).hexdigest(),
                'width': w,
                'height': h,
                'caption': caption,
            })
    return out


# --------------------------------------------------------------------------
# misc
# --------------------------------------------------------------------------

def backup_path(path, tag=None):
    """``<stem>.<YYYY-MM-DD>[<b|c|…>][.<tag>].bak.docx``, first name not in use."""
    stem, ext = os.path.splitext(path)
    date = _dt.date.today().isoformat()
    for suffix in [''] + [chr(c) for c in range(ord('b'), ord('z') + 1)]:
        parts = [stem, date + suffix]
        if tag:
            parts.append(tag)
        parts.append('bak')
        cand = '.'.join(parts) + (ext or '.docx')
        if not os.path.exists(cand):
            return cand
    raise RuntimeError('too many backups for %s' % path)


def open_doc(path):
    """``docx.Document(path)`` with a friendlier error for a missing file."""
    if not os.path.exists(path):
        raise SystemExit('no such file: %s' % path)
    return docx.Document(path)


def human_size(path):
    """File size as a short human string (e.g. ``'3.4 MB'``)."""
    n = os.path.getsize(path)
    if n >= 1 << 20:
        return '%.1f MB' % (n / (1 << 20))
    return '%.0f KB' % (n / 1024.0)
