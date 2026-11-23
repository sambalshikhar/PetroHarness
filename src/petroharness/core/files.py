"""Files written whole, so that no reader sees one cut short."""
from __future__ import annotations

import os
import threading
from pathlib import Path


def write_atomic(path, data) -> None:
    """Write `data` (bytes, or text as UTF-8) to `path` whole: it is written aside in the same folder and moved into
    place (os.replace), so a reader never sees a partial file, and a process killed while writing leaves the earlier
    file (or none) under the name. Each thread writes aside under its own name (`.NAME.<pid>.<thread>.tmp`)."""
    path = Path(path)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)
    os.replace(tmp, path)
