# song_detector.py
from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from typing import Optional, Dict


@dataclass(frozen=True)
class SongInfo:
    title: str
    artist: str
    source_app: str = ""

    @property
    def key(self) -> str:
        t = (self.title or "").strip()
        a = (self.artist or "").strip()
        if t and a:
            return f"{t} - {a}"
        return t


from song_backends import QQMusicSMTCBackend, QQMusicWindowTitleBackend, BackendResult
from song_stability import SongStabilityFilter


class SongDetector:
    """
    QQ音乐桌面版优先 SongDetector：
    - 后端：SMTC(锁定QQ音乐) + QQMusic(window-title兜底)
    - 并行采样 + 融合滤波
    - status() 输出每个后端 reason，便于 debug 排障
    """

    def __init__(self, poll_hz: float = 2.0):
        self.poll_hz = float(poll_hz)
        self._lock = threading.Lock()
        self._stop = threading.Event()

        self._latest: Optional[SongInfo] = None
        self._status: str = "init"
        self._last_best_title: str = ""
        self._last_candidate_count: int = 0
        self._backend_states: Dict[str, str] = {}

        self._filter = SongStabilityFilter(hold_bad_sec=20.0)
        self._backends = [
            QQMusicSMTCBackend(prefer_keywords=["qqmusic", "qq", "tencent"]),
            QQMusicWindowTitleBackend(),
        ]

        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def close(self):
        self._stop.set()
        try:
            self._thread.join(timeout=1.0)
        except Exception:
            pass

    def latest(self) -> Optional[SongInfo]:
        with self._lock:
            return self._latest

    def status(self) -> str:
        """
        例如：
        accept:SMTC | SMTC=ok | QQMusic(window-title)=empty:no-qqmusic-window
        """
        with self._lock:
            parts = [self._status]
            if self._backend_states:
                for k, v in self._backend_states.items():
                    parts.append(f"{k}={v}")
            return " | ".join(parts)

    def last_best_title(self) -> str:
        with self._lock:
            return self._last_best_title

    def last_candidate_count(self) -> int:
        with self._lock:
            return self._last_candidate_count

    def backend_states(self) -> Dict[str, str]:
        with self._lock:
            return dict(self._backend_states)

    def _set_debug(self, status: str, best_title: str, cand_count: int, states: Dict[str, str]):
        with self._lock:
            self._status = status
            self._last_best_title = best_title
            self._last_candidate_count = int(cand_count)
            self._backend_states = dict(states)

    def _set_latest(self, info: Optional[SongInfo]):
        with self._lock:
            self._latest = info

    def _worker(self):
        try:
            asyncio.run(self._loop())
        except Exception as e:
            self._set_debug(f"crashed:{type(e).__name__}", "", 0, {})

    async def _loop(self):
        interval = max(0.2, 1.0 / max(0.1, self.poll_hz))
        while not self._stop.is_set():
            tasks = [be.poll() for be in self._backends]
            results_list = await asyncio.gather(*tasks, return_exceptions=True)

            results: Dict[str, BackendResult] = {}
            states: Dict[str, str] = {}

            for be, r in zip(self._backends, results_list):
                if isinstance(r, Exception):
                    results[be.name] = BackendResult(None, "", 0, False, f"error:{type(r).__name__}")
                else:
                    results[be.name] = r
                states[be.name] = results[be.name].reason

            self._filter.update_round(results)
            stable = self._filter.latest()

            self._set_latest(stable)
            self._set_debug(
                self._filter.status(),
                self._filter.last_best_title(),
                self._filter.last_candidate_count(),
                states,
            )

            await asyncio.sleep(interval)
