"""The investigation's state (Session): the map, the ledger, the claims, the question's scope and frame, and how
one action runs on them; the step and size limits."""

from __future__ import annotations

from petroharness.agent.replies import action_text

from dataclasses import dataclass, field
from typing import Optional
from petroharness.agent import direction
from petroharness.agent.claims import Claims
from petroharness.agent.engine import Formation, ToolError
from petroharness.agent.ledger import Ledger, _terms
from petroharness.agent.map import render
from petroharness.agent.toolset import TOOLSET
from petroharness.agent import components as C  # noqa: E402  (the texts: src/petroharness/agent/components)


NEW_CHARS = 12000          # NEW's results at most (about 3k tokens); results beyond come first at the next step (the


#   guides read are not in NEW: they have their own block, GUIDES)
OPENED_CHARS = 6000        # digests of earlier results at most


def opened_chars() -> int:
    """OPENED's budget: OPENED_CHARS."""
    return OPENED_CHARS


ACTIONS = 6                 # lookups per step: the cap and the prompt's stated limit


MAX_GUIDES = 2             # guides read in a step, beside the actions


MAX_CALCS = 3              # calculations in a step, beside the actions


MAX_STEPS = 8


DIRECT_STEPS = 2            # look steps of a direct question


DIRECT_ACTIONS = 4          # lookups in one look step


POLISH_STEPS = 2           # settled and only rephrasing this many steps in a row: converged


# --- the session ----------------------------------------------------------------------------------------------------

