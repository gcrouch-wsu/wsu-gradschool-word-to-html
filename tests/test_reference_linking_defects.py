"""Regression tests for the reference-linking defects found in the 2026-08
Faculty Manual output.

Each case is reduced from a real paragraph in that manual:

1. The same label twice in one paragraph — only the first copy was linked.
2. A short label ("Section II.F") matched inside a longer one
   ("Section II.F.6"), linking the wrong target and stranding the remainder.
3. A Word cross-reference field covering only part of a label, leaving the
   rest of the label outside the anchor.
4. A stale ``#anchor`` in the External URL field silently deleting the link.

Headings are shaped like the real manual (an ``h1`` "Section N: …" establishing
the section, numbered descendants below it) because that is what
``scrape_heading_structure_from_html`` needs in order to key headings by their
reference label.
"""

from bs4 import BeautifulSoup

from core.html_processor import generate_stable_ref_id, process_html_pipeline


def _run(html: str, references: list, *, edits=None, external=None):
    """Run the pipeline with every listed reference approved."""
    validations = {
        generate_stable_ref_id(ref[0], ref[3], ref[2]): True for ref in references
    }
    config = {
        "toc_depth": 2,
        "preserve_numbers": True,
        "mapping_mode": "keep_old",
        "references": references,
        "reference_edits": edits or {},
        "reference_validations": validations,
        "reference_link_targets": {},
        "reference_ignored": {},
        "reference_external_urls": external or {},
        "auto_crosswalk": {ref[2]: ref[2] for ref in references},
        "new_headings": {},
    }
    body, _toc = process_html_pipeline(html, "s", config)
    return BeautifulSoup(body, "html.parser")


def _links(soup):
    return [
        (a.get_text(strip=True), a.get("href", ""))
        for a in soup.find_all("a", href=True)
    ]


def _rid(references, index=0):
    ref = references[index]
    return generate_stable_ref_id(ref[0], ref[3], ref[2])


PARA_TRADEMARKS = (
    "Distributed according to the schedule used for Patents, Section IV.G.8, "
    "or for Plant Varieties, Section IV.G.9, as appropriate, but see "
    "Section IV.G.8 again."
)

TRADEMARK_HTML = (
    "<body><div class='manual'>"
    "<h1>Section IV: University Policies</h1>"
    "<h2>IV.G. Intellectual Property</h2>"
    "<h3>IV.G.8. Patents</h3><p>Patent terms.</p>"
    "<h3>IV.G.9. Plant Varieties</h3><p>Variety terms.</p>"
    "<h2>IV.J. Trademarks</h2>"
    f"<p>{PARA_TRADEMARKS}</p>"
    "</div></body>"
)


def test_repeated_reference_in_one_paragraph_links_every_copy():
    """Every copy of a label in one paragraph gets its own link."""
    references = [
        (2, PARA_TRADEMARKS, "Section IV.G.8", PARA_TRADEMARKS.index("Section IV.G.8"), 0, False),
        (2, PARA_TRADEMARKS, "Section IV.G.9", PARA_TRADEMARKS.index("Section IV.G.9"), 0, False),
        (2, PARA_TRADEMARKS, "Section IV.G.8", PARA_TRADEMARKS.rindex("Section IV.G.8"), 0, False),
    ]
    links = _links(_run(TRADEMARK_HTML, references))
    assert sum(1 for text, _ in links if text == "Section IV.G.8") == 2, links
    assert sum(1 for text, _ in links if text == "Section IV.G.9") == 1, links
    assert all(href == "#ivg8-patents" for text, href in links if text == "Section IV.G.8"), links
    assert ("Section IV.G.9", "#ivg9-plant-varieties") in links, links


def test_repeated_reference_leaves_no_plain_text_copy():
    """The second copy is not left behind as unlinked text."""
    references = [
        (2, PARA_TRADEMARKS, "Section IV.G.8", PARA_TRADEMARKS.index("Section IV.G.8"), 0, False),
        (2, PARA_TRADEMARKS, "Section IV.G.8", PARA_TRADEMARKS.rindex("Section IV.G.8"), 0, False),
    ]
    soup = _run(TRADEMARK_HTML, references)
    para = soup.find_all("p")[-1]
    unlinked = "".join(
        str(node) for node in para.descendants
        if isinstance(node, str) and not node.find_parent("a")
    )
    assert "Section IV.G.8" not in unlinked, unlinked


