"""The zone table placed in the answer, once (src/petroharness/agent/compose.py).

    .venv/bin/python -m pytest tests/agent/test_compose.py -q
"""
from petroharness.agent.compose import ZONE_TABLE_TOKEN, compose

TABLE = """| Depth Interval (m) | Lithology | Mean SW (v/v) | Mean VCL (v/v) | NET_PAY fraction |
|---|---|---|---|---|
| 1938.0708-1944.3192 | Shaly | 0.9726 | 0.4195 | 0 |
| 1948.1292-1958.7972 | Shaly | 0.9283 | 0.4003 | 0 |
| 1959.2544-1990.6488 | Shaly | 0.8358 | 0.472 | 0 |"""


def _draft(own: str, label: str = "") -> str:
    return f"## Evidence\n\n{ZONE_TABLE_TOKEN}\n\n{label}{own}\n\n## Limits\n\nBad hole in Z2."


def test_a_table_that_repeats_the_zone_table_is_left_out():
    """The same zones under the zone table's own column headers (bold and case aside): a repeat, left out with its
    bold label."""
    own = """| depth interval (m) | Lithology | **Mean SW (v/v)** | mean vcl (v/v) |
|---|---|---|---|
| 1938.0708–1944.3192 | Shaly | 0.9726 | 0.4195 |
| 1948.13–1958.80 | Shaly | 0.9283 | 0.4003 |
| 1959.2544–1990.6488 | Shaly | 0.8358 | 0.472 |"""
    out = compose(_draft(own, "**Zone SW means**\n\n"), TABLE)
    assert out.count("| Shaly |") == 3 and "**Mean SW (v/v)**" not in out and "Zone SW means" not in out
    assert "## Limits\n\nBad hole in Z2." in out and out.index("Mean VCL") < out.index("## Limits")


def test_a_table_with_a_column_the_zone_table_does_not_have_stays():
    """A column named unlike every zone table column is the writer's own (NET_PAY runs beside a NET_PAY fraction, a
    median beside a mean), so the table stays with its label: deleting it dropped the model's content and left the
    sentence that points at it dangling."""
    runs = """| Depth Interval (m) | Lithology | Mean SW (v/v) | NET_PAY runs (m) |
|---|---|---|---|
| 1938.0708–1944.3192 | Shaly | 0.9726 | 0 |
| 1948.13–1958.80 | Shaly | 0.9283 | 0 |
| 1959.2544–1990.6488 | Shaly | 0.8358 | 0 |"""
    out = compose(_draft(runs, "**Zone SW means**\n\n"), TABLE)
    assert out.count("| Shaly |") == 6 and "NET_PAY runs (m)" in out and "**Zone SW means**" in out
    medians = """| Depth Interval (m) | Median SW (v/v) | Median VCL (v/v) |
|---|---|---|
| 1938.0708-1944.3192 | 0.9801 | 0.4102 |
| 1948.1292-1958.7972 | 0.9355 | 0.3987 |
| 1959.2544-1990.6488 | 0.8411 | 0.4650 |"""
    out = compose(_draft(medians, "**Zone medians**\n\n"), TABLE)
    assert "| 1938.0708-1944.3192 | 0.9801 | 0.4102 |" in out and "**Zone medians**" in out and "Mean VCL" in out


def test_a_table_of_some_zones_stays():
    own = """| Zone | Depth (m) | Mean SW |
|---|---|---|
| Z1 | 1938.0708-1944.3192 | 0.9726 |
| Z2 | 1948.1292-1958.7972 | 0.9283 |"""
    out = compose(_draft(own), TABLE)
    assert out.count("| Shaly |") == 3 and "| Z1 | 1938.0708-1944.3192 | 0.9726 |" in out


def test_a_table_with_a_curve_of_its_own_stays():
    own = """| Zone | Depth (m) | Mean RHOB (g/cc) | Mean SW |
|---|---|---|---|
| Z1 | 1938.0708-1944.3192 | 2.31 | 0.9726 |
| Z2 | 1948.1292-1958.7972 | 2.28 | 0.9283 |
| Z3 | 1959.2544-1990.6488 | 2.25 | 0.8358 |"""
    out = compose(_draft(own), TABLE)
    assert "Mean RHOB" in out and out.count("| Shaly |") == 3


def test_one_zone_is_never_taken_for_a_repeat():
    one = TABLE.split("\n| 1948")[0]
    own = "| Interval | SW |\n|---|---|\n| 1938.0708-1944.3192 | 0.9726 |"
    assert "| 1938.0708-1944.3192 | 0.9726 |" in compose(_draft(own), one)


def test_a_heading_with_no_text_is_left_out():
    out = compose(f"## Evidence\n\n###\n\n{ZONE_TABLE_TOKEN}\n\n### Point 3\n\nText.", TABLE)
    assert "###\n" not in out and "### Point 3" in out and "## Evidence" in out


def test_a_table_with_a_column_of_the_writers_own_stays():
    """A count, a thickness or a role per zone is the writer's reading, not a repeat of the zone table."""
    own = """| Zone | Depth (m) | Mean SW | n | Role |
|---|---|---|---|---|
| Z1 | 1938.0708-1944.3192 | 0.9726 | 42/42 | strongest |
| Z2 | 1948.1292-1958.7972 | 0.9283 | 2/18 | flow interval |
| Z3 | 1959.2544-1990.6488 | 0.8358 | 0/35 | flow interval |"""
    assert "| Role |" in compose(_draft(own), TABLE)
