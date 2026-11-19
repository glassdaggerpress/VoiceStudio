"""Opt-in Automation Central profile: reviewed weights and shared render budget.

The ordinary VoiceStudio application is unchanged unless AC_AUDIO_STUDIO=1.
Audio Studio never uses the legacy audiobook database or its output folders.
"""
from __future__ import annotations

import contextlib
import contextvars
import json
import os
import subprocess
import threading
import time
from pathlib import Path

VOICE_MODELS = {
    "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit",
    "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-bf16",
    "mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-4bit",
}
ASR_MODELS = {"Systran/faster-whisper-small"}
ALLOWED_MODELS = VOICE_MODELS | ASR_MODELS
_owned = contextvars.ContextVar("ac_audio_lease", default=False)


def enabled() -> bool:
    return os.environ.get("AC_AUDIO_STUDIO") == "1"


def require_model(repo: str) -> str:
    if enabled() and repo not in ALLOWED_MODELS:
        raise ValueError("This model has not been approved for commercial Audio Studio use.")
    if enabled():
        ledger = json.loads((Path(__file__).resolve().parents[1] / "config/ac_commercial_models.json").read_text())
        reviewed = {row["id"]: row["revision"] for row in ledger["models"]}
        from services.hf_revisions import revision_for
        if revision_for(repo) != reviewed.get(repo):
            raise ValueError("The installed model revision has not been reviewed for commercial use.")
    return repo


def review_overlay(registry: dict) -> dict:
    """Disclose the narrow model-licence review without claiming input clearance."""
    if not enabled():
        return registry
    ledger = json.loads((Path(__file__).resolve().parents[1] / "config/ac_commercial_models.json").read_text())
    rows = {row["id"]: row for row in registry["models"]}
    for review in ledger["models"]:
        repo = review["id"]
        if repo not in ALLOWED_MODELS:
            continue
        row = rows.get(repo)
        if row is None:
            row = {"id": repo, "license": review["license"], "credit": repo,
                   "source_url": "https://huggingface.co/" + repo,
                   "evidence_url": review["documents"][0]["url"],
                   "revision": review["revision"], "runtime_revision": review["revision"],
                   "runtime_pin_scope": "central", "engines": ["mlx-audio"]}
            registry["models"].append(row)
        row.update(commercial_use=True, review_status="reviewed_model_licence",
                   commercial_inference="permitted", commercial_outputs="permitted",
                   notes="Audio Studio reviewed the published model licence at this pinned revision. No separate noncommercial output restriction was found. Input voice/recording rights remain separate. Preserve licence and attribution notices when redistributing weights. Evidence: ac_commercial_models.json.")
    return registry


def audiobook_active() -> bool:
    runtime = Path.home() / "Library/Application Support/GlassDagger/VoiceStudio"
    try:
        result = subprocess.run(
            ["pgrep", "-f", str(runtime) + r"/(book_)?render.py"],
            capture_output=True, timeout=5,
        )
        return result.returncode != 1
    except (OSError, subprocess.SubprocessError):
        return True


def lock_path() -> Path:
    return Path(os.environ["AC_AUDIO_RENDER_LOCK"])


def status() -> dict:
    import psutil
    import fcntl
    path = lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    busy = False
    with path.open("a+") as probe:
        try:
            fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(probe, fcntl.LOCK_UN)
        except BlockingIOError:
            busy = True
    return {
        "profile": "audio-studio",
        "audiobook_active": audiobook_active(),
        "available_gb": round(psutil.virtual_memory().available / 1024**3, 1),
        "single_engine": True,
        "busy": busy,
        "background_separation": False,
        "models": sorted(ALLOWED_MODELS),
    }


def _native_busy() -> bool:
    from services import model_manager as mm, tts_backend
    stats = mm._get_gpu_pool().stats()
    with tts_backend._ENGINE_CACHE_LOCK:
        engine_busy = any(tts_backend._ENGINE_IN_USE.values())
    return bool(stats["running"] or stats["queued"] or engine_busy)


def _release(lease) -> None:
    """A disconnected HTTP client does not mean its native GPU work stopped."""
    import fcntl
    try:
        while _native_busy():
            time.sleep(0.2)
        from services.tts_backend import release_idle_engines, reset_active_backend
        release_idle_engines(0)
        reset_active_backend()
        import mlx.core as mx
        mx.clear_cache()
    finally:
        fcntl.flock(lease, fcntl.LOCK_UN)
        lease.close()


@contextlib.contextmanager
def resource_lease():
    """Hold across a full stream/task, including cleanup; reject overlapping work."""
    if not enabled() or _owned.get():
        yield
        return
    import fcntl
    import psutil
    from fastapi import HTTPException

    if audiobook_active():
        raise HTTPException(409, "An audiobook is generating. Pause it in Audiobooks before using VoiceStudio.")
    path = lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lease = path.open("a+")
    transferred = False
    try:
        try:
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise HTTPException(409, "Another audio job is running. Wait for it to finish.") from None
        try:
            if psutil.virtual_memory().available < 6 * 1024**3:
                raise HTTPException(409, "VoiceStudio needs 6 GB of available memory. Finish another task or close an app, then retry.")
            import mlx.core as mx
            mx.set_memory_limit(6 * 1024**3)
            mx.set_cache_limit(256 * 1024**2)
            token = _owned.set(True)
            try:
                yield
            finally:
                _owned.reset(token)
                # Retain the cross-process lease until native work and cleanup finish,
                # even when its streaming HTTP request has disconnected.
                transferred = True
                if _native_busy():
                    threading.Thread(target=_release, args=(lease,), daemon=True).start()
                else:
                    _release(lease)
        finally:
            if not transferred:
                fcntl.flock(lease, fcntl.LOCK_UN)
    finally:
        if not transferred:
            lease.close()


class AudioStudioMiddleware:
    """Keep disabled features and unreviewed engine downloads out of the AC profile."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if not enabled() or scope["type"] not in {"http", "websocket"}:
            return await self.app(scope, receive, send)
        from fastapi import HTTPException
        from starlette.responses import JSONResponse
        path = scope.get("path", "")
        if scope["type"] == "websocket":
            if path in {"/ws", "/ws/events"}:
                return await self.app(scope, receive, send)
            # The embedded studio uses HTTP/SSE, never hidden live microphone/TTS sessions.
            await send({"type": "websocket.close", "code": 1008})
            return
        if path == "/ac/status":
            return await JSONResponse(status())(scope, receive, send)
        disabled = ("/audiobook", "/stories", "/batch", "/workflows", "/calls", "/sfx", "/marketplace", "/watermark/detect", "/watermark/settings", "/mcp", "/capture", "/dictation", "/voice-convert", "/v1/audio/transcriptions", "/setup/warmup")
        if path == "/model/load" or path.startswith(disabled) or ("/engines/" in path and path.endswith(("/install", "/repair", "/local-model", "/local-model/discover"))):
            return await JSONResponse({"detail": "This feature is not included in Audio Studio."}, 403)(scope, receive, send)
        direct = path in {"/generate", "/v1/audio/speech", "/dub/translate", "/dub/agent-fit", "/model/load"} or path.startswith(("/dub/transcribe-stream/", "/dub/transcribe/", "/dub/preview-segment/"))
        try:
            if direct:
                with resource_lease():
                    return await self.app(scope, receive, send)
            return await self.app(scope, receive, send)
        except HTTPException as exc:
            return await JSONResponse({"detail": exc.detail}, exc.status_code)(scope, receive, send)
