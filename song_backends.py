# song_backends.py
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Optional, Protocol, Tuple, List


from song_detector import SongInfo


@dataclass(frozen=True)
class BackendResult:
    info: Optional[SongInfo]
    best_title: str
    candidate_count: int
    ok: bool
    reason: str  # ok / empty:... / unavailable:... / error:...


class ISongBackend(Protocol):
    name: str
    async def poll(self) -> BackendResult: ...


# -------------------- SMTC (锁定 QQ音乐) --------------------

class QQMusicSMTCBackend:
    """
    优先从 SMTC 获取 QQ音乐会话的曲目信息。
    - 不只用 current_session，避免被 Edge / 浏览器污染
    - 会枚举 sessions 并按 appid 关键字锁定 QQ音乐
    """
    name = "SMTC"

    def __init__(self, prefer_keywords: Optional[List[str]] = None):
        self._mgr = None
        self.prefer_keywords = [k.lower() for k in (prefer_keywords or ["qqmusic", "qq", "tencent"])]

    async def poll(self) -> BackendResult:
        try:
            from winsdk.windows.media.control import (
                GlobalSystemMediaTransportControlsSessionManager as SM,
            )
        except Exception:
            return BackendResult(None, "", 0, False, "unavailable:missing-winsdk")

        try:
            if self._mgr is None:
                self._mgr = await SM.request_async()

            sessions = list(self._mgr.get_sessions() or [])
            if not sessions:
                return BackendResult(None, "", 0, False, "empty:no-sessions")

            # 1) 优先匹配 QQ音乐 session
            target = None
            target_id = ""
            for s in sessions:
                try:
                    appid = (getattr(s, "source_app_user_model_id", "") or "").lower()
                except Exception:
                    appid = ""
                if appid and any(k in appid for k in self.prefer_keywords):
                    target = s
                    target_id = appid
                    break

            # 2) 找不到就退化 current_session（仍可能被污染，但比完全没有好）
            if target is None:
                target = self._mgr.get_current_session()
                if target is None:
                    return BackendResult(None, "", 0, False, "empty:no-session")
                try:
                    target_id = (getattr(target, "source_app_user_model_id", "") or "")
                except Exception:
                    target_id = ""

            props = await target.try_get_media_properties_async()
            title = (getattr(props, "title", "") or "").strip()
            artist = (getattr(props, "artist", "") or "").strip()

            if not title:
                return BackendResult(None, "", 0, False, "empty:no-title")

            # 用 appid 作为 source_app，debug 里能看出是否真的来自 QQ音乐
            return BackendResult(
                SongInfo(title=title, artist=artist, source_app=target_id or "SMTC"),
                "(SMTC)",
                0,
                True,
                "ok",
            )
        except Exception as e:
            return BackendResult(None, "", 0, False, f"error:{type(e).__name__}")


# -------------------- QQ音乐 Window Title 后端（兜底） --------------------

