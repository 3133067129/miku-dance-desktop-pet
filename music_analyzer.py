import time
import numpy as np
from collections import deque


class MusicState:
    __slots__ = ("in_session", "energy", "energy_smooth", "beat", "bpm", "timestamp")

    def __init__(self):
        self.in_session = False
        self.energy = 0.0
        self.energy_smooth = 0.0
        self.beat = False
        self.bpm = 0.0
        self.timestamp = time.time()


class MusicAnalyzer:
    """
    实时音乐分析（轻量 + 稳定）：
    - 能量门限判定“音乐会话”
    - onset-ish：能量差分 + 自适应阈值 + 最小拍间隔
    - BPM：由拍间隔估计并平滑
    - 支持运行时调参（gate/hold）
    """
    def __init__(
        self,
        samplerate: int,
        energy_smooth_alpha: float,
        music_gate_energy: float,
        music_hold_seconds: float,
        beat_min_interval: float,
        bpm_smooth_alpha: float,
    ):
        self.sr = int(samplerate)
        self.alpha = float(energy_smooth_alpha)
        self.music_gate = float(music_gate_energy)
        self.music_hold = float(music_hold_seconds)
        self.min_interval = float(beat_min_interval)
        self.bpm_alpha = float(bpm_smooth_alpha)

        self.state = MusicState()

        self._last_music_time = 0.0
        self._last_beat_time = 0.0
        self._energy_hist = deque(maxlen=50)
        self._diff_hist = deque(maxlen=50)
        self._intervals = deque(maxlen=10)
        self._bpm_smooth = 0.0
        self._prev_energy = 0.0

    def set_music_gate(self, value: float):
        self.music_gate = float(min(max(value, 0.001), 0.08))

    def set_music_hold(self, value: float):
        self.music_hold = float(min(max(value, 0.2), 8.0))

    @staticmethod
    def _rms(x: np.ndarray) -> float:
        if x.size == 0:
            return 0.0
        x = x.astype(np.float32, copy=False)
        return float(np.sqrt(np.mean(x * x) + 1e-12))

    def update(self, audio_window: np.ndarray) -> MusicState:
        now = time.time()
        self.state.timestamp = now
        self.state.beat = False

        rms = self._rms(audio_window)
        energy = min(rms * 28.0, 1.0)
        self.state.energy = energy

        self.state.energy_smooth = self.alpha * energy + (1.0 - self.alpha) * self.state.energy_smooth

        # 音乐会话判定
        if energy > self.music_gate:
            self._last_music_time = now
            if not self.state.in_session:
                self.state.in_session = True

        if self.state.in_session and (now - self._last_music_time > self.music_hold):
            self.state.in_session = False

        # Beat：能量差分 + 自适应阈值
        self._energy_hist.append(energy)
        diff = max(0.0, energy - self._prev_energy)
        self._prev_energy = energy
        self._diff_hist.append(diff)

        if len(self._energy_hist) < self._energy_hist.maxlen:
            self.state.bpm = self._bpm_smooth
            return self.state

        diff_avg = float(np.mean(self._diff_hist))
        diff_std = float(np.std(self._diff_hist))
        threshold = diff_avg + diff_std * 1.2

        if self.state.in_session:
            if diff > threshold and (now - self._last_beat_time) > self.min_interval:
                self.state.beat = True
                if self._last_beat_time > 0:
                    interval = now - self._last_beat_time
                    if 0.25 <= interval <= 1.2:  # 50~240 BPM
                        self._intervals.append(interval)
                        self._update_bpm()
                self._last_beat_time = now

        self.state.bpm = self._bpm_smooth
        return self.state

    def _update_bpm(self):
        if len(self._intervals) < 4:
            return
        avg = sum(self._intervals) / len(self._intervals)
        bpm = 60.0 / max(avg, 1e-6)

        while bpm < 70:
            bpm *= 2.0
        while bpm > 190:
            bpm *= 0.5

        if self._bpm_smooth <= 0:
            self._bpm_smooth = bpm
        else:
            self._bpm_smooth = self.bpm_alpha * bpm + (1.0 - self.bpm_alpha) * self._bpm_smooth
