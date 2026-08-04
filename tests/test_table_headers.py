"""Table header structure.

Word decides which row lands in ``<thead>`` and it is often wrong. Two real
shapes from the 2026-08 Faculty Manual:

* "Advance Notice Table" — a merged full-width title row became the ``<thead>``
  while the real column headers sat in the body as ``<td>``, so the table had
  no programmatic headers at all (WCAG 1.3.1).
* A committee timeline whose first *data* row was promoted to ``<thead>``, so
  screen readers announced "Faculty Status Committee Investigation" as the
  column header for every row.

The first is repaired automatically; the second needs the operator override
added to the Table Review step.
"""

from bs4 import BeautifulSoup

from core.html_processor import (
    TABLE_HEADER_MODES,
    describe_tables,
    normalize_table_headers,
)
from core.styling import coerce_theme_settings

TITLE_ROW_TABLE = (
    "<table>"
    "<thead><tr><th colspan='3'>Advance Notice Table</th></tr></thead>"
    "<tbody>"
    "<tr><td>Type of Appointment</td><td>Year of Employment</td><td>Minimum Notice</td></tr>"
    "<tr><td>Annual (twelve-month)</td><td>1</td><td>3</td></tr>"
    "</tbody></table>"
)

DATA_ROW_AS_HEADER_TABLE = (
    "<table>"
    "<thead><tr><th>Faculty Status Committee Investigation</th><th>120 calendar days</th></tr></thead>"
    "<tbody><tr><td>Faculty Member's Written Response</td><td>15 business days</td></tr></tbody>"
    "</table>"
)

REAL_HEADER_TABLE = (
    "<table>"
    "<thead><tr><th></th><th>Tenure Track</th><th>Career Track</th></tr></thead>"
    "<tbody><tr><td>Number of nominations</td><td>6</td><td>2</td></tr></tbody>"
    "</table>"
)


def _table(html):
    return BeautifulSoup(html, "html.parser").find("table")


def _head_cells(table):
    thead = table.find("thead")
    row = thead.find("tr") if thead else None
    return [(c.name, c.get_text(strip=True)) for c in row.find_all(["th", "td"])] if row else []


def test_full_width_title_row_becomes_a_caption():
    table = _table(normalize_table_headers(TITLE_ROW_TABLE))
    caption = table.find("caption")
    assert caption is not None and caption.get_text(strip=True) == "Advance Notice Table"
    # The row beneath the title is now the real, programmatic header row.
    assert _head_cells(table) == [
        ("th", "Type of Appointment"),
        ("th", "Year of Employment"),
        ("th", "Minimum Notice"),
    ]
    assert all(th.get("scope") == "col" for th in table.find("thead").find_all("th"))


def test_title_row_repair_does_not_lose_data_rows():
    table = _table(normalize_table_headers(TITLE_ROW_TABLE))
    body_rows = table.find("tbody").find_all("tr")
    assert [c.get_text(strip=True) for c in body_rows[0].find_all("td")] == [
        "Annual (twelve-month)", "1", "3",
    ]


def test_a_genuine_header_row_is_left_alone():
    table = _table(normalize_table_headers(REAL_HEADER_TABLE))
    assert table.find("caption") is None
    assert _head_cells(table) == [("th", ""), ("th", "Tenure Track"), ("th", "Career Track")]


def test_none_override_demotes_a_data_row_out_of_thead():
    html = normalize_table_headers(DATA_ROW_AS_HEADER_TABLE, {"0": "none"})
    table = _table(html)
    assert table.find("thead") is None
    cells = table.find("tr").find_all(["th", "td"])
    assert [(c.name, c.get_text(strip=True)) for c in cells] == [
        ("td", "Faculty Status Committee Investigation"),
        ("td", "120 calendar days"),
    ]


def test_first_row_override_promotes_a_header():
    html = "<table><tbody><tr><td>Term</td><td>Deadline</td></tr><tr><td>Fall</td><td>Aug 1</td></tr></tbody></table>"
    table = _table(normalize_table_headers(html, {"0": "first_row"}))
    assert _head_cells(table) == [("th", "Term"), ("th", "Deadline")]
    assert all(th.get("scope") == "col" for th in table.find("thead").find_all("th"))


def test_overrides_are_addressed_by_table_position():
    html = f"<div>{REAL_HEADER_TABLE}{DATA_ROW_AS_HEADER_TABLE}</div>"
    soup = BeautifulSoup(normalize_table_headers(html, {"1": "none"}), "html.parser")
    first, second = soup.find_all("table")
    assert first.find("thead") is not None, "table 0 must be untouched"
    assert second.find("thead") is None, "table 1 carried the override"


def test_unknown_mode_falls_back_to_auto():
    table = _table(normalize_table_headers(TITLE_ROW_TABLE, {"0": "nonsense"}))
    assert table.find("caption") is not None


def test_describe_tables_reports_rows_for_review(tmp_path):
    path = tmp_path / "t.html"
    path.write_text(f"<div class='manual'>{TITLE_ROW_TABLE}{DATA_ROW_AS_HEADER_TABLE}</div>", encoding="utf-8")
    described = describe_tables(path, {"1": "none"})
    assert len(described) == 2
    assert described[0]["looks_like_title_row"] is True
    assert described[0]["head_cells"] == ["Advance Notice Table"]
    assert described[0]["first_body_cells"][0] == "Type of Appointment"
    assert described[0]["columns"] == 3
    assert described[1]["looks_like_title_row"] is False
    assert described[1]["mode"] == "none"


def test_describe_tables_tolerates_a_missing_file(tmp_path):
    assert describe_tables(tmp_path / "nope.html") == []


def test_theme_settings_keep_only_known_table_header_modes():
    settings, _ = coerce_theme_settings(
        {
            "table_header_mode_0": "none",
            "table_header_mode_1": "bogus",
            "table_header_mode_2": "auto",
            "table_header_mode_x": "none",
        },
        "chapter",
    )
    # "auto" is the default and is not stored; invalid values and non-numeric
    # table ids are dropped.
    assert settings["table_headers"] == {"0": "none"}
    assert all(m in TABLE_HEADER_MODES for m in settings["table_headers"].values())


def test_partial_theme_form_does_not_wipe_table_header_choices():
    """The preview theme panel posts a partial form; choices must survive it."""
    prior = {"table_headers": {"2": "none"}}
    settings, _ = coerce_theme_settings({"primary_color": "#123456"}, "chapter", prior=prior)
    assert settings["table_headers"] == {"2": "none"}
