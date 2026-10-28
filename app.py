"""
Local Files Tagger (friends version)

Tags songs and files them into a discography folder laid out like
"1. Unreleased & Non-Streaming Discography": one "N. <Era> sessions" folder per
era, file names like "Title [V2] (feat. X) (prod. Y).mp3", album tag
"<Era> (Unreleased)" or "<Era> (Hosted)".

The older "one big album" mode (disc number = artist) is still in Settings.

Works on Windows and macOS. Runs a small local server and shows the UI in its
own window (pywebview).
If pywebview isn't available it opens in the default browser instead.
The tracker is only read through the tracker-player site's public endpoints.
"""

import base64
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

APP_DIR = os.path.dirname(os.path.abspath(__file__))
UI_DIR = os.path.join(APP_DIR, "ui")
DATA_DIR = os.path.join(APP_DIR, "data")
COVER_DIR = os.path.join(DATA_DIR, "covers")
SHEET_COVER_DIR = os.path.join(DATA_DIR, "sheet-covers")   # the tracker's own era art, downloaded
CACHE_DIR = os.path.join(DATA_DIR, "tracker-cache")
INCOMING_DIR = os.path.join(DATA_DIR, "incoming")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
HISTORY_FILE = os.path.join(DATA_DIR, "history.json")
LOG_FILE = os.path.join(DATA_DIR, "log.txt")

for d in (DATA_DIR, COVER_DIR, SHEET_COVER_DIR, CACHE_DIR, INCOMING_DIR):
    os.makedirs(d, exist_ok=True)

WINDOW = None  # pywebview window, when running in app mode

TAGGABLE = {".mp3", ".m4a"}
CONVERTIBLE = {".wav", ".flac", ".aif", ".aiff", ".ogg", ".opus", ".wma", ".aac", ".webm", ".mp4", ".m4b", ".alac"}

DEFAULT_SETTINGS = {
    # "discography": a folder per era, like "1. Unreleased & Non-Streaming Discography"
    # "album": everything in one album, disc number = artist
    "format": "discography",
    # discography mode: each artist gets <libraryFolder>\<artist> unless their slot has its own folder
    "libraryFolder": os.path.join(os.path.expanduser("~"), "Music", "Unreleased & Non-Streaming Discography"),
    "afterTag": "move",          # move or copy the song into its folder
    "comment": "",
    # album mode
    "albumFolder": os.path.join(os.path.expanduser("~"), "Music", "My Archive"),
    "album": "My Archive",
    "albumArtist": "",
    "discTotal": 100,
    "genre": "Hip-Hop/Rap",
    "trackerUrl": "https://tracker-player.onrender.com",
    "convertTo": "mp3",          # mp3 (320k), aac (256k) or alac (lossless)
    "lastSlot": 1,
    "eraFolders": {},            # tracker key -> {era: folder you picked for it}
    # artist slots (disc number is only used in album mode)
    "slots": [
        {"disc": 1, "name": "Yeat", "artist": "Yeat", "tracker": "yeat"},
        {"disc": 2, "name": "Destroy Lonely", "artist": "Destroy Lonely", "tracker": "lonely"},
        {"disc": 3, "name": "Ken Carson", "artist": "Ken Carson", "tracker": "ken"},
        {"disc": 4, "name": "Summrs", "artist": "Summrs", "tracker": "summrs"},
        {"disc": 5, "name": "Playboi Carti", "artist": "Playboi Carti", "tracker": "carti"},
        {"disc": 6, "name": "Lil Uzi Vert", "artist": "Lil Uzi Vert", "tracker": "uzi"},
        {"disc": 7, "name": "OsamaSon", "artist": "OsamaSon", "tracker": "osamason"},
        {"disc": 8, "name": "Other artists", "artist": "", "tracker": ""},
        {"disc": 9, "name": "Ye", "artist": "Ye", "tracker": "kanye"},
        {"disc": 10, "name": "Ski Mask The Slump God", "artist": "Ski Mask The Slump God", "tracker": "skimasktheslumpgod"},
        {"disc": 11, "name": "Edward Skeletrix", "artist": "Edward Skeletrix", "tracker": "edwardskeletrix"},
    ],
}
for _s in DEFAULT_SETTINGS["slots"]:
    _s["folder"] = ""


def log(msg):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + str(msg) + "\n")
    except Exception:
        pass


def read_json(path, fallback):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return fallback


