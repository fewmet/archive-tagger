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

If something breaks, `data/log.txt` has the error.
