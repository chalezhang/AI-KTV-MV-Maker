from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path


def probe(path: Path) -> dict:
    cp = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False
    )
    if cp.returncode:
        raise RuntimeError(cp.stderr.strip())
    return json.loads(cp.stdout)


def loudness_for_stream(path: Path, audio_index: int) -> float | None:
    af = "loudnorm=I=-16:TP=-1:LRA=50:print_format=json"
    cp = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-map", f"0:a:{audio_index}", "-af", af, "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False
    )
    text = (cp.stdout or "") + "\n" + (cp.stderr or "")
    m = re.findall(r'\{\s*"input_i".*?\}', text, flags=re.S)
    if not m:
        return None
    try:
        return float(json.loads(m[-1])["input_i"])
    except Exception:
        return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("video")
    parser.add_argument("--loudness", action="store_true", help="同时测量每条音轨 Integrated LUFS")
    args = parser.parse_args()
    path = Path(args.video)
    data = probe(path)
    audio_no = 0
    for s in data.get("streams", []):
        typ = s.get("codec_type")
        if typ not in {"video", "audio"}:
            continue
        tags = s.get("tags") or {}
        title = tags.get("title") or tags.get("handler_name") or "-"
        extra = ""
        if typ == "audio":
            if args.loudness:
                value = loudness_for_stream(path, audio_no)
                extra = f" loudness={value:.2f} LUFS" if value is not None else " loudness=?"
            audio_no += 1
        print(
            f"index={s.get('index')} type={typ} codec={s.get('codec_name')} "
            f"channels={s.get('channels', '-')} title={title}{extra}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
