"""iPhone-style adaptive-interval timelapse: capture stills, then compile to MP4.

Mirrors iPhone/iPad Time-Lapse behavior: there's no user-set interval, you just
start/stop like a normal recording. The capture interval widens the longer the
session runs, so an hours-long session still compiles into a short, smooth
clip. On stop, the captured stills are stitched into a single MP4 (via the
ffmpeg binary bundled by imageio-ffmpeg) and the raw stills are deleted.
"""

from __future__ import annotations

import shutil
import tempfile
import time
from pathlib import Path

import imageio_ffmpeg
from PySide6.QtCore import QObject, QProcess, QTimer, Signal

from camcontrol.camera_session import CameraSession

# Output framerate of the compiled timelapse clip.
OUTPUT_FPS = 30

# (elapsed_seconds_threshold, capture_interval_seconds) — mimics the iPhone's
# widening capture interval for longer sessions.
_INTERVAL_STAGES = [
    (10 * 60, 2),
    (40 * 60, 5),
    (2 * 60 * 60, 10),
    (4 * 60 * 60, 20),
    (8 * 60 * 60, 30),
]
_MAX_INTERVAL = 60


def _interval_for_elapsed(elapsed_seconds: float) -> float:
    for threshold, interval in _INTERVAL_STAGES:
        if elapsed_seconds < threshold:
            return interval
    return _MAX_INTERVAL


class TimelapseController(QObject):
    started = Signal()
    frameCaptured = Signal(int)  # running frame count
    compiling = Signal()
    finished = Signal(str)  # compiled output file path
    error = Signal(str)

    def __init__(self, camera_session: CameraSession, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._session = camera_session
        self._session.imageCaptured.connect(self._on_image_captured)
        self._session.imageCaptureError.connect(self._on_image_capture_error)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._capture_next_frame)

        self._process: QProcess | None = None

        self._running = False
        self._awaiting_frame = False
        self._frame_dir: Path | None = None
        self._frame_count = 0
        self._start_time = 0.0
        self._output_path: Path | None = None

    def is_running(self) -> bool:
        return self._running

    def start(self) -> None:
        if self._running:
            return
        self._frame_dir = Path(tempfile.mkdtemp(prefix="camcontrol_timelapse_"))
        self._frame_count = 0
        self._start_time = time.monotonic()
        self._running = True
        self.started.emit()
        self._capture_next_frame()

    def _capture_next_frame(self) -> None:
        if not self._running or self._frame_dir is None:
            return
        self._awaiting_frame = True
        frame_path = self._frame_dir / f"frame_{self._frame_count:06d}.jpg"
        self._session.capture_photo(frame_path)

    def _on_image_captured(self, path: str) -> None:
        if not self._running or not self._awaiting_frame:
            return
        self._awaiting_frame = False
        self._frame_count += 1
        self.frameCaptured.emit(self._frame_count)

        elapsed = time.monotonic() - self._start_time
        interval_ms = int(_interval_for_elapsed(elapsed) * 1000)
        self._timer.start(interval_ms)

    def _on_image_capture_error(self, message: str) -> None:
        if self._awaiting_frame:
            self._awaiting_frame = False
            self.error.emit(f"Timelapse frame capture failed: {message}")

    def stop(self, output_path: Path) -> None:
        if not self._running:
            return
        self._running = False
        self._timer.stop()
        self._output_path = output_path
        self._compile(output_path)

    def _compile(self, output_path: Path) -> None:
        if self._frame_dir is None or self._frame_count == 0:
            self._cleanup_frames()
            self.error.emit("Timelapse stopped with no frames captured.")
            return

        self.compiling.emit()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()

        args = [
            "-y",
            "-framerate", str(OUTPUT_FPS),
            "-i", str(self._frame_dir / "frame_%06d.jpg"),
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
            "-pix_fmt", "yuv420p",
            "-c:v", "libx264",
            str(output_path),
        ]

        process = QProcess(self)
        process.setProgram(ffmpeg_exe)
        process.setArguments(args)
        process.finished.connect(lambda code, _status: self._on_compile_finished(code, output_path))
        process.errorOccurred.connect(lambda _err: self.error.emit("Failed to launch ffmpeg for timelapse compile."))
        self._process = process
        process.start()

    def _on_compile_finished(self, exit_code: int, output_path: Path) -> None:
        self._cleanup_frames()
        self._process = None
        if exit_code == 0 and output_path.exists():
            self.finished.emit(str(output_path))
        else:
            self.error.emit("Timelapse compile failed (ffmpeg exited with an error).")

    def _cleanup_frames(self) -> None:
        if self._frame_dir is not None and self._frame_dir.exists():
            shutil.rmtree(self._frame_dir, ignore_errors=True)
        self._frame_dir = None
