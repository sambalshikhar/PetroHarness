"""The READ call: the model reads the question (its topics, its points, whether it is direct) and the stretches it
is about (scope); a question back when a unit is ambiguous (ask_back)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from petroharness.agent.prompts import _reach, brief

if TYPE_CHECKING:
    from petroharness.agent.state import Session

import json
import re
from typing import Optional
from petroharness.llm import LLM, Usage
from petroharness.agent import direction
from petroharness.agent.engine import Formation, ToolError
from petroharness.agent import components as C  # noqa: E402  (the texts: src/petroharness/agent/components)


# --- the READ call: the model reads the question and chooses its topics ------------------------------------------------

READ = C.text("C5", "read")


SCOPE_ITEM_CHARS = 60          # one scope item: a unit's name, a zone's, a depth range (a sentence is not a stretch)
DEPTH_WORD = "^[a-z_]{1,24}$"  # reach well: the reply's depth, one word as the model writes it (_reading reads it)


def read_schema(depth: bool = False, scope: bool = False, names: tuple = ()) -> dict:
    """The READ reply's JSON schema: the topics from the index's areas and the measurements the question names (nothing
    that frames the question before the evidence is in view); with `depth`, also what kind of answer it asks for; with
    `scope` (reach well), the stretches it is about, each one of `names` (selection.names) or a depth range.

    Where a request may be outside the well's logs (reach well, the depth read) the reply can hold what the model
    means either way: its depth is one word as the model writes it (DEPTH_WORD), and its topics may be none. A list
    of three words made the decoder put one of them where the reasoning meant another ("compare", step 1's intent),
    and it put "outside"; and a reply that had to name a topic for a request that needs none went on as for a
    question about the well. The benchmark's READ (reach focus) chooses between two words and names a topic."""
    offered = depth and scope
    schema = {"type": "object",
              "properties": {"topics": {"type": "array", "items": {"enum": list(direction.areas())},
                                        "minItems": 0 if offered else 1, "maxItems": 4},
                             "named": {"type": "array", "items": {"type": "string"}, "maxItems": 12}},
              "required": ["topics", "named"]}
    if depth:
        schema["properties"]["depth"] = ({"type": "string", "pattern": DEPTH_WORD} if offered
                                         else {"enum": ["direct", "investigate"]})
        schema["required"] = ["topics", "named", "depth"]
    if scope:                                        # reach well: the stretches the question is about
        from petroharness.agent.selection import RANGE_PATTERN
        typed = [{"type": "string", "pattern": RANGE_PATTERN}] + ([{"enum": list(names)}] if names else [])
        schema["properties"]["scope"] = {"type": "array", "items": {"anyOf": typed}, "maxItems": 8}   # items once each:
        #                                         read_question checks it (uniqueItems would move the server's decoder)
        schema["required"] = schema["required"] + ["scope"]
    return schema


def _reading(text: str, depth: bool = False, outside: bool = False) -> Optional[dict]:
    """The READ reply as {topics, named} (with `depth`: and depth); None when it is not the JSON object the schema asks
    for (topics not one of the areas). Other keys are not read. With `outside` (a request may be outside the well's
    logs) a reply that names no topic is read as it is: the model named none."""
    try:
        obj = json.loads(text or "")
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict) or not isinstance(obj.get("topics"), list):
        return None
    areas = direction.areas()
    topics = list(dict.fromkeys(x for x in obj["topics"] if isinstance(x, str) and x in areas))[:4]
    if not topics and (obj["topics"] or not outside):    # it named things that are no areas, or none where one is due
        return None
    named = obj.get("named")
    got = {"topics": topics,
           "named": [str(x).strip() for x in named if str(x).strip()][:12] if isinstance(named, list) else []}
    if depth:                                            # anything but a clear "direct" is an investigation
        said = str(obj.get("depth", "")).strip().lower()
        got["depth"] = "direct" if said == "direct" else "outside" if outside and said == "outside" else "investigate"
    return got


