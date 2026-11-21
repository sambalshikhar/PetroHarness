"""Figures for an answer, drawn by Petrophys (petrophys.visualization), where a plot says it better than text. For
interactive use (petroharness.session, the web UI); a benchmark run draws none.

How it works. The harness offers the Petrophys plots that can be drawn from what the answer rests on (`candidates`):
  - the plot of each result a settled claim cites: a statistics result gives a histogram of each curve by zone and the
    log viewer of its curves, a crossplot or a comparison gives the crossplot, a profile gives the log viewer;
  - the standard displays of the interval (DISPLAYS: density-neutron, M-N, MID, Pickett, Hingle, Buckles, flow units,
    triple combo, net pay) whose curves the interval holds and the answer's results read or were computed from.
After the answer is written, one model call (`pick`) is shown the question, the answer and the candidates, and chooses
which to show, in which order, or none. Petrophys then draws each (`draw`). The answer's text is never passed back
through the model, so it cannot change.

The harness has no drawing code of its own. It gives Petrophys what a plot needs from the question (`plot_well`: the
interval's well with the values the results read; the zones as the viewer's lithology track; the numbers a plot takes,
each said with its source) and writes the caption. A plot that is missing belongs in Petrophys; it is offered here by
one line in DISPLAYS.

Petrophys draws with pyplot, whose state is one per process: figures are drawn one at a time (a lock), each closed
once saved.
"""
from __future__ import annotations

import importlib
import inspect
import io
import json
import re
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from petroharness.agent import components as C
from petroharness.agent import engine as E

MAX_FIGURES = 3            # figures on one answer at most
MAX_RESULT_PLOTS = 10      # candidates from the cited results
MAX_CANDIDATES = 16        # candidates shown to the model, the standard displays included
VIEWER, HISTOGRAM, CROSSPLOT = "log_viewer", "histogram", "crossplot"
OVERVIEW = "overview.png"  # the interval's log display, drawn once per conversation
# the Petrophys function behind each plot of a result
FUNCTIONS = {VIEWER: "create_log_viewer", HISTOGRAM: "create_histogram_comparison", CROSSPLOT: "create_crossplot"}
# The standard displays offered: the Petrophys function -> the curves it draws, each as (its parameter, or None where
# the display reads the curve from the well itself; the curves that can serve, in the display's own lookup order). One
# of each entry must hold values in the interval. A display added to Petrophys is offered by adding its line here.
DISPLAYS = {
    "create_nd_crossplot": ((None, ("NPHI", "PHIN")), (None, ("RHOB",))),
    "create_mn_plot": ((None, ("NPHI", "PHIN")), (None, ("RHOB",)), (None, ("DTC", "DT"))),
    "create_mid_plot": ((None, ("NPHI", "PHIN")), (None, ("RHOB",)), (None, ("DTC", "DT"))),
    "create_pickett_plot": (("phie_curve", ("PHIE",)), ("rt_curve", ("RT", "RDEP"))),
    "create_hingle_plot": (("phie_curve", ("PHIE",)), ("rt_curve", ("RDEP", "RT"))),
    "create_buckles_plot": (("phie_curve", ("PHIE",)), ("sw_curve", ("SW",))),
    "create_flow_unit_plot": (("phi_e", ("PHIE",)), ("perm", ("PERM",))),
    "create_triple_combo": ((None, ("GR",)), (None, ("RDEP", "RT", "RMED")), (None, ("RHOB",)),
                            (None, ("NPHI", "PHIN"))),
    "create_net_pay_summary_plot": ((None, ("NET_RES", "NET_PAY", "NET_ROCK")),),
}
# a display's number the record holds as a curve: the interval's median of it (the one water line it draws); said
# with the figure, as every number a display is given
DISPLAY_MEDIANS = {"create_pickett_plot": {"rw": "RW"}, "create_hingle_plot": {"rw": "RW"}}
# parameters of a display that are not the interval's to give (the well is; the rest stay Petrophys' defaults)
_LEFT = ("well", "result", "depth_range", "figsize", "title", "cmap", "color_curve", "kwargs")
_NAME = re.compile(r"\b[A-Z][A-Z0-9_]+\b")
_LOCK = threading.Lock()


@dataclass
class Candidate:
    id: str                       # F1, F2, ...
    kind: str                     # log_viewer, histogram, crossplot, or a standard display (pickett, buckles, ...)
    source: str                   # the result it draws (E id); "interval" for a standard display
    title: str                    # what it shows, as the model and the caption read it
    spec: dict = field(default_factory=dict)


