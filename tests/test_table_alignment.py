"""Table column alignment.

Two defects from the published Faculty Manual:

1. Alignment was decided per *cell*, so the Advance Notice Table's columns came
   out ragged — "3" and "12" centred while "3*" and "3 or more" fell left, even
   though they belong to the same column.
2. `build_manual_grid_block` re-ran the alignment pass with default arguments,
   overwriting whatever the pipeline had computed. Every Table Review alignment
   choice was therefore discarded in the preview and in every download, so the
   setting appeared to do nothing.
"""

from bs4 import BeautifulSoup

from core.html_processor import (
    build_manual_grid_block,
    format_manual_tables,
    process_html_pipeline,
)
from core.styling import TABLE_ALIGN_MODES, coerce_theme_settings

# Column 2 mixes "1"/"2" with "3 or more"; column 3 mixes "3"/"12" with "3*".
ADVANCE_NOTICE = (
    "<table><thead><tr><th>Type of Appointment</th><th>Year</th><th>Notice</th></tr></thead>"
    "<tbody>"
    "<tr><td>Annual (twelve-month)</td><td>1</td><td>3</td></tr>"
    "<tr><td>Annual (twelve-month)</td><td>3 or more</td><td>12</td></tr>"
    "<tr><td>Academic (nine-month)</td><td>1</td><td>3*</td></tr>"
    "<tr><td>Academic (nine-month)</td><td>3 or more</td><td>9*</td></tr>"
    "</tbody></table>"
)


def _aligns(html, table_index=0):
    """Alignment class of every cell, row by row."""
    table = BeautifulSoup(html, "html.parser").find_all("table")[table_index]
    rows = []
    for tr in table.find_all("tr"):
        rows.append([
            next((c.replace("manual-align-", "") for c in (cell.get("class") or [])
                  if c.startswith("manual-align-")), None)
            for cell in tr.find_all(["th", "td"])
        ])
    return rows


def _column(html, idx, table_index=0):
    return [row[idx] for row in _aligns(html, table_index)]


def test_whole_column_is_aligned_together():
    """A footnote marker must not knock a cell out of line with its column."""
    out = format_manual_tables(ADVANCE_NOTICE)
    assert set(_column(out, 1)) == {"center"}, _column(out, 1)
    assert set(_column(out, 2)) == {"center"}, _column(out, 2)


def test_text_column_stays_left():
    out = format_manual_tables(ADVANCE_NOTICE)
    assert set(_column(out, 0)) == {"left"}, _column(out, 0)


def test_a_column_that_is_mostly_text_is_not_centred():
    """One stray number must not centre a column of prose."""
    html = (
        "<table><tbody>"
        "<tr><td>Investigation</td><td>120 calendar days</td></tr>"
        "<tr><td>Written response</td><td>15 business days</td></tr>"
        "<tr><td>Appeal</td><td>30</td></tr>"
        "</tbody></table>"
    )
    out = format_manual_tables(html)
    assert set(_column(out, 1)) == {"left"}, _column(out, 1)


def test_explicit_column_setting_still_overrides_detection():
    out = format_manual_tables(ADVANCE_NOTICE, col1_align="center")
    assert set(_column(out, 0)) == {"center"}


def test_per_table_align_override_is_scoped_to_that_table():
    html = f"<div>{ADVANCE_NOTICE}{ADVANCE_NOTICE}</div>"
    out = format_manual_tables(html, align_overrides={"1": "left_all"})
    assert set(_column(out, 2, table_index=0)) == {"center"}, "table 0 must be untouched"
    assert set(_column(out, 2, table_index=1)) == {"left"}, "table 1 carried the override"


def test_unknown_align_mode_falls_back_to_auto():
    out = format_manual_tables(ADVANCE_NOTICE, align_overrides={"0": "nonsense"})
    assert set(_column(out, 2)) == {"center"}


def test_grid_block_does_not_re_align_the_body():
    """The regression: the grid builder used to overwrite the pipeline's work."""
    aligned = format_manual_tables(ADVANCE_NOTICE, col1_align="center", col2_align="right")
    block = build_manual_grid_block(aligned, 2, "chapter", "preserve")
    assert set(_column(block, 0)) == {"center"}, _column(block, 0)
    assert set(_column(block, 1)) == {"right"}, _column(block, 1)


def test_pipeline_alignment_settings_reach_the_output():
    config = {
        "toc_depth": 2,
        "preserve_numbers": True,
        "table_col2_align": "right",
        "table_aligns": {},
    }
    body, _toc = process_html_pipeline(
        f"<body><div class='manual'>{ADVANCE_NOTICE}</div></body>", "s", config
    )
    assert set(_column(body, 1)) == {"right"}, _column(body, 1)
    # And the grid block the downloads are built from keeps it.
    block = build_manual_grid_block(body, 2, "chapter", "preserve")
    assert set(_column(block, 1)) == {"right"}


def test_theme_settings_collect_per_table_align_modes():
    settings, _ = coerce_theme_settings(
        {
            "table_align_mode_0": "left_all",
            "table_align_mode_1": "auto",
            "table_align_mode_2": "bogus",
            "table_align_mode_x": "left_all",
        },
        "chapter",
    )
    assert settings["table_aligns"] == {"0": "left_all"}
    assert all(m in TABLE_ALIGN_MODES for m in settings["table_aligns"].values())


def test_partial_theme_form_keeps_per_table_align_modes():
    prior = {"table_aligns": {"1": "center_all"}}
    settings, _ = coerce_theme_settings({"primary_color": "#123456"}, "chapter", prior=prior)
    assert settings["table_aligns"] == {"1": "center_all"}
