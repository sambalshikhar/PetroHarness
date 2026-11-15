"""Computation tests (P1-P6): the catalog's computations as named tools, on every formation of the configured dataset.

    .venv/bin/python -m pytest tests/agent/test_b2_compute.py -q   (PETROHARNESS_DATA selects the dataset)

The reference values (P3) are recomputed here with numpy from the view's arrays, not with the tools' helpers.
"""
import re
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np
import pytest

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / "src"), str(Path(__file__).resolve().parents[2]),
                str(Path(__file__).resolve().parent)]
from petroharness.record.catalog import CATALOG, EvidenceError, fmt  # noqa: E402
from petroharness.agent.compute import _plain_line  # noqa: E402
from petroharness.agent.engine import Result, ToolError, max_chars  # noqa: E402
from petroharness.agent.ledger import DIGEST_CHARS, Ledger  # noqa: E402
from petroharness.agent.schemas import arguments, call, fit  # noqa: E402

NUM = re.compile(r"(?<![A-Za-z0-9_.])-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?(?![A-Za-z0-9_])")


@lru_cache(maxsize=1)
def FS() -> list:
    from test_b2_tools import F
    return F()


def have(f, *names):
    return [c for c in names if c in f.inv.curves]


def std_args(f) -> dict:
    """Each tool's regular call on this formation (only where the curves it needs exist)."""
    out = {"pay_summary": {}, "core_vs_log": {}, "zone_classes": {"topic": "hc_indicators"}, "data_record": {}, "unit_roles": {}}
    if have(f, "PHIE", "SW", "VCL", "GR"):
        out["lithology_stats"] = {"curves": have(f, "PHIE", "SW", "VCL", "GR")[:3]}
        out["formation_summary"] = {"curves": have(f, "PHIE", "SW", "VCL", "PERM")[:4]}
    for c in ("PERM", "PHIE", "SW", "GR"):
        if have(f, c):
            out["zone_contrast"] = {"curve": c}
            break
    order = have(f, "RSHA", "RMED", "RDEP") if len(have(f, "RSHA", "RMED", "RDEP")) >= 2 else have(f, "PHID", "PHIN")
    if len(order) >= 2:
        out["curve_order"] = {"curves": order}
    if have(f, "SW"):
        out["threshold_exceedance"] = {"curve": "SW", "threshold": 0.5}
    if have(f, "GR", "RHOB", "NPHI", "DTC"):
        out["spike_flags"] = {"curves": have(f, "GR", "RHOB", "NPHI", "DTC")[:3]}
    jump = have(f, "DTC", "RHOB", "GR")
    if jump:
        out["adjacent_jumps"] = {"curve": jump[0], "threshold": {"DTC": 15.0, "RHOB": 0.1, "GR": 20.0}[jump[0]]}
    if have(f, "GR", "VCL") and len(f.view.zones) >= 2:
        out["vertical_sequence"] = {"curves": have(f, "GR", "VCL")[:2]}
    return out


def catalog_args(name, args):
    a = dict(args)
    for k in ("curves", "inputs"):
        if k in a:
            a[k] = [str(c).upper() for c in a[k]]
    if "curve" in a:
        a["curve"] = str(a["curve"]).upper()
    if name == "lithology_stats":
        a["stats"] = a.pop("statistics", None)
    a.pop("zones", None)
    return a


def rendered(d) -> list:
    """The catalog's table as the item writes it (written apart): the title, each row under it with every
    cell after the first named by its column, then the facts."""
    from petroharness.well.view import fmt
    cols = d.get("columns") or []
    cell = lambda v: "n/a" if v is None else (fmt(v) if isinstance(v, float) else str(v))
    rows = ["  " + (" | ".join([cell(r[0])] + [f"{c}: {cell(v)}" for c, v in zip(cols[1:], r[1:])]) if cols
                    else " | ".join(cell(v) for v in r)) for r in d.get("rows") or []]
    return [d["title"]] + rows + [f"- {x}" for x in d.get("facts") or []]


