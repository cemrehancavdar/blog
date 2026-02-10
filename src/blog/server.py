"""Local development server with auto-rebuild on file changes."""

import http.server
import logging
import socketserver
import threading
from functools import partial
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

logger = logging.getLogger(__name__)

DEFAULT_PORT = 8000


class RebuildHandler(FileSystemEventHandler):
    """Watches content/templates/static and triggers rebuilds."""

    def __init__(self, build_fn, debounce_seconds: float = 0.5):
        self.build_fn = build_fn
        self.debounce_seconds = debounce_seconds
        self._timer = None
        self._lock = threading.Lock()

    def _debounced_build(self):
        with self._lock:
            self._timer = None
        logger.info("Change detected, rebuilding...")
        try:
            self.build_fn()
            logger.info("Rebuild complete")
        except Exception:
            logger.exception("Rebuild failed")

    def on_any_event(self, event):
        if event.is_directory:
            return
        # Skip output dir and hidden files
        src_path = event.src_path
        if "/output/" in src_path or "/." in src_path:
            return
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self.debounce_seconds, self._debounced_build)
            self._timer.start()


class QuietHTTPHandler(http.server.SimpleHTTPRequestHandler):
    """HTTP handler that serves files and suppresses verbose logging."""

    def log_message(self, format, *args):
        # Only log errors, not every GET request
        if args and isinstance(args[0], str) and args[0].startswith("4"):
            logger.warning(format, *args)

    def do_GET(self):
        # Try to serve directory/index.html for clean URLs
        path = self.translate_path(self.path)
        path_obj = Path(path)
        if path_obj.is_dir() and (path_obj / "index.html").exists():
            self.path = self.path.rstrip("/") + "/index.html"
        super().do_GET()


def serve(
    project_root: Path,
    output_dir: Path,
    build_fn,
    port: int = DEFAULT_PORT,
    watch_dirs: list[Path] | None = None,
) -> None:
    """Start dev server with file watching."""
    # Initial build
    logger.info("Building site...")
    build_fn()

    # Set up file watcher
    observer = Observer()
    handler = RebuildHandler(build_fn)
    if watch_dirs is None:
        watch_dirs = [
            project_root / "content",
            project_root / "templates",
            project_root / "static",
        ]
    for watch_dir in watch_dirs:
        if watch_dir.exists():
            observer.schedule(handler, str(watch_dir), recursive=True)
            logger.info("Watching %s", watch_dir)
    observer.start()

    # Start HTTP server
    handler_class = partial(QuietHTTPHandler, directory=str(output_dir))
    with socketserver.TCPServer(("", port), handler_class) as httpd:
        httpd.allow_reuse_address = True
        logger.info("Serving at http://localhost:%d", port)
        logger.info("Press Ctrl+C to stop")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            observer.stop()
            observer.join()
            logger.info("Server stopped")
