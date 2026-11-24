# diagnose_song_detector.py
import time
from song_detector import SongDetector

if __name__ == "__main__":
    det = SongDetector(poll_hz=2.0)
    try:
        for _ in range(60):
            info = det.latest()
            print("status:", det.status())
            print("states:", det.backend_states())
            print("best_title:", det.last_best_title())
            print("song:", info)
            print("-" * 60)
            time.sleep(1.0)
    finally:
        det.close()
