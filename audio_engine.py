from __future__ import annotations

import numpy as np
import sounddevice as sd
from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from ring_buffer import RingBuffer
from music_analyzer import MusicAnalyzer, MusicState


class AudioEngine(QObject):
    """
    - 如果 use_loopback=True：尝试 WASAPI loopback（不推荐你当前 VB-Cable 场景）
    - 否则：打开普通输入设备（VB-Cable 的 CABLE Output 或 麦克风）
    - 发出 MusicState + source 字符串
    """
    music_state = pyqtSignal(object, str)  # (MusicState, source)

    def __init__(
        self,
        device_index: int | None,
        samplerate: int,
        channels: int,
        blocksize: int,
        buffer_seconds: float,
        analysis_hz: float,
        analyzer: MusicAnalyzer,
        use_loopback: bool = False,
        source_label: str = "Mic",
        parent=None,
    ):
        super().__init__(parent)

        self.sr = int(samplerate)
        self.channels = int(channels)
        self.blocksize = int(blocksize)
        self.analyzer = analyzer

        self.buffer = RingBuffer(int(self.sr * buffer_seconds))
        self.stream = None

        self.source = str(source_label)

        self._start_stream(device_index=device_index, use_loopback=use_loopback)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._analyze_tick)
        self.timer.start(int(1000 / max(1.0, analysis_hz)))

    def set_gate(self, value: float):
        self.analyzer.set_music_gate(value)

    def set_hold(self, value: float):
        self.analyzer.set_music_hold(value)

    def get_gate(self) -> float:
        return float(self.analyzer.music_gate)

    def get_hold(self) -> float:
        return float(self.analyzer.music_hold)

    def _start_stream(self, device_index: int | None, use_loopback: bool):
        extra = None
        if use_loopback:
            try:
                extra = sd.WasapiSettings(loopback=True)
                self.source = "Loopback"
            except Exception:
                extra = None
                use_loopback = False

        # 读取设备信息，自动对齐 samplerate + channels
        try:
            dev = sd.query_devices(device_index) if device_index is not None else sd.query_devices(kind="input")
            dev_sr = int(float(dev.get("default_samplerate", self.sr) or self.sr))
            max_in = int(dev.get("max_input_channels", 1) or 1)
        except Exception:
            dev_sr = self.sr
            max_in = 1

        # 关键：对齐采样率（VB-Cable 很敏感）
        self.sr = dev_sr

        # 关键：把输入通道限制到 1~2（避免 16ch 全是空/混乱）
        ch = max(1, min(self.channels, max_in, 2))
        self.channels = ch

        self.stream = sd.InputStream(
            device=device_index,
            channels=self.channels,
            samplerate=self.sr,
            blocksize=self.blocksize,
            dtype="float32",
            callback=self._callback,
            extra_settings=extra,
        )
        self.stream.start()

    def _callback(self, indata, frames, time_info, status):
        if indata is None:
            return
        arr = np.asarray(indata, dtype=np.float32)
        if arr.ndim == 2 and arr.shape[1] > 1:
            mono = np.mean(arr, axis=1)
        else:
            mono = arr.reshape(-1)
        self.buffer.write(mono)

    def _analyze_tick(self):
        window = self.buffer.read_last(4096)
        state: MusicState = self.analyzer.update(window)
        self.music_state.emit(state, self.source)

    def close(self):
        if self.timer:
            self.timer.stop()

        if self.stream:
            try:
                self.stream.stop()
            except Exception:
                pass
            try:
                self.stream.close()
            except Exception:
                pass
            self.stream = None
