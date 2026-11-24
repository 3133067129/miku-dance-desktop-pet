# match_rules.py
from __future__ import annotations

import difflib
from dataclasses import dataclass
from typing import List, Optional, Tuple

from choreo_library import (
    ChoreographyLibrary,
    ChoreoEntry,
    canonical_song_key,
    normalize_text,
    extract_bracket_contents,
)


@dataclass(frozen=True)
class MatchResult:
    entry: Optional[ChoreoEntry]
    level: str       # "exact" | "alias" | "fuzzy" | "none"
    score: float
    reason: str
    tried: List[str]


class MatchRules:
    """
    工程化落地版：
    - 生成多候选 canonical keys（title、括号内title、bestTitle解析、title-only）
    - 每个候选都走 exact/alias
    - 最后 fuzzy 扫库
    """

    def __init__(
        self,
        *,
        fuzzy_threshold: float = 0.78,
        fuzzy_threshold_title_only: float = 0.88,
        tried_cap: int = 30,
    ):
        self.fuzzy_threshold = float(fuzzy_threshold)
        self.fuzzy_threshold_title_only = float(fuzzy_threshold_title_only)
        self.tried_cap = int(tried_cap)

    def match(self, lib: ChoreographyLibrary, info, best_title: str = "") -> MatchResult:
        title = getattr(info, "title", "") or ""
        artist = getattr(info, "artist", "") or ""

        tried: List[str] = []
        candidates = self._build_candidates(title, artist, best_title)

        # 1) exact/alias 逐个尝试（优先用最“强信号”的候选）
        for c_title, c_artist, tag in candidates:
            ck = canonical_song_key(c_title, c_artist)
            if not ck:
                continue
            tried.append(f"cand({tag}):{ck}")

            resolved, entry = lib.resolve(c_title, c_artist)
            if entry is not None:
                level = "exact" if resolved == ck else "alias"
                tried.append(f"hit:{level}:{resolved}")
                return MatchResult(entry=entry, level=level, score=1.0, reason=f"resolved:{tag}", tried=tried[: self.tried_cap])

        # 2) fuzzy：先用“最强”的一两个候选做 fuzzy，避免无意义扫多次
        #    优先顺序：括号英文+artist > 原title+artist > best_title派生
        fuzzy_inputs = []
        for c_title, c_artist, tag in candidates:
            ck = canonical_song_key(c_title, c_artist)
            if ck and ck not in fuzzy_inputs:
                fuzzy_inputs.append(ck)
            if len(fuzzy_inputs) >= 3:
                break

        best_entry: Optional[ChoreoEntry] = None
        best_score = 0.0
        best_key = ""
        best_from = ""

        for ck in fuzzy_inputs:
            e, s, k = self._fuzzy_search(lib, ck)
            if s > best_score:
                best_score, best_key, best_entry = s, k, e
                best_from = ck

        if best_entry is not None:
            tried.append(f"fuzzy_from:{best_from}")
            tried.append(f"fuzzy_best:{best_key}={best_score:.3f}")
            if best_score >= self.fuzzy_threshold:
                return MatchResult(best_entry, "fuzzy", best_score, "fuzzy(title+artist)", tried[: self.tried_cap])

        # 3) title-only fuzzy（更严格阈值）
        title_only = canonical_song_key(title, "")
        if title_only:
            e2, s2, k2 = self._fuzzy_search(lib, title_only)
            tried.append(f"title_only:{title_only}")
            tried.append(f"fuzzy_title_best:{k2}={s2:.3f}")
            if e2 is not None and s2 >= self.fuzzy_threshold_title_only:
                return MatchResult(e2, "fuzzy", s2, "fuzzy(title-only)", tried[: self.tried_cap])

        # 4) none
        need = max(self.fuzzy_threshold, self.fuzzy_threshold_title_only)
        return MatchResult(None, "none", best_score, f"no-match best={best_score:.3f} need>={need:.3f}", tried[: self.tried_cap])

    def _build_candidates(self, title: str, artist: str, best_title: str) -> List[Tuple[str, str, str]]:
        """
        生成候选 (title, artist, tag)
        关键：把括号里的英文（World is Mine）作为强候选
        """
        out: List[Tuple[str, str, str]] = []

        # A) 原始（title+artist）
        out.append((title, artist, "raw"))

        # B) 括号内容（可能是英文/罗马字），与 artist 组合（强信号）
        for b in extract_bracket_contents(title):
            out.append((b, artist, "bracket"))

        # C) best_title 里也可能包含括号英文/更完整的串
        if best_title:
            out.append((best_title, artist, "best_title_raw"))
            for b in extract_bracket_contents(best_title):
                out.append((b, artist, "best_title_bracket"))

        # D) title-only（用于命中库中只存 title 的情况）
        out.append((title, "", "title_only"))
        for b in extract_bracket_contents(title):
            out.append((b, "", "bracket_title_only"))

        # 去重：按 canonical 去重，保持顺序
        seen = set()
        dedup: List[Tuple[str, str, str]] = []
        for t, a, tag in out:
            ck = canonical_song_key(t, a)
            if not ck or ck in seen:
                continue
            seen.add(ck)
            dedup.append((t, a, tag))
        return dedup

    def _fuzzy_search(self, lib: ChoreographyLibrary, canon_query: str) -> Tuple[Optional[ChoreoEntry], float, str]:
        if not canon_query:
            return None, 0.0, ""
        q = normalize_text(canon_query)
        best_entry: Optional[ChoreoEntry] = None
        best_score = 0.0
        best_key = ""

        for k in lib.all_keys():
            kk = normalize_text(k)

            s1 = difflib.SequenceMatcher(None, q, kk).ratio()
            s2 = self._token_coverage(q, kk)
            score = 0.78 * s1 + 0.22 * s2

            if score > best_score:
                best_score = score
                best_key = k
                best_entry = lib.match(k)

        return best_entry, float(best_score), best_key

    @staticmethod
    def _token_coverage(a: str, b: str) -> float:
        ta = [t for t in a.split() if t]
        tb = [t for t in b.split() if t]
        if not ta or not tb:
            return 0.0
        sa, sb = set(ta), set(tb)
        inter = len(sa & sb)
        return (2.0 * inter) / (len(sa) + len(sb))