def write_json(path, value):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(value, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def load_settings():
    s = json.loads(json.dumps(DEFAULT_SETTINGS))
    s.update(read_json(SETTINGS_FILE, {}))
    for slot in s["slots"]:
        slot.setdefault("folder", "")
    return s


def save_settings(values):
    s = load_settings()
    for k in DEFAULT_SETTINGS:
        if k in values:
            s[k] = values[k]
    s["slots"] = sorted(s["slots"], key=lambda x: int(x.get("disc") or 0))
    write_json(SETTINGS_FILE, s)
    return s


# ------------------------------------------------------------------ track numbers

FILE_NUM = re.compile(r"^(\d+)-(\d+)\s")


def used_numbers(disc):
    """Track numbers already taken on this disc: the library folder plus what this app tagged."""
    used = set()
    folder = load_settings()["albumFolder"]
    try:
        for name in os.listdir(folder):
            m = FILE_NUM.match(name)
            if m and int(m.group(1)) == int(disc):
                used.add(int(m.group(2)))
    except Exception:
        pass
    hist = read_json(HISTORY_FILE, {})
    for n in hist.get(str(disc), []):
        used.add(int(n))
    return used


def next_track(disc):
    used = used_numbers(disc)
    return (max(used) + 1) if used else 1


def remember_track(disc, track):
    hist = read_json(HISTORY_FILE, {})
    nums = set(hist.get(str(disc), []))
    nums.add(int(track))
    hist[str(disc)] = sorted(nums)
    write_json(HISTORY_FILE, hist)


# ------------------------------------------------------------------ tracker

def tracker_get(path):
    base = load_settings()["trackerUrl"].rstrip("/")
    req = urllib.request.Request(base + path, headers={"User-Agent": "LocalFilesTagger/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))


def tracker_artists(refresh=False):
    cache = os.path.join(CACHE_DIR, "_artists.json")
    if not refresh and os.path.exists(cache) and time.time() - os.path.getmtime(cache) < 86400:
        return read_json(cache, {})
    try:
        data = tracker_get("/artists")
        write_json(cache, data)
        return data
    except Exception as e:
        log(f"tracker artists failed: {e}")
        old = read_json(cache, None)
        if old:
            old["stale"] = True
            return old
        raise


def tracker_songs(key, refresh=False):
    key = re.sub(r"[^a-z0-9_]", "", key.lower())
    cache = os.path.join(CACHE_DIR, key + ".json")
    if not refresh and os.path.exists(cache) and time.time() - os.path.getmtime(cache) < 6 * 3600:
        return read_json(cache, [])
    try:
        raw = tracker_get("/songs?" + urllib.parse.urlencode({"artist": key, "section": "all"}))
        songs = [{
            "name": s.get("name", ""),
            "era": s.get("era", ""),
            "eraYear": s.get("eraYear"),
            "dateYear": s.get("dateYear"),
            "section": s.get("section", ""),
            "notes": (s.get("notes") or "")[:200],
        } for s in raw if s.get("name")]
        write_json(cache, songs)
        return songs
    except Exception as e:
        log(f"tracker songs {key} failed: {e}")
        if os.path.exists(cache):
            return read_json(cache, [])
        raise


# ------------------------------------------------------------------ covers

def cover_key(name):
    return re.sub(r"[^a-z0-9_-]", "", str(name or "").lower()) or "misc"


def era_file(tracker, era):
    folder = os.path.join(COVER_DIR, cover_key(tracker))
    if era == "_default":
        return os.path.join(folder, "_default.jpg")
    h = hashlib.sha1(era.strip().lower().encode("utf-8")).hexdigest()[:14]
    return os.path.join(folder, h + ".jpg")


def custom_eras(tracker):
    return read_json(os.path.join(COVER_DIR, cover_key(tracker), "eras.json"), [])


def set_custom_eras(tracker, eras):
    folder = os.path.join(COVER_DIR, cover_key(tracker))
    os.makedirs(folder, exist_ok=True)
    write_json(os.path.join(folder, "eras.json"), eras)


def image_to_jpeg(data):
    from PIL import Image
    img = Image.open(io.BytesIO(data))
    img = img.convert("RGB")
    longest = max(img.size)
    if longest > 1400:
        scale = 1400 / longest
        img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, "JPEG", quality=92)
    return out.getvalue()


def data_url_bytes(url):
    return base64.b64decode(url.split(",", 1)[1])


# ------------------------------------------------------------------ the tracker's own covers
#
# tracker-player already pulls each era's cover out of the tracker sheet and hands
# them out at /covers?artist=<key> as { era: image url }. An era you haven't given
# a cover of your own uses that one.

SHEET_LOCK = threading.Lock()


def loose_era(era):
    import unicodedata
    flat = unicodedata.normalize("NFD", str(era or ""))
    flat = "".join(c for c in flat if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", flat.lower())


def sheet_covers(key, refresh=False):
    """era -> image url for this tracker, from tracker-player. Cached on disk."""
    raw = str(key or "").lower()
    key = re.sub(r"[^a-z0-9_]", "", raw)
    # "slot-8" style keys are slots with no tracker - asking the site would get Yeat's art back
    if not key or raw.startswith("slot-"):
        return {"covers": {}, "pending": False}
    try:
        known = {a.get("key") for a in tracker_artists().get("artists", [])}
        if known and key not in known:
            return {"covers": {}, "pending": False}
    except Exception:
        pass
    cache = os.path.join(CACHE_DIR, key + "-covers.json")
    with SHEET_LOCK:
        old = read_json(cache, None)
        if old is not None and not refresh:
            age = time.time() - os.path.getmtime(cache)
            # the site may still have been reading the sheet last time, so ask again sooner
            if age < (120 if old.get("pending") else 6 * 3600):
                return old
        try:
            data = {}
            # a sleeping Render server can take a minute or two to read a big sheet
            for attempt in range(10):
                data = tracker_get("/covers?" + urllib.parse.urlencode({"artist": key}))
                if not data.get("pending"):
                    break
                time.sleep(6)
            result = {"covers": {k: v for k, v in (data.get("covers") or {}).items() if v},
                      "pending": bool(data.get("pending"))}
            if result["covers"] or not old:
                write_json(cache, result)
                return result
            return old
        except Exception as e:
            log(f"tracker covers {key} failed: {e}")
            if old is not None:
                return old
            return {"covers": {}, "pending": False, "error": str(e)}


SHEET_RECHECKED = {}  # tracker key -> when we last re-asked the site for an era the cache didn't have


def sheet_cover_url(key, era):
    if not era:
        return None
    want = loose_era(era)

    def find(covers):
        if covers.get(era):
            return covers[era]
        for name, url in covers.items():
            if want and loose_era(name) == want:
                return url
        return None

    url = find(sheet_covers(key)["covers"])
    # the cached list may be older than this era on the sheet - ask again, but not too often
    if not url and time.time() - SHEET_RECHECKED.get(key, 0) > 300:
        SHEET_RECHECKED[key] = time.time()
        url = find(sheet_covers(key, refresh=True)["covers"])
    return url


def sheet_cover_file(key, era):
    """The tracker's cover for this era as a jpg on disk, downloading it the first time."""
    url = sheet_cover_url(key, era)
    if not url:
        return None
    h = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    folder = os.path.join(SHEET_COVER_DIR, cover_key(key))
    path = os.path.join(folder, h + ".jpg")
    if os.path.exists(path):
        return path
    if url.startswith("/"):
        url = load_settings()["trackerUrl"].rstrip("/") + url
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 LocalFilesTagger/1.0"})
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
        os.makedirs(folder, exist_ok=True)
        with open(path, "wb") as f:
            f.write(image_to_jpeg(raw))
        return path
    except Exception as e:
        log(f"tracker cover {key}/{era} failed ({url}): {e}")
        return None


def cover_for(tracker, era):
    """Your cover for this era, else the tracker sheet's cover, else your artist default."""
    if era:
        p = era_file(tracker, era)
        if os.path.exists(p):
            return p
        p = sheet_cover_file(tracker, era)
        if p:
            return p
    p = era_file(tracker, "_default")
    return p if os.path.exists(p) else None


# ------------------------------------------------------------------ files

def ffmpeg_exe():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return shutil.which("ffmpeg")


def free_path(path):
    if not os.path.exists(path):
        return path
    root, ext = os.path.splitext(path)
    i = 2
    while os.path.exists(f"{root} ({i}){ext}"):
        i += 1
    return f"{root} ({i}){ext}"


def converted_ext(mode):
    return ".mp3" if mode == "mp3" else ".m4a"


def convert_audio(src, mode, dst=None):
    exe = ffmpeg_exe()
    if not exe:
        raise RuntimeError("ffmpeg isn't available, so this file can't be converted.")
    dst = free_path(dst or (os.path.splitext(src)[0] + converted_ext(mode)))
    if mode == "mp3":
        codec = ["-c:a", "libmp3lame", "-b:a", "320k"]
    elif mode == "alac":
        codec = ["-c:a", "alac"]
    else:
        codec = ["-c:a", "aac", "-b:a", "256k"]
    cmd = [exe, "-hide_banner", "-loglevel", "error", "-y", "-i", src, "-vn", "-map", "0:a:0",
           "-map_metadata", "-1"] + codec + [dst]
    flags = 0x08000000 if os.name == "nt" else 0  # no console window
    r = subprocess.run(cmd, capture_output=True, text=True, creationflags=flags)
    if r.returncode != 0 or not os.path.exists(dst):
        raise RuntimeError("Conversion failed: " + (r.stderr or "").strip()[-400:])
    return dst


def clean_title_from_name(path):
    name = os.path.splitext(os.path.basename(path))[0]
    return re.sub(r"^\d+-\d+\s+", "", name).strip()


def inspect_file(path):
    import mutagen
    ext = os.path.splitext(path)[1].lower()
    info = {"path": path, "name": os.path.basename(path), "ext": ext, "exists": os.path.exists(path),
            "title": "", "artist": "", "duration": None,
            "needsConvert": ext in CONVERTIBLE, "supported": ext in TAGGABLE or ext in CONVERTIBLE}
    if not info["exists"]:
        return info
    try:
        f = mutagen.File(path, easy=True)
        if f is not None:
            if f.info and getattr(f.info, "length", None):
                info["duration"] = round(f.info.length)
            tags = f.tags or {}
            info["title"] = (tags.get("title") or [""])[0]
            info["artist"] = (tags.get("artist") or [""])[0]
    except Exception as e:
        log(f"inspect {path}: {e}")
    if not info["title"]:
        info["title"] = clean_title_from_name(path)
    return info


def write_tags(path, t, cover_bytes):
    ext = os.path.splitext(path)[1].lower()
    disc = int(t["disc"]) if t.get("disc") else 0
    total = int(t.get("discTotal") or 100)
    track = int(t["track"]) if t.get("track") else 0
    year = str(t.get("year") or "").strip()
    comment = str(t.get("comment") or "").strip()

    if ext == ".mp3":
        from mutagen.id3 import ID3, ID3NoHeaderError, TIT2, TPE1, TPE2, TALB, TRCK, TPOS, TCON, TDRC, APIC, COMM
        try:
            tags = ID3(path)
        except ID3NoHeaderError:
            tags = ID3()
        # art already in the file stays unless there's a cover to replace it
        for frame in ("TIT2", "TPE1", "TPE2", "TALB", "TRCK", "TPOS", "TCON", "TDRC", "TYER", "COMM") + (("APIC",) if cover_bytes else ()):
            tags.delall(frame)
        tags.add(TIT2(encoding=3, text=t["title"]))
        tags.add(TPE1(encoding=3, text=t["artist"]))
        if t.get("albumArtist"):
            tags.add(TPE2(encoding=3, text=t["albumArtist"]))
        if t.get("album"):
            tags.add(TALB(encoding=3, text=t["album"]))
        if track:
            tags.add(TRCK(encoding=3, text=str(track)))
        if disc:
            tags.add(TPOS(encoding=3, text=f"{disc}/{total}"))
        if t.get("genre"):
            tags.add(TCON(encoding=3, text=t["genre"]))
        if year:
            tags.add(TDRC(encoding=3, text=year))
        if comment:
            tags.add(COMM(encoding=3, lang="eng", desc="", text=comment))
        if cover_bytes:
            tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=cover_bytes))
        tags.save(path, v2_version=3)  # 2.3 is what Apple Music on Windows reads best

    elif ext == ".m4a":
        from mutagen.mp4 import MP4, MP4Cover
        f = MP4(path)
        if f.tags is None:
            f.add_tags()
        tg = f.tags
        tg["\xa9nam"] = [t["title"]]
        tg["\xa9ART"] = [t["artist"]]
        for k, v in (("aART", t.get("albumArtist")), ("\xa9alb", t.get("album")), ("\xa9cmt", comment)):
            if v:
                tg[k] = [v]
            elif k in tg:
                del tg[k]
        if track:
            tg["trkn"] = [(track, 0)]
        elif "trkn" in tg:
            del tg["trkn"]
        if disc:
            tg["disk"] = [(disc, total)]
        elif "disk" in tg:
            del tg["disk"]
        if t.get("genre"):
            tg["\xa9gen"] = [t["genre"]]
        elif "\xa9gen" in tg:
            del tg["\xa9gen"]
        if year:
            tg["\xa9day"] = [year]
        elif "\xa9day" in tg:
            del tg["\xa9day"]
        tg["cpil"] = False
        if cover_bytes:
            tg["covr"] = [MP4Cover(cover_bytes, imageformat=MP4Cover.FORMAT_JPEG)]
        f.save()
    else:
        raise RuntimeError(f"Can't tag {ext} files.")


# ------------------------------------------------------------------ discography folders
#
# The layout this mode writes, same as "1. Unreleased & Non-Streaming Discography":
#   <artist folder>\1-10. Pre-Alivë sessions\2. 1500 sessions\Song [V2] (feat. X) (prod. Y).mp3
#   <artist folder>\11. Alivë sessions\...
#   <artist folder>\Deleted Tracks, Features\Unreleased Features, SoundCloud\Singles, ...
# Folders that already exist are reused; a new era gets the next number.

NUM_PREFIX = re.compile(r"^(\d+(?:\.\d+)?)(?:-(\d+))?\.\s+")
TRACK_PREFIX = re.compile(r"^(\d{1,3})\.\s")
ALBUM_SUFFIX = re.compile(r"\s*\((Unreleased|Hosted)\)\s*$", re.I)
AUDIO_EXT = TAGGABLE | CONVERTIBLE

STANDARD_FOLDERS = [
    "Deleted Tracks",
    "Other Singles",
    "Features\\Unreleased Features",
    "Features\\Released Features (Non-Streaming)",
    "Features\\Deleted Features",
    "Features\\Mixed-Era Collabs",
    "SoundCloud\\Singles",
]


def slot_for(disc):
    s = load_settings()
    for slot in s["slots"]:
        if int(slot.get("disc") or 0) == int(disc or 0):
            return slot
    return None


def safe_name(text):
    text = re.sub(r'[<>:"/\\\\|?*\x00-\x1f]', "", str(text or ""))
    text = re.sub(r"\s+", " ", text).strip().rstrip(". ")
    return text[:180]


def artist_root(disc):
    s = load_settings()
    slot = slot_for(disc) or {}
    if slot.get("folder"):
        return slot["folder"]
    name = safe_name(slot.get("artist") or slot.get("name") or "Other artists") or "Other artists"
    return os.path.join(s["libraryFolder"], name)


def era_of_folder(name):
    base = NUM_PREFIX.sub("", name)
    return re.sub(r"\s+sessions$", "", base, flags=re.I).strip()


def read_album(path):
    try:
        import mutagen
        f = mutagen.File(path, easy=True)
        if f is not None and f.tags:
            return (f.tags.get("album") or [""])[0]
    except Exception:
        pass
    return ""


def scan_folders(disc):
    """Every folder under this artist's root (4 levels deep) with what's in it."""
    root = artist_root(disc)
    out = []
    if not os.path.isdir(root):
        return {"root": root, "exists": False, "folders": [], "nextEra": 1, "standard": STANDARD_FOLDERS}
    top_nums = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel = os.path.relpath(dirpath, root)
        depth = 0 if rel == "." else rel.count(os.sep) + 1
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        if depth >= 4:
            dirnames[:] = []
        if rel == ".":
            for d in dirnames:
                m = NUM_PREFIX.match(d + " ")
                if m:
                    top_nums.append(float(m.group(2) or m.group(1)))
            continue
        audio = sorted(f for f in filenames if os.path.splitext(f)[1].lower() in AUDIO_EXT)
        nums = [int(m.group(1)) for m in (TRACK_PREFIX.match(f) for f in audio) if m]
        albums = {}
        for f in audio[:4]:
            a = read_album(os.path.join(dirpath, f))
            if a:
                albums[a] = albums.get(a, 0) + 1
        sample = sorted(albums.items(), key=lambda x: -x[1])
        name = os.path.basename(dirpath)
        out.append({
            "rel": rel.replace("/", "\\"),
            "name": name,
            "era": era_of_folder(name),
            "depth": depth,
            "files": len(audio),
            "numbered": bool(audio) and len(nums) >= max(1, len(audio) // 2),
            "nextNum": (max(nums) + 1) if nums else 1,
            "albums": [a for a, _ in sample],
            "albumShared": bool(sample) and sample[0][1] >= max(2, (min(len(audio), 4) + 1) // 2),
            "sessions": name.lower().endswith(" sessions"),
        })
    next_era = int(max(top_nums)) + 1 if top_nums else 1
    return {"root": root, "exists": True, "folders": out, "nextEra": next_era, "standard": STANDARD_FOLDERS}


def remember_era_folder(tracker, era, rel):
    if not tracker or not era or not rel:
        return
    s = load_settings()
    m = s.get("eraFolders") or {}
    m.setdefault(tracker, {})[era] = rel
    s["eraFolders"] = m
    write_json(SETTINGS_FILE, s)


def target_dir(disc, rel):
    root = os.path.abspath(artist_root(disc))
    rel = str(rel or "").replace("/", os.sep).replace("\\", os.sep).strip(os.sep)
    parts = [safe_name(p) for p in rel.split(os.sep) if p.strip()]
    if not parts or any(p in ("", ".", "..") for p in parts):
        raise RuntimeError("Pick a folder for this song.")
    path = os.path.abspath(os.path.join(root, *parts))
    if not path.startswith(root + os.sep):
        raise RuntimeError("That folder is outside the artist's folder.")
    return path


def tag_into_folder(p, s, cover):
    """Discography mode: convert/copy/move the song into its folder under its new name, then tag it."""
    src = p["path"]
    ext = os.path.splitext(src)[1].lower()
    folder = target_dir(p["disc"], p.get("folder"))
    os.makedirs(folder, exist_ok=True)
    name = safe_name(p.get("fileName") or p["title"]) or "Untitled"
    converted = False
    if ext in CONVERTIBLE:
        mode = s.get("convertTo", "mp3")
        dst = convert_audio(src, mode, os.path.join(folder, name + converted_ext(mode)))
        converted = True
    elif ext in TAGGABLE:
        dst = os.path.join(folder, name + ext)
        if os.path.normcase(os.path.abspath(dst)) != os.path.normcase(os.path.abspath(src)):
            dst = free_path(dst)
            if s.get("afterTag") == "copy" or src.startswith(INCOMING_DIR):
                shutil.copy2(src, dst)
            else:
                shutil.move(src, dst)
    else:
        raise RuntimeError(f"{ext} files aren't supported.")
    t = {
        "title": p["title"].strip(),
        "artist": p["artist"].strip(),
        "album": (p.get("album") or "").strip(),
        "albumArtist": (p.get("albumArtist") or "").strip(),
        "genre": p.get("genre", s["genre"]),
        "year": p.get("year", ""),
        "track": p.get("track") or 0,
        "comment": s.get("comment", ""),
    }
    write_tags(dst, t, cover)
    remember_era_folder(p.get("coverKey"), p.get("era"), p.get("folder"))
    s = load_settings()
    s["lastSlot"] = int(p["disc"])
    save_settings(s)
    log(f"filed {src} -> {dst} era={p.get('era')}")
    return {"path": dst, "converted": converted, "hasCover": bool(cover), "folder": p.get("folder")}


def tag_file(p):
    s = load_settings()
    src = p["path"]
    if not os.path.exists(src):
        raise RuntimeError("That file isn't there anymore.")

    cover = None
    if p.get("coverOverride"):
        cover = image_to_jpeg(data_url_bytes(p["coverOverride"]))
    else:
        cp = cover_for(p.get("coverKey") or "", p.get("era") or "")
        if cp:
            with open(cp, "rb") as f:
                cover = f.read()

    if s.get("format", "discography") == "discography":
        return tag_into_folder(p, s, cover)

    ext = os.path.splitext(src)[1].lower()
    target = src
    converted = False
    if ext in CONVERTIBLE:
        mode = s.get("convertTo", "mp3")
        target = convert_audio(src, mode)
        converted = True
    elif ext not in TAGGABLE:
        raise RuntimeError(f"{ext} files aren't supported.")

    t = {
        "title": p["title"].strip(),
        "artist": p["artist"].strip(),
        "album": p.get("album") or s["album"],
        "albumArtist": p.get("albumArtist") or s["albumArtist"],
        "genre": p.get("genre", s["genre"]),
        "year": p.get("year", ""),
        "disc": p["disc"],
        "discTotal": s.get("discTotal", 100),
        "track": p["track"],
        "comment": s.get("comment", ""),
    }
    write_tags(target, t, cover)
    remember_track(p["disc"], p["track"])
    s["lastSlot"] = int(p["disc"])
    save_settings(s)
    log(f"tagged {target} -> {t['disc']}-{t['track']} {t['title']} / {t['artist']} era={p.get('era')}")
    return {"path": target, "converted": converted, "hasCover": bool(cover),
            "nextTrack": next_track(p["disc"])}


IS_MAC = sys.platform == "darwin"
AUDIO_TYPES = ["mp3", "m4a", "wav", "flac", "aif", "aiff", "ogg", "opus", "aac", "wma"]


def _osascript(*lines):
    """macOS: run an AppleScript dialog and return its output lines (empty if cancelled)."""
    cmd = ["osascript", "-e", "activate"]  # bring the dialog to the front
    for line in lines:
        cmd += ["-e", line]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        return []
    return [line for line in r.stdout.splitlines() if line.strip()]


def browse_folder():
    if WINDOW is not None:
        import webview
        kind = getattr(getattr(webview, "FileDialog", None), "FOLDER", None) or webview.FOLDER_DIALOG
        res = WINDOW.create_file_dialog(kind)
        return (res or [""])[0] if isinstance(res, (list, tuple)) else (res or "")
    if IS_MAC:
        # tkinter can't open windows off the main thread on macOS, so ask Finder instead
        out = _osascript('POSIX path of (choose folder with prompt "Pick a folder")')
        return out[0].rstrip("/") if out else ""
    import tkinter
    from tkinter import filedialog
    root = tkinter.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    res = filedialog.askdirectory(title="Pick a folder")
    root.destroy()
    return res or ""


def browse_files():
    types = "Audio files (*.mp3;*.m4a;*.wav;*.flac;*.aif;*.aiff;*.ogg;*.opus;*.aac;*.wma)"
    if WINDOW is not None:
        import webview
        kind = getattr(getattr(webview, "FileDialog", None), "OPEN", None) or webview.OPEN_DIALOG
        res = WINDOW.create_file_dialog(kind, allow_multiple=True, file_types=(types, "All files (*.*)"))
        return list(res or [])
    if IS_MAC:
        types = ", ".join(f'"{t}"' for t in AUDIO_TYPES)
        return _osascript(
            f'set picked to choose file with prompt "Pick songs" of type {{{types}}} with multiple selections allowed',
            'set out to ""',
            'repeat with f in picked',
            'set out to out & POSIX path of f & linefeed',
            'end repeat',
            'return out')
    import tkinter
    from tkinter import filedialog
    root = tkinter.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    res = filedialog.askopenfilenames(title="Pick songs", filetypes=[
        ("Audio", "*.mp3 *.m4a *.wav *.flac *.aif *.aiff *.ogg *.opus *.aac *.wma"), ("All files", "*.*")])
    root.destroy()
    return list(res or [])


def open_in_explorer(path):
    if os.name == "nt":
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
    elif IS_MAC:
        subprocess.Popen(["open", "-R", path] if os.path.exists(path) else ["open", os.path.dirname(path)])
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(path)])


# ------------------------------------------------------------------ http

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send_json(self, value, code=200):
        body = json.dumps(value).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def do_GET(self):
        try:
            u = urllib.parse.urlparse(self.path)
            q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
            if u.path in ("/", "/index.html"):
                with open(os.path.join(UI_DIR, "index.html"), "rb") as f:
                    data = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)
            elif u.path == "/api/state":
                self.send_json({"settings": load_settings(), "appMode": WINDOW is not None})
            elif u.path == "/api/trackers":
                self.send_json(tracker_artists(q.get("refresh") == "1"))
            elif u.path == "/api/songs":
                self.send_json(tracker_songs(q["artist"], q.get("refresh") == "1"))
            elif u.path == "/api/folders":
                self.send_json(scan_folders(q.get("disc") or 0))
            elif u.path == "/api/next":
                self.send_json({"track": next_track(q["disc"]), "used": sorted(used_numbers(q["disc"]))})
            elif u.path == "/api/covers":
                key = q.get("key", "")
                folder = os.path.join(COVER_DIR, cover_key(key))
                have = {}
                if os.path.isdir(folder):
                    for n in os.listdir(folder):
                        if n.endswith(".jpg"):
                            have[n] = int(os.path.getmtime(os.path.join(folder, n)))
                self.send_json({"files": have, "custom": custom_eras(key)})
            elif u.path == "/api/sheet-covers":
                d = sheet_covers(q.get("key", ""), q.get("refresh") == "1")
                self.send_json({"eras": list(d["covers"].keys()), "pending": d.get("pending", False),
                                "error": d.get("error")})
            elif u.path == "/sheet-cover":
                p = sheet_cover_file(q.get("key", ""), q.get("era", ""))
                if not p:
                    self.send_response(404)
                    self.end_headers()
                    return
                with open(p, "rb") as f:
                    data = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Cache-Control", "max-age=86400")
                self.end_headers()
                self.wfile.write(data)
            elif u.path == "/cover":
                p = era_file(q.get("key", ""), q.get("era", ""))
                if not os.path.exists(p):
                    self.send_response(404)
                    self.end_headers()
                    return
                with open(p, "rb") as f:
                    data = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)
            else:
                self.send_response(404)
                self.end_headers()
        except Exception as e:
            log(traceback.format_exc())
            self.send_json({"error": str(e)}, 500)

    def do_POST(self):
        try:
            u = urllib.parse.urlparse(self.path)
            if u.path == "/api/upload":
                # browser mode only: a dropped file has no path, so keep a copy to tag
                name = os.path.basename(urllib.parse.unquote(self.headers.get("X-Filename", "song")))
                dst = free_path(os.path.join(INCOMING_DIR, name))
                with open(dst, "wb") as f:
                    f.write(self.body())
                return self.send_json(inspect_file(dst))
            p = json.loads(self.body() or b"{}")
            if u.path == "/api/settings":
                self.send_json(save_settings(p))
            elif u.path == "/api/inspect":
                self.send_json([inspect_file(x) for x in p.get("paths", [])])
            elif u.path == "/api/browse":
                self.send_json([inspect_file(x) for x in browse_files()])
            elif u.path == "/api/save":
                self.send_json(tag_file(p))
            elif u.path == "/api/cover":
                path = era_file(p["key"], p["era"])
                if p.get("remove"):
                    if os.path.exists(path):
                        os.remove(path)
                else:
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    with open(path, "wb") as f:
                        f.write(image_to_jpeg(data_url_bytes(p["image"])))
                self.send_json({"ok": True})
            elif u.path == "/api/custom-eras":
                set_custom_eras(p["key"], p.get("eras", []))
                self.send_json({"ok": True})
            elif u.path == "/api/pick-folder":
                self.send_json({"path": browse_folder()})
            elif u.path == "/api/reveal":
                open_in_explorer(p["path"])
                self.send_json({"ok": True})
            else:
                self.send_json({"error": "unknown"}, 404)
        except Exception as e:
            log(traceback.format_exc())
            self.send_json({"error": str(e)}, 500)


