# .docx internals the scripts rely on

A .docx is a zip. `word/document.xml` holds the body; `word/media/*` holds images; `word/_rels/document.xml.rels` maps relationship ids (`rId12`) to parts; `word/numbering.xml` holds list definitions; `word/styles.xml` holds styles. Everything below is a consequence of that.

## Reading text: `p.text` can be empty

Google Docs (and some Word add-ins) wrap heading text in a structured document tag `w:sdt`. python-docx's `paragraph.text` only walks direct `w:r` children, so such headings read as `""` and prefix searches miss them. Always read text as

```python
''.join(t.text or '' for t in el.iter(qn('w:t')))
```

`docxkit.ptext()` does this. When *writing* text into such a paragraph, set the first `w:t` and delete the rest (`docxkit.set_text`) instead of rebuilding runs, so the sdt wrapper and run formatting survive.

## Images

- A picture paragraph contains `w:drawing → … → a:blip r:embed="rIdN"`. The rId resolves through the document part's rels to `word/media/imageNN.png`.
- **Media names are per document.** `image50.png` in manual A and `image50.png` in manual B are unrelated files. Map images by caption (the next non-empty paragraph) and verify with the md5 or a thumbnail.
- The *displayed* size is `wp:extent cx/cy` (EMU, 914400 per inch) and the picture's own `a:ext`. Replacing the media bytes does not change layout; if the new image has a different aspect ratio it will be stretched. `docx_replace_images.py` therefore resizes the new PNG to the old pixel size by default (`--no-resize` rescales the extents instead).
- Replacing bytes is safe to do at zip level: rewrite the archive with the same entry names and only the media payload changed. Keep the original `ZipInfo` so compression flags stay identical.
- Every `wp:docPr` needs a unique `id` within the document, or Word reports the file as corrupt. After copying elements, renumber them (`docxkit.unique_docpr_ids`).
- An image part that no `a:blip` references still ships inside the file. A delta document built from two 20 MB manuals reaches 40 MB unless orphan image rels are removed (`docxkit.prune_unused_images`).

## Copying elements between documents

`copy.deepcopy(element)` copies XML only. Three kinds of references then point into the *source* package and must be rewritten (`docxkit.Importer`):

1. **Images**: read the source blob, `dst.part.get_or_add_image(BytesIO(blob))`, set the new rId on the blip.
2. **List numbering**: `w:numPr/w:numId` refers to `word/numbering.xml`. Copy the referenced `w:abstractNum` and `w:num` into the destination with an id offset (+100) and rewrite `numId`. Without this the paragraph shows the destination's list at that id (or nothing).
3. **Table styles**: `w:tblStyle` refers to a style id. Copy the style into the destination under a prefixed id (`ScnTable1`) so it cannot collide with an existing style of the same id but different look.

Hyperlinks (`w:hyperlink r:id`) are external relationships; recreate them with `relate_to(target, RT.HYPERLINK, is_external=True)`.

Paragraph styles (`w:pStyle`) are *not* copied on purpose: the destination's `Heading 2` should look like the destination's. If the source uses a style id the destination lacks, Word falls back to Normal, which is what you want in a delta document.

## Templates by cloning

The most robust way to get "a heading that looks like the client's headings" is to deep-copy one of the client's heading paragraphs and replace its text, rather than calling `add_heading` and hoping the style exists. `docxkit.TemplateSet` discovers one specimen of each construct (Heading 1-3, body paragraph, caption, horizontal rule, page break, table) by style id and by shape (an HR is a paragraph containing `w:pict`; a page break is `w:br w:type="page"`), then `clone_*` deep-copies and re-texts it.

When re-texting a cloned paragraph, remove *every* child except `w:pPr` before adding new runs. Text also lives inside `w:hyperlink`, `w:sdt`, `w:fldSimple` and `w:ins`; a naive "delete the `w:r` children" leaves a list item that still reads `https://…/` in front of your text. Take run formatting from the first `w:r/w:rPr` found anywhere in the specimen, minus the hyperlink's own `rStyle`/`color`/`u`, or every new bullet comes out blue and underlined. Prefer specimen paragraphs that carry no hyperlink or picture (`TemplateSet` does).

Horizontal rules from Google Docs are `w:pict` with a VML line, not a border. Copy the specimen; do not try to synthesise one.

## Assembling a document

Clear the body but keep the trailing `w:sectPr` (page size, margins, header/footer references), then insert new elements before it. Save through python-docx so the content types and rels are written consistently. Set `core_properties.title`; some clients' SharePoint shows it instead of the file name.

## Debugging a "corrupt" file

Word's "unreadable content" almost always means one of: duplicate `docPr` ids, a `numId` with no `w:num`, a `tblStyle` that does not exist, or an `r:embed` with no rel. `docx_inspect.py` shows the structure; unzip and diff `document.xml.rels` against the blips when in doubt. LibreOffice is more forgiving than Word, so test with Word (or Google Docs import) before delivery.

## Sizes

Typical: one 1080×2400 phone screenshot downscaled to 921×2047 PNG is 200–700 KB; a 1600×1100 web screenshot 150–400 KB. A 100-figure manual lands around 15–20 MB. Google Drive and email handle that; if a client's mail gateway rejects it, re-encode media as JPEG (quality 85) inside the zip rather than shrinking pixels.
