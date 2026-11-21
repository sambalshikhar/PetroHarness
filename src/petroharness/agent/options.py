"""The switches under test. A switch exists only while an A/B needs it: it defaults off, and once measured it becomes
the default (its branch deleted) or goes. Every trace records the options in force.

No switch is under test. A run that wants the full investigation for every question asks for it (`--investigate`,
`direct=False`): that is a setting of the run, not a switch.

    PETROHARNESS_SET="name=true,other=a+b"     overrides the defaults for one run
    options.get()                              the options in force
    with options.use(name=True): ...           tests
"""
from __future__ import annotations

import os
import re
from contextlib import contextmanager
from dataclasses import asdict, dataclass, fields, replace

ENV = "PETROHARNESS_SET"


@dataclass(frozen=True)
class Options:
    """One field per switch under test (bool, or str for a list of names joined by '+'); none at present."""


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
