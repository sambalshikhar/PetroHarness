"""The summary layer reads its data's shape. A curve of a few whole-number values is
class codes (shares per class on every basis, never a mean of codes), a 0/1 curve a flag (the share set), by the
values over the well, never by the curve's name; labels where the record maps the codes. Every value line names its
basis and its curve; a cut text names what it cut and the find that fetches it from the result; any statistic the
layer computes is served, and one it does not is said with how to derive it.

    .venv/bin/python -m pytest tests/agent/test_shape.py -q        (PETROHARNESS_DATA selects the dataset)
"""
import copy
import dataclasses
import re
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np
import pytest

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / "src"), str(Path(__file__).resolve().parents[2]),
                str(Path(__file__).resolve().parent)]
from petroharness.agent import engine as E  # noqa: E402
from petroharness.agent.engine import Formation  # noqa: E402
from petroharness.agent.ledger import Ledger  # noqa: E402
from petroharness.agent.schemas import call, fit  # noqa: E402
from petroharness.well import summary as S  # noqa: E402

CLASS = re.compile(r"class (\d+)(?: \(([^)]*)\))? ([\d.]+)% \((\d+) samples, ([\d.]+) \w+\)")


# --- the rule, on synthetic values ------------------------------------------------------------------------------------

def test_the_kind_follows_the_values_alone():
    rng = np.random.default_rng(0)
    codes = rng.choice([2.0, 5.0, 7.0], 600)
    assert S.kind_of(codes) == S.Kind("classes", (2.0, 5.0, 7.0))
    assert S.kind_of(np.r_[codes, np.nan, np.nan]).kind == "classes"                  # gaps do not count
    assert S.kind_of(rng.choice([0.0, 1.0], 40)) == S.Kind("flag", (0.0, 1.0))         # a flag, whatever its count
    assert S.kind_of(rng.normal(0.2, 0.05, 600)).kind == "values"
    assert S.kind_of(np.full(50, 11.0)) == S.Kind("one value", (11.0,))
    assert S.kind_of(np.full(50, 0.036)).kind == "values"                              # a constant that is no code
    assert S.kind_of(np.arange(31.0).repeat(40)).kind == "values"                      # more than 30 values
    assert S.kind_of(np.tile([1.0, 2.0, 3.0], 20)).kind == "values"                    # 3 values of 60: not < 5%
    assert S.kind_of(np.tile([1.0, 2.0, 3.0], 61)).kind == "classes"
    assert S.kind_of(np.round(rng.normal(2000, 300, 5000), -1)).kind == "values"       # a log read to whole numbers
    assert S.kind_of(np.array([0.0, 0.5, 1.0] * 40)).kind == "values"                  # a score of halves


def test_class_codes_and_their_labels_are_written_plainly():
    assert S.code_text(5.0, {5.0: "SILT"}) == "5 (SILT)" and S.code_text(5.0, {}) == "5"
    assert S.class_counts(np.array([5.0, 5.0, 7.0, np.nan]), (2.0, 5.0, 7.0)) == (3, [(5.0, 2), (7.0, 1)])
    note = S.kind_note(S.Kind("classes", (5.0, 7.0)), {5.0: "SILT"})
    assert "5 (SILT), 7" in note and "codes are labels, not quantities" in note
    assert S.kind_note(S.Kind("values"), {}) == ""


def test_any_statistic_the_layer_computes_is_served_and_another_is_derived():
    x = np.random.default_rng(1).lognormal(0, 1, 500)
    got = S.compute(x, ["n", "variance", "std", "cv", "iqr", "range", "harmonic_mean", "p25", "p75", "p95"])
    assert abs(got["variance"] - got["std"] ** 2) <= 1e-9 * got["variance"]
    assert abs(got["variance"] - np.var(x)) <= 1e-9 * np.var(x)
    assert abs(got["cv"] - np.std(x) / np.mean(x)) < 1e-9 and abs(got["range"] - np.ptp(x)) < 1e-9
    assert abs(got["iqr"] - (got["p75"] - got["p25"])) < 1e-12
    assert abs(got["harmonic_mean"] - len(x) / np.sum(1 / x)) < 1e-9 * got["harmonic_mean"]
    assert abs(got["p95"] - np.percentile(x, 95)) < 1e-9 * got["p95"]
    for asked, name in [("var", "variance"), ("Standard Deviation", "std"), ("coefficient of variation", "cv"),
                        ("geometric mean", "geo_mean"), ("percentile 25", "p25"), ("P50", "median"),
                        ("interquartile range", "iqr")]:
        assert S.statistic_name(asked) == name and S.known(name), asked
    line = S.derivation("sum")
    assert "sum = n * mean" in line and "calc" in line
    line = S.derivation("skewness")
    assert "skewness" in line and "calc" in line and "not make it missing from the record" in line
    assert not S.known("skewness") and not S.known("p100") and "p100 = max" in S.derivation("p100")
    assert fit("stats", {"curves": ["PHIE"], "statistics": "coefficient of variation, standard deviation"})[
        "statistics"] == ["cv", "std"]


