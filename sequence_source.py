from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QImage, QPixmap


@dataclass
class SequenceSourceStats:
    image_cache: int = 0
    pixmap_cache: int = 0
    last_io_ms: float = 0.0


class SequenceDiskSource:
    """
    连续帧磁盘源（World is Mine 用）：
    - 不全量加载
    - UI线程：get_frame() 同步保证当前帧可用（避免黑屏）
    - 后台线程：按 playhead 预取未来帧到 QImage cache
    - QPixmap 的创建/缩放在 UI 线程进行（Qt 推荐）
    """
    def __init__(
        self,
        frames_dir: str | Path,
        fps: float = 30.0,
        *,
        glob_pattern: str = "*.png",
        cache_max_images: int = 260,     # QImage 缓存上限（建议 8~10 秒）
        cache_max_pixmaps: int = 320,    # 已缩放 QPixmap 缓存上限
        window_frames: int = 180,        # 维护的“附近窗口”
        prefetch_ahead: int = 120,       # 预取未来帧数量
        prefetch_sleep: float = 0.002,   # 线程让步
    ):
        self.frames_dir = Path(frames_dir)
        self.fps = float(fps)

        # 构建帧列表（只存路径，不解码）
        self._paths = sorted(self.frames_dir.glob(glob_pattern))
        if not self._paths:
            raise FileNotFoundError(f"No frames found in: {self.frames_dir} (pattern={glob_pattern})")

        self._image_cache: "OrderedDict[int, QImage]" = OrderedDict()
        self._pixmap_cache: "OrderedDict[Tuple[int, int, int], QPixmap]" = OrderedDict()
        self._cache_max_images = int(cache_max_images)
        self._cache_max_pixmaps = int(cache_max_pixmaps)

        self._window_frames = int(window_frames)
        self._prefetch_ahead = int(prefetch_ahead)
        self._prefetch_sleep = float(prefetch_sleep)

        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._center_index = 0

        self.stats = SequenceSourceStats()

        self._worker = threading.Thread(target=self._prefetch_loop, daemon=True)
        self._worker.start()

    def frame_count(self) -> int:
        return len(self._paths)

    def clear_cache(self, *, keep_images: bool = True):
        """窗口大小变动时一般只清 pixmap 缓存。"""
        with self._lock:
            self._pixmap_cache.clear()
            if not keep_images:
                self._image_cache.clear()

    def close(self):
        self._stop.set()

    def update_playhead(self, index: int):
        with self._lock:
            self._center_index = max(0, min(int(index), self.frame_count() - 1))

    def _trim_lru(self):
        while len(self._image_cache) > self._cache_max_images:
            self._image_cache.popitem(last=False)
        while len(self._pixmap_cache) > self._cache_max_pixmaps:
            self._pixmap_cache.popitem(last=False)

        self.stats.image_cache = len(self._image_cache)
        self.stats.pixmap_cache = len(self._pixmap_cache)

    def _load_image_sync(self, index: int) -> QImage:
        t0 = time.perf_counter()
        path = self._paths[index]
        img = QImage(str(path))
        self.stats.last_io_ms = (time.perf_counter() - t0) * 1000.0
        return img if not img.isNull() else QImage()

    def _get_image(self, index: int) -> QImage:
        with self._lock:
            if index in self._image_cache:
                img = self._image_cache.pop(index)
                self._image_cache[index] = img
                return img

        img = self._load_image_sync(index)
        with self._lock:
            self._image_cache[index] = img
            self._trim_lru()
        return img

    def get_frame(self, index: int, target_size: QSize) -> QPixmap:
        """UI线程调用：返回已缩放 pixmap。"""
        w, h = int(target_size.width()), int(target_size.height())
        if w <= 0 or h <= 0:
            w = h = 1

        index = max(0, min(int(index), self.frame_count() - 1))
        key = (index, w, h)

        with self._lock:
            if key in self._pixmap_cache:
                pix = self._pixmap_cache.pop(key)
                self._pixmap_cache[key] = pix
                return pix

        img = self._get_image(index)
        if img.isNull():
            return QPixmap(w, h)

        scaled = img.scaled(
            QSize(w, h),
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        pix = QPixmap.fromImage(scaled)

        with self._lock:
            self._pixmap_cache[key] = pix
            self._trim_lru()

        self.update_playhead(index)  # hint 预取
        return pix

    def _prefetch_loop(self):
        while not self._stop.is_set():
            with self._lock:
                center = self._center_index
                count = self.frame_count()
                half = max(1, self._window_frames // 2)
                start = max(0, center - half)
                end = min(count - 1, center + self._prefetch_ahead)

                want = list(range(center + 1, end + 1))

            did_work = False
            for i in want:
                if self._stop.is_set():
                    break

                with self._lock:
                    if i in self._image_cache:
                        continue

                img = self._load_image_sync(i)
                with self._lock:
                    self._image_cache[i] = img
                    # 丢弃窗口外旧帧（简单有效）
                    for k in list(self._image_cache.keys()):
                        if k < start or k > end:
                            self._image_cache.pop(k, None)
                    self._trim_lru()

                did_work = True
                time.sleep(self._prefetch_sleep)

            if not did_work:
                time.sleep(0.01)
