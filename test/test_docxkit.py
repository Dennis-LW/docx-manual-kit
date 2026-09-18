"""End-to-end tests for the docx-manual scripts.

Everything is generated at test time (template .docx and PNG screenshots), so
the suite needs no fixture files and no real manual.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import docx
import pytest
from docx.oxml.ns import qn
from docx.shared import Cm
from PIL import Image

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'skills', 'docx-manual', 'scripts')
sys.path.insert(0, SCRIPTS)

import docx_build  # noqa: E402
import docx_extract  # noqa: E402
import docx_inspect  # noqa: E402
import docx_figures_diff  # noqa: E402
import docx_replace_images  # noqa: E402
from docxkit import backup_path, body_elements, figures, ptext  # noqa: E402


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------

def make_png(path, size, colour):
    Image.new('RGB', size, colour).save(path, 'PNG')
    return path


@pytest.fixture
def shots(tmp_path):
    """Three distinguishable screenshots of different sizes."""
    d = tmp_path / 'images'
    d.mkdir()
    return {
        'login': make_png(str(d / 'login.png'), (400, 700), (10, 30, 200)),
        'list': make_png(str(d / 'list.png'), (360, 640), (200, 30, 10)),
        'detail': make_png(str(d / 'detail.png'), (360, 640), (10, 160, 60)),
        'new': make_png(str(d / 'new.png'), (500, 900), (240, 200, 20)),
        'dir': str(d),
    }


@pytest.fixture
def template(tmp_path, shots):
    """A minimal 'client manual' whose styles the builder can inherit."""
    path = str(tmp_path / 'template.docx')
    doc = docx.Document()
    doc.add_heading('Client Manual', level=1)
    doc.add_heading('Section', level=2)
    doc.add_heading('Subsection', level=3)
    doc.add_paragraph('A plain body paragraph in the client house style.')
    doc.add_paragraph('A bullet in the client house style.', style='List Bullet')
    doc.add_picture(shots['login'], width=Cm(8))
    doc.add_paragraph('圖 1：template caption')
    t = doc.add_table(rows=2, cols=2)
    t.style = 'Table Grid'
    t.cell(0, 0).text = 'head'
    doc.save(path)
    return path


MD = """# Manual Title

Intro with **bold** and *italic* text.

> A quoted note.

- first bullet
- second bullet

1. first step
2. second step

| Field | Meaning |
| --- | --- |
| Account | email |

![Login screen](login.png)

---

<!-- pagebreak -->

## Second chapter

