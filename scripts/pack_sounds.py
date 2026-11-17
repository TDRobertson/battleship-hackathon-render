"""Pack recorded sound effects into viewer/sounds.js for the 3D viewer.

The viewer synthesises all of its sound by default. To use recordings instead,
put audio files named after the events below in viewer/sounds/ and run this
script from the repository root:

    python scripts/pack_sounds.py

Recognised names (any of .ogg .mp3 .wav .m4a .flac):

    gun    a ship firing
    hit    a shell striking a ship
    miss   a shell landing in the water
    sink   a ship being destroyed

Any event without a file keeps its synthesised sound. Run with --clear to go
back to fully synthesised sound. Only use audio you have the right to
redistribute (CC0 / public domain is simplest) and credit it in the README.
"""
from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVENTS = ("gun", "hit", "miss", "sink")
MIME = {".ogg": "audio/ogg", ".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4", ".flac": "audio/flac"}
HEADER = """/* Optional recorded sound effects for the viewer.
   Leave this empty to use the built-in synthesised sounds.
   To use recordings, put gun / hit / miss / sink audio files in viewer/sounds/
   and run:  python scripts/pack_sounds.py   (see README). */
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pack recorded sound effects into viewer/sounds.js.")
    parser.add_argument("--dir", default=str(ROOT / "viewer" / "sounds"), help="folder holding the audio files")
    parser.add_argument("--out", default=str(ROOT / "viewer" / "sounds.js"))
    parser.add_argument("--clear", action="store_true", help="write an empty sounds.js (synthesised sound only)")
    args = parser.parse_args(argv)

    sounds: dict[str, str] = {}
    folder = Path(args.dir)
    if not args.clear:
        for event in EVENTS:
            matches = [p for p in sorted(folder.glob(f"{event}.*")) if p.suffix.lower() in MIME] if folder.is_dir() else []
            if not matches:
                print(f"{event}: no file, keeping the synthesised sound")
                continue
            path = matches[0]
            data = path.read_bytes()
            sounds[event] = f"data:{MIME[path.suffix.lower()]};base64,{base64.b64encode(data).decode('ascii')}"
            print(f"{event}: {path.name} ({len(data) / 1024:.0f} KB)")
    Path(args.out).write_text(HEADER + f"window.SOUNDS = {json.dumps(sounds)};\n", encoding="utf-8")
    print(f"wrote {args.out} with {len(sounds)} recording(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
