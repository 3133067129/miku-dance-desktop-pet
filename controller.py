# controller.py
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QSize
from PyQt6.QtGui import QPixmap

from animation_bank import AnimationBank
from choreo_library import ChoreographyLibrary, ChoreoEntry
from choreography_player import ChoreographyPlayer
from music_analyzer import MusicState
from sequence_source import SequenceDiskSource
from song_detector import SongDetector, SongInfo

from match_rules import MatchRules, MatchResult
from choreo_switch_policy import ChoreoSwitchPolicy


@dataclass(frozen=True)
class RenderSnapshot:
    pixmap: QPixmap
    debug_text: str
    follow_clip: str
    frame_index: int


class AppController:
    def __init__(
        self,
        *,
        bank: AnimationBank,
        song_detector: Optional[SongDetector],
        choreo_lib: Optional[ChoreographyLibrary],
        auto_choreo_debounce_sec: float,
        get_gate=None,
        get_hold=None,
    ):
        self.bank = bank
        self.song_detector = song_detector
        self.choreo_lib = choreo_lib

        self._get_gate = get_gate
        self._get_hold = get_hold

        self._music_state = MusicState()
        self._source = "?"

        self._accent_frames_left = 0
        self._beat_flash = 0
        self._current_clip = "idle"
        self._frame_index = 0
        self._scaled_frames: list[QPixmap] = []
        self._last_size: Optional[QSize] = None

        self._seq_source: Optional[SequenceDiskSource] = None
        self._seq_player = ChoreographyPlayer()
        self._seq_fps = 30.0
        self._seq_entry_key = ""
        self._seq_offset_sec = 0.0

        self._match_rules = MatchRules()
        self._switch_policy = ChoreoSwitchPolicy(debounce_sec=auto_choreo_debounce_sec)

        self._fps = 0.0
        self._fps_count = 0
        self._fps_last_t = time.time()

        self._last_match: Optional[MatchResult] = None

    def on_music_state(self, state: MusicState, source: str):
        self._music_state = state
        self._source = source
        if state.beat:
            self._accent_frames_left = 8
            self._beat_flash = 6

    def clear_render_cache_on_resize(self):
        try:
            self.bank.clear_scaled_cache()
        except Exception:
            pass
        if self._seq_source:
            try:
                self._seq_source.clear_cache(keep_images=True)
            except Exception:
                pass

    def toggle_choreo_manual(self):
        if self._seq_player.active:
            self._stop_choreo()
            return
        if not self.song_detector or not self.choreo_lib:
            return
        info = self.song_detector.latest()
        if not info:
            return
        best_title = self.song_detector.last_best_title()
        match = self._match_rules.match(self.choreo_lib, info, best_title)
        self._last_match = match
        if match.entry:
            self._start_choreo(match.entry)

    def close(self):
        self._stop_choreo()

    def render_tick(self, size: QSize) -> RenderSnapshot:
        self._tick_fps()
        self._auto_choreo_tick()

        if self._seq_player.active and self._seq_source:
            pix = self._render_choreo(size)
        else:
            pix = self._render_follow(size)

        dbg = self._format_debug()
        return RenderSnapshot(pix, dbg, self._current_clip, self._frame_index)

    # ---- follow ----
    def _choose_clip_follow_music(self) -> str:
        s = self._music_state
        if self._accent_frames_left > 0:
            return "accent"
        if not s.in_session:
            return "idle"
        bpm = s.bpm
        if bpm <= 0:
            return "dance_mid"
        if bpm < 110:
            return "dance_slow"
        elif bpm < 150:
            return "dance_mid"
        return "dance_fast"

    def _refresh_scaled_frames(self, size: QSize, force: bool):
        if (not force) and (self._last_size is not None) and (size == self._last_size):
            return
        self._last_size = QSize(size)
        self._scaled_frames = self.bank.get_scaled_frames(self._current_clip, size)
        self._frame_index = 0

    def _render_follow(self, size: QSize) -> QPixmap:
        next_clip = self._choose_clip_follow_music()
        if next_clip != self._current_clip:
            self._current_clip = next_clip
            self._refresh_scaled_frames(size, force=True)
        else:
            self._refresh_scaled_frames(size, force=False)

        frames = self._scaled_frames or [QPixmap(max(1, size.width()), max(1, size.height()))]
        pix = frames[self._frame_index % len(frames)]
        self._frame_index += 1

        if self._accent_frames_left > 0:
            self._accent_frames_left -= 1
        if self._beat_flash > 0:
            self._beat_flash -= 1
        return pix

    # ---- choreo ----
    def _render_choreo(self, size: QSize) -> QPixmap:
        assert self._seq_source is not None
        idx = self._seq_player.frame_index(self._seq_fps)
        if self._seq_offset_sec != 0.0:
            idx += int(round(self._seq_offset_sec * self._seq_fps))
        if idx >= self._seq_source.frame_count():
            self._stop_choreo()
            return QPixmap(max(1, size.width()), max(1, size.height()))
        self._frame_index = idx
        return self._seq_source.get_frame(idx, size)

    def _start_choreo(self, entry: ChoreoEntry):
        if self._seq_source:
            try:
                self._seq_source.close()
            except Exception:
                pass
            self._seq_source = None
        self._seq_entry_key = entry.key
        self._seq_fps = float(entry.fps)
        self._seq_offset_sec = float(entry.start_offset_sec)
        self._seq_source = SequenceDiskSource(Path(entry.frames_dir), fps=self._seq_fps)
        self._seq_source.clear_cache(keep_images=True)
        self._seq_player.start()
        self._frame_index = 0

    def _stop_choreo(self):
        if self._seq_player.active:
            self._seq_player.stop()
        if self._seq_source:
            try:
                self._seq_source.close()
            except Exception:
                pass
            self._seq_source = None
        self._seq_entry_key = ""

    # ---- auto switch ----
    def _auto_choreo_tick(self):
        if not self.song_detector or not self.choreo_lib:
            return
        info = self.song_detector.latest()
        if not info:
            return
        best_title = self.song_detector.last_best_title()
        match = self._match_rules.match(self.choreo_lib, info, best_title)
        self._last_match = match

        action = self._switch_policy.decide(
            song_key=info.key,
            title_only=info.title,
            match=match,
            is_in_choreo=self._seq_player.active,
            current_entry_key=self._seq_entry_key,
        )
        if action.kind == "ENTER" and match.entry:
            self._start_choreo(match.entry)
        elif action.kind == "EXIT":
            self._stop_choreo()

    # ---- fps/debug ----
    def _tick_fps(self):
        self._fps_count += 1
        now = time.time()
        if now - self._fps_last_t >= 1.0:
            self._fps = self._fps_count / (now - self._fps_last_t)
            self._fps_count = 0
            self._fps_last_t = now

    def _format_debug(self) -> str:
        s = self._music_state
        bpm = f"{s.bpm:5.1f}" if s.bpm > 0 else "  -- "
        beat = "YES" if s.beat else "no"
        session = "YES" if s.in_session else "no"
        gate = self._get_gate() if callable(self._get_gate) else None
        hold = self._get_hold() if callable(self._get_hold) else None

        mode = "CHOREO" if self._seq_player.active else "Follow"
        t = self._seq_player.elapsed() if self._seq_player.active else 0.0

        song_line = "\nSong: <none>"
        match_line = "\nMatch: <n/a>"
        det_line = "\nDet: <none>"
        best_title_line = ""
        backends_line = ""

        if self.song_detector:
            det_line = f"\nDet: {self.song_detector.status()}  cand={self.song_detector.last_candidate_count()}"
            bt = self.song_detector.last_best_title()
            if bt:
                best_title_line = f"\nBestTitle: {bt}"
            # 额外：显示每个 backend reason（如果 status 已包含也无妨）
            states = self.song_detector.backend_states()
            if states:
                backends_line = "\nBackends: " + " | ".join([f"{k}={v}" for k, v in states.items()])

            info = self.song_detector.latest()
            if info:
                song_line = f"\nSong: {info.title} / {info.artist} ({info.source_app})"
                if self._last_match and self._last_match.entry:
                    match_line = f"\nMatch: YES [{self._last_match.level}] -> {self._last_match.entry.key}"
                elif self._last_match:
                    match_line = f"\nMatch: NO tried={self._last_match.tried[:3]}"

        gate_line = ""
        if gate is not None and hold is not None:
            gate_line = f"\nGate: {float(gate):.3f}  Hold: {float(hold):.1f}s"

        cache_line = ""
        if self._seq_player.active and self._seq_source:
            stt = self._seq_source.stats
            cache_line = f"\nSeq cache img:{stt.image_cache} pix:{stt.pixmap_cache} io:{stt.last_io_ms:.1f}ms"

        return (
            f"Mode: {mode}\n"
            f"Input: {self._source}   FPS: {self._fps:4.0f}\n"
            f"Clip: {self._current_clip}   Frame: {self._frame_index}\n"
            f"Energy: {s.energy:.3f}  Smooth: {s.energy_smooth:.3f}\n"
            f"BPM: {bpm}  InSession: {session}  Beat: {beat}"
            f"{gate_line}\n"
            f"Seq: {self._seq_entry_key or '<none>'}  t={t:.2f}s\n"
            f"F1 Debug | F2 Tuning | F3 Force toggle"
            f"{song_line}{match_line}{det_line}{best_title_line}{backends_line}{cache_line}"
        )
