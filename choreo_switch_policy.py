# choreo_switch_policy.py
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from match_rules import MatchResult


@dataclass(frozen=True)
class SwitchAction:
    kind: str               # "ENTER" / "EXIT" / "NOOP"
    reason: str


class ChoreoSwitchPolicy:
    """
    自动切编舞策略：
    - 同歌且正在编舞：NOOP
    - 命中编舞：debounce 后 ENTER
    - 未命中：如果正在编舞则 EXIT
    """

    def __init__(self, debounce_sec: float = 1.2):
        self.debounce_sec = float(debounce_sec)

        self._last_song_key = ""
        self._last_song_title = ""
        self._last_switch_t = 0.0

    @staticmethod
    def _norm(s: str) -> str:
        return " ".join((s or "").strip().lower().split())

    def decide(
        self,
        *,
        song_key: str,
        title_only: str,
        match: MatchResult,
        is_in_choreo: bool,
        current_entry_key: str,
    ) -> SwitchAction:
        now = time.time()
        sk = self._norm(song_key)
        tt = self._norm(title_only)
        same_song = (sk == self._last_song_key and tt == self._last_song_title)

        # 更新记忆（无论命中与否都更新）
        self._last_song_key = sk
        self._last_song_title = tt

        # 关键修复：同歌且已编舞 -> 不抖
        if same_song and is_in_choreo:
            return SwitchAction("NOOP", "same-song-in-choreo")

        # 未命中：若在编舞则退出
        if match.entry is None:
            if is_in_choreo:
                return SwitchAction("EXIT", "no-match-exit")
            return SwitchAction("NOOP", "no-match-stay-follow")

        # 命中：debounce
        if (now - self._last_switch_t) < self.debounce_sec:
            return SwitchAction("NOOP", "debounce")

        # 已经是这个 entry：不重启
        if is_in_choreo and self._norm(current_entry_key) == self._norm(match.entry.key):
            return SwitchAction("NOOP", "already-same-entry")

        self._last_switch_t = now
        return SwitchAction("ENTER", f"match-{match.level}")
