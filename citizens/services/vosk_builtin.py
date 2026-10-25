# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Vosk inside the app container (0.8): the patched websocket server of
scripts/vosk/asr_server.py, run in a thread of this process on a loopback
socket, so the live and final Vosk clients keep speaking the protocol they
always spoke — only the address changes (provider_config.BUILTIN_VOSK_URL).

Models come from Settings (services/vosk_models.py) under the persistent
volume. Loaded once per path and shared by every connection, bounded and
idle-evicted as in the server script; a model that would not fit the
container's memory is refused with a clear error rather than taking the app
down with it.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import os
import threading
import time
from collections import OrderedDict
from pathlib import Path

from citizens.logging_setup import get_logger

log = get_logger(__name__)

HOST = "127.0.0.1"
PORT = 2700
SAMPLE_RATE = 16000.0
#: languages live at once, not a memory budget: idle eviction reclaims memory
CACHE_SIZE = int(os.environ.get("VOSK_MODEL_CACHE", 2))
IDLE_SECONDS = float(os.environ.get("VOSK_MODEL_IDLE_SECONDS", 1800))
SWEEP_SECONDS = 60.0
#: a loaded model takes roughly this much more memory than its files
MEMORY_FACTOR = 1.3
EOF_MESSAGE = '{"eof" : 1}'
RESET_MESSAGE = '{"reset" : 1}'