def visualization():
    """petrophys.visualization, on the Agg canvas when nothing chose a canvas before (a script, the server); a
    session that already draws (a notebook) keeps its own."""
    if "matplotlib.pyplot" not in sys.modules:
        import matplotlib
        matplotlib.use("Agg")
    return importlib.import_module("petrophys.visualization")


def _function(name: str):
    V = visualization()
    fn = getattr(V, name, None)
    if fn is None:                                       # a plot the package does not export at its top
        for mod in ("zone_flags", "crossplot_viewer", "log_plot"):
            fn = getattr(importlib.import_module(f"petrophys.visualization.{mod}"), name, None)
            if fn is not None:
                break
    if fn is None:
        raise LookupError(f"petrophys.visualization has no {name}")
    return fn


def kind_of(function: str) -> str:
    """A display's short name: create_pickett_plot -> pickett, create_nd_crossplot -> nd."""
    return re.sub(r"_(cross)?plot$", "", re.sub(r"^(create|plot)_", "", function))


def summary(function: str) -> str:
    """What a Petrophys plot shows, in Petrophys' words: its docstring's first sentence."""
    doc = " ".join((inspect.getdoc(_function(function)) or "").split("\n\n")[0].split())
    first = re.split(r"(?<=[a-z0-9)%])\.\s", doc + " ", maxsplit=1)[0].strip().rstrip(".")
    first = re.sub(r"(?<=\S)/ (?=\S)", "/", re.sub(r"^(Create|Render|Plot)\s+(a|an|the)\s+", "", first))
    return first[:160] or kind_of(function)


# --- the plots of results ---------------------------------------------------------------------------------------------

def _zone_words(f, zones) -> str:
    zs = E.zones(f, zones)
    return "all zones" if len(zs) == len(f.view.zones) else "zones " + ", ".join(z.zone_id for z in zs)


def _name(f, c: str) -> str:
    cv = f.inv.curves.get(c)
    unit = f" [{cv.unit}]" if cv is not None and cv.unit else ""
    return f"{c}{unit}"


def forms(f, item) -> list:
    """(kind, title, spec) for each plot one result can be drawn as; [] for a result with none (a section, a step
    record, a calculation)."""
    a, out = dict(item.args or {}), []
    cond = f", where {a['where']}" if a.get("where") else ""
    sel = {"zones": a.get("zones"), "where": str(a.get("where") or "").strip() or None}

    def viewer(cs: list) -> tuple:
        return (VIEWER, f"Log display of {', '.join(cs)} against depth, beside the zones' lithology "
                        f"({_zone_words(f, a.get('zones'))}{cond})", {"curves": cs, **sel})
    try:
        zs = E.zones(f, a.get("zones"))                 # the same zones said two ways are one selection
        sel["zones"] = None if len(zs) == len(f.view.zones) else [z.zone_id for z in zs]
        if item.tool == "stats":
            cs = [c for c in E.curves(f, a.get("curves")) if c in f.inv.curves]
            zw = _zone_words(f, a.get("zones"))
            for c in cs[:3]:
                out.append((HISTOGRAM, f"Histogram of {_name(f, c)} by zone ({zw}{cond})", {"curve": c, **sel}))
            if cs:
                out.append(viewer(cs[:6]))
        elif item.tool == "crossplot":
            y, x = E.curve(f, str(a.get("y"))), str(a.get("x"))
            x = "DEPTH" if x.strip().upper() == "DEPTH" else E.curve(f, x)
            if x == "DEPTH":
                out.append(viewer([y]))
            else:
                title = (f"Crossplot of {_name(f, y)} against {_name(f, x)} "
                         f"({_zone_words(f, a.get('zones'))}{cond}), with the fitted line")
                out.append((CROSSPLOT, title, {"y": y, "x": x, **sel, "log_y": bool(a.get("log_y")),
                                               "log_x": bool(a.get("log_x")), "line": "fit"}))
        elif item.tool == "compare":
            ca, cb = E.curve(f, str(a.get("a"))), E.curve(f, str(a.get("b")))
            ua, ub = (getattr(f.inv.curves.get(c), "unit", "") or "" for c in (ca, cb))
            one = bool(ua) and ua == ub                 # a 1:1 line is read only where both are on one scale
            title = (f"Crossplot of {_name(f, ca)} against {_name(f, cb)} "
                     f"({_zone_words(f, a.get('zones'))}{cond})" + (", with the 1:1 line" if one else ""))
            out.append((CROSSPLOT, title, {"y": ca, "x": cb, **sel, "line": "one" if one else None}))
        elif item.tool == "profile":
            out.append(viewer([E.curve(f, str(a.get("curve")))]))
    except Exception:                                   # noqa: BLE001 - a result whose arguments do not resolve has no plot
        return []
    return out


