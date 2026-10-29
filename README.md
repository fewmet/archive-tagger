# Local Files Tagger

A small desktop app for tagging unreleased songs and filing them into a discography folder. Drop in a song, pick the artist, and it looks the song up on the tracker (through tracker-player), fills in the name, version, features, producers, era and year, adds the era's cover art, and moves or copies it into the right "N. Era sessions" folder.

Works on Windows and macOS.

## Download

Click the green **Code** button above, then **Download ZIP**, and unzip it somewhere you'll keep it (not inside Downloads if you clear that out).

## Setup

You need Python 3 from [python.org](https://www.python.org/downloads/). The first launch sets everything else up by itself (takes a minute and needs internet).

**Windows:** run the Python installer and tick "Add python.exe to PATH". Then double-click `Start Local Files Tagger.bat`.

**Mac:** run the macOS Python installer. The first time, right-click `Start Local Files Tagger.command` and choose **Open**, then **Open** again. macOS blocks double-clicking downloaded scripts the first time; if there's no Open button, go to System Settings > Privacy & Security, scroll down and press **Open Anyway**. After that a double-click works. A Terminal window shows the setup, and you can close it once the app opens.

If the Mac says "Permission denied", open Terminal, type `chmod +x ` (with the space), drag `Start Local Files Tagger.command` into the window, press Enter, and try again.

## Using it

See [How to use.txt](How%20to%20use.txt) for the full walkthrough: picking your music folder, tagging, covers, and file naming.

## Updates

From v1.2.0 on, the app checks for new versions when it opens. A bar at the top shows when one is out, and **Update now** updates it in place and reopens it, keeping your settings, covers and songs. Settings > Updates can check by hand or install updates by themselves. If you have v1.0.0 or v1.1.0, download v1.2.0 once from [Releases](https://github.com/fewmet/archive-tagger/releases/latest), and it updates itself after that.

If something breaks, `data/log.txt` has the error.

## Publishing a new version

Bump `VERSION` at the top of `app.py`, push, then publish a GitHub release whose tag matches (for example `v1.3.0`) with the ZIP attached (`git archive --format=zip --prefix="Local Files Tagger/" -o Local-Files-Tagger-v1.3.0.zip HEAD`). Installed copies pick it up from the latest release.