def cells(line: str) -> list:
    """A row's cells, each without its column's name."""
    parts = [c.strip() for c in line.split(" | ")]
    return parts[:1] + [c.split(": ", 1)[-1] for c in parts[1:]]


def table(r: Result) -> dict:
    """Rows of a computed item keyed by their first cell (a zone id, a curve, a flag, a lithology)."""
    out = {}
    for ln in r.text.split("\n")[1:]:
        if ln.startswith("  ") and " | " in ln:
            c = cells(ln)
            out[c[0]] = c
    return out


# --- P1 parity ------------------------------------------------------------------------------------------------------

HARNESS_OWN = ("spike_flags", "data_record")   # the harness's spike screen; computed primary logs are not missing


@pytest.mark.data
def test_p1_every_line_and_number_the_catalog_shows_is_in_the_item():
    checked, fails = 0, []
    for t, f in FS():
        for name, args in std_args(f).items():
            try:
                d = CATALOG[name](f.view, **catalog_args(name, args))
            except EvidenceError:
                with pytest.raises(ToolError):
                    call(f, name, args)
                continue
            if name in HARNESS_OWN or name == "unit_roles":
                continue                                       # test_views_and_scope.py; the roles: test_levels_and_rankings.py
            r = call(f, name, args)
            want, got = rendered(d), r.text.split("\n")
            want = [_plain_line(x) for x in want]            # verdict-reading lines as the tool words them (test_views_and_scope.py)
            cut = got[-1].startswith("(not shown here, to keep within the size limit: ")
            if not cut and got != want:
                fails.append((t.well, name, "text"))
            if cut and not all(ln in want for ln in got[:-1]):
                fails.append((t.well, name, "cut text"))
            shown = r.numbers                                  # every number the catalog's text shows is a number of the item
            tokens = [x for ln in want for x in NUM.findall(re.sub(r"\bZ\d+\b|[A-Za-z_]+\d[A-Za-z0-9_]*", " ", ln))]
            for tok in tokens:                                 # matched at the precision it is written, as the ledger verifies
                v = float(tok)
                half = 0.5 * 10 ** -(len(tok.split(".")[1]) if "." in tok and "e" not in tok.lower() else 0)
                if not cut and not any(abs(x - v) <= half * 1.0001 + 1e-12 or abs(abs(x) - abs(v)) <= half * 1.0001 + 1e-12
                                       for x in shown):
                    fails.append((t.well, name, f"shown {tok}"))
                    break
            checked += 1
    assert checked and not fails, fails[:10]


# --- P2 robustness --------------------------------------------------------------------------------------------------

