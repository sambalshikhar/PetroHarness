"""One definition per tool.

A tool is one `Tool`: the function that runs it, the arguments the model may send, the text that describes it to the
model, the group the brief lists it under, and how a call of it is read and listed. A `Toolset` holds the definitions
in order, and every list of tools the harness needs is read from it: the functions by name, the schemas, the brief's
groups, the names the reply parser knows, the argument a bare value fills, the argument a one-line listing leads with.
So a new tool is one definition (docs/TOOLS.md, "Adding a tool"); nothing else lists tools.

This module imports nothing of the harness: the definitions themselves are in petroharness.agent.toolset.
"""
from __future__ import annotations

import copy
import inspect
from dataclasses import dataclass, field
from typing import Callable, Iterator, Optional, Union



STRETCHES = ("selection", "whole_well", "focus_only")      # Tool.stretch

@dataclass(frozen=True)
class Tool:
    """One tool.

    name          as the model writes it: {"stats": {...}}
    run           run(formation, **arguments) -> Result
    group         the heading of the brief it is listed under (one of the toolset's groups)
    description   the text the model reads; a function where it is built when asked (a verb's list of Petrophys
                  methods comes from the library's catalog)
    arguments     name -> JSON schema, in the order the brief lists them; or a function returning that
    required      the arguments a call must give
    main          the argument a bare value fills: {"runs": "NET_PAY"} is {"runs": {"condition": "NET_PAY"}}
    lead          the argument a one-line listing of a call leads with ("runs NET_PAY (limit 5)"); "" for none
    table         its result is a computed table (header, rows, facts) and is read in that order
    verb          a verb over Petrophys: its calls can search and run every Petrophys function it serves
    stretch       what its zones reach: "selection" (the stretches the call names, or the question's scope),
                  "whole_well" (the same for any stretch, such as the well's record of a step: zones do not apply), or
                  "focus_only" (it rests on what the workflow computed for the focus: a stretch elsewhere is refused)
    focus_reason  for "focus_only": what it reads, as the refusal says it
    pair          the two arguments a list of two fills, in order ({"compare": ["PHIE", "PHIE_CC"]} is a and b); ()
    pair_word     the word that joins the pair in a one-line listing ("compare PHIE vs PHIE_CC"); "" for none
    """
    name: str
    run: Callable
    group: str
    description: Union[str, Callable[[], str]]
    arguments: Union[dict, Callable[[], dict]] = field(default_factory=dict)
    required: tuple = ()
    main: str = "curves"
    lead: str = ""
    table: bool = False
    verb: bool = False
    stretch: str = "selection"
    focus_reason: str = ""
    pair: tuple = ()
    pair_word: str = ""

    def text(self) -> str:
        """The description the model reads."""
        return self.description() if callable(self.description) else self.description

    def properties(self) -> dict:
        """The arguments (name -> JSON schema), a copy."""
        return copy.deepcopy(self.arguments() if callable(self.arguments) else self.arguments)

    def schema(self) -> dict:
        """The tool as a native tool-calling schema."""
        return {"type": "function",
                "function": {"name": self.name, "description": self.text(),
                             "parameters": {"type": "object", "properties": self.properties(),
                                            "required": list(self.required)}}}

    def parameters(self) -> list:
        """The names `run` takes beside the formation."""
        return list(inspect.signature(self.run).parameters)[1:]


class Toolset:
    """The tools, in the order they were defined, under the groups the brief lists them by."""

    def __init__(self, groups: tuple):
        self.groups = tuple(groups)
        self._tools: dict = {}

    def add(self, *tools: Tool) -> None:
        """Define tools. What is wrong with a definition is said here, when the harness is imported."""
        for t in tools:
            if not t.name or not t.name.isidentifier():
                raise ValueError(f"WHAT: a tool named {t.name!r}. FIX: a name the model can write as a JSON key, "
                                 "letters, digits and underscores.")
            if t.name in self._tools:
                raise ValueError(f"WHAT: the tool {t.name} is defined twice. FIX: one definition per tool.")
            if t.group not in self.groups:
                raise ValueError(f"WHAT: the tool {t.name} is in the group {t.group!r}, which the brief does not list. "
                                 f"FIX: one of {', '.join(repr(g) for g in self.groups)}.")
            if not callable(t.run):
                raise ValueError(f"WHAT: the tool {t.name} has nothing to run. FIX: run=the function that computes it.")
            if t.stretch not in STRETCHES:
                raise ValueError(f"WHAT: the tool {t.name} has stretch {t.stretch!r}. FIX: one of "
                                 f"{', '.join(STRETCHES)}.")
            if (t.stretch == "focus_only") != bool(t.focus_reason):
                raise ValueError(f"WHAT: the tool {t.name}: a focus_reason goes with stretch 'focus_only', and only "
                                 "with it. FIX: say what it reads, or drop the reason.")
            if not callable(t.description) and not str(t.description).strip():
                raise ValueError(f"WHAT: the tool {t.name} has no description. FIX: the text the model reads about it.")
            if not callable(t.arguments):
                names = list(t.arguments)
                missing = [r for r in t.required if r not in names]
                if missing:
                    raise ValueError(f"WHAT: the tool {t.name} requires {', '.join(missing)}, which its arguments do "
                                     f"not define. FIX: define them, or take them out of required.")
                if names and t.main not in names:
                    raise ValueError(f"WHAT: a bare value given to the tool {t.name} fills {t.main!r}, which it does "
                                     f"not define. FIX: main=one of {', '.join(names)}.")
                if t.pair and (len(t.pair) != 2 or any(p not in names for p in t.pair)):
                    raise ValueError(f"WHAT: the tool {t.name} pairs {t.pair}, which are not two of its arguments. "
                                     f"FIX: pair=two of {', '.join(names)}, or no pair.")
                if t.lead and t.lead not in names:
                    raise ValueError(f"WHAT: the tool {t.name} is listed by its argument {t.lead!r}, which it does "
                                     f"not define. FIX: lead=one of {', '.join(names) or 'none'}, or no lead.")
            self._tools[t.name] = t

    # --- reading -------------------------------------------------------------------------------------------------

    def __iter__(self) -> Iterator[Tool]:
        return iter(self._tools.values())

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name) -> bool:
        return name in self._tools

    def __getitem__(self, name: str) -> Tool:
        return self._tools[name]

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def names(self) -> list:
        return list(self._tools)

    def stretch(self, name: str) -> str:
        """What a tool's zones reach (Tool.stretch); "selection" for a name that is no tool."""
        t = self._tools.get(name)
        return t.stretch if t is not None else "selection"

    def functions(self) -> dict:
        """name -> the function that runs it."""
        return {t.name: t.run for t in self}

    def schemas(self) -> list:
        """The tools as native tool-calling schemas, in the order they were defined."""
        return [t.schema() for t in self]

    def by_group(self) -> tuple:
        """((heading, (tool names)), ...): the groups in the brief's order, each with its tools in the order they
        were defined; a group with no tool is left out."""
        out = []
        for g in self.groups:
            names = tuple(t.name for t in self if t.group == g)
            if names:
                out.append((g, names))
        return tuple(out)

    def main(self, name: str) -> str:
        """The argument a bare value fills ("curves" for a name that is no tool)."""
        t = self._tools.get(name)
        return t.main if t is not None else "curves"

    def lead(self, name: str) -> str:
        """The argument a one-line listing of a call leads with ("" for none, or for a name that is no tool)."""
        t = self._tools.get(name)
        return t.lead if t is not None else ""
