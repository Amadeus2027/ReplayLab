import hashlib
from time import perf_counter

from .compiler import compile_video
from .models import origin
from .store import Store, write_json
from .video import acquire, extract_frames


def analyze(store: Store, task_id: str, source: str, start_url: str) -> None:
    path = store.task(task_id)
    timings = {}
    started = perf_counter()
    try:
        origin(start_url)
        store.status(task_id, status="acquiring", error=None)
        stage = perf_counter()
        media = acquire(source, path)
        with media.open("rb") as handle:
            source_hash = hashlib.file_digest(handle, "sha256").hexdigest()
        store.status(task_id, media_path=str(media), media_sha256=source_hash)
        timings["acquire_seconds"] = round(perf_counter() - stage, 3)
        store.status(task_id, status="extracting")
        stage = perf_counter()
        manifest = extract_frames(media, path)
        timings["frames_seconds"] = round(perf_counter() - stage, 3)
        # Save stage outputs before inference; model failures do not discard evidence.
        store.status(task_id, status="compiling")
        stage = perf_counter()
        workflow = compile_video(path, manifest, start_url)
        timings["compile_seconds"] = round(perf_counter() - stage, 3)
        store.save(task_id, workflow)
        store.status(task_id, status="needs_review")
    except Exception as exc:
        store.status(task_id, status="failed", error=str(exc))
        raise
    finally:
        timings["analysis_seconds"] = round(perf_counter() - started, 3)
        write_json(path / "timings.json", timings)
