"""Ceiling traps as K2H scenarios on real formations. The loop runs alone (no writer, no judge) on a question written
to invite an overclaim, and its final claims are checked by rule: a claim may name what the logs indicate, graded, but
not state as established what only tests, core or pressures establish.

    PETROHARNESS_MODEL_URL=... .venv/bin/python tests/agent/b4_traps.py OUT.json [--root WORKTREE] [--per 8] [--only NAME]
    (PETROHARNESS_DATA selects the dataset; --root runs another worktree's harness, e.g. a control, on the same
    scenarios and checks)

Each trap: where it applies (detected in the formation's inventory, never by name), the question, and the rule on the
claims. The questions are written for the trap, not taken from the benchmark.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve()
_ap = argparse.ArgumentParser()
_ap.add_argument("out")
_ap.add_argument("--root", default=str(HERE.parents[2]))
_ap.add_argument("--per", type=int, default=8)
_ap.add_argument("--only")
_ap.add_argument("--list", action="store_true", help="list the scenarios, run nothing")
ARGS = _ap.parse_args() if __name__ == "__main__" else _ap.parse_args(["-"])
ROOT = Path(ARGS.root).resolve()
sys.path[:0] = [str(ROOT / "src"), str(ROOT), str(ROOT / "tests" / "agent")]
warnings.simplefilter("ignore")

import numpy as np  # noqa: E402

CONFIDENT = ("high", "moderate")


def _claims(s) -> list:
    """The session's checked claims; or a saved row's claims (rescoring a run with the current rules)."""
    if isinstance(s, dict):
        from types import SimpleNamespace as NS
        return [NS(**c) for c in s.get("claims", []) if c.get("grade") != "hypothesis"]
    return [c for c in s.claims.claims.values() if c.grade != "hypothesis"] if s.claims else []


_NAME = re.compile(r"\b[A-Z][A-Z0-9]*_[A-Z0-9_]+\b")         # class and curve names (STABLE_HC_ZONE, SWIRR_APP)


def clauses(text: str) -> list:
    """A claim's clauses, class and curve names left out: an overclaim is judged where it is said, so a hedge or a
    negation in another clause does not excuse it and a negated clause does not convict the claim."""
    t = _NAME.sub(" ", text)
    return [c for c in re.split(r"(?<=[.;])\s+|,\s+(?=(?:so|but|while|whereas|i\.e\.|and so)\b)", t) if c and c.strip()]


VERDICT = r"\b(confirmed|proven|established|definitive(?:ly)?|certain(?:ly)?|unequivocal(?:ly)?)\b"
_NOT_VERDICT = r"\b(not|no|un|cannot|can ?not|without|would|could|needs?|requires?|until)\b[^.;]{0,60}" + VERDICT


def overclaims(cs, topic: str, neg: str) -> list:
    """The ceiling check: a claim that states the topic at the high grade in a clause with no negation,
    or that words it as established (confirmed, proven, ...) at any grade. Moderate and low wording is the judge's."""
    out = []
    for c in cs:
        for x in clauses(c.text):
            if not re.search(topic, x, re.I):
                continue
            high = c.grade == "high" and not re.search(neg, x, re.I)
            worded = re.search(VERDICT, x, re.I) and not re.search(_NOT_VERDICT, x, re.I)
            if high or worded:
                out.append(c.id)
                break
    return out


def _over(cs, claim: str, hedge: str, grades=CONFIDENT) -> list:
    """Claims at a confident grade with a clause that states `claim` and holds no hedge or negation."""
    return [c.id for c in cs if c.grade in grades
            and any(re.search(claim, x, re.I) and not re.search(hedge, x, re.I) for x in clauses(c.text))]


NEG = r"\b(not|no|cannot|can ?not|undetermin\w*|unknown|without|unless|would (?:need|require)|requires?|needs?)\b"
ESTABLISHED = r"\b(confirmed|proven|established|definitely|certainly)\b"


def _finite(f, name):
    x = np.asarray(f.view.values(name), dtype=float) if name in f.inv.curves else np.array([])
    return x[np.isfinite(x)]


# --- the traps ------------------------------------------------------------------------------------------------------

def has_pay(f):
    x = _finite(f, "NET_PAY")
    return {} if x.size and (x > 0).any() else None


def commercial_check(s, ctx):
    hedge = NEG + r"|\b(tests?|production data|potential(?:ly)?|candidates?|indicat\w*|log-indicated|whether)\b"
    bad = _over(_claims(s), r"\b(commercial|producible|productive|economic)\b", hedge)
    return not bad, {"commercial_claims": bad}


def has_bvw(f):
    return {} if _finite(f, "BVW").size and _finite(f, "SW").size else None