def directory_bytes(path: str | Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.stat(os.path.join(root, name)).st_size
            except OSError:
                continue
    return total


def memory_available() -> int | None:
    """Bytes this container may still use: the cgroup limit minus the
    current usage (v2), else the host's available memory. None when nothing
    can be read — then nothing is refused."""
    try:
        limit = Path("/sys/fs/cgroup/memory.max").read_text().strip()
        current = int(Path("/sys/fs/cgroup/memory.current").read_text().strip())
        if limit != "max":
            return max(0, int(limit) - current)
    except (OSError, ValueError):
        pass
    try:
        return os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
    except (ValueError, OSError, AttributeError):
        return None


class ModelTooLarge(Exception):
    pass


class BuiltinVoskServer:
    """One per process. start() is idempotent; stop() closes the socket and
    forgets every loaded model."""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop: asyncio.Event | None = None
        self._ready = threading.Event()
        self._models: OrderedDict[str, object] = OrderedDict()
        self._users: dict[str, int] = {}
        self._idle_since: dict[str, float] = {}
        self._lock: asyncio.Lock | None = None
        self._pool: concurrent.futures.ThreadPoolExecutor | None = None
        self.models_dir: str = ""
        self.port = PORT
        self.started_at: float | None = None
        self.last_error: str = ""

    # ---- lifecycle ---------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and self._ready.is_set()

    def start(self, models_dir: str, port: int = PORT) -> bool:
        if self.running:
            return True
        try:
            import vosk  # noqa: F401  — the wheel is optional at import time
        except ImportError:
            self.last_error = "the vosk package is not installed in this image"
            log.error("vosk_builtin_unavailable")
            return False
        self.models_dir = models_dir
        self.port = port
        self._ready.clear()
        self._thread = threading.Thread(target=self._run, name="vosk-builtin", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=10):
            self.last_error = "the built-in engine did not start in time"
            log.error("vosk_builtin_start_timeout")
            return False
        self.started_at = time.time()
        self.last_error = ""
        log.info("vosk_builtin_started", port=port, models_dir=models_dir)
        return True

    def stop(self) -> None:
        loop, stop = self._loop, self._stop
        if loop is not None and stop is not None and self._thread and self._thread.is_alive():
            loop.call_soon_threadsafe(stop.set)
            self._thread.join(timeout=10)
        self._thread = None
        self._loop = None
        self._stop = None
        self._ready.clear()
        self._models.clear()
        self._users.clear()
        self._idle_since.clear()
        self.started_at = None
        log.info("vosk_builtin_stopped")

    def status(self) -> dict:
        return {
            "running": self.running,
            "port": self.port,
            "loaded": sorted(Path(p).name for p in self._models),
            "in_use": {Path(p).name: n for p, n in self._users.items() if n},
            "last_error": self.last_error,
            "memory_available_bytes": memory_available(),
        }

    def default_model_path(self) -> str | None:
        """The first usable model directory, by name."""
        try:
            for child in sorted(Path(self.models_dir).iterdir()):
                if child.is_dir() and (child / "am").exists() and (child / "conf").exists():
                    return str(child)
        except OSError:
            pass
        return None

    def in_use(self, model_name: str) -> bool:
        return any(Path(p).name == model_name and n for p, n in self._users.items())

    def _run(self) -> None:
        try:
            asyncio.run(self._serve())
        except Exception:
            log.error("vosk_builtin_crashed", exc_info=True)
            self.last_error = "the built-in engine stopped unexpectedly"
        finally:
            self._ready.clear()

    async def _serve(self) -> None:
        import websockets

        self._loop = asyncio.get_running_loop()
        self._stop = asyncio.Event()
        self._lock = asyncio.Lock()
        self._pool = concurrent.futures.ThreadPoolExecutor(max(1, (os.cpu_count() or 2) - 1))
        async with websockets.serve(self._recognize, HOST, self.port, max_size=None):
            self._ready.set()
            sweeper = asyncio.create_task(self._sweep_idle())
            await self._stop.wait()
            sweeper.cancel()
        self._pool.shutdown(wait=False)

    # ---- models ------------------------------------------------------------

    async def _load_model(self, path: str):
        from vosk import Model

        assert self._lock is not None and self._loop is not None
        async with self._lock:
            if path in self._models:
                self._models.move_to_end(path)
            else:
                if not os.path.isdir(path):
                    raise FileNotFoundError(path)
                need = int(directory_bytes(path) * MEMORY_FACTOR)
                available = memory_available()
                if available is not None and need > available:
                    raise ModelTooLarge(
                        f"{Path(path).name} needs about {need // (1024 * 1024)} MB, "
                        f"{available // (1024 * 1024)} MB are free in this container"
                    )
                log.info("vosk_builtin_loading", model=Path(path).name, bytes=need)
                self._models[path] = await self._loop.run_in_executor(None, Model, path)
                log.info("vosk_builtin_loaded", model=Path(path).name)
                self._evict_locked(keep=path)
            self._users[path] = self._users.get(path, 0) + 1
            self._idle_since.pop(path, None)
            return self._models[path]

    async def _release_model(self, path: str | None) -> None:
        if not path or self._lock is None:
            return
        async with self._lock:
            remaining = self._users.get(path, 1) - 1
            if remaining > 0:
                self._users[path] = remaining
            else:
                self._users.pop(path, None)
                self._idle_since[path] = time.monotonic()

    def _evict_locked(self, keep: str | None = None) -> None:
        for path in list(self._models):
            if len(self._models) <= max(CACHE_SIZE, 1):
                return
            if path == keep or self._users.get(path):
                continue
            self._models.pop(path, None)
            self._idle_since.pop(path, None)
            log.info("vosk_builtin_unloaded", model=Path(path).name, why="cache")

    async def _sweep_idle(self) -> None:
        assert self._lock is not None
        while True:
            await asyncio.sleep(SWEEP_SECONDS)
            now = time.monotonic()
            async with self._lock:
                for path, since in list(self._idle_since.items()):
                    if self._users.get(path) or now - since < IDLE_SECONDS:
                        continue
                    self._models.pop(path, None)
                    self._idle_since.pop(path, None)
                    log.info("vosk_builtin_unloaded", model=Path(path).name, why="idle")

    # ---- one connection ----------------------------------------------------

    async def _recognize(self, websocket) -> None:
        from vosk import KaldiRecognizer
        from websockets.exceptions import ConnectionClosed

        assert self._loop is not None and self._pool is not None
        rec = None
        sample_rate = SAMPLE_RATE
        show_words = True
        max_alternatives = 0
        conn_model = None
        conn_path: str | None = None
        model_changed = False
        try:
            while True:
                message = await websocket.recv()
                if isinstance(message, str) and "config" in message:
                    config = json.loads(message).get("config") or {}
                    if "sample_rate" in config:
                        sample_rate = float(config["sample_rate"])
                    if "model" in config:
                        previous = conn_path
                        conn_path = str(config["model"])
                        try:
                            conn_model = await self._load_model(conn_path)
                        except ModelTooLarge as exc:
                            log.warning("vosk_builtin_model_refused", error=str(exc))
                            await websocket.send(json.dumps({"error": str(exc)}))
                            conn_path = previous
                            return
                        except FileNotFoundError:
                            await websocket.send(json.dumps({"error": f"no such model: {conn_path}"}))
                            conn_path = previous
                            return
                        if previous and previous != conn_path:
                            await self._release_model(previous)
                        model_changed = True
                    if "words" in config:
                        show_words = bool(config["words"])
                    if "max_alternatives" in config:
                        max_alternatives = int(config["max_alternatives"])
                    continue
                if rec is None or model_changed:
                    model_changed = False
                    if conn_model is None:
                        # no model named (the Settings "Test" probe, a client
                        # before 0.7): the first installed model, as the
                        # server script falls back to its default directory
                        default = self.default_model_path()
                        if default is None:
                            await websocket.send(json.dumps({"error": "no model installed"}))
                            return
                        try:
                            conn_model = await self._load_model(default)
                        except (ModelTooLarge, FileNotFoundError) as exc:
                            await websocket.send(json.dumps({"error": str(exc)}))
                            return
                        conn_path = default
                    rec = KaldiRecognizer(conn_model, sample_rate)
                    rec.SetWords(show_words)
                    rec.SetMaxAlternatives(max_alternatives)
                response, stop = await self._loop.run_in_executor(
                    self._pool, _process_chunk, rec, message
                )
                await websocket.send(response)
                if stop:
                    break
        except ConnectionClosed:
            pass  # the client hung up (the Settings probe does, right after its reply)
        finally:
            await self._release_model(conn_path)


def _process_chunk(rec, message):
    if message == EOF_MESSAGE:
        return rec.FinalResult(), True
    if message == RESET_MESSAGE:
        return rec.FinalResult(), False
    if rec.AcceptWaveform(message):
        return rec.Result(), False
    return rec.PartialResult(), False


BUILTIN = BuiltinVoskServer()


def reconcile() -> bool:
    """Start or stop the engine to match the settings snapshot (called at
    startup, after a settings save and by the minute sweep). Reads memory
    only — never Nextcloud."""
    from citizens.services.provider_config import builtin_models_dir, config_snapshot

    wanted = config_snapshot().vosk_builtin
    if wanted and not BUILTIN.running:
        return BUILTIN.start(builtin_models_dir())
    if not wanted and BUILTIN.running:
        BUILTIN.stop()
    return BUILTIN.running