@dataclass
class Session:
    task: object
    f: Formation
    map: str
    ledger: Ledger
    claims: Optional[Claims] = None
    points: list = field(default_factory=list)
    intent: str = "characterize"
    guides: list = field(default_factory=list)
    topics: list = field(default_factory=list)       # the topic areas the model chose (READ); empty: none
    families: list = field(default_factory=list)     # the analyzer families those topics read; empty: no scoping
    reading: dict = field(default_factory=dict)      # the READ reply: topics, named
    card: str = ""                                   # the provenance card the writer was shown (its numbers count as shown)
    # the skill library the guides come from (None: none, so no DIRECTION and no guide action); left out, the plugged one
    library: Optional[direction.Library] = field(default_factory=direction.plugged)
    # a conversation on this well and interval (petroharness.session): the question's number in it, where its results
    # start in the ledger, and the earlier questions as the prompts show them ("" for the first question)
    turn: int = 1
    turn_start: int = 0
    earlier: str = ""
    reply: str = "full"       # a later question's answer length, as the model chose in step 1: "brief" or "full"
    # Depth: whether the READ call is asked how much work the question needs (reads_depth: on unless the run asked
    # for the investigation every time, --investigate), how it read this question ("direct": look steps and a
    # short answer), and the results a direct question's look steps were shown (its writer reads them: on a later
    # question they may be an earlier question's)
    reads_depth: bool = False
    depth: str = "investigate"
    scope: list = field(default_factory=list)        # the stretches this question is about (READ, reach well): the
    scope_note: str = ""                             #   default zones of every lookup; why a scope read was not used
    ask_user: str = ""                               # the question back to the user (read.ask_back)
    ask_status: str = "ask_user"                     # its status: ask_user, or outside (a request outside the well's logs)
    ask_choices: list = field(default_factory=list)  # its answers to pick, each {label, question, scope?} (the UI's buttons)
    unit_note: str = ""                              # a unit the question names that the tops file does not have
    unit_facts: list = field(default_factory=list)   # the same notes as data, for the answer's reader (vocabulary.facts)
    scope_merged: str = ""                           # what the scope's items became (one part of another, joined)
    frame: Optional[str] = None                      # "lithology": every lookup reports by the lithology zones
    user_scope: Optional[list] = None                # the user's scope (/scope), in force until the user changes it
    scope_chosen: bool = False                       # the user chose it for this question (an answer to a question back)
    scope_by_user: bool = False                      # this question's scope is the user's (no other stretch named)
    fetched: list = field(default_factory=list)
    # the lines get and find fetched beyond what each result shows ({id: [line]}): kept lines (a list cut at its limit,
    # "the other intervals") and lines read by zone; the writer and the settle step read them with their result
    got: dict = field(default_factory=dict)

    @classmethod
    def build(cls, task, cfg) -> "Session":
        from petroharness.well.view import FormationView
        from petroharness.record.store import build as build_store
        from petroharness.agent.inventory import from_view
        view = FormationView.build(task, cfg)
        store = build_store(view)
        f = Formation(from_view(view, store), view, store)
        s = cls(task, f, render(f.inv), Ledger(f), library=direction.plugged(cfg))
        s.take_user_scope(task)
        return s

    def take_user_scope(self, task) -> None:
        """The scope and frame the user set for this question on (a conversation's /scope, /frame): applied as the
        question starts; None keeps what is in force."""
        self.scope_chosen = bool(getattr(task, "scope_chosen", False))    # this question's stretch, chosen by the user
        if getattr(task, "scope", None) is not None:
            self.user_scope = [str(x) for x in task.scope]
        if self.user_scope is not None:              # the user's scope is the default; a question may name others
            from petroharness.agent.read import apply_scope   # the scope's one rule (agent.read)
            apply_scope(self, self.user_scope, "set by the user")
        self.scope_by_user = bool(self.user_scope) and bool(self.scope)
        if getattr(task, "frame", None) is not None:
            self.frame = None if task.frame in ("", "zones", "none") else task.frame

    def rewell(self, task, cfg, change: str, rezoned: bool = False) -> None:
        """A conversation's settings changed: the well as Petrophys interpreted it again (`task`: the new prepared
        well), read from here on; the ledger goes on and marks what was opened before (Ledger.rewell; rezoned: the
        change cut the zones anew)."""
        from petroharness.well.view import FormationView
        from petroharness.record.store import build as build_store
        from petroharness.agent.inventory import from_view
        view = FormationView.build(task, cfg)
        store = build_store(view)
        self.f = Formation(from_view(view, store), view, store)
        self.ledger.rewell(self.f, change, rezoned)
        self.task = task
        self.map = render(self.f.inv)

    def next_turn(self, task, earlier: str) -> None:
        """A further question of the same conversation: the well, the ledger and its ids stay (results opened before
        are read with get and find, and may be cited); the question's own state (topics, points, claims, guides)
        starts again. `earlier`: the earlier questions and what was found, as the prompts show them."""
        self.task, self.earlier = task, earlier
        self.turn += 1
        self.turn_start = self.ledger.turn_start = len(self.ledger.items)
        self.claims, self.points, self.intent, self.reply = None, [], "characterize", "full"
        self.depth, self.fetched, self.got = "investigate", [], {}
        self.guides, self.topics, self.families, self.reading, self.card = [], [], [], {}, ""
        self.scope, self.scope_note, self.scope_merged, self.scope_by_user = [], "", "", False   # this question's own:
        self.map = render(self.f.inv)                    #   a READ that reads no scope must not keep the last one
        self.take_user_scope(task)

    def choose(self, topics: list) -> None:
        """The topics the model chose: their families, and the map's notes scoped to them."""
        self.topics = list(topics)
        self.families = direction.families(self.topics)
        self.map = render(self.f.inv, self.families)

    def run(self, act: tuple) -> tuple:
        """One action -> (text for NEW, the item it shows whole or None). A call opened before shows its item whole
        again, as does get without find; a guide is read into the guides (Session.guides_text shows it)."""
        if act[0] == "get":
            item = self.ledger.by_id(act[1])
            whole = item is not None and not any(_terms(act[2]))
            self.ledger.take_fetched()                     # only this call's lines
            out = self.ledger.get(act[1], act[2])
            got = self.ledger.take_fetched()
            if not whole:
                self.keep_got(got)
            return out, (item if whole else None)
        if act[0] == "find":
            self.ledger.take_fetched()
            out = self.ledger.find(act[1])
            self.keep_got(self.ledger.take_fetched())
            return out, None
        if act[0] == "calc":
            try:
                item, new = self.ledger.calc(act[1], f"{self.map}\n{self.task.question}")
            except ToolError as e:
                return f"calc not run: {e}", None
            return self.ledger.show(item, new), item
        if act[0] == "guide":
            if self.library is None:                 # no library plugged: no action this harness reads
                return C.fill("C8", "not_run", items=action_text(act), guide=""), None
            name = act[1].strip().lower()
            g = self.library.guide(name, self.f)
            if not g.startswith("no facet") and name not in self.guides:
                self.guides.append(name)
            return f"GUIDE {g}", None
        args = act[2]
        keeps = TOOLSET.stretch(act[1]) != "selection"      # the scope does not apply (Tool.stretch)
        if (self.scope and isinstance(args, dict) and not keeps
                and (not args.get("zones") or _all(args["zones"]))):
            args = {**args, "zones": list(self.scope)}       # the question's scope: every lookup's default zones; ALL is
            #                                                  every row of it (the call names no stretch of its own)
        if self.frame and isinstance(args, dict) and "by" not in args and not keeps:
            args = {**args, "by": self.frame}                # the conversation's frame: by the lithology zones
        try:
            item, new = self.ledger.open(act[1], args)
        except ToolError as e:
            return f"{act[1]} not run: {e}", None
        except Exception as e:                       # never lose the question to one malformed call
            return f"{act[1]} not run: the arguments could not be used ({type(e).__name__}: {str(e)[:120]})", None
        return self.ledger.show(item, new), item

    def keep_got(self, fetched: dict) -> None:
        """The lines a get or find showed that their result's text does not (Session.got), each once, in order; the
        ledger hands them over as data (Ledger.take_fetched)."""
        for eid, lines in fetched.items():
            item = self.ledger.by_id(eid)
            if item is None:
                continue
            shown = set(item.text.splitlines())
            have = self.got.setdefault(eid, [])
            have += [ln for ln in lines if ln not in shown and ln not in have]
            if not have:
                del self.got[eid]

    def guides_text(self, fresh) -> str:
        """GUIDES: every guide read, in the order read; those read at the last step (fresh) in full, the earlier ones
        short (their Compare calls). Empty before any guide is read, and with no library."""
        if self.library is None or not self.guides:
            return ""
        short = [C.fill("C6", "guide_short", name=n, calls="; ".join(self.library.calls(n, self.f)))
                 for n in self.guides if n not in fresh]
        full = [f"GUIDE {self.library.guide(n, self.f)}" for n in self.guides if n in fresh]
        return C.text("C6", "guides_head") + "\n".join(short + full) + "\n\n"

    def read_items(self) -> list:
        """The results the steps and settle list and show: this question's, and the earlier ones it cites
        (own_items); for a conversation's first question, every result."""
        return own_items(self)

    def opened(self, exclude: set) -> str:
        """OPENED: every result listed; digests of earlier ones, newest first, within the budget."""
        items = self.read_items()
        if not items:
            return "(nothing yet)"
        lines, used = ["\n".join(f"  {e.id} {e.call_text()}" for e in items)], 0
        for e in reversed(items):
            if e.id in exclude:
                continue
            d = self.ledger.digest(e)
            if used + len(d) > opened_chars():
                break
            lines.append(d)
            used += len(d)
        return "\n\n".join(lines)


def own_items(s) -> list:
    """The results a question reads: every one for a first question; for a later question of a conversation, its own
    and the earlier ones its claims cite or it fetched whole."""
    items = s.ledger.items
    if getattr(s, "turn", 1) <= 1:
        return items
    claims = getattr(s, "claims", None)
    cited = {x for c in (claims.claims.values() if claims is not None else []) for x in c.ev}
    cited |= set(getattr(s, "fetched", ()))
    return [e for i, e in enumerate(items) if i >= s.turn_start or e.id in cited]


def _all(zones) -> bool:
    """A call's zones that name no stretch of their own: ALL (every zone in view)."""
    items = [zones] if isinstance(zones, str) else list(zones or [])
    return bool(items) and all(str(z).strip().upper() in ("ALL", "ALL ZONES") for z in items)
