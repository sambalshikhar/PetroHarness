"""petroharness chat: a conversation with one interval of a well, from the terminal.

    petroharness chat --las WELL.las [--formation NAME --tops TOPS.csv | --top D --base D] [--session DIR]
                      [--question "..."]... [--questions-file FILE] [model, settings and skills options as petroharness]
    petroharness chat --resume DIR [--question "..."]...

Questions come from --question (repeatable) and --questions-file (one per line), then from the terminal: type a
question and press Enter; an empty line or Ctrl-D ends the conversation. Answers go to stdout, what was run to stderr.
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
                                   figures=not args.no_figures, direct=not args.investigate)
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
    asked = list(args.question)
    if args.questions_file:
        asked += [ln.strip() for ln in Path(args.questions_file).read_text().splitlines() if ln.strip()]
    failed = False
    for q in asked:
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
        turn = c.ask(q)
        _say(turn)
        failed = failed or not turn.ok
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
