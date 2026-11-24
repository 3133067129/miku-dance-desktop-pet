from deps_check import format_deps_report
print(format_deps_report())

import sys
from PyQt6.QtWidgets import QApplication

from config import AppConfig
from audio_device import dump_devices, find_vbcable_input_device
from music_analyzer import MusicAnalyzer
from audio_engine import AudioEngine
from animation_bank import AnimationBank
from pet_window import PetWindow

from song_detector import SongDetector
from choreo_library import ChoreographyLibrary, ChoreoEntry
from controller import AppController


def main():
    cfg = AppConfig()
    app = QApplication(sys.argv)

    dump_devices()

    vb_in = find_vbcable_input_device()
    if vb_in is not None:
        device_index = vb_in
        use_loopback = False
        source_label = "VB-Cable"
        print(f"[Audio] Using VB-Cable input device index: {device_index}")
    else:
        device_index = None
        use_loopback = False
        source_label = "Mic(default)"
        print("[Audio] VB-Cable not found. Using default input device.")

    analyzer = MusicAnalyzer(
        samplerate=cfg.samplerate,
        energy_smooth_alpha=cfg.energy_smooth_alpha,
        music_gate_energy=cfg.music_gate_energy,
        music_hold_seconds=cfg.music_hold_seconds,
        beat_min_interval=cfg.beat_min_interval,
        bpm_smooth_alpha=cfg.bpm_smooth_alpha,
    )

    engine = AudioEngine(
        device_index=device_index,
        samplerate=cfg.samplerate,
        channels=cfg.channels,
        blocksize=cfg.blocksize,
        buffer_seconds=cfg.buffer_seconds,
        analysis_hz=cfg.analysis_hz,
        analyzer=analyzer,
        use_loopback=use_loopback,
        source_label=source_label,
    )

    bank = AnimationBank(cfg.assets_dir)

    detector = SongDetector(poll_hz=cfg.song_detect_poll_hz)

    # -------------------------
    # ChoreoLibrary 初始化（这里就是你要加的地方）
    # -------------------------
    lib = ChoreographyLibrary()

    # ✅【新增 1】扫描 assets 下的编舞帧目录，自动注册 entry，并自动加入 alias（world_is_mine -> world is mine）
    lib.scan_assets_for_choreo(
        cfg.assets_dir,
        ignore_dirs={"idle", "dance_fast", "dance_mid", "dance_slow", "accent", "assets"},
        fps_default=30.0,
    )
    print(lib.all_keys())

    # ✅【新增 2】加载你 assets/choreo_aliases.json（你目录里已经有这个文件）
    lib.load_aliases_json(cfg.assets_dir / "choreo_aliases.json")

    # （工程兜底）如果扫描没扫到 world_is_mine（例如帧格式不是 png/jpg/webp 或数量不足），仍然保留你原来的手写 add
    # 这样保证项目可用，不会因为扫描规则而突然 NO
    if lib.match("world is mine") is None:
        lib.add(
            ChoreoEntry(
                key="world is mine",
                frames_dir=cfg.assets_dir / "world_is_mine",
                fps=30.0,
                start_offset_sec=0.0,
            )
        )

    # 可选：启动时打印一下库规模，便于你确认“扫描+alias是否生效”
    try:
        print(f"[ChoreoLib] entries={len(lib.all_entries())} aliases={lib.alias_count()}")
    except Exception:
        pass

    controller = AppController(
        bank=bank,
        song_detector=detector,
        choreo_lib=lib,
        auto_choreo_debounce_sec=cfg.auto_choreo_debounce_sec,
        get_gate=engine.get_gate,
        get_hold=engine.get_hold,
    )

    # AudioEngine -> Controller
    engine.music_state.connect(controller.on_music_state)

    pet = PetWindow(
        controller=controller,
        engine=engine,
        default_size=cfg.default_size,
        target_fps=cfg.target_fps,
    )
    pet.show()

    ret = app.exec()

    try:
        controller.close()
    except Exception:
        pass
    try:
        detector.close()
    except Exception:
        pass
    try:
        engine.close()
    except Exception:
        pass

    sys.exit(ret)


if __name__ == "__main__":
    main()
