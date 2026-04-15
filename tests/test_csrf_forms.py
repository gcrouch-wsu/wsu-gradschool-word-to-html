import io
import re

import pytest

from word_to_wordpressV4 import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = True
    with app.test_client() as c:
        yield c


def test_index_includes_csrf_meta_and_hidden_fields(client):
    r = client.get("/")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert 'name="csrf-token"' in html
    assert html.count('name="csrf_token"') >= 3


def test_post_without_csrf_returns_400(client):
    r = client.post(
        "/convert",
        data={"docx": (io.BytesIO(b""), "x.docx")},
        content_type="multipart/form-data",
    )
    assert r.status_code == 400


def test_post_with_valid_csrf_passes_csrf_layer(client):
    idx = client.get("/")
    html = idx.get_data(as_text=True)
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
    assert m
    token = m.group(1)
    r = client.post(
        "/convert",
        data={
            "csrf_token": token,
            "docx": (io.BytesIO(b"not a real docx"), "x.docx"),
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert r.status_code != 400
