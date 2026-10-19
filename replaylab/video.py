"""Media adapters: yt-dlp for sources, FFmpeg for sparse and scene-change frames."""

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from .media import DOWNLOAD_TIMEOUT, MAX_BYTES
from .models import Frame, origin
from .store import write_json


def command(args: list[str]) -> str:
    result = subprocess.run(args, capture_output=True, text=True, timeout=300)
    if result.returncode:
        raise RuntimeError(f"{args[0]} failed: {result.stderr[-1600:]}")
    return result.stdout


def acquire(source: str, task_dir: Path) -> Path:
    if urlsplit(source).scheme in {"http", "https"}:
        origin(source)
        with tempfile.TemporaryDirectory(dir=task_dir, prefix="download-") as temporary:
            result = subprocess.run(
                [sys.executable, "-m", "replaylab.media", source, temporary],
                capture_output=True,
                text=True,
                timeout=DOWNLOAD_TIMEOUT,
            )
            if result.returncode:
                raise ValueError(f"Media acquisition failed: {result.stderr[-1600:]}")
            directory = Path(temporary)
            filename = json.loads((directory / "result.json").read_text())["filename"]
            path = (directory / filename).resolve()
            if not path.is_relative_to(directory.resolve()) or not path.is_file():
                raise ValueError("Invalid downloaded media path")
            if not 0 < path.stat().st_size <= MAX_BYTES:
                raise ValueError("Video exceeds the 200 MB limit or is empty")
            return path.replace(task_dir / f"source{path.suffix}")
    path = Path(source).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Video not found: {path}")
    return path


def extract_frames(media: Path, task_dir: Path, max_frames: int = 32) -> dict:
    metadata = json.loads(
        command(
            [
                "ffprobe",
                "-v",
                "error",
                "-protocol_whitelist",
                "file,pipe",
                "-show_entries",
                "format=duration:stream=codec_type",
                "-of",
                "json",
                str(media),
            ]
        )
    )
    if not any(stream["codec_type"] == "video" for stream in metadata.get("streams", [])):
        raise ValueError("Source has no video stream")
    duration = float(metadata["format"]["duration"])
    if not 0 < duration <= 1800:
        raise ValueError("v0.1 supports videos up to 30 minutes; 30–90 seconds recommended")
    # Reuse FFmpeg's scene detection; sparse coverage remains even without scene cuts.
    sparse_budget = max_frames // 2
    count = min(sparse_budget, max(2, int(duration) + 1))
    sparse = [round(i * max(0, duration - 0.05) / (count - 1), 3) for i in range(count)]
    scan = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-protocol_whitelist",
            "file,pipe",
            "-i",
            str(media),
            "-vf",
            "scale=320:-2,select='gt(scene,0.12)',showinfo",
            "-an",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if scan.returncode:
        raise RuntimeError(f"FFmpeg scene scan failed: {scan.stderr[-1200:]}")
    changes = [float(value) for value in re.findall(r"pts_time:([\d.]+)", scan.stderr)]
    # Include before/after evidence for scene candidates, bounded to control model cost.
    candidates = []
    for timestamp in changes:
        for offset in (-0.25, 0.25):
            value = round(max(0, min(timestamp + offset, duration - 0.01)), 3)
            if all(abs(value - existing) >= 0.2 for existing in sparse + candidates):
                candidates.append(value)
    room = max_frames - len(sparse)
    if len(candidates) > room:
        candidates = [candidates[int(i * len(candidates) / room)] for i in range(room)]
    frame_dir = task_dir / "frames"
    frame_dir.mkdir(exist_ok=True)
    frames = []
    for i, timestamp in enumerate(sorted(set(sparse + candidates))):
        frame_id = f"frame_{i:03d}"
        relative = f"frames/{frame_id}.jpg"
        command(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-ss",
                str(timestamp),
                "-protocol_whitelist",
                "file,pipe",
                "-i",
                str(media),
                "-frames:v",
                "1",
                "-vf",
                "scale=1280:-2",
                "-q:v",
                "3",
                str(task_dir / relative),
            ]
        )
        if not (task_dir / relative).is_file():
            raise RuntimeError(f"No frame at {timestamp}s")
        frames.append(Frame(id=frame_id, timestamp_ms=round(timestamp * 1000), path=relative))
    manifest = {"duration_ms": round(duration * 1000), "frames": [f.model_dump() for f in frames]}
    write_json(task_dir / "frames.json", manifest)
    return manifest