DISCIPLINE_HTML = (
    "<body><div class='manual'>"
    "<h1>Section II: Freedom, Responsibility, and Discipline</h1>"
    "<h2>II.F. Corrective Action and Disciplinary Process</h2><p>Process.</p>"
    "<h3>II.F.6. Temporary Reassignment</h3><p>Reassignment terms.</p>"
    "<h3>II.F.8. No Discipline</h3><p>No discipline terms.</p>"
    "{body}"
    "</div></body>"
)


def test_short_label_does_not_match_inside_longer_label():
    """'Section II.F' must not claim the text of 'Section II.F.6'."""
    para = "Pending resolution as set forth in Section II.F.6 below."
    html = DISCIPLINE_HTML.format(body=f"<p>{para}</p>")
    references = [(3, para, "Section II.F.6", para.index("Section II.F.6"), 0, False)]
    links = _links(_run(html, references))
    assert links == [("Section II.F.6", "#iif6-temporary-reassignment")], links


def test_label_ending_a_sentence_still_matches():
    """The boundary guard must not reject a label followed by a period."""
    para = "See Section II.F."
    html = DISCIPLINE_HTML.format(body=f"<p>{para}</p>")
    references = [(3, para, "Section II.F", para.index("Section II.F"), 0, False)]
    links = _links(_run(html, references))
    assert links == [
        ("Section II.F", "#iif-corrective-action-and-disciplinary-process")
    ], links


def test_split_word_cross_reference_is_absorbed():
    """A Word field covering only part of the label is repaired, not left split."""
    para = "Pending resolution as set forth in Section II.F.6 below."
    body = (
        "<p>Pending resolution as set forth in "
        "<a href='#iif-corrective-action-and-disciplinary-process'>Section II.F</a>.6 below.</p>"
    )
    html = DISCIPLINE_HTML.format(body=body)
    references = [(3, para, "Section II.F.6", para.index("Section II.F.6"), 0, False)]
    soup = _run(html, references)
    assert _links(soup) == [("Section II.F.6", "#iif6-temporary-reassignment")], _links(soup)
    para_tag = soup.find_all("p")[-1]
    # The stranded ".6" is pulled inside the anchor, not left beside it.
    assert "</a>.6" not in str(para_tag)
    assert para_tag.get_text().count("Section II.F.6") == 1


def test_stale_internal_anchor_in_external_url_falls_back():
    """A dead #anchor in the External URL field must not delete the link."""
    para = "As described in Section II.F.8 above."
    html = DISCIPLINE_HTML.format(body=f"<p>{para}</p>")
    references = [(3, para, "Section II.F.8", para.index("Section II.F.8"), 0, False)]
    # "#iif8" is a stale slug from an earlier cycle; the live id is longer, so
    # honoring it built a link that the dead-link sweep then stripped.
    soup = _run(html, references, external={_rid(references): "#iif8"})
    assert _links(soup) == [("Section II.F.8", "#iif8-no-discipline")], _links(soup)


def test_live_internal_anchor_in_external_url_is_honored():
    """A valid #anchor in the External URL field still overrides the auto-match."""
    para = "As described in Section II.F.8 above."
    html = DISCIPLINE_HTML.format(body=f"<p>{para}</p>")
    references = [(3, para, "Section II.F.8", para.index("Section II.F.8"), 0, False)]
    soup = _run(html, references, external={_rid(references): "#iif6-temporary-reassignment"})
    assert _links(soup) == [("Section II.F.8", "#iif6-temporary-reassignment")], _links(soup)


