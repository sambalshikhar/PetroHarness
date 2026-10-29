"""Benchmark tasks as the harness sees them: question, well, formation, LAS path (no reference fields)."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Iterable, Optional

from pydantic import BaseModel


class Task(BaseModel):
    task_id: str          # opaque; carries no reference information
    question: str
    well: str             # LAS stem, e.g. "12_3-4"
    formation: str        # top name as given by the task, e.g. "EXAMPLE FM. TOP"
    las_path: Path
    # Optional explicit interval. When given, no tops table is needed; base None = to the end of the log.
    top: Optional[float] = None
    base: Optional[float] = None
    # Unit of top/base: None = metres; "las" = the LAS file's own depth unit (formation info stated on the log's
    # depth index); or a unit name (m, ft).
    depth_unit: Optional[str] = None
    # A stated base (the formation's base depth) is included; a base that is the next top is not.
    base_closed: bool = False
    # The formation's lithology as the data states it (its tops), when it gives one; the lithology log is read too.
    formation_lithology: Optional[str] = None


def opaque_id(qa_id: str) -> str:
    return "t" + hashlib.sha256(qa_id.encode()).hexdigest()[:10]


def _formation_name(raw) -> str:
    if isinstance(raw, dict):
        return str(raw["name"])
    text = str(raw)
    if text.startswith("{"):
        return str(ast.literal_eval(text)["name"])
    return text


def _formation_depths(raw) -> dict:
    """The interval a formation entry states: {"name", "top", "base"[, "depth_unit"]}, depths in the LAS's own depth
    unit unless depth_unit says otherwise; the base is the formation's own (included). A name alone states none (the
    tops table gives the interval)."""
    if not isinstance(raw, dict) or raw.get("top") is None:
        return {}
    base = raw.get("base")
    return {"top": float(raw["top"]), "base": None if base is None else float(base),
            "depth_unit": raw.get("depth_unit") or "las", "base_closed": base is not None,
            "formation_lithology": (str(raw["lithology"]).strip().upper() or None) if raw.get("lithology") else None}


def load_tasks(
    questions_file: Path,
    las_dir: Path,
    categories: Optional[Iterable[str]] = None,
) -> tuple[list[Task], dict[str, dict]]:
    """Return (tasks, eval_index). eval_index maps task_id -> {qa_id, category} for scoring only."""
    rows = json.loads(Path(questions_file).read_text())
    wanted = set(categories) if categories else None
    tasks: list[Task] = []
    index: dict[str, dict] = {}
    for row in rows:
        if wanted and row["category"] not in wanted:
            continue
        tid = opaque_id(row["qa_id"])
        las_name = Path(row["las_path"]).name
        tasks.append(Task(
            task_id=tid,
            question=row["question"],
            well=Path(las_name).stem,
            formation=_formation_name(row["formation"]),
            las_path=Path(las_dir) / las_name,
            **_formation_depths(row["formation"]),
        ))
        index[tid] = {"qa_id": row["qa_id"], "category": row["category"]}
    return tasks, index
