"""The switches under test. A switch exists only while an A/B needs it: it defaults off, and once measured it becomes
the default (its branch deleted) or goes. Every trace records the options in force.

Two switches are left. tight_numbers stays off because its check on a number tied to a curve or zone flags numbers
the results show. cell_thickness stays off because a thickness of n sample steps does not equal the base minus the top
a reader computes from the depths written beside it. A run that wants the full investigation for every question asks
for it (`--investigate`, `direct=False`): that is a setting of the run, not a switch.

    PETROHARNESS_SET="name=true,other=a+b"     overrides the defaults for one run
    options.get()                              the options in force
    with options.use(name=True): ...           tests
"""
from __future__ import annotations

import os
import re
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, fields, replace

ENV = "PETROHARNESS_SET"


def _switch(on: str, off: str):
    """A switch under test, off by default: what it does on, and what happens off (today)."""
    return field(default=False, metadata={"on": on, "off": off})


@dataclass(frozen=True)
class Options:
    """One field per switch under test (bool, or str for a list of names joined by '+'), each off by default; the
    table in docs/reference/EXTENDING.md is generated from these fields."""
    tight_numbers: bool = _switch(
        "a mean is worked out only from three values or more, a small whole number with a unit is checked, and a "
        "number tied to a curve or zone is read only from a line naming one of them",
        "a midpoint of two passes whatever the mean; 'net pay 12 m' is never checked; 'Z3 SW 0.45' passes on any 0.45")
    cell_thickness: bool = _switch(
        "n regularly spaced samples are n steps thick (Petrophys's cells): a zone, a count of samples, the interval",
        "first to last sample: one sample step less than Petrophys's gross for the same interval")


def parse(text: str) -> Options:
    """'name=true' -> Options; an unknown name, or a value of the wrong kind, raises."""
    kinds = {f.name: f.type for f in fields(Options)}
    kw = {}
    for part in [p.strip() for p in (text or "").split(",") if p.strip()]:
        key, _, value = part.partition("=")
        key, value = key.strip(), value.strip().lower()
        if key not in kinds:
            raise ValueError(f"{ENV}: no option {key!r}; options: {', '.join(sorted(kinds)) or 'none'}")
        if kinds[key] in (str, "str"):                 # a list of names joined by '+'
            if value and not re.fullmatch(r"[a-z_]+(?:\+[a-z_]+)*", value):
                raise ValueError(f"{ENV}: {key} takes names joined by '+', not {value!r}")
            kw[key] = value
            continue
        if value not in ("true", "false", "1", "0", "on", "off"):
            raise ValueError(f"{ENV}: {key} takes true or false, not {value!r}")
        kw[key] = value in ("true", "1", "on")
    return Options(**kw)


_override = None


def get() -> Options:
    return _override if _override is not None else parse(os.environ.get(ENV, ""))


def as_dict() -> dict:
    return asdict(get())


@contextmanager
def use(**kw):
    global _override
    before, _override = _override, replace(get(), **kw)
    try:
        yield _override
    finally:
        _override = before
