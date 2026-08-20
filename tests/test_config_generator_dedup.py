"""Pin the deduplication of docx_config_generator.py against core/ and utils/.

The companion config generator used to carry drifted copies of ~10 helpers.
These tests assert it now shares the canonical implementations, so the two
apps cannot diverge again, and pin the behavior of the helpers it keeps
deliberately (its heading-prefix regex still strips bare letter prefixes
such as "A Title", which the pipeline copies do not).
"""
import core.docx_processor as dp
import docx_config_generator as g
import utils.helpers as uh


def test_generator_uses_canonical_implementations():
    assert g.is_heading_style is dp.is_heading_style
    assert g.serialize_sequence_map is dp.serialize_sequence_map
    assert g._extract_numbering_defs is dp._extract_numbering_defs
    assert g._extract_heading_prefix_tokens is dp._extract_heading_prefix_tokens
    assert g._classify_heading_token is dp._classify_heading_token
    assert g._int_to_roman is uh._int_to_roman
    assert g._int_to_letters is uh._int_to_letters


def test_generator_prefix_strip_handles_all_separators():
    # The generator regex still extends the canonical one with bare letter
    # prefixes; spelled-out chapter words and separators must match the
    # pipeline copies (en/em dashes must be present in the separator class).
    assert g._strip_heading_prefix_for_preview("Chapter One – Title") == "Title"
    assert g._strip_heading_prefix_for_preview("Chapter 2 — Overview") == "Overview"
    assert g._strip_heading_prefix_for_preview("Chapter 2 - Overview") == "Overview"
    assert g._strip_heading_prefix_for_preview("I.A.3. Duties") == "Duties"


def test_generator_style_map_tokens():
    assert g._extract_style_map_tokens("Section I.A. Governance") == ["I", "A"]


def test_docx_processor_prefix_separators():
    # The core/docx_processor copy had a stray literal backslash in its
    # separator class; en/em dashes must still match after the cleanup.
    assert dp._HEADING_PREFIX_RE.match("Chapter 2 – Title")
    assert dp._HEADING_PREFIX_RE.match("Chapter 2 — Title")
    assert dp._HEADING_PREFIX_RE.match("Chapter 2 - Title")


def test_generator_app_serves_home():
    client = g.app.test_client()
    assert client.get("/").status_code == 200