# --- on a real formation ----------------------------------------------------------------------------------------------

@lru_cache(maxsize=1)
def formation():
    from test_b2_tools import F
    hit = [(t, f) for t, f in F() if len(f.view.zones) >= 3 and S.outside(f.view) > 0 and "PHIE" in f.inv.curves]
    if not hit:
        pytest.skip("no formation with three zones, samples between them and PHIE")
    return min(hit, key=lambda x: len(x[1].view.zones))


class Shaped:
    """A view whose curve c holds other values (over the interval and over the well); everything else is the real
    view's. codes: a code table for c (the lithology log's, as the record gives it)."""

    def __init__(self, view, c, interval, well, codes=None):
        self._v, self._c, self._x, self._w = view, c, np.asarray(interval, float), np.asarray(well, float)
        self.code_table = codes if codes is not None else view.code_table
        self.lithology_curve = c if codes is not None else view.lithology_curve

    def __getattr__(self, k):
        return getattr(self._v, k)

    def values(self, curve):
        return self._x.copy() if curve == self._c else self._v.values(curve)

    def well_values(self, curve):
        return self._w.copy() if curve == self._c else self._v.well_values(curve)

    def zone_values(self, zone, curve):
        x = self.values(curve)
        return None if x is None else x[zone.indices]


def _shaped(f, c, interval, well, codes=None):
    from petroharness.agent.inventory import _codes
    v = Shaped(f.view, c, interval, well, codes)
    inv = copy.copy(f.inv)
    inv.curves = {**f.inv.curves, c: dataclasses.replace(f.inv.curves[c], codes=_codes(v, c))}
    return Formation(inv, v, f.store)


def _well(f, interval):
    """Well values that repeat the interval's (so the shape over the well is the interval's)."""
    n = np.asarray(f.view.prep.depth).size
    return np.resize(np.asarray(interval, float), max(n, 4 * np.asarray(interval).size))


def _block(text, c) -> list:
    """The value lines of curve c (they name it after their basis)."""
    return [ln for ln in text.splitlines() if re.match(rf"^  .*, {re.escape(c)}(?: \([a-z][a-z ,]*\))?: ", ln)]


def _basis(f, ln):
    """(the samples of the basis a line names, its zones)."""
    zs = list(f.view.zones)
    m = re.match(r"^  (Z\d+) ", ln)
    if m:
        z = next(z for z in zs if z.zone_id == m.group(1))
        return np.asarray(z.indices), [z]
    if ln.startswith("  zones pooled"):
        return np.flatnonzero(np.asarray(f.view.zoned)), zs
    if ln.startswith("  outside any zone ("):                    # the samples outside the zones
        return np.flatnonzero(~np.asarray(f.view.zoned)), None
    return np.arange(f.depth.size), None


def _thickness(f, idx, zs, on):
    if zs is None:
        return f.inv.gross * int(on[idx].sum()) / f.depth.size
    return sum(z.thickness * int(on[z.indices].sum()) / z.n_samples for z in zs)


@pytest.mark.data
def test_a_curve_of_whole_number_codes_gives_class_shares_on_each_basis():
    t, f = formation()
    n = f.depth.size
    x = np.array([2.0, 5.0, 7.0])[np.arange(n) * 7 % 3]
    x[::11] = np.nan
    g = _shaped(f, "PHIE", x, _well(f, x))                    # PHIE by name, codes by shape: codes win
    text = call(g, "stats", {"curves": ["PHIE"], "statistics": ["mean", "min", "max"]}).text
    lines = _block(text, "PHIE")
    tail = 3 if S.differs(f.view, x) else 1                 # the whole interval and the outside samples where they differ
    assert len(lines) == len(f.view.zones) + tail and "class codes (3 integer values over the well: 2, 5, 7)" in text
    for ln in lines:
        assert not re.search(r"\b(mean|median|min|max|p10|p90|geo_mean)\b", ln), ln      # never statistics of codes
        idx, zs = _basis(f, ln)
        xs = x[idx]
        have = int(np.isfinite(xs).sum())
        assert f": n {have} of {idx.size}" in ln, ln
        got = {int(c): (float(p), int(k), float(th)) for c, _, p, k, th in CLASS.findall(ln)}
        want = {int(c): int(np.sum(xs == c)) for c in (2, 5, 7) if np.any(xs == c)}
        assert {c: k for c, (_, k, _) in got.items()} == want, ln
        for c, (p, k, th) in got.items():
            assert abs(p - 100 * k / have) <= 0.051, ln
            assert abs(th - _thickness(f, idx, zs, np.isfinite(x) & (x == c))) <= 1e-3 * max(1.0, th), ln