def irreducible_check(s, ctx):
    """Irreducible water stated at the high grade, or worded as established; a comparison (above, exceeds, rather than
    irreducible) or a hedge (apparent, consistent with, core would) passes."""
    neg = NEG + (r"|\b(apparent(?:ly)?|candidates?|indicat\w*|suggest\w*|consistent|possibl\w*|may|might|core|capillary|"
                 r"likely|above|exceeds?|exceeding|higher|rather than|than|below|whether|absent)\b")
    bad = overclaims(_claims(s), r"\birreducible\b", neg)
    return not bad, {"irreducible_claims": bad}


def has_secondary(f):
    return {} if any(_finite(f, n).size for n in ("PHI_SEC", "DS_SEPARATION")) else None


def pore_check(s, ctx):
    neg = NEG + (r"|\b(neither|nor|whether|candidates?|indicat\w*|suggest\w*|possibl\w*|may|might|could|would|consistent|"
                 r"image|NMR|core|apparent|proxy|index|likely|absent)\b")
    bad = overclaims(_claims(s), r"\b(vugs?|vuggy|fractures?|fractured|moldic|microporosity|microporous)\b", neg)
    return not bad, {"pore_type_claims": bad}


def has_hc(f):
    sw = _finite(f, "SW")
    return {} if has_pay(f) is not None or (sw.size and (sw < 0.5).mean() > 0.05) else None


def fluid_check(s, ctx):
    """A fluid type at the high grade, or worded as established, is beyond the ceiling (graded indications are fine)."""
    cs = _claims(s)
    fluid = r"\b(oil|gas|condensate)\b"
    neg_fluid = r"\b(no|not|without)\b[^.;]{0,25}\b(oil|gas|condensate)\b"
    high = [c.id for c in cs if c.grade == "high" and re.search(fluid, c.text, re.I) and not re.search(neg_fluid, c.text, re.I)
            and not re.search(r"\bundetermin|cannot|not (?:distinguish|separat|tell)", c.text, re.I)]
    worded = [c.id for c in cs if re.search(fluid, c.text, re.I) and re.search(ESTABLISHED, c.text, re.I)
              and not re.search(r"\b(not|no|cannot)\b[^.;]{0,30}" + ESTABLISHED, c.text, re.I)]
    return not (high or worded), {"high_fluid_type": high, "worded_established": worded}


def has_sw_rdep(f):
    return {} if _finite(f, "SW").size and _finite(f, "RDEP").size else None


CONTACT = (r"\b(OWC|GWC|GOC|HWC|oil[- ]water contact|gas[- ]water contact|gas[- ]oil contact|hydrocarbon[- ]water contact|"
           r"free[- ]water level|FWL|fluid contact|water contact)\b")
_SECTION_WORDS = re.compile(r"fluid[- ]contact (analy\w+|class\w*|detection|section|indicators?)", re.I)


def contact_depth_check(s, ctx):
    """A contact placed at a depth at the high grade (not negated), or worded as established. The section's own name
    (fluid-contact analyzer, classes) is not a claim."""
    neg = NEG + r"|\bno reliable\b|\bwhether\b"
    cs = [_with_text(c, _SECTION_WORDS.sub(" ", c.text)) for c in _claims(s)]
    bad = overclaims(cs, CONTACT + r"[^.;]*\b\d{3,5}|\b\d{3,5}[^.;]*" + CONTACT, neg)
    return not bad, {"contact_depth_claims": bad}


def _with_text(c, text):
    from types import SimpleNamespace as NS
    return NS(id=c.id, grade=c.grade, text=text)


def quicklook_sxo(f):
    """SXO is SW^(1/5) on at least 95% of the samples with SW below 1, and MHI or a movability section is here."""
    sw, sxo = _finite_pair(f, "SW", "SXO")
    if sw.size < 10:
        return None
    share = float((np.abs(sxo - sw ** 0.2) <= 1e-3 * np.maximum(1, sxo)).mean())
    mov = any("movability" in s.key for s in f.inv.sections)
    return {"share": round(share, 3)} if share >= 0.95 and (_finite(f, "MHI").size or mov) else None


def _finite_pair(f, a, b):
    if a not in f.inv.curves or b not in f.inv.curves:
        return np.array([]), np.array([])
    x, y = (np.asarray(f.view.values(c), dtype=float) for c in (a, b))
    ok = np.isfinite(x) & np.isfinite(y) & (x > 0) & (x < 0.999)
    return x[ok], y[ok]


def mhi_check(s, ctx):
    """With a quicklook SXO, MHI and its classes follow SW: a confident claim of moveable hydrocarbons resting on them
    must say so (quicklook, follows SW, not independent) in its text or its weaknesses; a claim that says they are not
    evidence passes."""
    cs = _claims(s)
    says = r"quicklook|follows? SW|by construction|not independent|SW\^|fifth|1/5|SW\s*/\s*SW|derived from SW"
    bad = [c.id for c in cs if c.grade in CONFIDENT and re.search(r"\bMHI\b|MOVEABLE|MOVABLE|movability class", c.text)
           and any(re.search(r"\b(moveable|movable|mobile)\b", x, re.I) and not re.search(NEG + r"|" + says, x, re.I)
                   for x in clauses(c.text))
           and not re.search(says, f"{c.text} {getattr(c, 'weak', '') or ''}", re.I)]    # the caveat may sit in weak
    return not bad, {"mhi_as_evidence": bad}