def start_server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv.server_address[1]


def main():
    global WINDOW
    port = int(os.environ.get("TAGGER_PORT", "0"))
    if port:
        srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
    else:
        port = start_server()
    url = f"http://127.0.0.1:{port}/"

    browser_only = "--browser" in sys.argv
    webview = None
    if not browser_only:
        try:
            import webview  # noqa
        except Exception as e:
            log(f"pywebview unavailable, using browser: {e}")
            webview = None

    if webview is None:
        print("Local Files Tagger running at", url, "- close this window to stop it.")
        webbrowser.open(url)
        while True:
            time.sleep(3600)

    WINDOW = webview.create_window("Local Files Tagger", url, width=1320, height=880,
                                   min_size=(980, 660), background_color="#050906")

    def on_drop(e):
        try:
            files = (e.get("dataTransfer") or {}).get("files") or []
            paths = [f.get("pywebviewFullPath") for f in files if f.get("pywebviewFullPath")]
            if paths:
                WINDOW.evaluate_js(f"window.app && app.addPaths({json.dumps(paths)})")
        except Exception:
            log(traceback.format_exc())

    def bind():
        try:
            from webview.dom import DOMEventHandler
            WINDOW.dom.document.events.drop += DOMEventHandler(on_drop, True, True)
            WINDOW.evaluate_js("window.__nativeDrop = true")
        except Exception:
            log("native drop unavailable: " + traceback.format_exc())

    WINDOW.events.loaded += bind
    webview.start()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log(traceback.format_exc())
        raise
