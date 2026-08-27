# Cam Control

Cross-platform desktop camera control console (Windows/macOS/Ubuntu target,
built and tested first on macOS/Apple Silicon). Mimics the core behavior of
the iPhone/iPad Camera app: pick a camera, take photos/videos at a chosen
native resolution, and shoot an auto-adaptive time-lapse.

## Session status / where to pick up next

Two sessions in. First got the app running end-to-end on macOS (window,
camera enumeration, permission prompt/grant flow). Second session fixed two
bugs found by manually testing the built `.app`, both now confirmed working
by the user:

- **Photo/time-lapse preview looked stretched when switching resolution.**
  Root cause: `CameraSession.set_photo_resolution()` only told
  `QImageCapture` the target pixel size, never reconfigured the camera's own
  sensor format — so picking a resolution with a different aspect ratio than
  whatever format the camera happened to be streaming caused Qt to stretch
  the frame to fit instead of resizing correctly. Fixed by
  `_match_camera_format_aspect()` in `camera_session.py`, which picks the
  camera's `QCameraFormat` whose aspect ratio best matches the requested
  still resolution and applies it via `setCameraFormat()` before capture.
  Also added `_pending_photo_resolution` / `_pending_video_resolution`
  bookkeeping so a resolution requested before the camera finishes
  activating (permission grant is async) gets re-applied once it does,
  instead of silently no-oping.
- **Video "wasn't saving."** Turned out video recording was actually
  working correctly the whole time (confirmed via `ffprobe` — valid
  1080p60 H.264+AAC MP4s were landing in `~/Movies/CamControl/Videos`);
  the real problem was the app gave no clear feedback that a save
  succeeded. Fixed by making the status label bold and showing just the
  filename (full path as a tooltip) for save confirmations in
  `main_window.py`. Also added an explicit `QMediaFormat` (MPEG4/H264/AAC)
  on the recorder instead of relying on Qt's auto-negotiation, as a
  robustness improvement alongside this (not proven to have been the actual
  cause, but cheap insurance).
- Confirmed by the user: Photos, Videos, and Time-lapses all save to their
  correct OS-standard folders (`Pictures/CamControl/{Photos,Timelapses}`,
  `Movies/CamControl/Videos`) — the split was a deliberate earlier design
  choice, re-confirmed with the user rather than changed.

**Verified working (manually, by the user, on macOS):** app launch, camera
enumeration/switching, permission prompt + grant flow, photo capture with
correct (non-stretched) resolution, video capture with audio saved to disk
and playable, time-lapse resolution/preview no longer stretched.

**Still not manually verified:**
- Time-lapse full cycle specifically (start → capture several frames over
  time → stop → ffmpeg compile → resulting MP4 plays back → raw stills
  actually got deleted). Preview/resolution behavior is confirmed good;
  the compile-and-cleanup tail end hasn't been explicitly exercised.
- Gallery window (opens, lists library files, previews both images and
  videos, "Open Other File…" for files outside the library).
- Not tested at all yet: Windows, Ubuntu (target platforms per the original
  ask, but dev/test machine is macOS only so far).

Debugging technique worth remembering: when something "isn't working" but
the code path looks right, verify at the filesystem/`ffprobe` level before
assuming the capture pipeline is broken — the video bug turned out to be a
missing UI confirmation, not a missing file.

## Stack

- Python + `uv` (project/venv management, no `pip` in the venv — always use `uv add` / `uv run`)
- PySide6 (Qt for Python) for the GUI
- Qt Multimedia (`QMediaDevices`, `QCamera`, `QImageCapture`, `QMediaRecorder`, `QVideoWidget`) for all camera/mic access, enumeration, capture, and playback
- `imageio-ffmpeg` (bundled static ffmpeg binary) to compile time-lapse stills into an MP4
- `pyside6-deploy` (wraps Nuitka) to produce a real signed `.app` bundle for macOS — required for camera/mic permissions to work at all, see below

## Layout

- `camcontrol/app.py` — entry point (`main()`), also the `camcontrol` console script
- `camcontrol/main_window.py` — the main window: camera picker, resolution picker, Photo/Video/Time-Lapse mode switch, shutter button
- `camcontrol/camera_session.py` — wraps the whole Qt Multimedia pipeline (one `QCamera` at a time) behind a small signal-based API; also owns camera/mic permission requesting (see below)
- `camcontrol/timelapse.py` — `TimelapseController`: iPhone-style auto-adaptive capture interval, compiles captured stills to MP4 via ffmpeg on stop, deletes raw stills after
- `camcontrol/gallery_window.py` — browses the library folders and previews any image/video file (not just ones this app recorded)
- `camcontrol/paths.py` — resolves the OS-standard library folders (`Pictures/CamControl/{Photos,Timelapses}`, `Movies/CamControl/Videos`) via `QStandardPaths`
- `run_app.py` — thin entry point used only by `pyside6-deploy`/Nuitka as the compile target (not used by normal `uv run camcontrol`)
- `pysidedeploy.spec` — `pyside6-deploy` config; carries the macOS `NSCameraUsageDescription`/`NSMicrophoneUsageDescription` strings (`[nuitka] macos.permissions`)

