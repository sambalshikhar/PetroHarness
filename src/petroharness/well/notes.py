"""Field notes: a team's standing choices for a field or project, as a data file (docs/SESSIONS.md, "Field notes").

    name: North field, 2026 study          # optional: how answers name the notes
    settings:                              # interpretation settings in force from the start (the names
      m: 1.8                               # petroharness.well.settings lists; unset ones keep their defaults)
      rw: 0.04
      sw_cutoff: 0.6
    notes:                                 # optional: standing choices in words, read with every question
      - Report water saturation from the Indonesia model.
      - Call the upper sand the A sand.

The settings are the ones in force when a conversation (or a single question) starts, each marked as coming from the
field notes; settings the user gives at the start take precedence, and a later change is the user's (Conversation.adopt).
The notes reach the model with every question, marked as the user's statement, as the operator's lithology does. A
benchmark run never reads field notes. What is wrong in the file is said per entry, with the fix.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

KEYS = ("name", "settings", "notes")
MAX_NOTES = 20
MAX_NOTE_CHARS = 300


def load(path) -> dict:
    """The field notes in `path` -> {"path", "sha256", "name", "settings", "notes"} (settings checked as the settings
    panel checks them; notes as a list of short sentences). Raises ValueError saying what is wrong and the fix."""
    import yaml
    from petroharness.well import settings as T
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise FileNotFoundError(f"WHAT: no field notes file at {p}. FIX: give the path of a YAML file "
                                "(name, settings, notes; docs/SESSIONS.md).")
    body = p.read_bytes()
    try:
        data = yaml.safe_load(body.decode("utf-8")) or {}
    except (yaml.YAMLError, UnicodeDecodeError) as exc:
        raise ValueError(f"WHAT: the field notes file {p.name} is not readable YAML ({str(exc)[:200]}). FIX: write it "
                         "as name, settings and notes (docs/SESSIONS.md).") from None
    if not isinstance(data, dict):
        raise ValueError(f"WHAT: the field notes file {p.name} is not a table. FIX: give name, settings and notes.")
    unknown = [k for k in data if k not in KEYS]
    if unknown:
        raise ValueError(f"WHAT: the field notes file {p.name} has entries no reader knows: {', '.join(map(str, unknown))}. "
                         f"FIX: use {', '.join(KEYS)}.")
    settings = data.get("settings") or {}
    if not isinstance(settings, dict):
        raise ValueError(f"WHAT: the settings in {p.name} are not a table of setting -> value. FIX: write them as "
                         "'m: 1.8' lines under settings.")
    wrong = T.validate(settings)
    if wrong:
        raise ValueError(f"WHAT: settings in {p.name} that cannot be used: "
                         + "; ".join(f"{k}: {v}" for k, v in wrong.items()) + ". FIX: correct them or take them out.")
    notes = data.get("notes") or []
    notes = [notes] if isinstance(notes, str) else notes
    if not isinstance(notes, list) or not all(isinstance(n, str) and n.strip() for n in notes):
        raise ValueError(f"WHAT: the notes in {p.name} are not a list of sentences. FIX: write each as a '- ...' line "
                         "under notes.")
    if len(notes) > MAX_NOTES or any(len(n) > MAX_NOTE_CHARS for n in notes):
        raise ValueError(f"WHAT: the notes in {p.name} are too long. FIX: at most {MAX_NOTES} notes of "
                         f"{MAX_NOTE_CHARS} characters each; standing values belong under settings.")
    name = str(data.get("name") or p.stem).strip()
    return {"path": str(p), "sha256": hashlib.sha256(body).hexdigest(), "name": name,
            "settings": dict(settings), "notes": [" ".join(n.split()) for n in notes]}


def statement(notes: dict | None) -> str:
    """The notes as they reach the model with each question ("" with none)."""
    lines = (notes or {}).get("notes") or []
    if not lines:
        return ""
    said = " ".join(n if n.endswith((".", "!", "?")) else n + "." for n in lines)
    return f"(The user's field notes for this field, {notes.get('name') or 'unnamed'}: {said})"


def sources(in_force: dict, notes: dict | None, changed: set | None = None) -> dict:
    """{setting: "field notes" | "user"} for the settings in force: a value the field notes set and nobody changed
    is the field notes'; any other is the user's."""
    from_notes = (notes or {}).get("settings") or {}
    return {k: "field notes" if k in from_notes and from_notes[k] == v and k not in (changed or set()) else "user"
            for k, v in (in_force or {}).items()}
