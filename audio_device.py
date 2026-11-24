import sounddevice as sd


def _norm(s: str) -> str:
    return (s or "").lower()


def find_vbcable_input_device() -> int | None:
    """
    查找 VB-Cable 的“录音端口”：通常叫 CABLE Output (VB-Audio Virtual Cable)
    """
    try:
        devices = sd.query_devices()
    except Exception:
        return None

    best = None
    best_score = -1

    for idx, d in enumerate(devices):
        name = _norm(d.get("name", ""))
        max_in = int(d.get("max_input_channels", 0) or 0)
        if max_in <= 0:
            continue

        score = 0
        if "cable output" in name:
            score += 20
        if "vb-audio" in name or "vb audio" in name or "vbaudio" in name:
            score += 6
        if "virtual cable" in name:
            score += 3
        if "cable" in name:
            score += 2

        if score > best_score:
            best_score = score
            best = idx

    return best if best_score >= 12 else None


def dump_devices():
    """
    devices = sd.query_devices()
    print("=== sounddevice devices ===")
    for i, d in enumerate(devices):
        print(
            f"[{i}] {d['name']} | in:{d['max_input_channels']} out:{d['max_output_channels']} "
            f"sr:{d.get('default_samplerate')}"
        )
    print("===========================")
    """