def edge_cases(f) -> list:
    z0 = f.view.zones[0].zone_id
    flag = next((c for c in ("NET_PAY", "BAD_HOLE", "CROSSOVER_FLAG") if c in f.inv.curves), "NET_PAY")
    any_curve = next(iter(sorted(f.inv.curves)))
    return [
        ("lithology_stats", {"curves": ["NOSUCH"]}), ("lithology_stats", {"curves": []}), ("lithology_stats", {"curves": "GR, VCL"}),
        ("lithology_stats", {"curves": [any_curve], "statistics": ["median", "p90", "geo_mean"]}),
        ("lithology_stats", {"curves": [any_curve], "zones": [z0]}), ("lithology_stats", {"curves": [any_curve], "zones": ["Z999"]}),
        ("zone_contrast", {"curve": "BWV"}), ("zone_contrast", {"curve": flag}), ("zone_contrast", {"curve": [any_curve, any_curve]}),
        ("zone_contrast", {"curve": any_curve, "inputs": ["NOSUCH"]}),
        ("curve_order", {"curves": [any_curve]}), ("curve_order", {"curves": ["RDEP", "RMED"], "relation": "up"}),
        ("curve_order", {"curves": ["RDEP", "RMED"], "relation": "Increasing"}),
        ("threshold_exceedance", {"curve": any_curve}), ("threshold_exceedance", {"curve": any_curve, "threshold": 1e9}),
        ("threshold_exceedance", {"curve": any_curve, "threshold": -1, "op": "<"}),
        ("threshold_exceedance", {"curve": any_curve, "threshold": 0.5, "op": "=>"}),
        ("threshold_exceedance", {"curve": any_curve, "threshold": 0.5, "baseline": "pooled"}),
        ("threshold_exceedance", {"curve": any_curve, "threshold": 0.5, "absolute": True}),
        ("spike_flags", {"curves": [any_curve], "k": 0}), ("spike_flags", {"curves": [any_curve], "k": 100}),
        ("spike_flags", {"curves": [any_curve], "k": True}), ("spike_flags", {"curves": [any_curve], "k": "2"}),
        ("spike_flags", {"curves": [any_curve], "baseline": "zone"}), ("spike_flags", {"curves": [flag]}),
        ("adjacent_jumps", {"curve": any_curve, "threshold": 0}), ("adjacent_jumps", {"curve": any_curve, "threshold": -5}),
        ("adjacent_jumps", {"curve": any_curve, "threshold": "15"}), ("adjacent_jumps", {"curve": any_curve, "threshold": 1e9}),
        ("adjacent_jumps", {"curve": any_curve}), ("adjacent_jumps", {"curve": "DTC_", "threshold": 15}),
        ("vertical_sequence", {}), ("vertical_sequence", {"curves": [any_curve], "min_change": 0}),
        ("vertical_sequence", {"curves": [any_curve], "min_change": -1}),
        ("pay_summary", {"curves": ["GR"]}), ("core_vs_log", {}),
        ("zone_classes", {"topic": "nonsense"}), ("zone_classes", {"topic": "HC_INDICATORS"}), ("zone_classes", {"topic": "hc_indicator"}),
        ("zone_classes", {}), ("formation_summary", {}), ("formation_summary", {"curves": [flag]}),
        ("data_record", {"zones": [z0]}), ("data_record", {"zones": "all"}), ("unit_roles", {"zones": [z0]}),
    ]


@pytest.mark.data
def test_p2_regular_edge_and_malformed_calls_give_an_item_or_a_message():
    crashes, big, ran = [], [], 0
    for t, f in FS():
        for name, args in list(std_args(f).items()) + edge_cases(f):
            ran += 1
            try:
                r = call(f, name, args)
            except ToolError:
                continue
            except Exception as e:                                        # anything else is a bug
                crashes.append((t.well, name, args, f"{type(e).__name__}: {str(e)[:120]}"))
                continue
            if len(r.text) > max_chars():
                big.append((t.well, name, len(r.text)))
    assert ran and not crashes, crashes[:10]
    assert not big, big[:10]


@pytest.mark.data
def test_p2_messages_name_what_to_do():
    t, f = FS()[0]
    for name, args, says in [("lithology_stats", {"curves": ["NOSUCH"]}, "not a curve here"),
                             ("zone_contrast", {"curve": "BWV"}, ""), ("zone_classes", {"topic": "nonsense"}, "topics:"),
                             ("zone_classes", {"topic": "hc_indicator"}, "did you mean"),
                             ("curve_order", {"curves": ["GR", "GR"], "relation": "up"}, ""),
                             ("adjacent_jumps", {"curve": "GR", "threshold": 0}, "positive change"),
                             ("spike_flags", {"curves": ["GR"], "k": 0}, "standard deviations"),
                             ("threshold_exceedance", {"curve": "GR", "threshold": 1, "op": "=>"}, "op must be one of"),
                             ("lithology_stats", {"curves": ["GR"], "zones": ["Z999"]}, "no zone Z999")]:
        if name == "zone_contrast" and "BVW" not in f.inv.curves:
            continue
        with pytest.raises(ToolError) as e:
            call(f, name, args)
        assert says in str(e.value), (name, str(e.value)[:200])


# --- P3 reference ---------------------------------------------------------------------------------------------------

def close(shown: str, v: float) -> bool:
    if shown in ("n/a", "", "-"):
        return not np.isfinite(v)
    x = float(shown.replace("%", ""))
    dec = len(shown.split(".")[1]) if "." in shown else 0
    return abs(x - v) <= max(0.5 * 10 ** -dec * 1.0001, 1e-9) or abs(x - v) <= 5e-4 * max(1, abs(v))


