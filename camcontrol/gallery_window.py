"""Gallery: browses the app's library folders and previews any image/video file."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from camcontrol import paths

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".heic"}
VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}


class GalleryWindow(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Gallery")
        self.resize(1000, 640)

        self._file_list = QListWidget()
        self._file_list.setMinimumWidth(280)
        self._file_list.currentItemChanged.connect(self._on_selection_changed)

        open_other_btn = QPushButton("Open Other File…")
        open_other_btn.clicked.connect(self._open_other_file)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh)

        left_layout = QVBoxLayout()
        left_layout.addWidget(self._file_list, stretch=1)
        row = QHBoxLayout()
        row.addWidget(refresh_btn)
        row.addWidget(open_other_btn)
        left_layout.addLayout(row)
        left_panel = QWidget()
        left_panel.setLayout(left_layout)

        # -- preview pane --
        self._image_label = QLabel("No file selected")
        self._image_label.setAlignment(Qt.AlignCenter)
        self._image_label.setMinimumSize(320, 240)

        self._video_widget = QVideoWidget()
        self._player = QMediaPlayer(self)
        self._audio_output = QAudioOutput(self)
        self._player.setAudioOutput(self._audio_output)
        self._player.setVideoOutput(self._video_widget)
        self._player.durationChanged.connect(self._on_duration_changed)
        self._player.positionChanged.connect(self._on_position_changed)

        self._preview_stack = QStackedWidget()
        self._preview_stack.addWidget(self._image_label)  # index 0
        self._preview_stack.addWidget(self._video_widget)  # index 1

        self._play_btn = QPushButton("Play")
        self._play_btn.clicked.connect(self._toggle_playback)
        self._seek_slider = QSlider(Qt.Horizontal)
        self._seek_slider.sliderMoved.connect(self._player.setPosition)

        transport = QHBoxLayout()
        transport.addWidget(self._play_btn)
        transport.addWidget(self._seek_slider, stretch=1)

        right_layout = QVBoxLayout()
        right_layout.addWidget(self._preview_stack, stretch=1)
        right_layout.addLayout(transport)
        right_panel = QWidget()
        right_panel.setLayout(right_layout)

        root = QHBoxLayout(self)
        root.addWidget(left_panel)
        root.addWidget(right_panel, stretch=1)

        self.refresh()

    def refresh(self) -> None:
        self._file_list.clear()
        groups = [
            ("Photos", paths.PHOTOS_DIR),
            ("Videos", paths.VIDEOS_DIR),
            ("Timelapses", paths.TIMELAPSES_DIR),
        ]
        for label, directory in groups:
            if not directory.exists():
                continue
            files = sorted(directory.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
            for file_path in files:
                if file_path.is_file():
                    item = QListWidgetItem(f"[{label}] {file_path.name}")
                    item.setData(Qt.UserRole, str(file_path))
                    self._file_list.addItem(item)

    def _open_other_file(self) -> None:
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "Open Image or Video",
            str(Path.home()),
            "Media files (*.jpg *.jpeg *.png *.bmp *.gif *.webp *.heic "
            "*.mp4 *.mov *.m4v *.avi *.mkv *.webm)",
        )
        if file_name:
            self._preview_file(Path(file_name))

    def _on_selection_changed(self, current: QListWidgetItem | None, _previous) -> None:
        if current is None:
            return
        file_path = Path(current.data(Qt.UserRole))
        self._preview_file(file_path)

    def _preview_file(self, file_path: Path) -> None:
        self._player.stop()
        suffix = file_path.suffix.lower()
        if suffix in VIDEO_SUFFIXES:
            self._preview_stack.setCurrentWidget(self._video_widget)
            self._player.setSource(QUrl.fromLocalFile(str(file_path)))
            self._play_btn.setEnabled(True)
            self._seek_slider.setEnabled(True)
        elif suffix in IMAGE_SUFFIXES:
            self._preview_stack.setCurrentWidget(self._image_label)
            pixmap = QPixmap(str(file_path))
            if not pixmap.isNull():
                pixmap = pixmap.scaled(
                    self._image_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
                self._image_label.setPixmap(pixmap)
            else:
                self._image_label.setText(f"Could not preview:\n{file_path.name}")
            self._play_btn.setEnabled(False)
            self._seek_slider.setEnabled(False)
        else:
            self._preview_stack.setCurrentWidget(self._image_label)
            self._image_label.setText(f"Unsupported file type:\n{file_path.name}")

    def _toggle_playback(self) -> None:
        if self._player.playbackState() == QMediaPlayer.PlayingState:
            self._player.pause()
            self._play_btn.setText("Play")
        else:
            self._player.play()
            self._play_btn.setText("Pause")

    def _on_duration_changed(self, duration: int) -> None:
        self._seek_slider.setRange(0, duration)

    def _on_position_changed(self, position: int) -> None:
        if not self._seek_slider.isSliderDown():
            self._seek_slider.setValue(position)