@pytest.mark.data
def test_a_0_1_curve_gives_the_share_set():
    t, f = formation()
    n = f.depth.size
    x = (np.arange(n) % 4 == 0).astype(float)
    g = _shaped(f, "PHIE", x, _well(f, x))
    text = call(g, "stats", {"curves": ["PHIE"]}).text
    assert "0/1 values over the well" in text
    for ln in _block(text, "PHIE"):
        idx, zs = _basis(f, ln)
        on = np.isfinite(x) & (x > 0.5)
        m = re.search(r"set in (\d+) samples \(([\d.]+)% of those with a value\), thickness ([\d.]+)", ln)
        assert m and int(m.group(1)) == int(on[idx].sum()), ln
        assert abs(float(m.group(2)) - 100 * on[idx].sum() / idx.size) <= 0.051, ln
        assert abs(float(m.group(3)) - _thickness(f, idx, zs, on)) <= 1e-3 * max(1.0, float(m.group(3))), ln
        assert "mean" not in ln, ln


@pytest.mark.data
def test_a_continuous_curve_keeps_its_statistics():
    t, f = formation()
    text = call(f, "stats", {"curves": ["PHIE"]}).text
    assert E.kind(f, "PHIE").kind == "values" and "class" not in text and "set in" not in text
    x = np.asarray(f.view.values("PHIE"), float)
    for ln in _block(text, "PHIE"):
        idx, _ = _basis(f, ln)
        m = re.search(r": n (\d+) of (\d+), mean (-?[\d.]+), (median|min)", ln)
        xs = x[idx][np.isfinite(x[idx])]
        assert m and int(m.group(1)) == xs.size and abs(float(m.group(3)) - xs.mean()) <= 5e-4 * max(1, abs(xs.mean())), ln


@pytest.mark.data
def test_measured_logs_and_computed_properties_read_as_values_on_every_formation():
    """The rule on real data: no measured log or computed property is taken for codes (the rule's survey over the
    datasets found only lithology logs, electrofacies and lithology group codes as classes)."""
    from test_b2_tools import F
    for t, f in F():
        for c in ("GR", "RHOB", "NPHI", "RDEP", "DTC", "CALI", "PEF", "PHIE", "PHIT", "SW", "VCL", "PERM", "BVW"):
            if c in f.inv.curves:
                assert E.kind(f, c).kind == "values", (t.well, t.formation, c, E.kind(f, c))
        lith = f.view.lithology_curve
        if lith and lith in f.inv.curves:
            assert E.kind(f, lith).kind in ("classes", "one value"), (t.well, lith)


@pytest.mark.data
def test_labels_apply_where_the_record_maps_the_codes():
    t, f = formation()
    n = f.depth.size
    x = np.array([5.0, 7.0])[np.arange(n) % 2]
    g = _shaped(f, "PHIE", x, _well(f, x), codes={5: "SILT", 7: "SHALE", 9: "LIMESTONE"})
    assert g.inv.curves["PHIE"].codes == {5.0: "SILT", 7.0: "SHALE"}                 # the codes it holds
    text = call(g, "stats", {"curves": ["PHIE"]}).text
    assert "class 5 (SILT)" in text and "class 7 (SHALE)" in text and "LIMESTONE" not in text
    plain = _shaped(f, "PHIE", x, _well(f, x))                                         # no map: the codes as they are
    assert plain.inv.curves["PHIE"].codes == {} and "class 5 " in call(plain, "stats", {"curves": ["PHIE"]}).text


@pytest.mark.data
def test_the_lithology_log_is_labelled_from_the_code_table():
    from test_b2_tools import F
    done = 0
    for t, f in F():
        lith = f.view.lithology_curve
        if not lith or lith not in f.inv.curves or E.kind(f, lith).kind != "classes":
            continue
        codes = f.inv.curves[lith].codes
        assert codes and all(f.view.code_table[int(c)] == lab for c, lab in codes.items()), (t.well, lith)
        text = call(f, "stats", {"curves": [lith]}).text
        for c, lab, *_ in CLASS.findall(text):
            assert lab == codes.get(float(c), ""), (t.well, c, lab)
        assert not re.search(r"\bmean \d", text)
        fs = call(f, "formation_summary", {"curves": [lith]}).text
        assert "share of class" in fs and "| statistic: mean" not in fs
        done += 1
        if done >= 5:
            break
    assert done or pytest.skip("no lithology log of class codes here")