@pytest.mark.data
def test_p3_threshold_shares_per_zone():
    n = 0
    for t, f in FS():
        if "SW" not in f.inv.curves:
            continue
        r = call(f, "threshold_exceedance", {"curve": "SW", "threshold": 0.5})
        rows = table(r)
        x = np.asarray(f.view.values("SW"), dtype=float)
        for z in f.view.zones:
            xi = x[z.indices]
            ok = np.isfinite(xi)
            want = 100 * np.mean(xi[ok] > 0.5) if ok.any() else np.nan
            assert close(rows[z.zone_id][3], want), (t.well, z.zone_id, rows[z.zone_id], want)
            n += 1
    assert n


@pytest.mark.data
def test_p3_adjacent_jumps_per_zone():
    n = 0
    for t, f in FS():
        c = next((c for c in ("DTC", "RHOB", "GR") if c in f.inv.curves), None)
        if c is None:
            continue
        thr = {"DTC": 15.0, "RHOB": 0.1, "GR": 20.0}[c]
        r = call(f, "adjacent_jumps", {"curve": c, "threshold": thr})
        rows = table(r)
        x = np.asarray(f.view.values(c), dtype=float)
        dx = np.diff(x)
        for z in f.view.zones:
            zi = np.asarray(z.indices[:-1]) if len(z.indices) > 1 else np.asarray([], dtype=int)
            d = dx[zi] if zi.size else np.asarray([])
            fin = d[np.isfinite(d)]
            assert int(rows[z.zone_id][3]) == int((np.abs(fin) > thr).sum()), (t.well, z.zone_id, rows[z.zone_id])
            if fin.size:
                assert close(rows[z.zone_id][4], float(np.max(np.abs(fin)))), (t.well, z.zone_id)
            n += 1
    assert n


@pytest.mark.data
def test_p3_formation_summary_ranks_each_statistic_and_pools_the_samples():
    """Each statistic's zone values high to low, the zones pooled and the whole interval (sample statistics; no
    thickness weighting, no best or weakest zone)."""
    n = 0
    for t, f in FS():
        cs = [c for c in ("PHIE", "SW") if c in f.inv.curves]
        if not cs:
            continue
        text = call(f, "formation_summary", {"curves": cs}).text
        rows = {(c[0], c[1]): c for ln in text.split("\n")[1:] if ln.startswith("  ") and " | " in ln
                for c in [cells(ln)]}
        for c in cs:
            if (c, "mean") not in rows:
                continue
            x = np.asarray(f.view.values(c), dtype=float)
            pooled = x[np.asarray(f.view.zoned)]
            assert close(rows[(c, "mean")][3], float(np.nanmean(pooled))), (t.well, c, rows[(c, "mean")])
            assert close(rows[(c, "mean")][4], float(np.nanmean(x))), (t.well, c, rows[(c, "mean")])
            zm = {z.zone_id: np.nanmean(np.asarray(f.view.zone_values(z, c), dtype=float)) for z in f.view.zones
                  if np.isfinite(np.asarray(f.view.zone_values(z, c), dtype=float)).any()}
            first = re.match(r"(Z\d+) ", rows[(c, "mean")][2])
            assert first and zm[first.group(1)] >= max(zm.values()) - 1e-9 * max(1, abs(max(zm.values()))), (t.well, c)
            n += 1
        assert "best" not in text.lower() and "weakest" not in text.lower()
    assert n


@pytest.mark.data
def test_p3_lithology_shares_add_up_and_match_the_zones():
    n = 0
    for t, f in FS():
        c = next((c for c in ("PHIE", "GR", "VCL") if c in f.inv.curves), None)
        if c is None:
            continue
        rows = table(call(f, "lithology_stats", {"curves": [c]}))
        thick = {}
        for z in f.view.zones:
            thick[z.lithology] = thick.get(z.lithology, 0) + z.thickness
        sig4 = lambda x: float(f"{x:.4g}")                    # the share of the zoned thickness, the thickness to 4 figures
        got = {k: float(v[3]) for k, v in rows.items() if k in thick and re.fullmatch(r"[\d.]+", v[3])}
        assert abs(sum(got.values()) - 100) <= 0.1 * len(got) + 0.05, (t.well, got)
        for k, v in got.items():
            want = 100 * sig4(thick[k]) / f.view.zoned_thickness
            assert abs(v - want) <= 0.05 + 1e-9, (t.well, k, v, want)
        n += 1
    assert n