def read_question(llm: LLM, s: Session, usage: Usage, max_tokens: int, trace: dict) -> None:
    """The READ call, before the first look: one schema-guided call (one retry of the same call when the reply is not
    readable). The model's topics key the first look, the index, the sections a guide opens and the map's notes; no
    readable reply leaves no topics (the general first look, the index in its own order). How the question is read
    is step 1's, with the evidence in view."""
    well = _reach(s) == "well"
    s.ask_user = s.unit_note = ""                    # each question's own (a conversation's session goes on)
    s.unit_facts = []
    s.ask_status, s.ask_choices = "ask_user", []
    say_zones_left(s)                                # said under every question, whatever its scope or reach
    head = (C.text("C5", "read_depth") if s.reads_depth else READ)
    if well:                                     # the stretches the question is about (agent.selection)
        head = _with_scope(head, s)
        if s.reads_depth:                        # a request outside the well's logs (users type anything)
            parts = head.rsplit("\nReply with one JSON object", 1)
            line = C.text("C5", "read_outside").strip()
            head = (parts[0] + "\n" + line + "\nReply with one JSON object" + parts[1] if len(parts) == 2
                    else head + "\n" + line).replace("<direct or investigate>", "<direct, investigate or outside>", 1)
    user = (head
            + f"\n\nQUESTION:\n{s.task.question}\n" + (f"\n{s.earlier}\n" if s.earlier else "")
            + f"\nTHE MAP\n{s.map}\n\nTOPIC AREAS:\n"
            + "\n".join(f"{name} - {a['when']}" for name, a in direction.areas().items()))
    messages = [{"role": "system", "content": brief(s.library, _reach(s))}, {"role": "user", "content": user}]
    got, how, kept = None, "ok", None
    for stage in ("read", "read_retry"):
        text = llm.chat(stage, messages, usage, max_tokens, json_schema=read_schema(
            s.reads_depth, well, tuple(selection_names(s.f)) if well else ()))
        got = _reading(text, s.reads_depth, outside=well and s.reads_depth)
        if got is not None and well and _scope_repeats(text):   # its scope's items are a set, which the schema
            kept, got = kept or (got, text), None                # does not hold (read_schema): asked once more
        if got is not None:
            break
        how = "retry"
    if got is None and kept:                         # repeated again: the first such reply, each item read once
        got, text = kept
    if got is None:
        got, how = {"topics": [], "named": []}, "failed"
    s.reading = got
    s.depth = got.get("depth", "investigate")
    if s.depth == "outside":                         # not about the well: what this assistant does, nothing computed
        from petroharness.agent.selection import interval_name
        s.ask_user, s.ask_status = C.fill("C9", "outside_reply", interval=interval_name(s.f)), "outside"
        s.ask_choices = [{"label": q, "question": q} for q in
                         (x.format(interval=interval_name(s.f)) for x in C.text("C9", "outside_examples"))]
        trace["outside"] = True
    s.choose(got["topics"])
    if well:
        read = _scope_read(text) if how != "failed" else None
        if s.scope_chosen and s.user_scope:           # the user's answer to a question back: this question's stretch,
            trace["scope_chosen"] = list(s.user_scope)   # whatever the READ reads (UI check: a misread unit replaced it)
            read = None
        if s.depth != "outside":
            s.ask_user = "" if s.user_scope else ask_back(s, [s.task.question])     # the user's own words (question
        #   the READ restated the unit the user's answer had resolved, and the question was asked again)
        if s.ask_user:                               # a unit listed more than once: the user chooses (a scope the user
            #                                          set is that choice), nothing read on
            trace["scope"] = {"read": read, "used": [], "note": "", "merged": ""}
            trace["ask_user"] = s.ask_user
            trace["ask_choices"] = list(s.ask_choices)
            read = None
        if read:                                     # the stretches this question names: for this question
            apply_scope(s, read)
            if not s.scope and s.scope_note:         # it named no stretch: asked again once, with the reason (the
                again = llm.chat("read_scope", [messages[0], {"role": "user", "content": user + "\n\n" + C.fill(
                    "C5", "read_scope_again", reason=s.scope_note)}], usage, max_tokens,   # same single-turn prompt)
                    json_schema=read_schema(s.reads_depth, well, tuple(selection_names(s.f))))
                second = _scope_read(again)
                trace["read_scope_again"] = {"reply": (again or "")[:1500], "scope": second, "note": s.scope_note}
                if second:
                    apply_scope(s, second)
                    read = second
            s.scope_by_user = False
            if not s.scope and s.user_scope:         # not usable: the user's scope stays, the reason said
                note = s.scope_note
                apply_scope(s, s.user_scope, "set by the user")
                s.scope_note, s.scope_by_user = note, bool(s.scope)
        elif read is not None and s.user_scope is None:  # none named, no user scope: the interval
            apply_scope(s, [])
        if not s.ask_user:
            trace["scope"] = {"read": read, "used": list(s.scope), "note": s.scope_note, "merged": s.scope_merged,
                              **({"by": "user"} if s.scope_by_user else {}), **({"frame": s.frame} if s.frame else {})}
    trace["read"] = {"reply": (text or "")[:3000], "parse": how, **got}
    trace["topics"] = list(s.topics)