@pytest.mark.data
def test_compare_and_crossplot_take_no_class_codes():
    t, f = formation()
    x = np.array([2.0, 5.0, 7.0])[np.arange(f.depth.size) % 3]
    g = _shaped(f, "PHIE", x, _well(f, x))
    other = next(c for c in ("VCL", "SW", "GR", "RHOB") if c in f.inv.curves)
    for tool, args in (("compare", {"a": "PHIE", "b": other}), ("crossplot", {"y": other, "x": "PHIE"})):
        with pytest.raises(E.ToolError, match="class codes .* stats PHIE"):
            call(g, tool, args)


@pytest.mark.data
def test_stats_serves_variance_and_says_how_to_derive_a_statistic_it_lacks():
    t, f = formation()
    r = call(f, "stats", {"curves": ["PHIE"], "statistics": ["variance", "std", "skewness"]})
    lines = r.text.splitlines()
    assert lines[0].startswith("no statistic 'skewness' in this tool") and "calc" in lines[0]
    for ln in _block(r.text, "PHIE"):
        var, std = (float(re.search(rf"\b{k} (-?[\d.]+)", ln).group(1)) for k in ("variance", "std"))
        assert abs(var - std ** 2) <= 2e-3 * max(var, 1e-12) + 1e-9, ln
    only = call(f, "stats", {"curves": ["PHIE"], "statistics": ["sum"]}).text
    assert "sum = n * mean" in only.splitlines()[0] and ", mean " in only               # the default set still runs
    p = call(f, "profile", {"curve": "PHIE", "statistics": ["var"]}).text
    assert re.search(r"variance -?[\d.]+", p)


FULL = r"^  (Z\d+) \S.*? -?[\d.]+--?[\d.]+ \w+, ({c})(?: \([a-z][a-z ,]*\))?: n \d+ of \d+"   # a zone's full row of c
SHORT = r"^  (Z\d+), ({c})(?: \([a-z][a-z ,]*\))?: n \d+"                   # its shorter row (with its cautions)


@pytest.mark.data
@pytest.mark.parametrize("limit", [5000, 2500])
def test_a_cut_text_names_what_it_cut_and_the_find_fetches_it(monkeypatch, limit):
    """Every zone's full row is in the item; the text shows each zone of every curve (full, or a shorter row when the
    full rows do not fit), or names it as cut; its last line names what is not shown and the find that fetches it."""
    from test_b2_tools import F
    t, f = max(F(), key=lambda tf: len(tf[1].view.zones))
    cs = [c for c in ("PHIE", "VCL", "SW", "GR") if c in f.inv.curves][:3]
    if len(f.view.zones) < 6 or len(cs) < 2:
        pytest.skip("too few zones or curves")
    monkeypatch.setattr(E, "WIDE_CHARS", limit)                  # a small size limit: a cut is certain
    led = Ledger(f)
    item, _ = led.open("stats", {"curves": cs})
    text = item.text.splitlines()
    m = re.match(r'^\(not shown here, to keep within the size limit: (.*); they are in this result: get E1 with find '
                 r'"([^"]+)"(?: \(a zone at a time: [^)]+\))?\)$', text[-1])
    assert m, text[-1]
    held = [ln for ln in item.lines if ln not in text]
    zones = [z.zone_id for z in f.view.zones]
    for c in cs:
        full = [re.match(FULL.format(c=c), ln) for ln in item.lines]
        assert [x.group(1) for x in full if x] == zones, c       # the item holds every zone's full row
        shown = {x.group(1) for ln in text for x in [re.match(FULL.format(c=c), ln) or re.match(SHORT.format(c=c), ln)
                                                     or re.match(rf"^  (Z\d+): .*\b{c} ", ln)] if x}
        cut = [x.group(1) for ln in held for x in [re.match(FULL.format(c=c), ln)] if x]
        assert set(zones) <= shown | set(cut), c
        assert re.search(rf"  zones pooled, {c}(?: \([^)]*\))?: ", item.text)
        assert re.search(rf"samples outside any zone\), {c}(?: \([^)]*\))?: ", item.text)
    assert held and all(re.match(r"^  (Z\d+[ :]|zones pooled, |whole interval \(|outside any zone \()", ln)
                        for ln in held)                           # only zone rows, and the tails' full lines
    named = m.group(1)
    assert "zones " in named and all(c in named for c in cs)
    if any(re.match(SHORT.format(c=cs[0]), ln) or re.match(r"^  Z\d+: ", ln) for ln in text):
        assert "the full rows of zones" in named                  # shorter rows shown: the full ones named
    from petroharness.agent.ledger import zones_in
    asked = zones_in(m.group(2))                                  # the find fetches what was cut (a zone at a time
    target = [ln for ln in held if zones_in(ln.split(":", 1)[0]) & asked]      #   when that is more than one get)
    got = led.get("E1", m.group(2))
    assert target and all(ln in got for ln in target[:4]), (m.group(2), target[:2])
    numbers = [x for ln, ns in item.rows if ln in held for x in ns]
    assert numbers and all(x in item.numbers for x in numbers)    # and the item holds its numbers


