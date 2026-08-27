"""Wraps Qt Multimedia's camera/audio/capture pipeline behind a small, UI-friendly API.

Owns exactly one active QCamera at a time and exposes device enumeration,
per-camera native resolution lists, photo capture, video capture (with audio),
and still capture (used by the timelapse controller) through one object so the
UI layer never touches QtMultimedia types directly.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import (
    Qt,
    QCameraPermission,
    QCoreApplication,
    QMicrophonePermission,
    QObject,
    QSize,
    QUrl,
    Signal,
)
from PySide6.QtMultimedia import (
    QAudioInput,
    QCamera,
    QCameraDevice,
    QImageCapture,
    QMediaCaptureSession,
    QMediaDevices,
    QMediaRecorder,
)


def _dedup_sorted_resolutions(sizes: list[QSize]) -> list[QSize]:
    seen: dict[tuple[int, int], QSize] = {}
    for size in sizes:
        if size.width() <= 0 or size.height() <= 0:
            continue
        seen[(size.width(), size.height())] = size
    return sorted(seen.values(), key=lambda s: s.width() * s.height(), reverse=True)


class CameraSession(QObject):
    camerasChanged = Signal()
    activeCameraChanged = Signal(object)  # QCameraDevice or None
    cameraError = Signal(str)

    imageCaptured = Signal(str)  # saved file path
    imageCaptureError = Signal(str)

    recorderDurationChanged = Signal("qlonglong")  # milliseconds
    recorderStopped = Signal(str)  # saved file path
    recorderError = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)

        self._media_devices = QMediaDevices(self)
        self._media_devices.videoInputsChanged.connect(self.camerasChanged)

        self._capture_session = QMediaCaptureSession(self)

        self._audio_input = QAudioInput(self)
        self._capture_session.setAudioInput(self._audio_input)

        self._image_capture = QImageCapture(self)
        self._capture_session.setImageCapture(self._image_capture)
        self._image_capture.imageSaved.connect(lambda _id, path: self.imageCaptured.emit(path))
        self._image_capture.errorOccurred.connect(
            lambda _id, _error, msg: self.imageCaptureError.emit(msg)
        )

        self._recorder = QMediaRecorder(self)
        self._capture_session.setRecorder(self._recorder)
        self._recorder.durationChanged.connect(self.recorderDurationChanged)
        self._recorder.errorOccurred.connect(
            lambda _error, msg: self.recorderError.emit(msg)
        )
        self._recorder.actualLocationChanged.connect(
            lambda url: self.recorderStopped.emit(url.toLocalFile())
        )

        self._camera: QCamera | None = None
        self._pending_device: QCameraDevice | None = None

        # Qt 6.5+ requires explicitly requesting permission before a camera
        # will actually prompt the OS / start capturing — QCamera.start()
        # alone only ever performs a silent status *check*, never a real
        # request, so without this the app is stuck at "undetermined" forever.
        self._request_mic_permission()

    def _request_mic_permission(self) -> None:
        app = QCoreApplication.instance()
        permission = QMicrophonePermission()
        status = app.checkPermission(permission)
        if status == Qt.PermissionStatus.Undetermined:
            app.requestPermission(permission, self, self._on_mic_permission_result)
        elif status == Qt.PermissionStatus.Denied:
            self.recorderError.emit(
                "Microphone access denied — enable it in System Settings > Privacy & Security > Microphone."
            )

    def _on_mic_permission_result(self, permission: QMicrophonePermission) -> None:
        app = QCoreApplication.instance()
        if app.checkPermission(permission) == Qt.PermissionStatus.Denied:
            self.recorderError.emit(
                "Microphone access denied — enable it in System Settings > Privacy & Security > Microphone."
            )

    # -- device enumeration -------------------------------------------------

    def available_cameras(self) -> list[QCameraDevice]:
        return QMediaDevices.videoInputs()

    def photo_resolutions(self, device: QCameraDevice) -> list[QSize]:
        return _dedup_sorted_resolutions(list(device.photoResolutions()))

    def video_resolutions(self, device: QCameraDevice) -> list[QSize]:
        sizes = [fmt.resolution() for fmt in device.videoFormats()]
        return _dedup_sorted_resolutions(sizes)

    # -- active camera --------------------------------------------------

    def set_video_output(self, video_widget) -> None:
        self._capture_session.setVideoOutput(video_widget)

    def active_camera_device(self) -> QCameraDevice | None:
        return self._camera.cameraDevice() if self._camera else None

    def set_camera(self, device: QCameraDevice) -> None:
        self._pending_device = device

        app = QCoreApplication.instance()
        permission = QCameraPermission()
        status = app.checkPermission(permission)
        if status == Qt.PermissionStatus.Granted:
            self._activate_camera(device)
        elif status == Qt.PermissionStatus.Undetermined:
            app.requestPermission(permission, self, self._on_camera_permission_result)
        else:
            self.cameraError.emit(
                "Camera access denied — enable it in System Settings > Privacy & Security > Camera."
            )

    def _on_camera_permission_result(self, permission: QCameraPermission) -> None:
        app = QCoreApplication.instance()
        status = app.checkPermission(permission)
        if status == Qt.PermissionStatus.Granted and self._pending_device is not None:
            self._activate_camera(self._pending_device)
        elif status == Qt.PermissionStatus.Denied:
            self.cameraError.emit(
                "Camera access denied — enable it in System Settings > Privacy & Security > Camera."
            )

    def _activate_camera(self, device: QCameraDevice) -> None:
        if self._camera is not None:
            self._camera.stop()
            self._camera.deleteLater()
            self._camera = None

        camera = QCamera(device, self)
        camera.errorOccurred.connect(lambda _error, msg: self.cameraError.emit(msg))
        self._capture_session.setCamera(camera)
        self._camera = camera
        camera.start()
        self.activeCameraChanged.emit(device)

    def stop_camera(self) -> None:
        if self._camera is not None:
            self._camera.stop()

    # -- photo / timelapse stills -------------------------------------------

    def set_photo_resolution(self, resolution: QSize) -> None:
        self._image_capture.setResolution(resolution)

    def capture_photo(self, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        self._image_capture.captureToFile(str(destination))

    # -- video -------------------------------------------------------------

    def set_video_resolution(self, device: QCameraDevice, resolution: QSize) -> None:
        if self._camera is None:
            return
        candidates = [f for f in device.videoFormats() if f.resolution() == resolution]
        if not candidates:
            return
        best = max(candidates, key=lambda f: f.maxFrameRate())
        self._camera.setCameraFormat(best)

    def start_recording(self, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        self._recorder.setOutputLocation(QUrl.fromLocalFile(str(destination)))
        self._recorder.record()

    def stop_recording(self) -> None:
        self._recorder.stop()

    def is_recording(self) -> bool:
        return self._recorder.recorderState() == QMediaRecorder.RecordingState
