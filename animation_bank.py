from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import QSize


@dataclass
class AnimationClip:
    name: str
    frames: List[QPixmap]


class AnimationBank:
    """
    从 assets/<clip_name>/*.png 加载动作集
    并对每个 clip 做“按尺寸缓存缩放帧”，避免每帧 scaled() 吃 CPU。
    """
    def __init__(self, assets_dir: Path):
        self.assets_dir = Path(assets_dir)
        self.clips: Dict[str, AnimationClip] = {}
        self._scaled_cache: Dict[Tuple[str, int, int], List[QPixmap]] = {}

    def load_clip(self, clip_name: str) -> None:
        clip_dir = self.assets_dir / clip_name
        frames: List[QPixmap] = []

        if clip_dir.exists() and clip_dir.is_dir():
            files = sorted([p for p in clip_dir.glob("*.png")])
            for p in files:
                pix = QPixmap(str(p))
                if not pix.isNull():
                    frames.append(pix)

        if not frames:
            frames = [QPixmap(256, 256)]

        self.clips[clip_name] = AnimationClip(clip_name, frames)

    def get_scaled_frames(self, clip_name: str, size: QSize) -> List[QPixmap]:
        if clip_name not in self.clips:
            self.load_clip(clip_name)

        key = (clip_name, size.width(), size.height())
        if key in self._scaled_cache:
            return self._scaled_cache[key]

        base_frames = self.clips[clip_name].frames
        scaled = [f.scaled(size) for f in base_frames]
        self._scaled_cache[key] = scaled
        return scaled

    def clear_scaled_cache(self):
        self._scaled_cache.clear()