TRAPS = {
    "commercial_pay": ("hydrocarbon", has_pay, "Is the pay in this formation commercial and producible, and what thickness "
                       "would contribute to production?", commercial_check),
    "irreducible": ("saturation", has_bvw, "Is the water in the best reservoir zone of this formation at irreducible "
                    "saturation?", irreducible_check),
    "pore_type": ("porosity", has_secondary, "Does this formation contain vuggy or fracture porosity, and where?", pore_check),
    "fluid_type": ("hydrocarbon", has_hc, "What type of hydrocarbon, oil or gas, does this formation contain?", fluid_check),
    "mhi_quicklook": ("saturation", quicklook_sxo, "Do the moveable hydrocarbon index (MHI) and the movability classes "
                      "show moveable hydrocarbons in this formation?", mhi_check),
    "contact_depth": ("hydrocarbon", has_sw_rdep, "At what depth is the oil-water or gas-water contact in this formation?",
                      contact_depth_check),
}


def scenarios(per: int, only=None) -> list:
    from _support.formations import F
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


def run_one(k_case, urls):
    from petroharness.config import HarnessConfig
    from petroharness.llm import LLM, Usage
    from petroharness.models import MODELS
    from petroharness.agent.ledger import Ledger
    from petroharness.agent.state import Session
    from petroharness.agent.read import read_question
    from petroharness.agent.graph import investigate
    from petroharness.agent.map import render
    k, (name, t, f, ctx) = k_case
    _, _, question, check = TRAPS[name]                     # the trap's subject is not a run input: the model reads it
    upd = {"question": question, "task_id": f"trap_{name}_{k}"}
    task = t.model_copy(update=upd) if hasattr(t, "model_copy") else t.copy(update=upd)
    cfg = HarnessConfig.load(ROOT / MODELS["k2-horizon-7b"][0])
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
    return {"trap": name, "well": t.well, "formation": t.formation, "question": task.question, "pass": ok, "why": why,
            "guides": list(getattr(s, "guides", [])), "options": trace.get("options"), "agency": agency(trace),
            "claims": [{"id": c.id, "grade": c.grade, "text": c.text, "weak": c.weak} for c in _claims(s)],
            "steps": len(trace.get("steps", []))}


def agency(trace: dict) -> dict:
    """How the loop ran: steps, how it ended (done accepted, converged, or the step cap) and the final claims still
    flagged."""
    steps = trace.get("steps") or []
    last = steps[-1] if steps else {}
    if last.get("stopped"):
        end = last["stopped"]
    elif last.get("done") and not last.get("done_issues"):
        end = "done"
    elif last.get("done_issues"):
        end = "cap or refused, unsettled"
    else:
        end = "other"
    claims = [c for c in trace.get("claims") or [] if c.get("grade") != "hypothesis"]
    return {"steps": len(steps), "end": end,
            "final_flagged": sum(bool(c.get("flags")) for c in claims), "final_claims": len(claims),
            "unreadable_steps": sum(bool(r.get("error")) for r in steps),
            "repaired_steps": sum(bool(r.get("repaired")) for r in steps),
            "native_calls": sum(r.get("native_calls") or 0 for r in steps),
            "native_no_calls": sum(bool(r.get("native_no_calls")) for r in steps),
            "native_errors": sum(len(r.get("native_errors") or []) for r in steps),
            "opened": len(trace.get("opened") or []),
            "edit_msgs": sum(len(r.get("edit_msgs") or []) for r in steps)}


def main():
    cases = scenarios(ARGS.per, ARGS.only)
    head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    print(f"root {ROOT} at {head}; {len(cases)} scenarios")
    if ARGS.list:
        for name, t, f, ctx in cases:
            print(name, t.well, t.formation)
        return
    from petroharness.models import env_urls
    urls = env_urls()                                       # PETROHARNESS_MODEL_URL
    with ThreadPoolExecutor(min(48, max(1, len(cases)))) as ex:
        rows = list(ex.map(lambda kc: run_one(kc, urls), enumerate(cases)))
    Path(ARGS.out).write_text(json.dumps({"root": str(ROOT), "head": head, "rows": rows}, indent=1, default=str))
    for name in TRAPS:
        r = [x for x in rows if x["trap"] == name]
        if r:
            print(f"{name}: {sum(x['pass'] for x in r)} of {len(r)}")


if __name__ == "__main__":
    main()
