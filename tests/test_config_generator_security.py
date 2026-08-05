"""Session-id handling and import recovery in the companion config generator.

`docx_config_generator.py` is a second Flask app, described as local-only. It has
no auth and no CSRF, and it interpolated the URL's session id straight into a
filesystem path — so `/export/..%5Cwhatever` read a file outside its directory on
Windows and `/example/..%5Cwhatever` wrote one. "Local-only" is a deployment
choice, not a control the app enforces, so the app has to defend itself.
"""

import importlib.util
import io
import json
import sys
import tempfile
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "config_generator_under_test",
    Path(__file__).resolve().parent.parent / "docx_config_generator.py",
)


@pytest.fixture(scope="module")
def generator():
    module = importlib.util.module_from_spec(_SPEC)
    sys.modules["config_generator_under_test"] = module
    _SPEC.loader.exec_module(module)
    module.app.config["TESTING"] = True
    return module


@pytest.fixture
def client(generator):
    return generator.app.test_client()


@pytest.mark.parametrize("route", ["/export", "/example", "/editor"])
@pytest.mark.parametrize("escape", ["..%5Cescape_probe", "..%2F..%2Fescape_probe",
                                    "....%5C%5Cescape_probe", "not-a-uuid"])
def test_a_session_id_that_is_not_a_uuid_is_refused(client, route, escape):
    assert client.get(f"{route}/{escape}").status_code == 404


def test_a_planted_file_outside_the_session_directory_is_not_served(client):
    """The reproduction: read a file the app never created."""
    planted = Path(tempfile.gettempdir()) / "escape_probe_config.json"
    planted.write_text('{"secret": "outside PERSIST_DIR"}', encoding="utf-8")
    try:
        response = client.get("/export/..%5Cescape_probe")
        assert response.status_code == 404
        assert b"outside PERSIST_DIR" not in response.data
    finally:
        planted.unlink(missing_ok=True)


def test_nothing_is_written_outside_the_session_directory(client):
    """The other half: /example wrote a .docx wherever the id pointed."""
    written = Path(tempfile.gettempdir()) / "escape_probe_example.docx"
    written.unlink(missing_ok=True)
    planted = Path(tempfile.gettempdir()) / "escape_probe_config.json"
    planted.write_text(json.dumps({"styles": {"body": {}}, "headings": []}), encoding="utf-8")
    try:
        assert client.get("/example/..%5Cescape_probe").status_code == 404
        assert not written.exists(), "a DOCX was written outside PERSIST_DIR"
    finally:
        planted.unlink(missing_ok=True)
        written.unlink(missing_ok=True)


def test_a_well_formed_but_unknown_session_is_a_redirect_not_an_error(client):
    """A real id for a session that has expired is a normal miss."""
    response = client.get("/export/00000000-0000-4000-8000-000000000000")
    assert response.status_code == 302


def test_an_imported_config_can_actually_be_edited(client):
    """Import accepted the upload, then the editor returned 500 on the next hop.

    The route wrote `{}` as the analysis file while the editor template requires
    the shape analyse_docx() produces, so the advertised "resume from an exported
    configuration" path failed after appearing to succeed.
    """
    response = client.post(
        "/import-config",
        data={"config_json": (io.BytesIO(json.dumps({}).encode()), "c.json")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 302
    session_id = response.headers["Location"].rstrip("/").split("/")[-1]
    assert client.get(f"/editor/{session_id}").status_code == 200
    assert client.get(f"/export/{session_id}").status_code == 200
    assert client.get(f"/example/{session_id}").status_code == 200


def test_the_empty_analysis_shape_covers_what_the_editor_reads(generator):
    analysis = generator.empty_analysis()
    assert analysis["accessibility"]["heading_order_issues"] == []
    assert analysis["accessibility"]["heading_levels_used"] == []
    for key in ("headings", "style_samples", "list_formats", "resolved_styles"):
        assert key in analysis, key


# --- malformed configs are rejected, not crashed on ------------------------

@pytest.mark.parametrize("payload,expected", [
    ([], "not an object"),
    ("just a string", "not an object"),
    ({"styles": []}, '"styles" should be an object'),
    ({"conversion": []}, '"conversion" should be an object'),
    ({"numbering": []}, '"numbering" should be an object'),
    ({"lists": []}, '"lists" should be an object'),
    ({"document_info": "not-a-dict"}, '"document_info" should be an object'),
    ({"styles": {"body": []}}, '"styles.body" should be an object'),
    ({"styles": {"headings": 3}}, '"styles.headings" should be an object'),
    ({"lists": {"multilevel_formats": "x"}}, '"lists.multilevel_formats" should be an object'),
])
def test_a_config_of_the_wrong_shape_is_refused_with_a_reason(client, payload, expected):
    """These raised AttributeError from .setdefault() and returned a 500.

    An administrator who picks the wrong JSON file should get a sentence
    naming the problem, not a stack trace after an apparently successful upload.
    """
    import html as html_module

    response = client.post(
        "/import-config",
        data={"config_json": (io.BytesIO(json.dumps(payload).encode()), "c.json")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert response.status_code == 200
    body = html_module.unescape(response.get_data(as_text=True))
    assert "not a usable configuration" in body
    assert expected in body


@pytest.mark.parametrize("payload", [
    {},
    {"styles": {"body": {"font": "Calibri"}}},
    {"conversion": {"manual_type": "section"}, "lists": {"unordered_formats": {"0": "disc"}}},
])
def test_a_config_of_a_usable_shape_is_still_accepted(client, payload):
    response = client.post(
        "/import-config",
        data={"config_json": (io.BytesIO(json.dumps(payload).encode()), "c.json")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 302
    session_id = response.headers["Location"].rstrip("/").split("/")[-1]
    assert client.get(f"/editor/{session_id}").status_code == 200
