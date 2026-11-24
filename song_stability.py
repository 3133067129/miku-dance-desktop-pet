# song_stability.py
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, Optional

from song_detector import SongInfo
from song_backends import BackendResult


@dataclass
class BackendSnapshot:
    ts: float
    result: BackendResult


class SongStabilityFilter:
    """
    QQ音乐优先稳定滤波：
    - 跨后端融合评分：SMTC > QQMusic(window-title)
    - 拒绝明显非歌曲标题（防止应用名/页面名污染）
    - hold：短时间拿不到也保持上次稳定值，避免抖动
    """

    _HARD_BAD = [
        "qq音乐", "qqmusic",
        "登录", "设置", "推荐", "歌单", "电台", "直播", "视频", "活动", "广告", "会员",
        "下载", "本地和下载", "下载管理", "听歌识曲",
    ]

    def __init__(self, hold_bad_sec: float = 20.0):
        self.hold_bad_sec = float(hold_bad_sec)
        self._stable: Optional[SongInfo] = None
        self._stable_score: int = -10_000
        self._stable_t: float = 0.0

        self._status: str = "init"
        self._snapshots: Dict[str, BackendSnapshot] = {}

        self._last_best_title: str = ""
        self._last_candidate_count: int = 0

    def status(self) -> str:
        return self._status

    def latest(self) -> Optional[SongInfo]:
        now = time.time()
        if self._stable and (now - self._stable_t) <= self.hold_bad_sec:
            return self._stable
        return None

    def last_best_title(self) -> str:
        return self._last_best_title

    def last_candidate_count(self) -> int:
        return self._last_candidate_count

    def update_round(self, results: Dict[str, BackendResult]) -> None:
        now = time.time()
        for name, res in results.items():
            self._snapshots[name] = BackendSnapshot(ts=now, result=res)

        best_info: Optional[SongInfo] = None
        best_score = -10_000
        best_res: Optional[BackendResult] = None
        best_name = ""

        for name, res in results.items():
            score = self._score(name, res)
            if score > best_score:
                best_score = score
                best_info = res.info
                best_res = res
                best_name = name

        if best_res:
            self._last_best_title = best_res.best_title or ""
            self._last_candidate_count = int(best_res.candidate_count)

        if best_info is None or best_score < 0:
            self._status = "all-empty/low-quality"
            return

        if (self._stable is None) or (best_score > self._stable_score) or (now - self._stable_t > 2.0):
            self._stable = best_info
            self._stable_score = best_score
            self._stable_t = now
            self._status = f"accept:{best_name}"
        else:
            self._status = "keep"

    @classmethod
    def _is_hard_bad(cls, s: str) -> bool:
        t = (s or "").strip().lower()
        if not t:
            return True
        if len(t) <= 3:
            return True
        return any(b.lower() in t for b in cls._HARD_BAD)

    def _score(self, backend_name: str, res: BackendResult) -> int:
        if not res.ok or res.info is None:
            return -10_000

        info = res.info
        title = (info.title or "").strip()
        bt = (res.best_title or "").strip()

        # 明显垃圾标题直接拒绝
        if self._is_hard_bad(title) or self._is_hard_bad(bt):
            return -10_000

        score = 0

        # 后端优先级：SMTC 最高（稳定且不受最小化影响）
        if backend_name == "SMTC":
            score += 10000
        elif "QQMusic(window-title)" in backend_name:
            score += 7000
        else:
            score += 5000

        # 信息完整度
        if title:
            score += 100
        if " - " in title or "|" in title or "—" in title or "–" in title:
            score += 120

        # 窗口标题兜底如果没有分隔符，适当扣分（避免页面名）
        if "window-title" in backend_name and not ((" - " in title) or ("|" in title) or ("—" in title) or ("–" in title)):
            score -= 200

        return score