# --- the standard displays --------------------------------------------------------------------------------------------

def _held(f, names) -> str | None:
    """The first of the curves that holds values in the interval."""
    return next((c for c in names if c in f.inv.curves and f.view.available(c)), None)


def bind(f, function: str) -> tuple | None:
    """A standard display's arguments from the interval -> (kwargs without the well, the curves it draws, the source of
    each number); None when the interval holds none of the curves one of its entries can use, or lacks a number it
    requires.
      - curves: its DISPLAYS entry, the first curve of each that holds values here (to its parameter, a name or the
        values as Petrophys declares the parameter; or read by the display from the well);
      - numbers (Petrophys declares the parameter a value): DISPLAY_MEDIANS' line the display draws, else the
        record's parameter of that name, else Petrophys' default."""
    from petrophys import function_schema
    from petroharness.agent import library_api as A
    fn = _function(function)
    decl = function_schema.declaration(fn)
    kinds = dict(decl.parameters) if decl else {}
    kw, curves, said = {}, [], []
    for param, names in DISPLAYS.get(function, ()):
        c = _held(f, names)
        if c is None:
            return None
        curves.append(c)
        if param is not None:
            d = kinds.get(param)
            kw[param] = np.asarray(f.view.values(c), dtype=float) if d is not None and d.kind == "curve" else c
    record = A._record_params(f)
    medians = DISPLAY_MEDIANS.get(function, {})
    for p, par in inspect.signature(fn).parameters.items():
        d = kinds.get(p)
        if p in _LEFT or p in kw or d is None or d.kind != "value":
            continue
        c = medians.get(p)
        if c is not None and _held(f, [c]):
            kw[p] = float(np.nanmedian(np.asarray(f.view.values(c), dtype=float)))
            said.append(f"{p} {kw[p]:.4g} (median of {c} over the interval)")
        elif p in record:
            kw[p] = record[p][0]
            said.append(f"{p} {record[p][0]:g} (record, {record[p][1]})")
        elif par.default is inspect.Parameter.empty:
            return None
        elif isinstance(par.default, (int, float)) and not isinstance(par.default, bool):
            said.append(f"{p} {par.default:g} (Petrophys' default)")
    return kw, curves, said


def behind(s, cited: list) -> set:
    """The curves an answer rests on: those its cited results' calls name, and the curves the steps that computed
    them read (petroharness.basis; one step back, so a display is offered for what the results show, not for
    everything the workflow ran)."""
    from petroharness import basis
    items = [e for e in (s.ledger.by_id(i) for i in cited) if e is not None]
    names = set(_NAME.findall("\n".join(e.call_text() for e in items)))
    for r in basis.used(s, cited):
        if r["why"] == basis.NAMED:
            names |= set(_NAME.findall(" ".join(r["inputs"])))
    return {c for c in names if c in s.f.inv.curves}


def displays(s, cited: list) -> list:
    """(kind, title, spec) of each standard display the interval can show from what the answer rests on: every curve
    it reads holds values here and is among the curves the answer rests on (`behind`)."""
    out, touched = [], behind(s, cited)
    for function in DISPLAYS:
        try:
            got = bind(s.f, function)
        except Exception:                               # noqa: BLE001 - a display that cannot be bound is not offered
            got = None
        if got is None or not set(got[1]) <= touched:
            continue
        _, curves, said = got
        title = f"{summary(function)} (the interval's {', '.join(curves)}" + (f"; {'; '.join(said)}" if said else "") + ")"
        out.append((kind_of(function), title, {"function": function, "curves": curves}))
    return out


