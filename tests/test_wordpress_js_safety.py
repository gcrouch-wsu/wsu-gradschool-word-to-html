"""Source-level guards on the published JavaScript.

``wordpress.js`` runs on the live WordPress page, so a defect there is reachable
by any visitor. It has no browser test harness, and an independent review found a
cross-site scripting hole in the TOC search that had been shipping: search results
were assembled by concatenating the manual's own text into an HTML string and
assigning it through ``innerHTML``. Text that is inert in the published page —
a heading quoting an HTML example, say — became live markup the moment a reader
searched for it.

These tests read the file rather than execute it. They cannot prove the search
behaves correctly, but they do enforce the rule that made the bug possible:
manual text is never turned into markup.
"""

import re
from pathlib import Path

import pytest

JS = Path(__file__).resolve().parent.parent / "wordpress.js"
SOURCE = JS.read_text(encoding="utf-8")

# A double- or single-quoted JS string literal.
_STRING = re.compile(r'"(?:[^"\\]|\\.)*"' + r"|'(?:[^'\\]|\\.)*'")
# To end of line, not to the first ";": these right-hand sides contain inline CSS
# with semicolons inside the string literal.
_INNER_HTML_ASSIGN = re.compile(r'\.innerHTML\s*=\s*(.+)$', re.MULTILINE)


def _assignments():
    for match in _INNER_HTML_ASSIGN.finditer(SOURCE):
        line = SOURCE[: match.start()].count("\n") + 1
        yield line, match.group(1).strip().rstrip(";").strip()


def test_the_file_is_present_and_substantial():
    assert len(SOURCE) > 10_000, "wordpress.js looks truncated"


def _residue(rhs: str) -> str:
    """What is left of a right-hand side once string literals are removed."""
    return re.sub(r"[\s+]", "", _STRING.sub("", rhs))


def test_the_guard_itself_catches_the_original_defect():
    """A test that never fails proves nothing — check it flags the real bug."""
    assert _residue("snippet + parentInfo"), \
        "the guard must reject a right-hand side built from variables"
    assert _residue('"prefix" + match.title'), \
        "a literal concatenated with page content must still be rejected"
    literal_with_semicolons = '''"<div style='padding: 12px; color: #666;'>No matches</div>"'''
    assert not _residue(literal_with_semicolons), \
        "a literal containing semicolons must be accepted"


def test_no_innerHTML_assignment_takes_anything_but_a_literal():
    """The rule the XSS broke: never build markup out of page content.

    A literal is fine — a static "no matches" message, an icon glyph, or "" to
    clear a container. Anything with a variable in it means manual text is being
    turned into HTML, which is how the search bug worked.
    """
    offenders = [
        f"wordpress.js:{line}  innerHTML = {rhs[:70]}"
        for line, rhs in _assignments() if _residue(rhs)
    ]
    assert not offenders, (
        "innerHTML assigned from something other than a string literal:\n  "
        + "\n  ".join(offenders)
    )


def test_search_results_use_text_nodes_for_manual_content():
    assert "resultItem.textContent = levelIndicator + match.title" in SOURCE, \
        "heading titles must go into the DOM as text, not markup"
    assert "appendHighlighted(contentItem" in SOURCE, \
        "content snippets must be built as nodes"


def test_the_snippet_builder_no_longer_emits_markup():
    """createSnippet used to splice a <span> into the string it returned."""
    start = SOURCE.index("var createSnippet = function")
    body = SOURCE[start:start + 1200]
    assert "<span" not in body, "createSnippet must return plain text"
    assert "manual-search-highlight" not in body, \
        "highlighting belongs to appendHighlighted, as elements"


def test_the_highlighter_builds_elements_rather_than_strings():
    start = SOURCE.index("var appendHighlighted = function")
    body = SOURCE[start:start + 1400]
    assert 'document.createElement("span")' in body
    assert "mark.textContent" in body, "the matched run must be set as text"
    assert "document.createTextNode" in body, "surrounding text must be text nodes"


def test_search_fallback_removes_orphan_clear_text():
    start = SOURCE.index("if (!tocSearch)")
    body = SOURCE[start:start + 1200]
    assert "child.nodeType === 3" in body
    assert 'child.nodeValue.trim() === "X"' in body
    assert "searchDiv.removeChild(child)" in body


def test_heading_copy_icon_stays_with_the_last_word():
    start = SOURCE.index("var appendHeadingLinkIcon")
    body = SOURCE[start:start + 2600]
    assert "heading-link-cluster" in body
    assert 'cluster.style.setProperty("white-space", "nowrap", "important")' in body
    assert "window.getComputedStyle" in body
    assert 'cluster.style.setProperty(prop, headingStyle.getPropertyValue(prop), "important")' in body
    assert "document.createTextNode(match[2])" in body
    assert "cluster.appendChild(icon)" in body
    assert 'this.closest("h1, h2, h3, h4, h5, h6")' in SOURCE


@pytest.mark.parametrize("sink", ["insertAdjacentHTML", "outerHTML", "document.write"])
def test_other_markup_sinks_are_absent(sink):
    """Keep the surface to the one reviewed sink."""
    assert sink not in SOURCE, f"{sink} is another way to turn text into markup"
