"""The methods and parameters an answer rests on. For the curves the answer and its cited results name, the workflow
steps that computed them and the steps those read from: each with its method, its inputs and its parameters as the
well's record holds them. Read by code from the record after the answer is final (petroharness.evidence.record walks
it); nothing here reaches a prompt, so it cannot change an answer.

    used(session, cited ids, answer) -> [{"step", "method", "curves", "inputs", "parameters", "why"}]
    markdown(rows)                   -> the section of the answer file
"""
from __future__ import annotations

from petroharness.evidence import record as R
from petroharness.evidence.record import MAX_PARAMETERS, NAMED, ON_REQUEST, UPSTREAM, parameters  # noqa: F401


def named(s, cited: list, answer: str = "") -> list:
    """The curve-like names the answer and the calls of its cited results hold."""
    items = [e for e in (s.ledger.by_id(i) for i in cited) if e is not None]
    return R.names("\n".join([answer or ""] + [e.call_text() for e in items]))


def used(s, cited: list, answer: str = "") -> list:
    """The steps behind an answer, in the workflow's order (evidence.record.behind on the live session's record)."""
    return R.behind(R.snapshot(s.f.inv), named(s, cited, answer))


def _value(v) -> str:
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float):
        return f"{v:.6g}"
    return str(v)


def line(r: dict) -> str:
    """One step in one line: its method, the curves it computed, what it read, its parameters."""
    parts = [f"**{r['step']}**: {r['method']}", f"computed {', '.join(r['curves'])}" if r["curves"] else ""]
    if r["inputs"]:
        parts.append(f"read {', '.join(r['inputs'])}")
    if r["parameters"]:
        parts.append("parameters " + "; ".join(f"{k} = {_value(v)}" for k, v in r["parameters"].items()))
    return ". ".join(p for p in parts if p) + "."


def markdown(rows: list) -> str:
    """The rows as a section of the answer file ("" for none)."""
    if not rows:
        return ""
    first = [r for r in rows if r["why"] == NAMED]
    upstream = [r for r in rows if r["why"] == UPSTREAM]
    lines = ["", "", "## Methods and parameters this answer rests on", "",
             "Read from the well's record, not written by the model. The steps that computed the curves this answer "
             "names:", ""]
    lines += [f"- {line(r)}" for r in first]
    if upstream:
        lines += ["", "The steps those read from:", ""] + [f"- {line(r)}" for r in upstream]
    return "\n".join(lines) + "\n"
