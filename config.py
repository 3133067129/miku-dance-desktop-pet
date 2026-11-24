from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppConfig:
    # ===== Audio =====
    samplerate: int = 44100
    channels: int = 2
    blocksize: int = 1024

    buffer_seconds: float = 6.0
    analysis_hz: float = 60.0

    # ===== Music session =====
    music_gate_energy: float = 0.008   # 建议 VB-Cable 用 0.004~0.012 之间调
    music_hold_seconds: float = 2.8
    beat_min_interval: float = 0.22

    # ===== Smoothing =====
    energy_smooth_alpha: float = 0.12
    bpm_smooth_alpha: float = 0.20

    # ===== UI =====
    default_size: int = 300
    target_fps: int = 60

    # ===== Assets =====
    assets_dir: Path = Path("assets")

    # ===== Auto choreography =====
    song_detect_poll_hz: float = 2.0
    auto_choreo_debounce_sec: float = 1.2  # 防抖：避免歌名抖动频繁切换
