"""Core reference by input (evidence.core_vs_log) and the porosity step's parameters on demand (provenance): where the
interval has no plug samples but the LAS supplies a core-corrected curve, that curve is the core reference and every
log porosity is compared with it zone by zone; otherwise the plug comparison stands. Runs on the configured dataset,
whatever its inputs.

    PYTHONPATH=src:. .venv/bin/python -m pytest tests/test_core_reference.py -q
"""
import re
import warnings
from functools import lru_cache

import numpy as np
import pytest

from petroharness.record.card import curve_origin, porosity_parameters
from petroharness.tasks import load_tasks
from petroharness.record.catalog import core_vs_log, provenance
from petroharness.well.view import FormationView

from _reference import CFG


@lru_cache(maxsize=1)
def views() -> list:
    tasks, _ = load_tasks(CFG.eval.questions, CFG.data.las_dir, ["porosity"])
    out, seen = [], set()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for t in tasks:
            if (t.las_path, t.formation) not in seen:
                seen.add((t.las_path, t.formation))
                out.append(FormationView.build(t, CFG.for_tasks()))
    return out[:12]


def has_plugs(v) -> bool:
    x = v.values("PHIC")
    return x is not None and bool(np.isfinite(x).any())


@pytest.mark.data
def test_the_core_reference_follows_the_inputs():
    for v in views():
        facts = core_vs_log(v)["facts"]
        supplied = v.available("PHIE_CC") and curve_origin(v, "PHIE_CC") == ("supplied",)
        referenced = any("PHIE_CC, the core-corrected curve the LAS supplies, is the core reference" in f for f in facts)
        assert referenced is (supplied and not has_plugs(v)), (v.task.well, facts[:2])
        if referenced:
            rows = next(f for f in facts if f.startswith("PHIE against PHIE_CC by zone"))
            assert len(re.findall(r"\bZ\d+ ", rows)) >= 1 and "beyond 0.03 in" in rows


@pytest.mark.data
def test_reference_rows_are_the_zone_means_and_shares():
    for v in views():
        facts = core_vs_log(v)["facts"]
        rows = next((f for f in facts if f.startswith("PHIE against PHIE_CC by zone")), None)
        if rows is None:
            continue
        z = v.zones[0]
        a, b = v.zone_values(z, "PHIE"), v.zone_values(z, "PHIE_CC")
        ok = np.isfinite(a) & np.isfinite(b)
        if ok.sum() < 3:
            continue
        share = 100 * np.mean(np.abs(a[ok] - b[ok]) > 0.03)
        m = re.search(rf"{z.zone_id} \S+ n=(\d+) .*?beyond 0.03 in (<?[\d.]+)%", rows)
        assert m and int(m.group(1)) == int(ok.sum())
        assert m.group(2).startswith("<") or abs(float(m.group(2)) - share) <= 0.5
        return
    pytest.skip("no interval with a supplied core reference in this dataset")


@pytest.mark.data
def test_provenance_porosity_gives_the_recorded_matrix_values():
    for v in views():
        st = v.prep.steps.get("porosity") or {}
        eps = (st.get("parameters") or {}).get("matrix_endpoints") or []
        facts = " ".join(provenance(v, ["porosity"])["facts"])
        if eps:
            assert "matrix by lithology:" in facts
            shown = re.findall(r"([A-Z]+) rho_ma ([\d.]+) g/cc", facts)
            recorded = {(e["lithology_group"], float(e["rho_ma"])) for e in eps}
            assert shown and all((g, float(r)) in recorded for g, r in shown)


def test_porosity_parameters_matches_lithology_names_loosely():
    rec = {"parameters": {"matrix_endpoints": [{"lithology_group": "SANDSTONE", "rho_ma": 2.65, "nphi_ma": -0.02, "dt_ma": 55.5},
                                               {"lithology_group": "LIMESTONE", "rho_ma": 2.71, "nphi_ma": 0.0, "dt_ma": 47.6}],
                          "rho_fl": 1.0, "phit_method": "adaptive_nd", "phit_source_counts": {"weighted_nd": 10, "nan": 0}}}
    line = porosity_parameters(rec, ["SAND", "SHALY SANDSTONE"])
    assert "SANDSTONE rho_ma 2.65 g/cc" in line and "LIMESTONE" not in line and "rho_fl 1 g/cc" in line and "nan" not in line
    assert porosity_parameters({}, ["SAND"]) is None
    assert "LIMESTONE rho_ma 2.71" in porosity_parameters(rec, ["COAL"])          # no match: every recorded group