def candidates(s, cited: list) -> list:
    """The plots an answer can carry: the plots of the results it rests on (`cited`: E ids, in the order to offer
    them), then the standard displays of the interval drawn from the same curves; each once, and a log display whose
    curves an offered one already shows (same zones and condition) is not offered again."""
    out, seen = [], set()

    def add(kind, title, spec, source, cap):
        key = (kind, json.dumps(spec, sort_keys=True, default=str))
        same = lambda c: (c.spec.get("zones"), c.spec.get("where")) == (spec.get("zones"), spec.get("where"))
        shown = kind == VIEWER and any(c.kind == VIEWER and set(spec["curves"]) <= set(c.spec["curves"]) and same(c)
                                       for c in out)
        if kind == CROSSPLOT:                           # one crossplot of a pair: the one with a line where there is one
            pair = next((c for c in out if c.kind == CROSSPLOT and same(c)
                         and (c.spec["y"], c.spec["x"]) == (spec["y"], spec["x"])), None)
            if pair is not None:
                if spec.get("line") and not pair.spec.get("line"):
                    pair.title, pair.spec, pair.source = title, spec, source
                return
        if key not in seen and not shown and len(out) < cap:
            seen.add(key)
            out.append(Candidate(f"F{len(out) + 1}", kind, source, title, spec))
    known = [item for item in (s.ledger.by_id(eid) for eid in cited) if item is not None]
    for item in known:
        for kind, title, spec in forms(s.f, item):
            add(kind, title, spec, item.id, MAX_RESULT_PLOTS)
    for kind, title, spec in (displays(s, cited) if known else []):
        add(kind, title, spec, "interval", MAX_CANDIDATES)
    return out


# --- the model's choice ------------------------------------------------------------------------------------------------

def schema(cands: list) -> dict:
    """The choice's JSON schema: the offered ids, at most MAX_FIGURES of them."""
    return {"type": "object", "properties": {"figures": {"type": "array", "items": {"enum": [c.id for c in cands]},
                                                         "maxItems": MAX_FIGURES}}, "required": ["figures"]}


def _from(c: Candidate) -> str:
    return "a standard display of the interval" if c.source == "interval" else f"from result {c.source}"


def pick(llm, usage, question: str, answer: str, cands: list, max_tokens: int | None = None):
    """The candidates the model chooses to show, in its order (at most MAX_FIGURES): [] for none, None when no reply
    could be read. One call, stage `figures`, on the output allowance of an investigation step (a reasoning model
    thinks before it replies; a smaller allowance ends it mid-thought); an empty reply is asked for once more."""
    if not cands:
        return []
    listing = "\n".join(f"{c.id}: {c.title} ({_from(c)})" for c in cands)
    user = f"QUESTION:\n{question}\n\nTHE ANSWER:\n{answer}\n\nCANDIDATE FIGURES:\n{listing}"
    messages = [{"role": "system", "content": C.text("C9", "figures")}, {"role": "user", "content": user}]
    cap = max_tokens or getattr(getattr(getattr(llm, "cfg", None), "model", None), "max_tokens_spec", None) or 3000
    text = llm.chat("figures", messages, usage, cap, json_schema=schema(cands))
    if not (text or "").strip():
        text = llm.chat("figures_retry", messages, usage, cap, json_schema=schema(cands), retry=True)
    return chosen(text, cands) if (text or "").strip() else None


def chosen(reply: str, cands: list) -> list:
    """The reply read: {"figures": ["F2", "F1"]} (or a bare list); ids it does not offer are dropped."""
    m = re.search(r"\{.*\}|\[.*\]", reply or "", re.DOTALL)
    got = None
    if m:
        try:
            got = json.loads(m.group(0))
        except ValueError:
            got = None
    if got is None:                                     # not JSON: the ids it names, in order
        got = re.findall(r"\bF\d+\b", reply or "")
    ids = got.get("figures", []) if isinstance(got, dict) else got
    by = {c.id: c for c in cands}
    out = []
    for x in ids if isinstance(ids, list) else []:
        x = str(x.get("id", "") if isinstance(x, dict) else x).strip().upper()
        if x in by and by[x] not in out:
            out.append(by[x])
    return out[:MAX_FIGURES]


# --- what Petrophys is given --------------------------------------------------------------------------------------------

def _kept(f, zones) -> np.ndarray:
    """The interval's samples inside the zones asked for (all zones when none are)."""
    keep = np.zeros(f.depth.size, dtype=bool)
    for z in E.zones(f, zones):
        keep[np.asarray(z.indices)] = True
    return keep