@pytest.mark.data
def test_p3_the_workflow_s_strongest_role_is_its_highest_mean_permeability():
    n = 0
    for t, f in FS():
        perm = "PERM_CC" if "PERM_CC" in f.inv.curves else ("PERM" if "PERM" in f.inv.curves else None)
        if perm is None or len(f.view.zones) < 2:
            continue
        try:
            r = call(f, "unit_roles", {})
        except ToolError:
            continue
        rows = table(r)
        best = next((k for k, v in rows.items() if v[-1].startswith("strongest")), None)      # the workflow's role
        if best is None:
            continue
        means = {z.zone_id: np.nanmean(np.asarray(f.view.zone_values(z, perm), dtype=float)) for z in f.view.zones
                 if np.isfinite(np.asarray(f.view.zone_values(z, perm), dtype=float)).any()}
        top = max(means, key=means.get)
        assert means[best] >= means[top] - 1e-9 or abs(means[best] - means[top]) <= 1e-6 * max(1, means[top]), (t.well, best, top)
        n += 1
    assert n


@pytest.mark.data
def test_p3_vertical_sequence_steps_are_differences_of_zone_means():
    n = 0
    for t, f in FS():
        if "GR" not in f.inv.curves or len(f.view.zones) < 2:
            continue
        try:
            r = call(f, "vertical_sequence", {"curves": ["GR"]})
        except ToolError:
            continue
        rows = table(r)
        zs = list(f.view.zones)
        mean = {z.zone_id: np.nanmean(np.asarray(f.view.zone_values(z, "GR"), dtype=float)) for z in zs}
        order = sorted(zs, key=lambda z: -z.top)                    # base to top
        for below, above in zip(order, order[1:]):
            if above.zone_id in rows and rows[above.zone_id][4] not in ("n/a", ""):
                assert close(rows[above.zone_id][4], mean[above.zone_id] - mean[below.zone_id]), (t.well, above.zone_id)
                n += 1
    assert n


@pytest.mark.data
def test_p3_curve_order_by_zone_means():
    n = 0
    for t, f in FS():
        pair = [c for c in ("PHID", "PHIN") if c in f.inv.curves]
        if len(pair) < 2:
            continue
        rows = table(call(f, "curve_order", {"curves": pair}))
        for z in f.view.zones:
            a = np.nanmean(np.asarray(f.view.zone_values(z, "PHID"), dtype=float))
            b = np.nanmean(np.asarray(f.view.zone_values(z, "PHIN"), dtype=float))
            if not (np.isfinite(a) and np.isfinite(b)) or z.zone_id not in rows or a == b:
                continue
            want = "decreasing" if a > b else "increasing"
            assert rows[z.zone_id][-1] == want, (t.well, z.zone_id, rows[z.zone_id], a, b)
            n += 1
    assert n


# --- P4 ledger ------------------------------------------------------------------------------------------------------

@pytest.mark.data
def test_p4_items_digest_fetch_verify_and_dedupe():
    n = 0
    for t, f in FS()[:40]:
        led = Ledger(f)
        for name, args in std_args(f).items():
            try:
                item, new = led.open(name, args)
            except ToolError:
                continue
            dg = led.digest(item)
            assert len(dg) <= max(DIGEST_CHARS, len(item.text) + len(item.id) + 3), (t.well, name, len(dg))
            for ln in dg.split("\n")[1:]:
                if not ln.startswith("  ("):
                    assert ln.rstrip(" .") and (ln in item.text or ln.rstrip(" .").rstrip(" ...") in item.text or ln.endswith(" ...")), (t.well, name, ln)
            z = next((z.zone_id for z in f.view.zones if re.search(rf"\b{z.zone_id}\b", item.text)), None)
            if z:
                got = led.get(item.id, z)
                assert z in got, (t.well, name)
            for x in item.numbers[:6]:
                if np.isfinite(x):
                    assert led.verify(fmt(float(x)), [item.id]), (t.well, name, x)
            again, new2 = led.open(name, {k: (([str(c).lower() for c in v] if isinstance(v, list) else str(v).lower())
                                              if k in ("curves", "curve") else v) for k, v in args.items()})
            assert again is item and not new2, (t.well, name)
            n += 1
    assert n