@pytest.mark.data
def test_a_cut_table_names_its_rows(monkeypatch):
    from test_b2_tools import F
    t, f = max(F(), key=lambda tf: len(tf[1].view.zones))
    if len(f.view.zones) < 4:
        pytest.skip("too few zones")
    monkeypatch.setattr(E, "WIDE_CHARS", 1200)
    led = Ledger(f)
    item, _ = led.open("zone_classes", {"topic": "porosity_quality"})                # a row per zone
    last = item.text.splitlines()[-1]
    if not last.startswith("(not shown here"):
        pytest.skip("the table fits")
    assert "rows " in last and 'get E1 with find "' in last
    held = [ln for ln in item.lines if ln not in item.text.splitlines()]
    assert [ln for ln in held if re.match(r"^  Z\d+ \| lithology: ", ln)]          # its rows, each cell named
    key = re.search(r'find "([^"]+)"', last).group(1)
    assert held[0] in led.get("E1", key)


# --- every value line says what it is ---------------------------------------------------------------------------------

STAT = re.compile(r"\b(n|mean|median|geo_mean|harmonic_mean|mode|min|max|range|std|variance|cv|iqr|p\d{1,2}|slope|"
                  r"intercept|R2|correlation|share|shares|set|class|beyond|statistic)\b")
NUMBER = re.compile(r"(?<![A-Za-z0-9_.])-?\d+(?:\.\d+)?")
BASIS = re.compile(r"\bZ\d+\b|zones pooled|whole interval|each zone|by zone|all zones|zones asked|outside any zone")


def _value_lines(text: str) -> list:
    """The indented lines that hold a statistic and a number (headings, labels and facts are not value lines)."""
    out = []
    for ln in text.splitlines():
        if not ln.startswith("  "):
            continue
        bare = re.sub(r"\b[A-Za-z_]+\d[A-Za-z0-9_]*\b|\bZ\d+\b", " ", ln)
        if STAT.search(ln) and NUMBER.search(bare):
            out.append(ln)
    return out


def _labelled(f, ln) -> bool:
    liths = {str(x).upper() for x in np.unique(np.asarray(f.view.labels, dtype=object))}
    names = set(re.findall(r"[A-Z][A-Z0-9_]+", ln))
    basis = bool(BASIS.search(ln)) or bool(names & liths) or any(w.strip().upper() in liths
                                                                  for w in re.split(r"\|", ln)[:1])
    return basis and bool(names & set(f.inv.curves))


@pytest.mark.data
def test_every_value_line_of_a_summary_names_its_basis_and_curve():
    from test_b2_tools import F
    checked = 0
    for t, f in F()[:6]:
        cs = [c for c in ("PHIE", "PERM", "VCL", "SW", "GR", "NET_PAY", "ELECTROFACIES", f.view.lithology_curve or "")
              if c and c in f.inv.curves]
        values = [c for c in cs if E.kind(f, c).kind == "values"]
        calls = [("stats", {"curves": cs}), ("stats", {"curves": cs[:2], "statistics": ["variance", "cv", "p25"]}),
                 ("lithology_stats", {"curves": cs[:3]}), ("formation_summary", {"curves": cs}),
                 ("core_vs_log", {}), ("spike_flags", {"curves": values[:2]})]
        calls += [("profile", {"curve": c}) for c in cs[:3]]
        if len(values) >= 2:
            calls += [("compare", {"a": values[0], "b": values[1]}), ("crossplot", {"y": values[0], "x": values[1]}),
                      ("stats", {"curves": values[:2], "where": f"{values[1]} > 0"})]
        for tool, args in calls:
            try:
                r = call(f, tool, args)
            except E.ToolError:
                continue
            bad = [ln for ln in _value_lines(r.text) if not _labelled(f, ln)]
            assert not bad, (t.well, tool, args, bad[:3])
            checked += len(_value_lines(r.text))
    assert checked > 100
