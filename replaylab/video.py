"""Media adapters: yt-dlp for sources, FFmpeg for sparse and scene-change frames."""

import json
import re
import subprocess
from pathlib import Path

from .models import Frame, origin
from .store import write_json


def command(args: list[str]) -> str:
    result = subprocess.run(args, capture_output=True, text=True, timeout=300)
    if result.returncode:
        raise RuntimeError(f"{args[0]} failed: {result.stderr[-1600:]}")
    return result.stdout


def acquire(source: str, task_dir: Path) -> Path:
    if source.startswith(("http://", "https://")):
        import yt_dlp

        origin(source)
        with yt_dlp.YoutubeDL(
            {
                "outtmpl": str(task_dir / "source.%(ext)s"),
                "format": "best[height<=720]/best",
                "noplaylist": True,
                "quiet": True,
                "socket_timeout": 30,
                "retries": 1,
                "overwrites": False,
            }
        ) as downloader:
            info = downloader.extract_info(source, download=True)
            if info.get("entries") is not None:
                raise ValueError("Playlists are not supported")
            path = Path(downloader.prepare_filename(info))
        if not path.is_file():
            raise FileNotFoundError("Media downloader did not produce a file")
        return path
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
