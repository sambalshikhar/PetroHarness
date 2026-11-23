"""Tables of the reference pages generated from the code, so they cannot drift from it.

A generated block sits between two markers in a page:

    <!-- generated: NAME (tests/docs_tables.py) -->
    ...
    <!-- end generated: NAME -->

    .venv/bin/python tests/docs_tables.py            # say which blocks are out of date
    .venv/bin/python tests/docs_tables.py --write    # rewrite them

tests/test_docs_tables.py fails when a block differs from what the code gives.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def _runs(t) -> str:
    """Where a tool's call goes: the function, or a verb's binder over its own function."""
    mod = t.run.__module__.replace("petroharness.agent.", "")
    if t.verb:
        inner = t.run.curated
        return f"`library.api.verb_tool` over `{inner.__module__.replace('petroharness.agent.', '')}.{inner.__name__}`"
    return f"`{mod}.{t.run.__name__}`"


def tools() -> str:
    """The master table of the tool reference: every tool of TOOLSET, in the brief's order."""
    from petroharness.agent.toolset import TOOLSET
    rows = ["| # | Tool | Kind | Bare value fills | Listing leads with | Its zones reach | Pair | Runs |",
            "|---|---|---|---|---|---|---|---|"]
    for i, t in enumerate(TOOLSET, 1):
        kind = "verb over Petrophys" if t.verb else "computed table" if t.table else "lookup"
        reach = {"selection": "the selection", "whole_well": "the whole well (zones do not apply)",
                 "focus_only": "the focus only"}[t.stretch]
        pair = f"`{t.pair[0]}`, `{t.pair[1]}`" if t.pair else "-"
        rows.append(f"| {i} | [`{t.name}`](#{t.name}) | {kind} | `{t.main}` | {f'`{t.lead}`' if t.lead else '-'} | "
                    f"{reach} | {pair} | {_runs(t)} |")
    return "\n".join(rows)


def verbs() -> str:
    """The Petrophys functions each verb reaches, with their groups (library.api.functions and groups)."""
    from petroharness.agent.library import api
    order = ("calculate", "estimate", "calibrate", "summarize", "classify", "check", "what_if")
    rows = ["| Verb | Functions | Groups (named from the Petrophys modules) |", "|---|---|---|"]
    for v in order:
        rows.append(f"| `{v}` | {len(api.functions(v))} | {', '.join(api.groups(v))} |")
    modules = {fn.path for fn in api.registry()}
    rows.append(f"| All | {len(api.registry())} | from {len(modules)} modules |")
    return "\n".join(rows)


def _value(v) -> str:
    """A default as the settings page writes it."""
    if v is None:
        return "from the data"
    if isinstance(v, bool):
        return f"`{str(v).lower()}`"
    return f"`{v}`"


def settings_group(key: str):
    """The table of one group of the settings sheet (well.settings.schema), in the sheet's order."""
    def make() -> str:
        from petroharness.well import settings as T
        group = next(g for g in T.schema()["groups"] if g["key"] == key)
        rows = ["| Name | Type | Default | Meaning | Choices | Unit | Label |", "|---|---|---|---|---|---|---|"]
        for f in group["fields"]:
            choices = ", ".join(f"`{c}`" for c in f["choices"]) or "-"
            rows.append(f"| `{f['key']}` | {f['kind']} | {_value(f['default'])} | {f['help']} | {choices} | "
                        f"{f['unit'] or '-'} | {f['label']} |")
        return "\n".join(rows)
    return make


def components() -> str:
    """The ten prompt components: what each owns and the code files whose text is part of its version
    (agent/components/*/component.yaml: purpose and frames)."""
    from petroharness.agent import components as C
    rows = ["| Component | Owns | Frames |", "|---|---|---|"]
    for cid in C.COMPONENTS:
        m = C.meta(cid)
        frames = ", ".join(f"`{f}`" for f in m.get("frames") or []) or "none"
        rows.append(f"| {cid} {m['name']} | {m['purpose']} | {frames} |")
    return "\n".join(rows)


def switches() -> str:
    """The switches under test (options.Options): what each does on, and what happens off."""
    from dataclasses import fields
    from petroharness.options import Options
    rows = ["| Switch | On | Off (today) |", "|---|---|---|"]
    for f in fields(Options):
        m = f.metadata
        rows.append(f"| `{f.name}` | {m.get('on', '')} | {m.get('off', '')} |")
    return "\n".join(rows)


SETTING_GROUPS = ("zones", "clay", "porosity", "water", "saturation", "permeability", "pay", "temperature", "mud",
                  "lithology", "input")

BLOCKS = {"tools": (tools, "docs/reference/TOOLS_REFERENCE.md"),
          "verbs": (verbs, "docs/reference/PETROPHYS_INTEGRATION.md"),
          "components": (components, "docs/reference/PROMPT_COMPONENTS.md"),
          "switches": (switches, "docs/reference/EXTENDING.md"),
          **{f"settings_{g}": (settings_group(g), "docs/reference/INTERPRETATION_SETTINGS.md") for g in SETTING_GROUPS}}


def _span(text: str, name: str):
    m = re.search(rf"<!-- generated: {name} \(tests/docs_tables\.py\) -->\n(.*?)\n<!-- end generated: {name} -->",
                  text, re.S)
    return m


def stale() -> list:
    """(name, page) of every block that differs from what the code gives."""
    out = []
    for name, (make, page) in BLOCKS.items():
        text = (ROOT / page).read_text(encoding="utf-8")
        m = _span(text, name)
        if m is None or m.group(1) != make():
            out.append((name, page))
    return out


def write() -> None:
    for name, (make, page) in BLOCKS.items():
        path = ROOT / page
        text = path.read_text(encoding="utf-8")
        m = _span(text, name)
        if m is None:
            raise SystemExit(f"{page}: no '<!-- generated: {name} (tests/docs_tables.py) -->' block to fill")
        path.write_text(text[:m.start(1)] + make() + text[m.end(1):], encoding="utf-8")


if __name__ == "__main__":
    if "--write" in sys.argv:
        write()
    print("out of date:", stale() or "none")