def plot_well(f, curves: list, zones=None, where=None, inside: bool = False):
    """The interval's well as Petrophys takes it (FormationView.interval_well: a copy holding the interval's samples,
    depths in the reporting unit), with each named curve as the results read it: a curve the workflow's well lacks (an
    analyzer's, one computed on request) is added, the analyzers' fills are in, and the samples outside a condition
    (and, with `inside`, outside the zones) are empty."""
    w = f.view.interval_well()
    sel = E.where(f, where)
    keep = _kept(f, zones) if inside else None
    for c in curves:
        x = E.restricted(f, c, sel)
        x = x if keep is None else np.where(keep, x, np.nan)
        old = w.get(c)
        if old is not None and np.array_equal(np.asarray(old.data, dtype=float), x, equal_nan=True):
            continue                                    # the workflow's curve, as it is
        cv = f.inv.curves.get(c)
        meta = getattr(old, "metadata", None)
        extra = {"data_type": meta.data_type} if getattr(meta, "data_type", None) is not None else {}
        w.add_curve(c, x, unit=(old.unit if old is not None else (cv.unit if cv is not None else "")) or "",
                    description=(getattr(meta, "description", "") or (cv.meaning if cv is not None else "")), **extra)
    return w


def _zone_rows(zs):
    import pandas as pd
    return pd.DataFrame([{"top": float(z.top), "bottom": float(z.base), "lithology": str(z.lithology)} for z in zs])


def zone_table(f, zones=None):
    """The zones as the log viewer's lithology intervals (top, bottom, lithology; the well's depth unit)."""
    return _zone_rows(E.zones(f, zones))


def overview(view, name: str = "") -> bytes:
    """The interval as Petrophys displays it, before any question (PNG bytes): the log viewer with its own tracks for
    the curves the well holds, beside the zones' lithology."""
    V = visualization()
    import matplotlib.pyplot as plt
    with _LOCK:
        viewer = V.create_log_viewer(view.interval_well(), interpreted=True, formation_name=name or None,
                                     lithology_intervals=_zone_rows(view.zones) if view.zones else None)
        fig = _figure_of(viewer)
        try:
            buf = io.BytesIO()
            V.save_figure(fig, buf, format="png")
        finally:
            plt.close(fig)
    return buf.getvalue()


def _data(w, c: str) -> np.ndarray:
    return np.asarray(w.get(c).data, dtype=float)


def _viewer(f, spec: dict) -> tuple:
    cs = list(spec["curves"])
    w = plot_well(f, cs, spec.get("zones"), spec.get("where"))
    n = int(np.isfinite(np.vstack([_data(w, c) for c in cs])).any(axis=0).sum())
    if not n:
        raise ValueError(f"no values of {', '.join(cs)} to draw")
    return visualization().create_log_viewer(w, curves=cs, interpreted=True, formation_name=f.inv.formation,
                                             lithology_intervals=zone_table(f, spec.get("zones"))), n


def _histogram(f, spec: dict) -> tuple:
    c, zs = spec["curve"], E.zones(f, spec.get("zones"))
    x = E.restricted(f, c, E.where(f, spec.get("where")))
    groups = {f"{z.zone_id} {z.lithology}".strip(): x[np.asarray(z.indices)] for z in zs}
    groups = {k: v[np.isfinite(v)] for k, v in groups.items()}
    groups = {f"{k} (n={v.size})": v for k, v in groups.items() if v.size}
    n = int(sum(v.size for v in groups.values()))
    if not n:
        raise ValueError(f"no values of {c} to draw")
    # outlines stay readable where several zones overlap (Petrophys' own advice for many datasets)
    return visualization().create_histogram_comparison(groups, bins=30, xlabel=_name(f, c), title=f"{c} by zone",
                                                       histtype="step" if len(groups) > 3 else "bar"), n


def _crossplot(f, spec: dict) -> tuple:
    y, x = spec["y"], spec["x"]
    w = plot_well(f, [y, x], spec.get("zones"), spec.get("where"), inside=True)
    xa, ya = _data(w, x), _data(w, y)
    log_x, log_y = bool(spec.get("log_x")), bool(spec.get("log_y"))
    ok = np.isfinite(xa) & np.isfinite(ya) & ((xa > 0) | (not log_x)) & ((ya > 0) | (not log_y))
    if not ok.any():
        raise ValueError(f"no samples with both {y} and {x} to draw")
    w.add_curve("DEPTH", np.asarray(w.depth, dtype=float), unit=f.inv.depth_unit, description="depth")
    plot = visualization().create_crossplot(w, x, y, color_curve="DEPTH", title=f"{y} against {x}",
                                            x_log=log_x, y_log=log_y)
    xa, ya = xa[ok], ya[ok]
    if spec.get("line") == "one":                       # the line a comparison is read against
        lo, hi = float(min(xa.min(), ya.min())), float(max(xa.max(), ya.max()))
        plot.add_line([lo, hi], [lo, hi], color="black", linestyle="--", label="1:1")
    elif spec.get("line") == "fit" and xa.size >= 3 and float(np.ptp(xa)) > 0:
        fx, fy = (np.log10(xa) if log_x else xa), (np.log10(ya) if log_y else ya)
        slope, intercept = np.polyfit(fx, fy, 1)
        gx = np.linspace(fx.min(), fx.max(), 50)
        gy = intercept + slope * gx
        plot.add_line(10 ** gx if log_x else gx, 10 ** gy if log_y else gy, color="black",
                      label="least-squares line (the plotted samples)")
    return plot, int(ok.sum())