class QQMusicWindowTitleBackend:
    """
    兜底方案：从 QQ音乐窗口标题解析歌名/歌手
    - 只枚举 QQMusic 进程窗口，避免 Edge/系统窗口污染
    - 强过滤“歌单/推荐/广告/登录”等非歌曲标题
    """
    name = "QQMusic(window-title)"

    # 硬排除：命中直接判定不是“歌曲标题”
    _HARD_BAD = [
        "登录", "注册", "设置", "关于", "帮助", "反馈",
        "推荐", "精选", "首页", "发现", "歌单", "电台", "直播", "视频",
        "mv", "活动", "商城", "会员", "广告", "推广",
        "本地和下载", "下载", "正在下载", "下载管理",
        "听歌识曲",
        "qq音乐", "qqmusic",  # 仅有应用名通常不是曲名
    ]

    # 标题分隔符候选：不同版本可能使用不同符号
    _SEP_PATTERNS = [
        r"\s*-\s*",        # A - B
        r"\s*–\s*",        # A – B
        r"\s*—\s*",        # A — B
        r"\s*\|\s*",       # A | B
        r"\s*·\s*",        # A · B（少见）
    ]

    async def poll(self) -> BackendResult:
        # 依赖检查
        try:
            import win32gui  # type: ignore
            import win32process  # type: ignore
            import psutil  # type: ignore
        except Exception:
            return BackendResult(None, "", 0, False, "unavailable:missing-pywin32/psutil")

        try:
            wins = self._enum_windows_all(win32gui, win32process, psutil)
            # 只保留 QQ音乐进程窗口
            candidates = []
            for w in wins:
                title = (w["title"] or "").strip()
                exe = (w["exe"] or "").lower()
                if not title:
                    continue
                if "qqmusic" in exe or exe == "qqmusic.exe":
                    candidates.append(w)

            if not candidates:
                return BackendResult(None, "", 0, False, "empty:no-qqmusic-window")

            # 对候选进行过滤与评分，选“最像歌曲标题”的那个
            filtered = []
            for w in candidates:
                t = (w["title"] or "").strip()
                if self._is_hard_bad(t):
                    continue
                filtered.append(w)

            if not filtered:
                # 全被过滤，返回一个 best_title 便于你看到“QQ音乐窗口到底在写什么”
                best_any = max(candidates, key=lambda x: (x["visible"], x["w"] * x["h"]))
                return BackendResult(None, best_any["title"].strip(), len(candidates), False, "empty:all-filtered")

            best = max(filtered, key=self._score_window)
            best_title = (best["title"] or "").strip()

            title, artist = self._parse_title_artist(best_title)
            if not title:
                # parse 失败仍给 title=best_title，让上层还能看到并尝试匹配（但 filter 可能会拒绝低质量）
                title = best_title
                artist = ""

            info = SongInfo(title=title, artist=artist, source_app=self.name)
            return BackendResult(info, best_title, len(candidates), True, "ok")
        except Exception as e:
            return BackendResult(None, "", 0, False, f"error:{type(e).__name__}")

    @classmethod
    def _is_hard_bad(cls, s: str) -> bool:
        t = (s or "").strip().lower()
        if not t:
            return True
        # 过短基本不是曲名
        if len(t) <= 3:
            return True
        return any(b.lower() in t for b in cls._HARD_BAD)

    @classmethod
    def _parse_title_artist(cls, s: str) -> Tuple[str, str]:
        s = (s or "").strip()
        if not s:
            return "", ""

        # 常见形式：歌名 - 歌手 / 歌手 - 歌名（不确定）
        # 我们更偏向：title - artist（QQ音乐标题常见）
        for sep in cls._SEP_PATTERNS:
            parts = re.split(sep, s)
            parts = [p.strip() for p in parts if p and p.strip()]
            if len(parts) >= 2:
                # 先按 title - artist 解析
                title = parts[0]
                artist = " - ".join(parts[1:])
                # 如果 artist 太长而 title 很短，反过来试一试
                if len(title) <= 4 and len(artist) >= 6:
                    title2 = parts[-1]
                    artist2 = " - ".join(parts[:-1])
                    return title2, artist2
                return title, artist

        # 找不到分隔符，只能返回整串当 title
        return s, ""

    @classmethod
    def _score_window(cls, w) -> int:
        title = (w["title"] or "").strip()
        t = title.lower()

        score = 0
        if w["visible"]:
            score += 1500

        # 面积权重适中：大窗口更可能是主界面，但不让它压倒一切
        score += (w["w"] * w["h"]) // 1200

        # 有分隔符强加分（更像“歌名-歌手”）
        if any(re.search(sep, title) for sep in cls._SEP_PATTERNS):
            score += 2500

        # 长度合理加分
        if 6 <= len(title) <= 80:
            score += 200

        # 含“QQ音乐”本身扣分（很多页面/标题只显示应用名）
        if "qq音乐" in t or "qqmusic" in t:
            score -= 400

        # 命中硬坏关键词（虽然已过滤，但以防漏网）强扣分
        for b in cls._HARD_BAD:
            if b.lower() in t:
                score -= 5000

        return score

    @staticmethod
    def _enum_windows_all(win32gui, win32process, psutil):
        out = []

        def cb(hwnd, _):
            try:
                title = win32gui.GetWindowText(hwnd) or ""
                if not title:
                    return True
                visible = bool(win32gui.IsWindowVisible(hwnd))
                _, pid = win32process.GetWindowThreadProcessId(hwnd)

                exe = ""
                try:
                    exe = psutil.Process(pid).name()
                except Exception:
                    exe = ""

                l, t, r, b = win32gui.GetWindowRect(hwnd)
                out.append({
                    "hwnd": hwnd,
                    "pid": pid,
                    "exe": exe,
                    "title": title,
                    "visible": visible,
                    "w": max(0, r - l),
                    "h": max(0, b - t),
                })
            except Exception:
                pass
            return True

        win32gui.EnumWindows(cb, None)
        return out
