"""The investigation loop's measure L4: traps as K2H scenarios on real formations. The loop runs alone
(no writer, no judge) on a question written here for the trap, and its final claims are checked by rule.

    K2H_TOOL_URLS=... .venv/bin/python tests/agent/b5_traps.py OUT.json [--per 8] [--only NAME]
    (PETROHARNESS_DATA selects the dataset)

Each trap: where it applies (detected in the formation's inventory, never by name), the question, and the rule on the
claims. The questions are written for the trap, not taken from the benchmark.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT), str(Path(__file__).resolve().parent)]
warnings.simplefilter("ignore")

SHALLOW = ("RMED", "RSHA", "RXO", "RMIC")


def _said_absent(name: str, text: str) -> bool:
    n = re.escape(name)
    return bool(re.search(rf"\b{n}\b[^.;]{{0,80}}\b(absent|not (?:available|present|logged|recorded|acquired|run|in)|missing|"
                          rf"unavailable|lack)|\b(no|without|lacks?|missing|absent)\b[^.;]{{0,40}}\b{n}\b", text, re.I))


def _claims(s) -> list:
    return [c for c in s.claims.claims.values() if c.grade != "hypothesis"] if s.claims else []


def _text(c) -> str:
    return f"{c.text} {c.means} {c.weak}"


# --- the traps ------------------------------------------------------------------------------------------------------

def drho_absent(f):
    inv = f.inv
    if "DRHO" in inv.logs_absent and "RHOB" in inv.curves:
        return {}
    return None


def drho_check(s, ctx):
    cs = _claims(s)
    said = any(_said_absent("DRHO", _text(c)) or re.search(r"density correction[^.;]{0,60}\b(absent|not (?:available|"
                                                            r"recorded|logged)|unavailable|missing)", _text(c), re.I)
               for c in cs)
    proxy = [c.id for c in cs if re.search(r"(separation|crossover|PHID\s*-\s*PHIN|NPHI\s*-)[^.;]{0,60}\b(as|is|gives|"
                                           r"serves as|stands? for) (the |a )?density correction", c.text, re.I)]
    return said and not proxy, {"said_absent": said, "proxy_claims": proxy}


def invasion_no_shallow(f):
    inv = f.inv
    if "RDEP" in inv.curves and not any(c in inv.curves for c in SHALLOW):
        return {}
    return None


def invasion_check(s, ctx):
    cs = _claims(s)
    said = any(re.search(r"\b(shallow|medium|flushed|micro)[- ]?(zone |reading )?(resistivity|curves?|logs?)\b[^.;]{0,80}"
                         r"\b(absent|not (?:available|present|logged|recorded|acquired|run)|missing|unavailable|lack)|"
                         r"\b(no|without|lacks?|missing)\b[^.;]{0,40}\b(shallow|medium|flushed|micro)", _text(c), re.I)
               or any(_said_absent(n, _text(c)) for n in SHALLOW) for c in cs)
    confident = [c.id for c in cs if c.grade == "high" and re.search(r"invasion|invaded|filtrate", c.text, re.I)
                 and not re.search(r"\bnot\b|\bno\b|cannot|undetermin", c.text, re.I)]
    return said and not confident, {"said_absent": said, "high_invasion_claims": confident}


def perm_copy(f):
    c = f.inv.curves.get("PERM")
    if c is not None and c.copy_of == "PERM_CC":
        return {}
    return None


def perm_copy_check(s, ctx):
    cs = _claims(s)
    said = any(re.search(r"(same values|identical|a copy|copies|equal (?:to|values)|duplicate|the same curve|no "
                         r"difference|differ(?:ence)? (?:of |is )?0\b)", _text(c), re.I)
               and re.search(r"PERM", _text(c)) for c in cs)
    gap = [c.id for c in cs if re.search(r"PERM_CC", c.text) and re.search(r"(higher|lower|exceeds|under|over)[- ]?"
                                                                           r"(estimates?|predicts?)?\b[^.;]{0,40}\bPERM\b|"
                                                                           r"\bPERM\b[^.;]{0,40}(higher|lower|exceeds)", c.text)
           and not re.search(r"same|identical|copy|equal", c.text, re.I)]
    return said and not gap, {"said_same": said, "gap_claims": gap}


def contact_at_boundary(f):
    if "SW" not in f.inv.curves:
        return None
    zs = list(f.view.zones)
    x = np.asarray(f.view.values("SW"), dtype=float)
    for a, b in zip(zs, zs[1:]):
        if a.lithology.upper() == b.lithology.upper() or "NO_LITHOLOGY" in (a.lithology + b.lithology).upper():
            continue
        ma, mb = (np.nanmedian(x[z.indices]) if np.isfinite(x[z.indices]).any() else np.nan for z in (a, b))
        if np.isfinite(ma) and np.isfinite(mb) and abs(ma - mb) >= 0.3:
            return {"boundary": float(b.top), "above": a.zone_id, "below": b.zone_id,
                    "lith": [a.lithology, b.lithology], "sw": [round(float(ma), 3), round(float(mb), 3)]}
    return None


def contact_check(s, ctx):
    cs = _claims(s)
    lith = r"litholog|limestone|dolomite|sand|shale|carbonate|boundary|rock type|facies|" + "|".join(
        re.escape(w.lower()) for w in ctx["lith"])
    bad = []
    for c in cs:
        if c.grade not in ("high", "moderate"):
            continue
        if not re.search(r"\b(OWC|GWC|GOC|fluid contact|oil[- ]water contact|gas[- ]water contact|gas[- ]oil contact|"
                         r"free[- ]water level|FWL)\b", c.text, re.I):
            continue
        if re.search(r"\bno\b|\bnot\b|cannot|undetermin|absent|none", c.text, re.I):
            continue
        near = any(abs(float(v) - ctx["boundary"]) <= 5 for v in re.findall(r"\d{3,5}(?:\.\d+)?", c.text))
        if near and not re.search(lith, _text(c), re.I):
            bad.append(c.id)
    return not bad, {"contact_at_boundary_claims": bad}


def screen_not_run(f):
    for sec in f.inv.sections:
        cls = {c.name.upper(): c for c in sec.classes}
        ni = cls.get("NO_INDICATION")
        share = float(re.sub(r"[^\d.]", "", ni.share_pct or "0") or 0) if ni else 0
        other = " ".join(map(str, sec.other)) + f" {sec.method or ''} {sec.basis or ''}"
        if ni and share >= 99 and re.search(r"unavailable|not available|missing|could not|not run|insufficient", other, re.I):
            return {"key": sec.key}
    return None


def screen_check(s, ctx):
    """A confident denial of hydrocarbons that rests on the screen that could not run (cites its item, or its
    NO_INDICATION) without saying the screen could not run. Denials on other evidence (SW, the pay flags) are fine."""
    key = ctx["key"]
    ledger = getattr(s, "ledger", None)
    screen = {e.id for e in (ledger.items if ledger is not None else [])
              if e.tool == "section" and (e.args.get("key") == key or key.endswith("." + str(e.args.get("key"))))}
    denies = re.compile(r"\bno (?:hydrocarbons?|gas|oil)\b|hydrocarbons?[^.;]{0,30}\b(?:not indicated|absent)\b|"
                        r"\bnot indicated\b|water[- ]bearing throughout", re.I)
    caveat = re.compile(r"could not|cannot|unavailable|missing|not run|undetermin|insufficient|without", re.I)
    bad = [c.id for c in _claims(s) if c.grade in ("high", "moderate", "not indicated") and denies.search(c.text)
           and (set(c.ev) & screen or "NO_INDICATION" in c.text) and not caveat.search(_text(c))]
    return not bad, {"confident_denials_on_the_screen": bad}


TRAPS = {
    "drho_absent": ("hydrocarbon", drho_absent, lambda f, c: "Was a density correction (DRHO) applied to the bulk density "
                    "in this formation, and how large is it in the porous zones?", drho_check),
    "invasion_no_shallow": ("hydrocarbon", invasion_no_shallow, lambda f, c: "Is there evidence of mud-filtrate invasion in "
                            "the permeable zones of this formation, and how deep does it reach?", invasion_check),
    "perm_copy": ("permeability", perm_copy, lambda f, c: "How does the log-model permeability (PERM) compare with the "
                  "core-calibrated permeability (PERM_CC) zone by zone, and which should be used?", perm_copy_check),
    "contact_at_boundary": ("hydrocarbon", contact_at_boundary, lambda f, c: "Is there a fluid contact in this formation, "
                            "and at what depth?", contact_check),
    "screen_not_run": ("hydrocarbon", screen_not_run, lambda f, c: "Does the hydrocarbon screening indicate hydrocarbons in "
                       "this formation?", screen_check),
}


def scenarios(per: int, only=None) -> list:
    from test_b2_tools import F
    out = {k: [] for k in TRAPS}
    for t, f in F():
        for name, (cat, detect, question, _) in TRAPS.items():
            if only and name != only or len(out[name]) >= per:
                continue
            if any(x[0].well == t.well for x in out[name]):         # one formation per well: spread the cases
                continue
            ctx = detect(f)
            if ctx is not None:
                out[name].append((t, f, ctx))
    return [(name, t, f, ctx) for name, xs in out.items() for t, f, ctx in xs]


def trap_task(t, question: str, task_id: str):
    """The formation's task with the trap's question (a pydantic model: copied, never changed in place)."""
    upd = {"question": question, "task_id": task_id}
    return t.model_copy(update=upd) if hasattr(t, "model_copy") else t.copy(update=upd)


def run_one(k_case, urls):
    from petroharness.config import HarnessConfig
    from petroharness.llm import LLM, Usage
    from petroharness.models import MODELS
    from petroharness.agent.ledger import Ledger
    from petroharness.agent.loop import Session, investigate, read_question
    from petroharness.agent.map import render
    k, (name, t, f, ctx) = k_case
    _, _, question, check = TRAPS[name]                     # the trap's subject is not a run input: the model reads it
    task = trap_task(t, question(f, ctx), f"trap_{name}_{k}")
    cfg = HarnessConfig.load(ROOT / MODELS["k200t"][0])
    cfg.model.base_url = urls[k % len(urls)] if urls else cfg.model.base_url
    tcfg = cfg.for_tasks()
    s = Session(task, f, render(f.inv), Ledger(f))
    trace = {}
    try:
        llm, usage = LLM(tcfg), Usage()
        read_question(llm, s, usage, tcfg.model.max_tokens_spec, trace)
        investigate(llm, s, usage, tcfg.model.max_tokens_spec, trace)
        ok, why = check(s, ctx)
    except Exception as e:                                   # a lost scenario fails the trap
        ok, why = False, {"error": f"{type(e).__name__}: {e}"}
    return {"trap": name, "well": t.well, "formation": t.formation, "context": ctx, "question": task.question, "pass": ok,
            "why": why, "claims": trace.get("claims", []), "opened": trace.get("opened", []),
            "steps": len(trace.get("steps", []))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--per", type=int, default=8)
    ap.add_argument("--only")
    ap.add_argument("--list", action="store_true", help="list the scenarios, run nothing")
    args = ap.parse_args()
    cases = scenarios(args.per, args.only)
    if args.list:
        for name, t, f, ctx in cases:
            print(name, t.well, t.formation, ctx)
        return
    urls = [u for u in os.environ.get("K2H_TOOL_URLS", "").split(",") if u]
    with ThreadPoolExecutor(min(48, len(cases))) as ex:
        rows = list(ex.map(lambda kc: run_one(kc, urls), enumerate(cases)))
    Path(args.out).write_text(json.dumps(rows, indent=1, default=str))
    for name in TRAPS:
        r = [x for x in rows if x["trap"] == name]
        if r:
            print(f"{name}: {sum(x['pass'] for x in r)} of {len(r)}")


if __name__ == "__main__":
    main()