def _display(f, spec: dict) -> tuple:
    function = spec["function"]
    got = bind(f, function)
    if got is None:
        raise ValueError(f"the interval lacks a curve {function} needs")
    kw, curves, _ = got
    fn = _function(function)
    w = plot_well(f, curves)
    finite = np.isfinite(np.vstack([_data(w, c) for c in curves]))
    n = int((finite.all(axis=0) if len(curves) <= 3 else finite.any(axis=0)).sum())    # a crossplot's points; a display's depths
    if not n:
        raise ValueError(f"no samples with {', '.join(curves)} to draw")
    return (fn(w, **kw) if "well" in inspect.signature(fn).parameters else fn(**kw)), n


DRAW = {VIEWER: _viewer, HISTOGRAM: _histogram, CROSSPLOT: _crossplot}


def _figure_of(got):
    """The Matplotlib figure of what a Petrophys plot returns: (figure, axes), an object holding .fig, or the figure."""
    if isinstance(got, tuple):
        got = got[0]
    return getattr(got, "fig", None) or getattr(got, "figure", None) or got


def draw(f, cand: Candidate) -> tuple:
    """(PNG bytes, the samples drawn) of one candidate: Petrophys draws it on the interval's well and saves it
    (petrophys.visualization.save_figure); the figure is closed."""
    V = visualization()
    import matplotlib.pyplot as plt
    with _LOCK:
        got, samples = DRAW.get(cand.kind, _display)(f, cand.spec)
        fig = _figure_of(got)
        try:
            buf = io.BytesIO()
            V.save_figure(fig, buf, format="png")
        finally:
            plt.close(fig)
    return buf.getvalue(), samples


def caption(n: int, cand: Candidate, samples: int) -> str:
    function = cand.spec.get("function") or FUNCTIONS.get(cand.kind, "")
    return (f"Figure {n}. {cand.title}; {samples} samples. Drawn by Petrophys ({function}) "
            + ("from the interval's curves." if cand.source == "interval" else f"from result {cand.source}."))


# --- one answer's figures ----------------------------------------------------------------------------------------------

def attach(s, question: str, answer: str, cited: list, llm, usage, folder: Path) -> dict:
    """The figures of one answer: the candidates of the cited results and the interval's standard displays, the model's
    choice, the drawn files in `folder`. -> {"candidates": [...], "chosen": [...], "figures": [{id, kind, source,
    caption, file, samples}], "errors": [...]} (the record kept in the trace and the session log)."""
    cands = candidates(s, cited)
    rec = {"candidates": [{"id": c.id, "kind": c.kind, "source": c.source, "title": c.title} for c in cands],
           "chosen": [], "figures": [], "errors": []}
    if not cands:
        return rec
    picked = pick(llm, usage, question, answer, cands)
    if picked is None:                                    # said, not hidden: the answer simply has no figures
        rec["errors"].append("the model gave no readable choice of figures")
        picked = []
    rec["chosen"] = [c.id for c in picked]
    for c in picked:
        try:
            png, samples = draw(s.f, c)
        except Exception as exc:                          # noqa: BLE001 - one figure that cannot be drawn is reported
            rec["errors"].append(f"{c.id}: {type(exc).__name__}: {str(exc)[:200]}")
            continue
        folder.mkdir(parents=True, exist_ok=True)
        n = len(rec["figures"]) + 1
        name = f"figure_{n}_{c.kind}.png"
        (folder / name).write_bytes(png)
        rec["figures"].append({"id": c.id, "kind": c.kind, "source": c.source, "spec": c.spec,
                               "caption": caption(n, c, samples), "file": f"{folder.name}/{name}", "samples": samples})
    return rec


def markdown(figs: list) -> str:
    """The figures as a section of the answer file ("" for none)."""
    if not figs:
        return ""
    return "\n\n## Figures\n\n" + "\n\n".join(f"![{g['caption']}]({g['file']})\n\n*{g['caption']}*" for g in figs) + "\n"
