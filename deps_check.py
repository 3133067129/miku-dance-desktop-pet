# deps_check.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple


@dataclass(frozen=True)
class DepStatus:
    ok: bool
    detail: str


def _try_import(mod: str) -> Tuple[bool, str]:
    try:
        __import__(mod)
        return True, "ok"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def check_deps() -> Dict[str, DepStatus]:
    out: Dict[str, DepStatus] = {}

    ok, msg = _try_import("winsdk.windows.media.control")
    out["winsdk(SMTC)"] = DepStatus(ok, msg)

    ok1, msg1 = _try_import("win32gui")
    ok2, msg2 = _try_import("win32process")
    out["pywin32(win32gui)"] = DepStatus(ok1, msg1)
    out["pywin32(win32process)"] = DepStatus(ok2, msg2)

    ok, msg = _try_import("psutil")
    out["psutil"] = DepStatus(ok, msg)

    ok, msg = _try_import("pyaimp")
    out["pyaimp(AIMP remote)"] = DepStatus(ok, msg)

    return out


def format_deps_report() -> str:
    deps = check_deps()
    lines = ["[Deps]"]
    for k, v in deps.items():
        lines.append(f" - {k}: {'OK' if v.ok else 'MISSING'} ({v.detail})")
    return "\n".join(lines)


if __name__ == "__main__":
    print(format_deps_report())