![List](list.png) ![Detail](detail.png)
"""


@pytest.fixture
def built(tmp_path, template, shots):
    """The manual built from MD; returns its path."""
    md = tmp_path / 'manual.md'
    md.write_text(MD, encoding='utf-8')
    out = str(tmp_path / 'built.docx')
    rc = docx_build.main([str(md), '--template', template, '--out', out,
                          '--images-dir', shots['dir'], '--width-cm', '12'])
    assert rc == 0
    return out


# --------------------------------------------------------------------------
# build
# --------------------------------------------------------------------------

def test_build_produces_numbered_figures_and_all_constructs(built, capsys):
    doc = docx.Document(built)
    els = body_elements(doc)
    texts = [ptext(e) for e in els]

    assert 'Manual Title' in texts
    assert 'Second chapter' in texts
    assert '圖 1：Login screen' in texts
    assert '圖 2：List｜Detail' in texts

    # three pictures: one single figure plus the side-by-side pair
    assert len(figures(doc)) == 3
    # the pair shares one caption paragraph
    caps = {f['caption'] for f in figures(doc)}
    assert caps == {'圖 1：Login screen', '圖 2：List｜Detail'}

    # table, HR and page break survived
    assert any(e.tag == qn('w:tbl') for e in els)
    assert any(e.findall('.//' + qn('w:pict')) or _has_bottom_border(e) for e in els)
    assert any(b.get(qn('w:type')) == 'page' for e in els for b in e.iter(qn('w:br')))

    # lists
    assert 'first bullet' in texts and 'first step' in texts

    # bold / italic runs made it through
    assert _has_bold(els, 'bold')
    assert _has_italic(els, 'A quoted note.')


def _has_bottom_border(el):
    return el.find('.//' + qn('w:pBdr')) is not None


def _has_bold(els, word):
    for el in els:
        for r in el.iter(qn('w:r')):
            t = r.find(qn('w:t'))
            rpr = r.find(qn('w:rPr'))
            if t is not None and t.text and word in t.text:
                if rpr is not None and rpr.find(qn('w:b')) is not None:
                    return True
    return False


def _has_italic(els, text):
    for el in els:
        if ptext(el) != text:
            continue
        for r in el.iter(qn('w:r')):
            rpr = r.find(qn('w:rPr'))
            if rpr is not None and rpr.find(qn('w:i')) is not None:
                return True
    return False


def test_build_reports_missing_images(tmp_path, template):
    md = tmp_path / 'bad.md'
    md.write_text('# T\n\n![Nope](nope.png)\n', encoding='utf-8')
    out = str(tmp_path / 'bad.docx')
    with pytest.raises(SystemExit) as e:
        docx_build.main([str(md), '--template', template, '--out', out])
    assert 'nope.png' in str(e.value)
    assert not os.path.exists(out)


# --------------------------------------------------------------------------
# inspect
# --------------------------------------------------------------------------

def test_inspect_lists_two_captions(built, capsys):
    docx_inspect.main([built, '--figures'])
    out = capsys.readouterr().out
    assert '3 figure(s)' in out
    figure_list = out.split('3 figure(s)', 1)[1]
    assert figure_list.count('圖 1：Login screen') == 1
    assert figure_list.count('圖 2：List｜Detail') == 2   # the pair shares one caption
    assert 'image1.png' in figure_list


def test_inspect_json(built, capsys):
    docx_inspect.main([built, '--figures', '--json'])
    data = json.loads(capsys.readouterr().out)
    assert len(data['figures']) == 3
    assert all('md5' in f and 'media_name' in f for f in data['figures'])


# --------------------------------------------------------------------------
# replace images
# --------------------------------------------------------------------------

def test_replace_image_by_caption_keeps_dimensions_and_backs_up(built, shots, capsys):
    before = {f['caption']: f for f in figures(docx.Document(built)) if '圖 1' in f['caption']}
    old = before['圖 1：Login screen']

    rc = docx_replace_images.main([built, '--set',
                                   'caption:圖 1：Login screen=' + shots['new']])
    assert rc == 0
    out = capsys.readouterr().out
    assert 'backup:' in out

    bak = [p for p in os.listdir(os.path.dirname(built)) if p.endswith('.bak.docx')]
    assert len(bak) == 1

    after = {f['caption']: f for f in figures(docx.Document(built))}
    new = after['圖 1：Login screen']
    assert new['md5'] != old['md5']
    assert (new['width'], new['height']) == (old['width'], old['height'])
    # the other figures are untouched
    assert {f['md5'] for f in figures(docx.Document(built)) if '圖 2' in f['caption']} == \
           {f['md5'] for f in figures(docx.Document(bak[0] and os.path.join(
               os.path.dirname(built), bak[0]))) if '圖 2' in f['caption']}


def test_replace_refuses_ambiguous_and_unknown_keys(built, shots):
    with pytest.raises(SystemExit) as e:
        docx_replace_images.main([built, '--no-backup', '--set',
                                  'caption:圖 2=' + shots['new']])
    assert '#0' in str(e.value)

    with pytest.raises(SystemExit) as e:
        docx_replace_images.main([built, '--no-backup', '--set',
                                  'caption:nothing here=' + shots['new']])
    assert 'no caption' in str(e.value)

    with pytest.raises(SystemExit) as e:
        docx_replace_images.main([built, '--no-backup', '--set',
                                  'image999.png=' + shots['new']])
    assert 'no media' in str(e.value)


def test_replace_side_by_side_by_index(built, shots):
    old = [f for f in figures(docx.Document(built)) if '圖 2' in f['caption']]
    assert len(old) == 2
    docx_replace_images.main([built, '--no-backup', '--set',
                              'caption:圖 2：List｜Detail#1=' + shots['new']])
    new = [f for f in figures(docx.Document(built)) if '圖 2' in f['caption']]
    assert new[0]['md5'] == old[0]['md5']
    assert new[1]['md5'] != old[1]['md5']


def test_replace_no_resize_rescales_the_drawing(tmp_path, built, shots):
    """--no-resize keeps the new pixels and adjusts wp:extent to the new aspect."""
    out = str(tmp_path / 'noresize.docx')
    before = _extent(built, '圖 1：Login screen')
    docx_replace_images.main([built, '--no-backup', '--no-resize', '--out', out,
                              '--set', 'caption:圖 1：Login screen=' + shots['new']])
    fig = [f for f in figures(docx.Document(out)) if '圖 1' in f['caption']][0]
    assert (fig['width'], fig['height']) == (500, 900)     # bytes went in untouched
    cx, cy = _extent(out, '圖 1：Login screen')
    assert cx == before[0]                                  # displayed width kept
    assert abs(cy / cx - 900 / 500.0) < 0.01                # new aspect adopted


def _extent(path, caption):
    doc = docx.Document(path)
    els = body_elements(doc)
    for i, el in enumerate(els):
        if ptext(el) == caption:
            ext = els[i - 1].find('.//' + qn('wp:extent'))
            return int(ext.get('cx')), int(ext.get('cy'))
    raise AssertionError(caption)


def test_figures_diff_reports_reshot(tmp_path, built, shots, capsys):
    patched = str(tmp_path / 'patched.docx')
    docx_replace_images.main([built, '--no-backup', '--out', patched,
                              '--set', 'caption:圖 1：Login screen=' + shots['new']])
    docx_figures_diff.main([built, patched])
    out = capsys.readouterr().out.split('-- 2 image')[-1]
    assert 'RESHOT' in out and 'Login screen' in out
    assert 'NEW' not in out and 'REMOVED' not in out


# --------------------------------------------------------------------------
# extract
# --------------------------------------------------------------------------

def test_extract_renumbers_and_prunes(tmp_path, built, template):
    package = str(tmp_path / 'package.docx')
    docx.Document(template).save(package)
    spec = {
        'package': package,
        'sources': {'src': built},
        'title': 'Delta',
        'fixes': [['Second chapter', 'Chapter two']],
        'parts': [
            {'heading': [1, 'What changed']},
            {'para': 'Only the changed parts.', 'bold_prefix': 'Scope: '},
            {'hr': True},
            {'range': {'from': 'src', 'start': 'Second chapter',
                       'end': '圖 2：List｜Detail'}},
            {'figure': {'from': 'src', 'caption': '圖 1：Login screen'}},
        ],
    }
    spec_path = tmp_path / 'spec.json'
    spec_path.write_text(json.dumps(spec, ensure_ascii=False), encoding='utf-8')
    out = str(tmp_path / 'delta.docx')

    rc = docx_extract.main(['--spec', str(spec_path), '--out', out])
    assert rc == 0

    doc = docx.Document(out)
    texts = [ptext(e) for e in body_elements(doc)]
    assert 'What changed' in texts
    assert 'Chapter two' in texts          # fix applied
    assert 'Second chapter' not in texts

    figs = figures(doc)
    # the pair (2 pictures, 1 caption) came first, the single figure second
    assert [f['caption'] for f in figs] == ['圖 1：List｜Detail'] * 2 + ['圖 2：Login screen']

    # no orphan image parts: every image rel of the package is referenced
    body = doc.element.body
    used = {b.get(qn('r:embed')) for b in body.iter(qn('a:blip'))}
    image_rels = {rid for rid, rel in doc.part.rels.items() if 'image' in rel.reltype}
    assert image_rels == used
    assert len(image_rels) == 3

    # docPr ids are unique, otherwise Word calls the file corrupt
    ids = [dp.get('id') for dp in body.iter(qn('wp:docPr'))]
    assert len(ids) == len(set(ids))


def test_extract_detects_split_fix(tmp_path, built, template):
    package = str(tmp_path / 'package2.docx')
    docx.Document(template).save(package)
    spec = {
        'package': package,
        'sources': {'src': built},
        # 'bold' sits in its own run, 'Intro with bold' therefore spans runs
        'fixes': [['Intro with bold', 'X']],
        'parts': [{'one': {'from': 'src', 'start': 'Intro with'}}],
    }
    spec_path = tmp_path / 'spec2.json'
    spec_path.write_text(json.dumps(spec, ensure_ascii=False), encoding='utf-8')
    with pytest.raises(SystemExit) as e:
        docx_extract.main(['--spec', str(spec_path), '--out', str(tmp_path / 'o.docx')])
    assert 'split across runs' in str(e.value)


# --------------------------------------------------------------------------
# misc
# --------------------------------------------------------------------------

def test_backup_path_picks_free_suffix(tmp_path):
    target = tmp_path / 'm.docx'
    target.write_bytes(b'x')
    first = backup_path(str(target))
    assert first.endswith('.bak.docx')
    open(first, 'wb').close()
    second = backup_path(str(target))
    assert second != first
    tagged = backup_path(str(target), 'reshoot')
    assert '.reshoot.' in tagged


def test_scripts_have_help():
    for name in ('docxkit.py', 'docx_inspect.py', 'docx_figures_diff.py',
                 'docx_replace_images.py', 'docx_build.py', 'docx_extract.py',
                 'trim_screenshot.py'):
        path = os.path.join(SCRIPTS, name)
        if name == 'docxkit.py':
            continue  # library, no CLI
        r = subprocess.run([sys.executable, path, '--help'],
                           capture_output=True, text=True)
        assert r.returncode == 0, (name, r.stderr)
        assert 'usage' in r.stdout.lower()


# --------------------------------------------------------------------------
# regressions found on a real client manual (Google Docs export, ~100 figures)
# --------------------------------------------------------------------------

def media_names(path):
    """Names of the image parts actually written into the .docx package."""
    import zipfile
    with zipfile.ZipFile(path) as z:
        return [n for n in z.namelist() if n.startswith('word/media/')]


def add_hyperlink(paragraph, url, text):
    """python-docx has no hyperlink API; build the ``w:hyperlink`` by hand."""
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    from docx.oxml import parse_xml
    from docx.oxml.ns import nsdecls
    rid = paragraph.part.relate_to(url, RT.HYPERLINK, is_external=True)
    paragraph._p.append(parse_xml(
        '<w:hyperlink %s r:id="%s"><w:r><w:rPr>'
        '<w:rStyle w:val="Hyperlink"/><w:color w:val="0000FF"/>'
        '<w:u w:val="single"/></w:rPr><w:t>%s</w:t></w:r></w:hyperlink>'
        % (nsdecls('w', 'r'), rid, text)))


URL = 'https://dev-admin.example.com/'


def make_list_paragraph(doc, num_id=1):
    """A list item the Google-Docs way: direct ``w:numPr``, no List Bullet style."""
    from docx.oxml import parse_xml
    from docx.oxml.ns import nsdecls
    p = doc.add_paragraph()
    p._p.append(parse_xml(
        '<w:pPr %s><w:numPr><w:ilvl w:val="0"/><w:numId w:val="%d"/></w:numPr>'
        '</w:pPr>' % (nsdecls('w'), num_id)))
    return p


def strip_list_styles(doc):
    """Drop the List Bullet/Number styles so the builder must clone instead."""
    styles = doc.styles.element
    for st in list(styles.findall(qn('w:style'))):
        if st.get(qn('w:styleId')) in ('ListBullet', 'ListNumber', 'ListParagraph'):
            styles.remove(st)


@pytest.fixture
def messy_template(tmp_path, shots):
    """A template like a real export: hyperlink inside the only list item,
    no List Bullet style to fall back on, and several images."""
    path = str(tmp_path / 'messy.docx')
    doc = docx.Document()
    doc.add_heading('Client Manual', level=1)
    doc.add_heading('Section', level=2)
    doc.add_heading('Sub', level=3)
    doc.add_paragraph('House-style body paragraph.')
    bullet = make_list_paragraph(doc)
    add_hyperlink(bullet, URL, URL)
    for key in ('login', 'list', 'detail'):
        doc.add_picture(shots[key], width=Cm(6))
        doc.add_paragraph('圖 N：template caption')
    strip_list_styles(doc)
    doc.save(path)
    return path


def test_clone_para_runs_discards_hyperlink_and_its_colour(messy_template):
    """Unit-level regression for the cloning rule itself."""
    from docxkit import TemplateSet, clone_para_runs
    doc = docx.Document(messy_template)
    tpl = TemplateSet.from_doc(doc).bullet
    assert tpl is not None and tpl.find('.//' + qn('w:hyperlink')) is not None

    p = clone_para_runs(tpl, [('開啟後台網址。', {})])
    assert ptext(p) == '開啟後台網址。'
    assert p.find('.//' + qn('w:hyperlink')) is None
    assert p.find('.//' + qn('w:rStyle')) is None
    assert p.find('.//' + qn('w:u')) is None
    assert len(p.findall('.//' + qn('w:t'))) == 1          # no stale w:t left
    assert p.find(qn('w:pPr') + '/' + qn('w:numPr')) is not None   # numbering kept


def test_template_discovery_prefers_a_plain_list_paragraph(tmp_path, shots):
    """With several list items, the one without a hyperlink or picture wins."""
    from docxkit import TemplateSet
    path = str(tmp_path / 'two-lists.docx')
    doc = docx.Document()
    doc.add_paragraph('body')
    linked = make_list_paragraph(doc)
    add_hyperlink(linked, URL, URL)
    plain = make_list_paragraph(doc)
    plain.add_run('a plain list item')
    strip_list_styles(doc)
    doc.save(path)

    tpl = TemplateSet.from_doc(docx.Document(path))
    assert ptext(tpl.bullet) == 'a plain list item'


def test_cloned_list_item_drops_template_hyperlink(tmp_path, messy_template, shots):
    """Regression: the bullet came out as 'https://…/開啟後台網址。'."""
    md = tmp_path / 'm.md'
    md.write_text('# Title\n\n- 開啟後台網址。\n\n![Login screen](login.png)\n',
                  encoding='utf-8')
    out = str(tmp_path / 'clean.docx')
    assert docx_build.main([str(md), '--template', messy_template, '--out', out,
                            '--images-dir', shots['dir']]) == 0

    doc = docx.Document(out)
    items = [e for e in body_elements(doc)
             if e.tag == qn('w:p') and e.find('.//' + qn('w:numPr')) is not None]
    assert len(items) == 1
    assert ptext(items[0]) == '開啟後台網址。'      # not 'https://…/開啟後台網址。'
    assert items[0].find('.//' + qn('w:hyperlink')) is None
    assert URL not in ' '.join(ptext(e) for e in body_elements(doc))


def test_build_prunes_template_image_parts(tmp_path, messy_template, shots):
    """Regression: a 2-figure document inherited every screenshot of the template."""
    md = tmp_path / 'm.md'
    md.write_text('# Title\n\n- item\n\n![Login screen](login.png)\n', encoding='utf-8')
    out = str(tmp_path / 'small.docx')
    docx_build.main([str(md), '--template', messy_template, '--out', out,
                     '--images-dir', shots['dir']])

    assert len(media_names(messy_template)) == 3
    assert len(media_names(out)) == 1
    assert len(figures(docx.Document(out))) == 1
    assert os.path.getsize(out) < os.path.getsize(messy_template)


def test_extract_prunes_package_image_parts(tmp_path, built, messy_template):
    """The package document's own screenshots must not ride along either."""
    spec = {
        'package': messy_template,
        'sources': {'src': built},
        'parts': [{'figure': {'from': 'src', 'caption': '圖 1：Login screen'}}],
    }
    spec_path = tmp_path / 's.json'
    spec_path.write_text(json.dumps(spec, ensure_ascii=False), encoding='utf-8')
    out = str(tmp_path / 'delta2.docx')
    docx_extract.main(['--spec', str(spec_path), '--out', out])
    assert len(media_names(out)) == 1