def _with_scope(head: str, s: Session) -> str:
    """The READ text under reach "well": the scope line, before the reply's example, which gains "scope"; the scope
    in force (a conversation's) said when there is one."""
    line = C.text("C5", "read_scope").strip()
    if s.scope:                                      # as a reply's scope can write it (selection.as_written)
        from petroharness.agent.selection import as_written
        line += f" Scope in force: {json.dumps(as_written(s.f, s.scope))}."
    parts = head.rsplit("\nReply with one JSON object", 1)
    head = parts[0] + "\n" + line + "\nReply with one JSON object" + parts[1] if len(parts) == 2 else head + "\n" + line
    return head.replace('"named": ["..."]', '"named": ["..."], "scope": ["..."]', 1)


def _scope_strings(text: str) -> list:
    """The READ reply's scope strings, as written, in order (repeats kept; none when the reply has none)."""
    try:
        obj = json.loads(text or "")
    except json.JSONDecodeError:
        return []
    raw = obj.get("scope") if isinstance(obj, dict) else None
    return [str(x).strip() for x in (raw if isinstance(raw, list) else []) if str(x).strip()]


def _scope_repeats(text: str) -> bool:
    """The READ reply's scope names an item twice (its items are a set)."""
    got = _scope_strings(text)
    return len(got) != len(set(got))


def _scope_read(text: str) -> list:
    """The READ reply's scope: its strings, as written, each once (none when the reply has none)."""
    return list(dict.fromkeys(_scope_strings(text)))[:8]


def selection_names(f: Formation) -> list:
    """The names a READ reply's scope items are typed to (agent.selection.names)."""
    from petroharness.agent.selection import names
    return names(f)


def scope_items(f: Formation, asked) -> list:
    """A scope's items as a selection takes them: "the whole well" (one typed item, selection.WHOLE_WELL_ITEM) as the
    well's span; every other item as written (a user's /scope that names no stretch is refused with the reason)."""
    from petroharness.agent.selection import WHOLE_WELL_ITEM
    span = getattr(f.inv, "well_span", ()) or ()
    items = [str(x).strip() for x in asked or [] if str(x).strip()]
    return [f"{span[0]:g}-{span[1]:g}" if x.lower() == WHOLE_WELL_ITEM and span else x for x in items]


