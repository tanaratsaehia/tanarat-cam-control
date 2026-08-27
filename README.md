# Cam Control

A cross-platform desktop camera control console, built to feel like the
iPhone/iPad Camera app: pick a camera, switch instantly, take photos and
videos at a resolution you choose, and shoot a time-lapse that behaves the
way it does on iOS.

Targets Windows, macOS, and Ubuntu. Built and tested first on macOS
(Apple Silicon).

## Features

- **Scan & switch cameras** — a live dropdown lists every connected camera
  (built-in, USB, iPhone Continuity Camera, etc.) and updates automatically
  when devices are plugged/unplugged. Click one to switch the live preview
  instantly.
- **Photo capture** — resolution dropdown is populated from what the
  selected camera actually supports; saves as JPEG.
- **Video capture** — records MP4/H.264 with audio, at the native frame
  rate for the resolution you pick.
- **Time-lapse** — no interval to configure: just start/stop, like the
  iPhone. The capture interval automatically widens the longer the session
  runs, so an hours-long recording still compiles into a short, smooth
  clip. On stop, it's compiled into a single MP4 and the raw stills are
  discarded.
- **Gallery** — browse everything the app has saved, or open and preview
  any other image/video file on disk.

## Requirements

- [uv](https://docs.astral.sh/uv/) (manages the Python version and
  virtual environment — no separate Python install needed)
- A webcam or built-in camera

## Setup

```bash
uv sync
```

## Running

```bash
uv run camcontrol
```

### macOS: camera/mic permissions need a real app bundle

On macOS, `uv run camcontrol` **cannot** get a camera/microphone permission
prompt — this is a hard requirement from macOS and Qt, not a bug: the
requesting process has to be a real, signed `.app` bundle with usage-
description strings in its `Info.plist`. Build one with:

```bash
uv run pyside6-deploy -c pysidedeploy.spec -f
open CamControl.app
```

Rebuild it whenever you change code and want to test camera/mic behavior.
`CamControl.app` is a generated build artifact (gitignored) — see
[`CLAUDE.md`](CLAUDE.md) for the full story on why this is necessary.

## Where files are saved

- Photos → `Pictures/CamControl/Photos`
- Videos → `Movies/CamControl/Videos`
- Time-lapses → `Pictures/CamControl/Timelapses`

(Standard OS Pictures/Movies directories, so they also show up in your
system's own Photos/gallery apps.)

## Project layout

```
camcontrol/
├── app.py             entry point
├── main_window.py      camera picker, resolution picker, mode switch, shutter
├── camera_session.py   Qt Multimedia pipeline + camera/mic permission handling
├── timelapse.py         adaptive-interval capture + MP4 compilation
├── gallery_window.py    library browser / media preview
└── paths.py             OS-standard save-folder resolution
```

See [`CLAUDE.md`](CLAUDE.md) for architecture notes, v1 scope boundaries,
and a detailed writeup of the macOS permission debugging.

## Status

v1 in progress. Not yet packaged for distribution — this is a dev-mode
project run via `uv run` (or the `pyside6-deploy` build, for macOS camera
testing).
