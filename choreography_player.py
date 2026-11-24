import time


class ChoreographyPlayer:
    """
    整首连续帧播放：
    - start(): 从 0 秒开始计时
    - frame_index(fps): 根据 elapsed 计算应该显示第几帧（从 0 开始）
    """
    def __init__(self):
        self.active = False
        self._t0 = 0.0

    def start(self):
        self.active = True
        self._t0 = time.perf_counter()

    def stop(self):
        self.active = False

    def elapsed(self) -> float:
        if not self.active:
            return 0.0
        return time.perf_counter() - self._t0

    def frame_index(self, fps: float) -> int:
        return int(self.elapsed() * fps)