def say_zones_left(s: Session) -> None:
    """The user's zones with no sample here, said under the question (Session.unit_note) and kept as data for the
    answer's reader (Session.unit_facts), under every question while the zones are in force: a question with the
    user's scope, or one about the whole well, skips the question back but not this."""
    left = getattr(s.f.view, "user_zones_left", None) or []
    if not left:
        return
    u = s.f.view.report_unit
    s.unit_note = C.fill("C10", "zones_left_note", items="; ".join(f"{n} {t:g}-{b:g} {u} ({why})" for n, t, b, why in left))
    s.unit_facts = [{"kind": "zones_left", "zones": [{"name": n, "top": t, "base": b, "unit": u, "why": why}
                                                     for n, t, b, why in left]}]


def ask_back(s: Session, texts) -> str:
    """The question back to the user when the question cannot be read as one stretch of the tops file: a unit it lists
    more than once (which one), a unit whose row was left out (the row to fix), a name close to units it lists but
    none of them (did you mean). A name close to none is said under the question (Session.unit_note) and answered as
    absent. "" when the question reads as it is (keep the user in the loop)."""
    from petroharness.agent.selection import left_out_named, shared_names_unread, unit_names_unread
    asked = ask_listed_twice(s, texts)
    if asked:
        return asked
    u = s.f.view.report_unit
    q = s.task.question
    shared = shared_names_unread(s.f, texts)
    if shared:
        name, us = shared[0]
        s.ask_choices = [{"label": f"{x.name} {x.top:g}-{x.base:g} {u}", "question": _named_as(q, name, x.name)} for x in us]
        return C.fill("C9", "ask_which_unit", name=name, n=len(us),
                      listed="; ".join(f"{x.name} {x.top:g}-{x.base:g} {u}" for x in us),
                      example=f"{us[0].top:g}-{us[0].base:g} {u}")
    rows = left_out_named(s.f, texts)
    if rows:
        r = rows[0]
        if r.get("top") is not None and r.get("base") is not None:     # the row's own depths, in order: one choice
            lo, hi = sorted((float(r["top"]), float(r["base"])))
            ru = r.get("unit") or u
            s.ask_choices = [{"label": f"{r['name']} as {lo:g}-{hi:g} {ru} (the row's depths, in order)",
                              "question": q, "scope": [f"{lo:g}-{hi:g} {ru}"]}]
        return C.fill("C9", "ask_left_out", name=r["name"], line=r["line"], why=r["why"], unit=r.get("unit") or u)
    unread = unit_names_unread(s.f, texts)
    close = [(n, c) for n, c in unread if c]
    if close:
        name, cands = close[0]
        units = {x.name: x for x in s.f.view.units}
        ex = units[cands[0]]
        s.ask_choices = [{"label": c, "question": _named_as(q, name, c)} for c in cands]
        return C.fill("C9", "ask_did_you_mean", name=name, candidates=" or ".join(cands),
                      example=f"{ex.top:g}-{ex.base:g} {u}")
    if unread:
        listed = sorted({x.name for x in s.f.view.units}, key=lambda n: min(x.top for x in s.f.view.units if x.name == n))
        s.unit_note = (s.unit_note + "\n" if s.unit_note else "") + C.fill("C10", "absent_unit_note", items="; ".join(n for n, _ in unread),
                             units=", ".join(listed[:UNITS_LISTED]) + (f" and {len(listed) - UNITS_LISTED} more"
                                                                      if len(listed) > UNITS_LISTED else ""))
        s.unit_facts.append({"kind": "absent_unit", "names": [n for n, _ in unread], "units": listed})
    return ""


UNITS_LISTED = 16           # the tops file's units a note names (the rest counted)


def _named_as(question: str, written: str, name: str) -> str:
    """The question with a name as the user wrote it replaced by the one meant (a choice's question to send)."""
    return re.sub(rf"(?<![A-Za-z0-9]){re.escape(written)}(?![A-Za-z0-9])", lambda m: name, question, count=1, flags=re.I)


