"""Main console window: camera picker, resolution picker, mode switch, shutter."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from camcontrol import paths
from camcontrol.camera_session import CameraSession
from camcontrol.gallery_window import GalleryWindow
from camcontrol.timelapse import TimelapseController

MODE_PHOTO = "photo"
MODE_VIDEO = "video"
MODE_TIMELAPSE = "timelapse"


def _format_resolution(size: QSize) -> str:
    return f"{size.width()} × {size.height()}"


def _format_duration_ms(ms: int) -> str:
    total_seconds = ms // 1000
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes:02d}:{seconds:02d}"


def _timestamped_name(prefix: str, suffix: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{stamp}{suffix}"


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Cam Control")
        self.resize(960, 640)

        paths.ensure_library_dirs()

        self._session = CameraSession()
        self._timelapse = TimelapseController(self._session)
        self._gallery_window: GalleryWindow | None = None

        self._mode = MODE_PHOTO
        self._awaiting_photo = False

        self._video_widget = QVideoWidget()
        self._session.set_video_output(self._video_widget)

        self._camera_combo = QComboBox()
        self._camera_combo.currentIndexChanged.connect(self._on_camera_selected)

        self._resolution_combo = QComboBox()
        self._resolution_combo.currentIndexChanged.connect(self._on_resolution_selected)

        self._photo_radio = QRadioButton("Photo")
        self._video_radio = QRadioButton("Video")
        self._timelapse_radio = QRadioButton("Time-Lapse")
        self._photo_radio.setChecked(True)
        mode_group = QButtonGroup(self)
        for button, mode in (
            (self._photo_radio, MODE_PHOTO),
            (self._video_radio, MODE_VIDEO),
            (self._timelapse_radio, MODE_TIMELAPSE),
        ):
            mode_group.addButton(button)
            button.toggled.connect(
                lambda checked, m=mode: self._on_mode_toggled(m) if checked else None
            )

        self._shutter_button = QPushButton("Take Photo")
        self._shutter_button.clicked.connect(self._on_shutter_clicked)

        self._status_label = QLabel("Select a camera to begin.")
        self._status_label.setStyleSheet("font-weight: 600;")
        self._status_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        gallery_button = QPushButton("Gallery")
        gallery_button.clicked.connect(self._open_gallery)

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("Camera:"))
        top_row.addWidget(self._camera_combo, stretch=1)
        top_row.addWidget(QLabel("Resolution:"))
        top_row.addWidget(self._resolution_combo, stretch=1)

        mode_row = QHBoxLayout()
        mode_row.addWidget(self._photo_radio)
        mode_row.addWidget(self._video_radio)
        mode_row.addWidget(self._timelapse_radio)
        mode_row.addStretch(1)
        mode_row.addWidget(gallery_button)

        bottom_row = QHBoxLayout()
        bottom_row.addWidget(self._status_label, stretch=1)
        bottom_row.addWidget(self._shutter_button)

        layout = QVBoxLayout()
        layout.addLayout(top_row)
        layout.addWidget(self._video_widget, stretch=1)
        layout.addLayout(mode_row)
        layout.addLayout(bottom_row)

        central = QWidget()
        central.setLayout(layout)
        self.setCentralWidget(central)

        self._session.camerasChanged.connect(self._refresh_camera_list)
        self._session.cameraError.connect(lambda msg: self._set_status(f"Camera error: {msg}"))
        self._session.imageCaptured.connect(self._on_photo_captured)
        self._session.imageCaptureError.connect(self._on_photo_capture_error)
        self._session.recorderDurationChanged.connect(self._on_recording_duration)
        self._session.recorderStopped.connect(self._on_recording_stopped)
        self._session.recorderError.connect(lambda msg: self._set_status(f"Recording error: {msg}"))

        self._timelapse.started.connect(self._on_timelapse_started)
        self._timelapse.frameCaptured.connect(self._on_timelapse_frame)
        self._timelapse.compiling.connect(lambda: self._set_status("Compiling time-lapse…"))
        self._timelapse.finished.connect(self._on_timelapse_finished)
        self._timelapse.error.connect(self._on_timelapse_error)

        self._refresh_camera_list()

    # -- camera list ---------------------------------------------------

    def _refresh_camera_list(self) -> None:
        current_id = self._camera_combo.currentData()
        self._camera_combo.blockSignals(True)
        self._camera_combo.clear()
        devices = self._session.available_cameras()
        for device in devices:
            self._camera_combo.addItem(device.description(), device.id())
        self._camera_combo.blockSignals(False)

        if not devices:
            self._set_status("No camera detected.")
            return

        restore_index = 0
        if current_id is not None:
            for i in range(self._camera_combo.count()):
                if self._camera_combo.itemData(i) == current_id:
                    restore_index = i
                    break
        self._camera_combo.setCurrentIndex(restore_index)
        self._on_camera_selected(restore_index)

    def _current_device(self):
        index = self._camera_combo.currentIndex()
        if index < 0:
            return None
        devices = self._session.available_cameras()
        device_id = self._camera_combo.itemData(index)
        for device in devices:
            if device.id() == device_id:
                return device
        return None

    def _on_camera_selected(self, _index: int) -> None:
        device = self._current_device()
        if device is None:
            return
        self._session.set_camera(device)
        self._refresh_resolutions()

    # -- mode / resolution -----------------------------------------------

    def _on_mode_toggled(self, mode: str) -> None:
        if self._session.is_recording() or self._timelapse.is_running():
            self._set_status("Stop the current capture before switching modes.")
            return
        self._mode = mode
        self._shutter_button.setText(
            {"photo": "Take Photo", "video": "Start Recording", "timelapse": "Start Time-Lapse"}[mode]
        )
        self._refresh_resolutions()

    def _refresh_resolutions(self) -> None:
        device = self._current_device()
        self._resolution_combo.blockSignals(True)
        self._resolution_combo.clear()
        if device is not None:
            if self._mode == MODE_VIDEO:
                resolutions = self._session.video_resolutions(device)
            else:
                resolutions = self._session.photo_resolutions(device)
            for size in resolutions:
                self._resolution_combo.addItem(_format_resolution(size), size)
        self._resolution_combo.blockSignals(False)
        if self._resolution_combo.count() > 0:
            self._resolution_combo.setCurrentIndex(0)
            self._apply_resolution(self._resolution_combo.itemData(0))

    def _on_resolution_selected(self, index: int) -> None:
        if index < 0:
            return
        self._apply_resolution(self._resolution_combo.itemData(index))

    def _apply_resolution(self, size: QSize | None) -> None:
        if size is None:
            return
        device = self._current_device()
        if device is None:
            return
        if self._mode == MODE_VIDEO:
            self._session.set_video_resolution(device, size)
        else:
            self._session.set_photo_resolution(size)

    # -- shutter -----------------------------------------------------------

    def _on_shutter_clicked(self) -> None:
        if self._mode == MODE_PHOTO:
            self._take_photo()
        elif self._mode == MODE_VIDEO:
            self._toggle_video_recording()
        else:
            self._toggle_timelapse()

    def _take_photo(self) -> None:
        if self._awaiting_photo:
            return
        self._awaiting_photo = True
        destination = paths.PHOTOS_DIR / _timestamped_name("photo", ".jpg")
        self._set_status("Capturing photo…")
        self._session.capture_photo(destination)

    def _on_photo_captured(self, path: str) -> None:
        if not self._awaiting_photo:
            return  # a timelapse frame, not a manual photo
        self._awaiting_photo = False
        self._set_status(f"Saved photo: {Path(path).name}", tooltip=path)

    def _on_photo_capture_error(self, message: str) -> None:
        if self._awaiting_photo:
            self._awaiting_photo = False
            self._set_status(f"Photo capture failed: {message}")

    def _toggle_video_recording(self) -> None:
        if self._session.is_recording():
            self._session.stop_recording()
            self._shutter_button.setText("Start Recording")
            self._set_ui_locked(False)
        else:
            destination = paths.VIDEOS_DIR / _timestamped_name("video", ".mp4")
            self._session.start_recording(destination)
            self._shutter_button.setText("Stop Recording")
            self._set_ui_locked(True)
            self._set_status("Recording… 00:00")

    def _on_recording_duration(self, ms: int) -> None:
        if self._session.is_recording():
            self._set_status(f"Recording… {_format_duration_ms(ms)}")

    def _on_recording_stopped(self, path: str) -> None:
        self._set_status(f"Saved video: {Path(path).name}", tooltip=path)

    def _toggle_timelapse(self) -> None:
        if self._timelapse.is_running():
            destination = paths.TIMELAPSES_DIR / _timestamped_name("timelapse", ".mp4")
            self._timelapse.stop(destination)
            self._shutter_button.setText("Start Time-Lapse")
            self._shutter_button.setEnabled(False)
        else:
            self._timelapse.start()
            self._shutter_button.setText("Stop Time-Lapse")
            self._set_ui_locked(True)

    def _on_timelapse_started(self) -> None:
        self._set_status("Time-lapse started… 0 frames")

    def _on_timelapse_frame(self, count: int) -> None:
        self._set_status(f"Time-lapse recording… {count} frames")

    def _on_timelapse_finished(self, path: str) -> None:
        self._set_status(f"Saved time-lapse: {Path(path).name}", tooltip=path)
        self._shutter_button.setEnabled(True)
        self._set_ui_locked(False)

    def _on_timelapse_error(self, message: str) -> None:
        self._set_status(message)
        self._shutter_button.setText("Start Time-Lapse")
        self._shutter_button.setEnabled(True)
        self._set_ui_locked(False)

    # -- helpers -------------------------------------------------------

    def _set_ui_locked(self, locked: bool) -> None:
        self._camera_combo.setEnabled(not locked)
        self._resolution_combo.setEnabled(not locked)
        self._photo_radio.setEnabled(not locked)
        self._video_radio.setEnabled(not locked)
        self._timelapse_radio.setEnabled(not locked)

    def _set_status(self, message: str, tooltip: str | None = None) -> None:
        self._status_label.setText(message)
        self._status_label.setToolTip(tooltip or "")

    def _open_gallery(self) -> None:
        if self._gallery_window is None:
            self._gallery_window = GalleryWindow()
        self._gallery_window.refresh()
        self._gallery_window.show()
        self._gallery_window.raise_()
        self._gallery_window.activateWindow()

    def closeEvent(self, event) -> None:
        self._session.stop_camera()
        super().closeEvent(event)