# --- P5 call shapes -------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("name,raw,want", [
    ("adjacent_jumps", {"curves": ["DTC"], "threshold": "15"}, {"curve": "DTC", "threshold": 15.0}),
    ("adjacent_jumps", '{"curve": "DTC", "threshold": 15}', {"curve": "DTC", "threshold": 15}),
    ("spike_flags", {"curve": "GR", "k": "2.5"}, {"curves": ["GR"], "k": 2.5}),
    ("spike_flags", {"curves": "GR, RHOB"}, {"curves": ["GR", "RHOB"]}),
    ("lithology_stats", {"curve": "PHIE", "statistics": ["P90", "Mean"]}, {"curves": ["PHIE"], "statistics": ["p90", "mean"]}),
    ("zone_contrast", {"curves": ["PERM"], "inputs": "VCL, PHIE"}, {"curve": "PERM", "inputs": ["VCL", "PHIE"]}),
    ("vertical_sequence", {"curve": "GR", "min_change": "3"}, {"curves": ["GR"], "min_change": 3.0}),
    ("unit_roles", {"zones": True}, {}),
    ("data_record", {"zones": ["Z1-Z3"], "reason": "coverage"}, {"zones": ["Z1", "Z2", "Z3"]}),
    ("threshold_exceedance", {"curve": "VCL", "threshold": "0.3", "note": "x"}, {"curve": "VCL", "threshold": 0.3}),
])
def test_p5_shapes_k2h_sends_are_read_as_meant(name, raw, want):
    assert fit(name, arguments(raw)) == want


def test_p5_a_list_written_as_json_text_is_a_list():
    assert fit("spike_flags", arguments({"curves": '["GR", "RHOB"]'})) == {"curves": ["GR", "RHOB"]}


def test_p5_two_curves_where_one_belongs_is_a_message():
    with pytest.raises(ToolError, match="takes one curve"):
        fit("adjacent_jumps", arguments({"curve": ["DTC", "GR"], "threshold": 15}))


# --- P6 one call answers --------------------------------------------------------------------------------------------

@pytest.mark.data
def test_p6_one_call_answers():
    seen = {"cycle": 0, "spikes": 0, "packages": 0, "roles": 0}
    for t, f in FS():
        if "DTC" in f.inv.curves:
            r = call(f, "adjacent_jumps", {"curve": "DTC", "threshold": 15})
            head = "\n".join(r.text.split("\n")[:2 + len(f.view.zones)])
            assert "changes beyond threshold" in head and all(z.zone_id in head for z in f.view.zones[:5]), t.well
            assert re.search(r"\d+ changes exceed 15", r.text), t.well
            seen["cycle"] += 1
        if "GR" in f.inv.curves:                     # the spike screen (its tiers against numpy: test_views_and_scope.py)
            r = call(f, "spike_flags", {"curves": ["GR"]})
            assert "GR" in r.text and "std" in r.text, t.well
            seen["spikes"] += 1
        if "GR" in f.inv.curves and len(f.view.zones) >= 2:
            try:
                r = call(f, "vertical_sequence", {"curves": ["GR"]})
                assert "base to top" in r.text.split("\n")[0], t.well
                seen["packages"] += 1
            except ToolError:
                pass
        try:
            r = call(f, "unit_roles", {})
            assert "strongest" in r.text, t.well
            seen["roles"] += 1
        except ToolError:
            pass
    assert all(seen.values()) or (seen["cycle"] == 0 and seen["spikes"]), seen