def ask_listed_twice(s: Session, texts) -> str:
    """The question back to the user when the question (or the scope read from it) names a unit the tops file lists
    more than once: which one, or a fixed tops file (C9 ask_listed_twice); "" otherwise."""
    from petroharness.agent.selection import listed_more_than_once
    found = listed_more_than_once(s.f, texts)
    if not found:
        return ""
    u = s.f.view.report_unit
    listed = "; ".join(f"{name} {len(rows)} times (" + ", ".join(f"line {ln}: {top:g}-{base:g} {u}" for ln, top, base
                                                                in rows) + ")" for name, rows in found)
    name, rows = found[0]
    spans = [f"{top:g}-{base:g} {u}" for _, top, base in rows]
    s.ask_choices = [{"label": f"{name} {sp}", "question": s.task.question, "scope": [sp]} for sp in spans] \
        + [{"label": f"all {len(spans)} of them", "question": s.task.question, "scope": spans}]
    return C.fill("C9", "ask_listed_twice", listed=listed, example=f"{rows[0][1]:g}-{rows[0][2]:g} {u}")


def apply_scope(s: Session, asked, who: str = "read from the question") -> None:
    """The stretches the question is about, as the model read them (READ) or a conversation keeps them: checked as a
    selection (agent.selection.resolve), then every lookup's default zones; "the whole well" is the well's own span.
    One that cannot be used is left out, and step 1 says why (Session.scope_note)."""
    from petroharness.agent import selection
    s.scope, s.scope_note, s.scope_merged = [], "", ""
    items = [str(x).strip() for x in asked or [] if str(x).strip()]
    if not items:
        return
    asked = scope_items(s.f, items)
    merged = []
    try:
        on, _ = selection.resolve(s.f, asked, force=True, notes=merged)   # the union of its items (selection._union)
        used = selection.union_labels(s.f, asked)
    except ToolError as e:
        said, short = str(e), [x if len(x) <= SCOPE_ITEM_CHARS else x[:SCOPE_ITEM_CHARS] + "..." for x in items]
        for x, y in zip(items, short):               # each item said short
            said = said.replace(x, y)
        s.scope_note = f"The scope {who} ({', '.join(short)}) is not used: {said}"
        return
    if merged:                                       # what its items became, said with the scope (or its absence)
        s.scope_merged = (f"The scope {who} ({', '.join(items)}): " + "; ".join(merged)
                          + ("; together they are the interval's own samples" if on is s.f else "") + ".")
    if on is s.f:
        return                                       # the interval's own samples: the interval, not a selection of it
    s.scope = used


def scope_text(s: Session) -> str:
    """The prompt's line of the question's scope (reach well): what every lookup computes on, or why the scope read
    was not used; empty with none."""
    frame = ("FRAME: every lookup reports by the lithology zones (L1..), as the user set it, unless its call gives "
             "\"by\".\n\n" if s.frame == "lithology" else "")
    if s.scope:
        who = "set by the user" if s.scope_by_user else "the stretches this question is about"
        return ((f"{s.scope_note}\n" if s.scope_note else "") + (f"{s.scope_merged}\n" if s.scope_merged else "")
                + f"SCOPE: {', '.join(s.scope)} ({who}): every lookup computes on it unless its call names other zones "
                "(\"ALL\" is every row of it); the record's sections and classes stay the interval's.\n\n" + frame)
    stretch = ""
    if _reach(s) == "well":                          # no scope: the stretch in force is the interval, said every time
        from petroharness.agent.selection import interval_name   # (a scope cleared was kept)
        stretch = (f"SCOPE: none: every lookup computes on the interval the session opened on, {interval_name(s.f)}, "
                   "unless its call names other zones.\n\n")
    return ((f"{s.scope_note}\n\n" if s.scope_note else "") + (f"{s.scope_merged}\n" if s.scope_merged else "")
            + stretch + frame)


def topics_text(s: Session) -> str:
    """Step 1's reminder of the topics the READ call chose (empty when none were read)."""
    if not s.topics:
        return ""
    return "YOUR TOPICS: " + ", ".join(s.topics) + "\n\n"
