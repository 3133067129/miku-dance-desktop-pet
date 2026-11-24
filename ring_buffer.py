import threading
import numpy as np


class RingBuffer:
    """线程安全环形缓冲：存 float32 单声道。"""
    def __init__(self, capacity: int):
        self.capacity = int(capacity)
        self.buf = np.zeros(self.capacity, dtype=np.float32)
        self.write_pos = 0
        self.full = False
        self.lock = threading.Lock()

    def write(self, data: np.ndarray) -> None:
        data = np.asarray(data, dtype=np.float32)
        if data.ndim != 1:
            data = data.reshape(-1)

        n = data.size
        if n <= 0:
            return

        with self.lock:
            if n >= self.capacity:
                self.buf[:] = data[-self.capacity:]
                self.write_pos = 0
                self.full = True
                return

            end = self.write_pos + n
            if end < self.capacity:
                self.buf[self.write_pos:end] = data
            else:
                first = self.capacity - self.write_pos
                self.buf[self.write_pos:] = data[:first]
                self.buf[:end % self.capacity] = data[first:]
            self.write_pos = end % self.capacity
            if self.write_pos == 0:
                self.full = True

    def read_last(self, n: int) -> np.ndarray:
        n = int(n)
        if n <= 0:
            return np.zeros(0, dtype=np.float32)

        with self.lock:
            available = self.capacity if self.full else self.write_pos
            if available <= 0:
                return np.zeros(0, dtype=np.float32)

            n = min(n, available)
            start = (self.write_pos - n) % self.capacity

            if (not self.full) and start < self.write_pos:
                return self.buf[start:self.write_pos].copy()

            if start < self.write_pos:
                return self.buf[start:self.write_pos].copy()
            else:
                return np.concatenate([self.buf[start:], self.buf[:self.write_pos]]).copy()