def test_external_http_url_still_wins_and_is_marked():
    """An http External URL is unaffected by the stale-anchor check."""
    para = "As described in Section II.F.8 above."
    html = DISCIPLINE_HTML.format(body=f"<p>{para}</p>")
    references = [(3, para, "Section II.F.8", para.index("Section II.F.8"), 0, False)]
    soup = _run(html, references, external={_rid(references): "https://policies.wsu.edu/x"})
    anchor = soup.find("a", href="https://policies.wsu.edu/x")
    assert anchor is not None, _links(soup)
    assert anchor.get("target") == "_blank"
    assert "external-link" in (anchor.get("class") or [])


# --- citation prefixes belong inside the anchor --------------------------

def test_a_citation_prefix_is_pulled_inside_the_anchor():
    """"RCW" sat outside the link because the app drew the boundary there.

    The reference pattern matches the number, so the anchor covered
    "42.52.040" and left "RCW" as plain text beside it. Nothing in the source
    document places that link — the app creates it — so extending it to the
    whole citation is the app correcting its own structure.
    """
    para = "A contract prohibited by RCW 42.52.040 is void."
    html = DISCIPLINE_HTML.format(body=f"<p>{para}</p>")
    references = [(3, para, "42.52.040", para.index("42.52.040"), 0, False)]
    soup = _run(html, references,
                external={_rid(references): "https://app.leg.wa.gov/RCW/default.aspx?cite=42.52.040"})
    anchor = soup.find("a", href=lambda h: h and "leg.wa.gov" in h)
    assert anchor is not None
    assert anchor.get_text() == "RCW 42.52.040"
    assert "RCW" not in str(anchor.previous_sibling or "")


def test_ordinary_words_before_a_link_are_left_alone():
    """Only citation words are absorbed, not the preceding prose."""
    para = "As set out in 42.52.040 the rule applies."
    html = DISCIPLINE_HTML.format(body=f"<p>{para}</p>")
    references = [(3, para, "42.52.040", para.index("42.52.040"), 0, False)]
    soup = _run(html, references,
                external={_rid(references): "https://app.leg.wa.gov/RCW/default.aspx?cite=42.52.040"})
    anchor = soup.find("a", href=lambda h: h and "leg.wa.gov" in h)
    assert anchor.get_text() == "42.52.040", "'in' is prose, not a citation prefix"


def test_a_prefix_is_absorbed_whichever_path_created_the_link():
    """Links are built in three places; absorption runs once over the result.

    "RCW Chapter 42.52" is the real manual's shape — the label already contains
    "Chapter", so it takes a different replacement path from a bare number, and
    an earlier per-branch implementation missed it.
    """
    para = "The Act, RCW Chapter 42.52, and its regulations apply."
    html = DISCIPLINE_HTML.format(body=f"<p>{para}</p>")
    references = [(3, para, "Chapter 42.52", para.index("Chapter 42.52"), 0, False)]
    soup = _run(html, references,
                external={_rid(references): "https://app.leg.wa.gov/RCW/default.aspx?cite=42.52"})
    anchor = soup.find("a", href=lambda h: h and "leg.wa.gov" in h)
    assert anchor.get_text() == "RCW Chapter 42.52", anchor.get_text()


def test_a_prefix_inside_formatting_markup_is_left_alone():
    """Known limit: only a plain-text prefix is absorbed.

    Pulling "RCW" out of an <em> would either drop the emphasis or require
    restructuring the run. No citation in the Faculty Manual is formatted that
    way, so the anchor is left as-is rather than mangling the markup.
    """
    para = "The Act, RCW Chapter 42.52, applies."
    body = "<p>The Act, <em>RCW </em>Chapter 42.52, applies.</p>"
    html = DISCIPLINE_HTML.format(body=body)
    references = [(3, para, "Chapter 42.52", para.index("Chapter 42.52"), 0, False)]
    soup = _run(html, references,
                external={_rid(references): "https://app.leg.wa.gov/RCW/default.aspx?cite=42.52"})
    anchor = soup.find("a", href=lambda h: h and "leg.wa.gov" in h)
    assert anchor.get_text() == "Chapter 42.52"
    assert "RCW" in soup.find("em").get_text(), "the emphasis is preserved untouched"
