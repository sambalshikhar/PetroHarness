"""petroharness chat: a conversation with one interval of a well, from the terminal.

    petroharness chat --las WELL.las [--formation NAME --tops TOPS.csv | --top D --base D] [--session DIR]
                      [--question "..."]... [--questions-file FILE] [model, settings and skills options as petroharness]
    petroharness chat --resume DIR [--question "..."]...

Questions come from --question (repeatable) and --questions-file (one per line), then from the terminal: type a
question and press Enter; an empty line or Ctrl-D ends the conversation. Answers go to stdout, what was run to stderr.

Commands change the interpretation settings (docs/SESSIONS.md, "Changing a setting"; the well is interpreted again
with them) and the stretches the questions are about ("Changing the scope, the frame or the zones"), from the next
question on:
    /set m=1.8 rw=0.04         a setting's new value (several at once); name=default takes it back to its default
    /scope <unit>, 2900-3000   the stretches the next questions are about (a unit, a depth range, your zones, the
                               whole well) until changed; /scope alone: the interval
    /frame lithology           the next questions report by the lithology zones; /frame zones: by the zones in force
    /zones zones.csv           your zones from the next question (CSV, TSV or Excel); /zones none: the lithology zones
    /settings                  the settings in force and the changes made
The conversation is kept in --session (default ./petroharness-sessions/<LAS name>-<time>): resume it later with --resume.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from petroharness import ask as A
from petroharness.session.conversation import Conversation


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="petroharness chat", formatter_class=argparse.RawDescriptionHelpFormatter,
                                 description="A conversation about one interval of one LAS file: ask, then keep "
                                             "asking; each question reads what the earlier ones opened.")
    ap.add_argument("--las", type=Path, help="the well's LAS file (a new conversation)")
    ap.add_argument("--resume", type=Path, help="the folder of a conversation to go on with")
    ap.add_argument("--session", type=Path, help="the folder a new conversation is kept in (default: "
                                                 "./petroharness-sessions/<LAS name>-<time>)")
    ap.add_argument("--question", action="append", default=[], help="a question (repeatable; asked in order)")
    ap.add_argument("--questions-file", type=Path, help="a text file of questions, one per line")
    ap.add_argument("--no-figures", action="store_true", help="do not draw figures for the answers")
    A.interval_options(ap)
    A.run_options(ap)
    return ap


def _value(text: str):
    """A /set value: a number, on/off, default (back to the default), a pair of numbers (a,b) or the text itself."""
    t = text.strip()
    if t.lower() in ("default", "none"):
        return None
    if t.lower() in ("true", "on", "yes"):
        return True
    if t.lower() in ("false", "off", "no"):
        return False
    if "," in t:
        try:
            return [float(x) for x in t.split(",")]
        except ValueError:
            return t
    try:
        return int(t) if t.lstrip("-").isdigit() else float(t)
    except ValueError:
        return t


def command(c: Conversation, line: str) -> str:
    """A /set or /settings line -> what to print (the change made, or the settings in force)."""
    from petroharness.well.settings import describe
    word, _, rest = line.strip().partition(" ")
    if word == "/settings":
        made = "; ".join(f"before question {x['turn']}: {describe(x['changes'])}" for x in c.changes())
        src = c.sources()
        shown = ", ".join(f"{k}={v}" + (" (field notes)" if src.get(k) == "field notes" else "")
                          for k, v in c.settings.items()) or "Petrophys defaults"
        return f"settings in force: {shown}" + (f"\nchanged {made}" if made else "")
    if word == "/set":
        # name=value pairs; a value may hold a space, quoted or not (bht="110 degC", bht=110 degC): a word with no "="
        # belongs to the value before it
        import shlex
        try:
            words = shlex.split(rest)
        except ValueError:
            words = rest.split()
        pairs = []
        for w in words:
            if "=" in w or not pairs:
                pairs.append(w)
            else:
                pairs[-1] += " " + w
        if not pairs or any("=" not in p for p in pairs):
            return "usage: /set name=value [name=value ...]   (name=default takes a setting back to its default)"
        try:
            made = c.adopt({k.strip(): _value(v) for k, v in (p.split("=", 1) for p in pairs)})
        except ValueError as exc:
            return f"not changed: {exc}"
        return (f"from question {len(c.turns) + 1}: {describe(made)} (the well was interpreted again)" if made
                else "no change: those are the settings in force")
    if word == "/scope":                            # the stretches of the next questions (agent.selection)
        items = [x.strip() for x in rest.split(",") if x.strip()]
        try:
            got = c.set_scope(items)
        except ValueError as exc:
            return f"not changed: {exc}"
        return (f"from question {len(c.turns) + 1}: scope {', '.join(got)}" if got
                else f"from question {len(c.turns) + 1}: scope the interval")
    if word == "/frame":
        try:
            got = c.set_frame(rest.strip() or None)
        except ValueError as exc:
            return f"not changed: {exc}"
        return f"from question {len(c.turns) + 1}: " + ("by the lithology zones" if got else "by the zones in force")
    if word == "/zones":
        try:
            said = c.adopt_zones(rest.strip() if rest.strip() and rest.strip().lower() != "none" else None)
        except (ValueError, OSError) as exc:
            return f"not changed: {exc}"
        return f"from question {len(c.turns) + 1}: {said}"
    return (f"unknown command {word}: /set name=value, /settings, /scope ITEMS, /frame lithology|zones, "
            "/zones FILE|none")


def _say(turn) -> None:
    t = turn.trace
    print(f"\n--- question {turn.number} ({turn.status}; {A._route_text(t)}, "
          f"{t.get('seconds', '?')} s; {turn.folder}) ---", file=sys.stderr)
    print(turn.answer if turn.answer else f"(no answer: {t.get('error', turn.status)})")
    for g in turn.figures:
        print(f"[{g['caption']} -> {turn.folder / g['file']}]")
    sys.stdout.flush()


def main(argv: list | None = None) -> int:
    args = parser().parse_args(argv)
    if bool(args.las) == bool(args.resume):
        print("petroharness chat: give --las (a new conversation) or --resume (an earlier one), not both",
              file=sys.stderr)
        return 2
    asked = list(args.question)
    if args.questions_file:                         # read before a session folder is made
        try:
            asked += [ln.strip() for ln in Path(args.questions_file).read_text(encoding="utf-8").splitlines() if ln.strip()]
        except (OSError, UnicodeDecodeError) as exc:
            print(f"petroharness chat: WHAT: the questions file {args.questions_file} cannot be read "
                  f"({getattr(exc, 'strerror', None) or exc}). FIX: give a text file with one question per line.",
                  file=sys.stderr)
            return 2
    try:
        if args.resume:
            c = Conversation.resume(args.resume, model_url=args.model_url,
                                    direct=False if args.investigate else None)
            print(f"resumed {c.folder}: {len(c.turns)} questions so far", file=sys.stderr)
        else:
            folder = args.session or (Path.cwd() / "petroharness-sessions"
                                      / f"{Path(args.las).stem}-{dt.datetime.now():%Y%m%d-%H%M%S}")
            c = Conversation.start(args.las, folder, formation=args.formation, tops=args.tops, top=args.top,
                                   base=args.base, depth_unit=args.depth_unit, lithology_curve=args.lithology_curve,
                                   formation_lithology=args.formation_lithology, profile=args.profile,
                                   settings=args.settings, skills=args.skills, model_url=args.model_url,
                                   model=args.model, model_card=args.model_card, max_steps=args.max_steps,
                                   figures=not args.no_figures, direct=not args.investigate,
                                   field_notes=args.field_notes, zones=args.zones, zones_sheet=args.zones_sheet)
            print(f"conversation in {c.folder}\n{c.p.las.name}: {A._interval_text(c.p.used)}", file=sys.stderr)
            shown = c.overview()
            if shown is not None:
                print(f"the interval's log display (Petrophys): {shown}", file=sys.stderr)
    except (ValueError, LookupError, OSError) as exc:
        print(f"petroharness chat: {exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:                     # Petrophys could not interpret the LAS
        print(f"petroharness chat: {exc}", file=sys.stderr)
        return 1
    failed = False
    for q in asked:
        if q.startswith("/"):                       # a /set or /settings line among the questions
            print(command(c, q), file=sys.stderr)
            continue
        turn = c.ask(q)
        _say(turn)
        failed = failed or not turn.ok
    if asked and not sys.stdin.isatty():
        return 1 if failed else 0
    while True:                                     # the terminal: one question per line
        try:
            q = input("\nquestion> " if sys.stdin.isatty() else "").strip()
        except EOFError:
            break
        if not q:
            break
        if q.startswith("/"):
            print(command(c, q), file=sys.stderr)
            continue
        turn = c.ask(q)
        _say(turn)
        failed = failed or not turn.ok
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