## Running

Day-to-day development (Linux/Windows, or macOS code changes that don't touch camera/mic):

```
uv run camcontrol
```

**On macOS, camera/mic access only works from a real compiled `.app` bundle**, not from `uv run camcontrol` directly (see "macOS camera permission" below). Build and run it with:

```
uv run pyside6-deploy -c pysidedeploy.spec -f
open CamControl.app
```

Rebuild whenever `camcontrol/` changes and you need to test camera/mic behavior on macOS. `CamControl.app` is gitignored (build artifact, regenerate it, don't commit it).

## Scope (v1, confirmed)

1. Scan cameras, switch instantly via a live dropdown (auto-updates on hotplug)
2. Take a photo — resolution list is populated from the camera's actual native supported resolutions only; saves as JPEG
3. Record video (with audio) — MP4/H.264 at the native frame rate for the selected resolution
4. Time-lapse — no manual interval; capture interval auto-widens the longer the session runs (mirrors iPhone behavior); compiles to a single smooth MP4 on stop, raw stills discarded
5. In-app gallery: browses the app's library folders, plus can open/preview any arbitrary image or video file from disk

Explicitly out of scope for v1: zoom, flash/torch, exposure/focus/white-balance controls, filters, simultaneous multi-camera capture, other iPhone camera modes (slow-mo/portrait/etc.), cloud sync, installer/distribution packaging.

## macOS camera permission — how we solved it (read before touching camera code)

Getting the camera/mic permission prompt to appear at all took a long debugging session. Two **separate**, both-required root causes:

**1. Qt 6.5+ requires explicitly requesting permission in code.** `QCamera.start()` alone never triggers the OS permission dialog — it only ever performs a silent status *check* (visible in macOS's own logs as a `preflight=yes, query=1` TCC call). Without an explicit request, the app is stuck at `Undetermined` forever with no popup. Fixed in `camera_session.py` via `QCameraPermission`/`QMicrophonePermission` + `QCoreApplication.requestPermission(permission, context, callback)` — note the 3-arg form; PySide6 requires a `context` object, `app.requestPermission(permission, callback)` (2-arg) raises `TypeError`. `CameraSession.set_camera()` now gates actual camera activation on `Qt.PermissionStatus.Granted`, requesting first if `Undetermined`.

**2. The requesting process must be a real, on-disk `.app` bundle with `NSCameraUsageDescription`/`NSMicrophoneUsageDescription` in its `Info.plist`.** A bare `uv run camcontrol` (or any bare `python3` process, even one launched from Terminal.app) can never get the prompt — Qt's own permission API refuses outright with `qt.permissions: Requesting QCameraPermission requires "NSCameraUsageDescription" in Info.plist`. We initially tried hand-rolling a thin `.app` wrapper (a bash script `exec`ing `uv run`), which **does not work**: a shell script isn't a Mach-O binary, so code-signing/entitlements can't attach to it, and `exec`ing into an external interpreter outside the bundle discards the bundle/Info.plist context before Qt ever calls into AVFoundation. The fix was to stop hand-rolling and use Qt's own official deploy tool, `pyside6-deploy` (bundles the app via Nuitka into a real compiled, signed Mach-O executable inside `Contents/MacOS/`, with a real `Info.plist` generated from `pysidedeploy.spec`'s `[nuitka] macos.permissions` key).

Net effect: **regular `uv run camcontrol` will never be able to prompt for camera/mic access on macOS**, by design of the OS + Qt, regardless of anything else we do to it. Always test camera/mic-touching changes via the rebuilt `.app`, not bare `uv run`.

Other things learned along the way, in case they matter again:
- `tccutil reset Camera` / `tccutil reset Microphone` resets that permission for **every app on the machine**, not just this one — use sparingly, and warn before running.
- `log show --predicate 'subsystem == "com.apple.TCC"'` (or filter `eventMessage CONTAINS "kTCCServiceCamera"`) is the fastest way to see the real TCC request/reply, including whether a call was a no-UI `preflight` query or a real request.
- `python3` inside the `uv`-managed venv (from `.local/share/uv/python/...`) is already ad-hoc/linker-signed by default — signature *presence* was a red herring; it was never about signing, always about the bundle + explicit-request requirement above.
