# choreo_library.py
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple, List, Iterable


# ============================
# normalization helpers
# ============================

_SPACE_RE = re.compile(r"\s+")
_NON_ALNUM = re.compile(r"[^\w\s]", re.UNICODE)


def normalize_text(s) -> str:
    if s is None:
        return ""
    try:
        s = str(s)
    except Exception:
        return ""
    s = s.lower()
    s = s.replace("_", " ")
    s = _NON_ALNUM.sub(" ", s)
    s = _SPACE_RE.sub(" ", s)
    return s.strip()


def canonical_song_key(title, artist="") -> str:
    t = normalize_text(title)
    a = normalize_text(artist)
    if t and a:
        return f"{t} {a}"
    return t


def extract_bracket_contents(s: str) -> List[str]:
    if not s:
        return []
    out = []
    for m in re.finditer(r"\((.*?)\)|\[(.*?)\]|（(.*?)）", str(s)):
        for g in m.groups():
            if g:
                out.append(g.strip())
    return out


# ============================
# entry data class
# ============================

@dataclass
class ChoreoEntry:

    key: str
    frames_dir: Path
    fps: float = 30.0
    start_offset_sec: float = 0.0


# ============================
# main library class
# ============================

class ChoreographyLibrary:

    def __init__(self):

        self._entries: Dict[str, ChoreoEntry] = {}

        self._aliases: Dict[str, str] = {}

    # ============================================================
    # CRITICAL FIX: add() method (required by main.py and scan)
    # ============================================================

    def add(self, entry: ChoreoEntry):

        try:

            key = canonical_song_key(entry.key)

            if not key:
                print("[ChoreoLib] add skipped empty key")
                return

            entry.key = key

            self._entries[key] = entry

            # auto self-alias
            self._aliases[key] = key

            print(f"[ChoreoLib] added entry: {key}")

        except Exception as e:

            print(f"[ChoreoLib] add failed: {e}")

    # ============================================================
    # match (used by main.py and MatchRules)
    # ============================================================

    def match(self, key: str) -> Optional[ChoreoEntry]:

        if not key:
            return None

        ck = canonical_song_key(key)

        if ck in self._entries:
            return self._entries[ck]

        resolved = self._aliases.get(ck)

        if resolved:
            return self._entries.get(resolved)

        return None

    # ============================================================
    # resolve (advanced fallback match)
    # ============================================================

    def resolve(self, title: str, artist: str = "") -> Tuple[str, Optional[ChoreoEntry]]:

        tried = set()

        primary = canonical_song_key(title, artist)

        if primary:

            tried.add(primary)

            resolved = self._aliases.get(primary, primary)

            entry = self._entries.get(resolved)

            if entry:
                return resolved, entry

        # fallback title-only

        title_only = canonical_song_key(title, "")

        if title_only and title_only not in tried:

            tried.add(title_only)

            resolved = self._aliases.get(title_only, title_only)

            entry = self._entries.get(resolved)

            if entry:
                return resolved, entry

        # bracket fallback

        for b in extract_bracket_contents(title):

            ck = canonical_song_key(b, artist)

            if ck and ck not in tried:

                tried.add(ck)

                resolved = self._aliases.get(ck, ck)

                entry = self._entries.get(resolved)

                if entry:
                    return resolved, entry

            ck2 = canonical_song_key(b, "")

            if ck2 and ck2 not in tried:

                tried.add(ck2)

                resolved = self._aliases.get(ck2, ck2)

                entry = self._entries.get(resolved)

                if entry:
                    return resolved, entry

        return primary, None

    # ============================================================
    # scan assets folder automatically
    # ============================================================

    def scan_assets_for_choreo(
        self,
        root: Path,
        ignore_dirs=None,
        fps_default=30.0,
    ):

        ignore_dirs = ignore_dirs or set()

        root = Path(root)

        if not root.exists():
            print(f"[ChoreoLib] assets dir not found: {root}")
            return

        for d in root.iterdir():

            try:

                if not d.is_dir():
                    continue

                if d.name in ignore_dirs:
                    continue

                frames = (
                    list(d.glob("*.png"))
                    + list(d.glob("*.jpg"))
                    + list(d.glob("*.webp"))
                )

                if len(frames) < 3:
                    continue

                key = normalize_text(d.name)

                entry = ChoreoEntry(
                    key=key,
                    frames_dir=d,
                    fps=fps_default,
                )

                self.add(entry)

            except Exception as e:

                print(f"[ChoreoLib] scan failed: {d} : {e}")

    # ============================================================
    # load alias json
    # ============================================================

    def load_aliases_json(self, path: Path):

        path = Path(path)

        if not path.exists():
            print(f"[ChoreoLib] alias file not found: {path}")
            return

        try:

            with open(path, "r", encoding="utf8") as f:

                data = json.load(f)

        except Exception as e:

            print(f"[ChoreoLib] alias load failed: {e}")
            return

        if not isinstance(data, dict):
            print("[ChoreoLib] alias json invalid format")
            return

        for alias, target in data.items():

            alias_key = canonical_song_key(alias)

            if isinstance(target, str):

                target_key = canonical_song_key(target)

                self._aliases[alias_key] = target_key

            elif isinstance(target, Iterable):

                for t in target:

                    target_key = canonical_song_key(t)

                    self._aliases[target_key] = alias_key

                    self._aliases[alias_key] = target_key

    # ============================================================
    # debug helpers
    # ============================================================

    def all_keys(self) -> List[str]:

        return list(self._entries.keys())

    def alias_count(self) -> int:

        return len(self._aliases)

    def all_entries(self) -> List[ChoreoEntry]:

        return list(self._entries.values())
