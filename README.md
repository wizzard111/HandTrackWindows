<div align="center">

<img src="src/handtrack/assets/icon.png" width="96" alt="HandTrack">

# HANDTRACK — Windows

**Gestures, gaze, face hiding and drawing in the air, right inside your calls.**
Its own virtual camera for Discord, Telegram, Zoom, Google Meet, Teams, Skype and OBS. No OBS needed.

*In collaboration with [Claude](https://claude.ai).*

[⬇ Download](../../releases/latest) · [Step-by-step install](HOW-TO-INSTALL.txt) · [Linux](https://github.com/OWNER/HandTrackLinux) · [macOS](https://github.com/OWNER/HandTrackMac)

<img src="docs/screenshots/live.png" width="880" alt="HandTrack">

</div>

## Install in a minute

1. [Releases](../../releases/latest) → download **HandTrack-windows.zip** and unzip it.
2. Double-click **Install HandTrack.bat**. On the blue SmartScreen window: "More info" → "Run anyway"; on the Windows prompt: "Yes".
3. HandTrack appears in the Start menu. In your call, pick the camera **HandTrack Camera**.

The full walkthrough, with common problems and fixes, is in [HOW-TO-INSTALL.txt](HOW-TO-INSTALL.txt).
Uninstall with **Uninstall HandTrack.bat**, "Start → Uninstall HandTrack" or "Settings → Apps".
Running the installer again only adds what is missing or changed.

> You can also download just the code (Code → Download ZIP): the same installer sets up an
> isolated Python 3.12 and all libraries inside the program folder. Nothing to install by hand.

## Features

- **HandTrack Camera**: its own virtual camera (the driver is installed with the app). The resolution adapts by itself and the picture is never stretched. While nobody watches the camera, almost no frames are sent, so the CPU rests.
- **Hide face**: a plain black square over your face; if the face is lost, the whole frame is covered. The app shows a blinking **COVERING** badge meanwhile.
- **Pinch drawing**: lines that fade out smoothly, with jitter smoothing and a choice of colour, thickness and lifetime; clear them with a button or a gesture.
- **My gestures**: any finger combination → hotkeys, media, volume, programs, links, a screenshot, face hiding, clearing the drawing.
- **Photos on gestures**: show 1–5 fingers and your picture "sticks" to your hand.
- **Gaze tracking** with 9-point calibration, **auto-AFK**, gesture calibration for your hand.
- Dark and light themes.

<table><tr>
<td><img src="docs/screenshots/gestures.png" alt="My gestures"></td>
<td><img src="docs/screenshots/effects.png" alt="Effects"></td>
</tr></table>

## Repository layout

```
Install HandTrack.bat     the installer (the only thing you need to run)
Uninstall HandTrack.bat   the uninstaller
HOW-TO-INSTALL.txt        step-by-step guide
src/handtrack/            the program: engine, vision, vcam, ui, …
packaging/                build: windows/, shared PyInstaller spec, model and driver download
tests/                    tests (python -m pytest)
docs/                     screenshots, third-party licenses
```

The Linux and macOS versions live in their own repositories with the same code and their own installers.

### Development

```powershell
python -m venv .venv; .venv\Scripts\activate
pip install -r packaging\requirements-dev.txt
$env:PYTHONPATH = "src"; python -m handtrack        # run
python -m pytest                                    # tests
powershell -ExecutionPolicy Bypass -File packaging\windows\build.ps1   # release dist\HandTrack-windows.zip
```

GitHub Actions builds and checks the release on every push; a `v*` tag publishes it to Releases.

## Performance

Processing runs on its own thread and the neural networks run asynchronously, so the interface
never waits for the camera. Frames are not converted for the preview or the camera (Qt and the
driver take BGR directly), stickers are blended with integer maths, the drawing is rendered
straight into the frame without per-pixel blending (a full-frame drawing: 0.9 ms instead of
26 ms), and no preview is prepared while it is not visible.

## License

[MIT](LICENSE). Third-party components: [docs/THIRD_PARTY_NOTICES.md](docs/THIRD_PARTY_NOTICES.md).
