"""
Background Media and Music Stream Manager for agy-rortings.

Supports streaming presets (Lofi, Synthwave, Ambient, Deep Space) or custom audio streams.
Supports Spotify (tracks, albums, playlists) and YouTube (videos, playlists) via yt-dlp.
Uses headless ffplay (with mpv fallback) and monitors Antigravity CLI lifecycle to auto-terminate
upon exit, preventing orphan background playback.
"""

import os
import sys
import signal
import json
import time
import shutil
import random
import re
import urllib.request
import subprocess
from typing import Optional, List, Dict, Tuple
from alvarez.core.models import StreamState

BASE_DIR = os.path.expanduser("~/.gemini/antigravity-cli")
STATE_FILE = os.path.join(BASE_DIR, "stream_state.json")
SESSION_FILE = os.path.join(BASE_DIR, "agy_active_session.json")
CONFIG_FILE = os.path.join(BASE_DIR, "stream_config.json")
TITLE_CACHE_FILE = os.path.join(BASE_DIR, "stream_title_cache.json")
SESSION_PLAYLIST_FILE = os.path.join(BASE_DIR, "stream_playlist.json")
DEFAULT_STREAMS_DIR = os.path.expanduser("~/Streams")

# Fallback built-in playlists
SYNTH_PLAYLIST = [
    {
        "id": "1OdQcWnzkpQ",
        "title": "1983 Heavenly Glitch (Synthwave)",
        "url": "https://youtu.be/1OdQcWnzkpQ",
    },
    {
        "id": "-aYe0sAcmLw",
        "title": "1999 Drift Beyond Earth (Synthwave)",
        "url": "https://youtu.be/-aYe0sAcmLw",
    },
    {
        "id": "NJf4A2gjZok",
        "title": "Midnight Chill Phonk Vol. 3",
        "url": "https://youtu.be/NJf4A2gjZok",
    },
    {
        "id": "SjFdWqcZ1WE",
        "title": "1981 Touched by the Ghost (Synthwave)",
        "url": "https://youtu.be/SjFdWqcZ1WE",
    },
]

AMBIENT_PLAYLIST = [
    {
        "id": "W-KDUgbnIOU",
        "title": "Medieval Fantasy Music 432Hz – Peaceful Journey",
        "url": "https://youtu.be/W-KDUgbnIOU",
    },
    {
        "id": "dJ5VtIE3kwU",
        "title": "The Quiet Night Medieval Village",
        "url": "https://youtu.be/dJ5VtIE3kwU",
    },
    {
        "id": "H7LboIeQN3c",
        "title": "A Quiet Medieval Winter – Gentle Celtic Music",
        "url": "https://youtu.be/H7LboIeQN3c",
    },
    {
        "id": "L1ADUN9DFxY",
        "title": "The Elf Maid's Rest at Riverside Tavern",
        "url": "https://youtu.be/L1ADUN9DFxY",
    },
    {
        "id": "6zvv1FBVYNQ",
        "title": "Elder Wizard Forest Rest",
        "url": "https://youtu.be/6zvv1FBVYNQ",
    },
]

LOFI_PLAYLIST = [
    {
        "url": "https://ice2.somafm.com/groovesalad-128-mp3",
        "title": "SomaFM Groove Salad (Lofi Chill Radio)"
    }
]

DEEP_STREAM = {
    "url": "https://ice2.somafm.com/deepspaceone-128-mp3",
    "title": "Deep Space One (Ambient Chill Radio)"
}

PRESETS = {
    "lofi": {
        "title": "Lofi Chill Stream",
        "type": "playlist",
        "playlist": LOFI_PLAYLIST
    },
    "ambient": {
        "title": "Medieval Fantasy Ambient Rotation",
        "type": "playlist",
        "playlist": AMBIENT_PLAYLIST
    },
    "synth": {
        "title": "Synthwave YouTube Rotation",
        "type": "playlist",
        "playlist": SYNTH_PLAYLIST
    },
    "synthwave": {
        "title": "Synthwave YouTube Rotation",
        "type": "playlist",
        "playlist": SYNTH_PLAYLIST
    },
    "deep": {
        "title": "Deep Space Chill",
        "type": "direct",
        "url": DEEP_STREAM["url"]
    }
}


def load_title_cache() -> Dict[str, str]:
    if os.path.exists(TITLE_CACHE_FILE):
        try:
            with open(TITLE_CACHE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_title_cache(cache: Dict[str, str]):
    try:
        os.makedirs(os.path.dirname(TITLE_CACHE_FILE), exist_ok=True)
        with open(TITLE_CACHE_FILE, "w") as f:
            json.dump(cache, f, indent=2)
    except Exception:
        pass


def resolve_spotify_entity(url: str) -> Optional[Dict[str, Any]]:
    m = re.search(r'spotify\.(?:com|link)/(?:embed/)?(track|playlist|album)/([a-zA-Z0-9]+)', url)
    if not m:
        m = re.search(r'spotify:(track|playlist|album):([a-zA-Z0-9]+)', url)
    if not m:
        return None
    kind, id_val = m.group(1), m.group(2)
    embed_url = f"https://open.spotify.com/embed/{kind}/{id_val}"
    req = urllib.request.Request(embed_url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        html = urllib.request.urlopen(req, timeout=12).read().decode("utf-8")
        m_json = re.search(r'<script id="(?:__NEXT_DATA__|initial-data)"[^>]*>(.*?)</script>', html)
        if not m_json:
            return None
        data = json.loads(m_json.group(1))
        entity = data.get("props", {}).get("pageProps", {}).get("state", {}).get("data", {}).get("entity", {})
        if kind == "track":
            title = entity.get("title")
            artists = ", ".join(a.get("name", "") for a in entity.get("artists", []))
            full_title = f"{artists} - {title}" if artists else title
            return {"kind": "track", "title": full_title, "query": f"ytsearch1:{full_title}"}
        else:
            title = entity.get("title") or f"Spotify {kind.capitalize()}"
            track_list = entity.get("trackList", [])
            items = []
            for t in track_list:
                item_title = f"{t.get('subtitle')} - {t.get('title')}" if t.get('subtitle') else t.get('title')
                items.append({"url": f"ytsearch1:{item_title}", "title": item_title})
            return {"kind": kind, "title": title, "items": items}
    except Exception:
        return None


def extract_media_info(url: str, fallback_title: Optional[str] = None) -> Tuple[Optional[str], Optional[str], str]:
    url_lower = url.lower()
    if "spotify.com/track/" in url_lower or "spotify:track:" in url_lower:
        entity = resolve_spotify_entity(url)
        if entity and entity.get("query"):
            url = entity["query"]
            fallback_title = fallback_title or entity.get("title")
            url_lower = url.lower()

    cache = load_title_cache()
    cached_title = cache.get(url)

    if "youtube.com" in url_lower or "youtu.be" in url_lower or url_lower.startswith("ytsearch"):
        ytdlp_bin = shutil.which("yt-dlp") or os.path.expanduser("~/.local/bin/yt-dlp")
        cmd = [ytdlp_bin, "--js-runtimes", "node", "-f", "bestaudio", "-g", "--print", "%(title)s", url]
        try:
            out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, timeout=20).decode().strip()
            lines = [l.strip() for l in out.split("\n") if l.strip()]
            extracted_title = lines[0] if lines else None
            stream_urls = [l for l in lines if l.startswith("http")]
            direct_url = stream_urls[0] if stream_urls else None
            title = fallback_title or extracted_title or cached_title or "YouTube Audio"
            if extracted_title and extracted_title != cached_title:
                cache[url] = extracted_title
                save_title_cache(cache)
            return direct_url, title, "youtube"
        except Exception:
            return None, fallback_title or cached_title, "youtube"

    return url, fallback_title or "Direct Stream", "direct"


def is_agy_active(target_pid: Optional[int] = None) -> bool:
    if target_pid and target_pid > 1:
        try:
            status_file = f"/proc/{target_pid}/status"
            if os.path.exists(status_file):
                with open(status_file, "r") as f:
                    for line in f:
                        if line.startswith("State:"):
                            st = line.split()[1]
                            return st not in ("Z", "X")
            os.kill(target_pid, 0)
            return True
        except Exception:
            return False

    if os.path.exists(SESSION_FILE):
        try:
            with open(SESSION_FILE, "r") as f:
                info = json.load(f)
            spid = info.get("pid")
            if spid and is_agy_active(spid):
                return True
        except Exception:
            pass

    try:
        import psutil
        for p in psutil.process_iter(['name', 'status']):
            try:
                if p.info['name'] == 'agy' and p.info['status'] not in (psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD):
                    return True
            except Exception:
                pass
    except Exception:
        pass
    return False


def get_first_active_agy_pid() -> Optional[int]:
    if os.path.exists(SESSION_FILE):
        try:
            with open(SESSION_FILE, "r") as f:
                info = json.load(f)
            spid = info.get("pid")
            if is_agy_active(spid):
                return spid
        except Exception:
            pass
    try:
        import psutil
        for p in psutil.process_iter(['name', 'status']):
            try:
                if p.info['name'] == 'agy' and p.info['status'] not in (psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD):
                    return p.pid
            except Exception:
                pass
    except Exception:
        pass
    return None


class StreamPlayer:
    """Manages audio playback processes and state synchronization."""

    def __init__(self, streams_dir: str = DEFAULT_STREAMS_DIR, state_file: str = STATE_FILE):
        self.streams_dir = os.path.expanduser(streams_dir)
        self.state_file = os.path.expanduser(state_file)

    def get_state(self) -> StreamState:
        if not os.path.exists(self.state_file):
            return StreamState()
        try:
            with open(self.state_file, "r") as f:
                data = json.load(f)
            state = StreamState(
                status=data.get("status", "stopped"),
                title=data.get("title", ""),
                preset=data.get("preset", "live"),
                pid=data.get("pid"),
                runner_pid=data.get("runner_pid"),
                url=data.get("url"),
                source=data.get("source"),
                index=data.get("index", 0),
                volume=data.get("volume", 100),
                timestamp=data.get("started_at", 0.0),
                resume_on_boot=data.get("resume_on_boot", False),
            )
            # Verify if process is actually alive
            is_alive = False
            if state.pid:
                try:
                    os.kill(state.pid, 0)
                    is_alive = True
                except OSError:
                    pass
            if not is_alive and state.runner_pid:
                try:
                    os.kill(state.runner_pid, 0)
                    is_alive = True
                except OSError:
                    pass
            if not is_alive and state.status == "playing":
                state.status = "stopped"
            return state
        except Exception:
            return StreamState()

    def save_state(self, state: StreamState):
        try:
            os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
            with open(self.state_file, "w") as f:
                json.dump({
                    "status": state.status,
                    "pid": state.pid,
                    "runner_pid": state.runner_pid,
                    "title": state.title,
                    "preset": state.preset,
                    "source": state.source,
                    "url": state.url,
                    "index": state.index,
                    "volume": state.volume,
                    "started_at": state.timestamp,
                    "resume_on_boot": state.resume_on_boot,
                }, f, indent=2)
        except Exception:
            pass

    def stop(self) -> bool:
        state = self.get_state()
        stopped = False
        pids_to_kill = [state.pid, state.runner_pid]
        for p in pids_to_kill:
            if p:
                try:
                    os.kill(p, signal.SIGTERM)
                    for _ in range(8):
                        time.sleep(0.05)
                        try:
                            os.kill(p, 0)
                        except OSError:
                            break
                    try:
                        os.kill(p, signal.SIGKILL)
                    except OSError:
                        pass
                    stopped = True
                except OSError:
                    pass

        # Cleanup orphan ffplay/mpv processes
        try:
            import psutil
            for proc in psutil.process_iter(['name', 'cmdline']):
                try:
                    name = proc.info['name']
                    cmd = " ".join(proc.info['cmdline'] or [])
                    if name in ('ffplay', 'mpv') and any(k in cmd for k in ('ice2.somafm', 'googlevideo.com', 'youtu')):
                        proc.kill()
                        stopped = True
                except Exception:
                    pass
        except Exception:
            pass

        self.save_state(StreamState(status="stopped", title="None", preset=state.preset, index=state.index, resume_on_boot=False))
        return stopped

    def get_available_presets(self) -> List[str]:
        """Dynamically discovers all available stream categories (folders in streams_dir + built-in PRESETS)."""
        presets = set(PRESETS.keys())
        # Alias synthwave to synth
        if "synthwave" in presets:
            presets.remove("synthwave")

        if os.path.isdir(self.streams_dir):
            try:
                for entry in os.listdir(self.streams_dir):
                    full_p = os.path.join(self.streams_dir, entry)
                    if os.path.isdir(full_p):
                        name = entry.lower()
                        if name == "synthwave":
                            name = "synth"
                        presets.add(name)
            except Exception:
                pass

        # Return sorted list with standard defaults prioritized first
        default_order = ["synth", "ambient", "lofi", "deep"]
        ordered = [p for p in default_order if p in presets]
        others = sorted([p for p in presets if p not in default_order])
        return ordered + others

    def get_playlist_for_category(self, category_name: str) -> Tuple[List[Dict[str, str]], Optional[str]]:
        cat_name = category_name.lower()
        if cat_name == "synthwave" and not os.path.isdir(os.path.join(self.streams_dir, cat_name)):
            cat_name = "synth"
        # Case-insensitive directory matching (e.g. "Popular" vs "popular")
        target_dir = None
        if os.path.isdir(self.streams_dir):
            for entry in os.listdir(self.streams_dir):
                if entry.lower() == cat_name and os.path.isdir(os.path.join(self.streams_dir, entry)):
                    target_dir = os.path.join(self.streams_dir, entry)
                    break

        cat_dir = target_dir or os.path.join(self.streams_dir, cat_name)
        streams_file = None

        if os.path.isdir(cat_dir):
            primary = os.path.join(cat_dir, "streams.txt")
            if os.path.exists(primary):
                streams_file = primary
            else:
                txts = [os.path.join(cat_dir, f) for f in os.listdir(cat_dir) if f.endswith(".txt")]
                if txts:
                    txts.sort()
                    streams_file = txts[0]

        playlist = []
        if streams_file and os.path.exists(streams_file):
            try:
                with open(streams_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if " | " in line:
                            parts = line.split(" | ", 1)
                            playlist.append({"url": parts[0].strip(), "title": parts[1].strip()})
                        else:
                            playlist.append({"url": line, "title": None})
            except Exception:
                pass

        if playlist:
            return playlist, streams_file

        preset = PRESETS.get(cat_name)
        if preset:
            if preset.get("type") == "playlist":
                return preset.get("playlist", []), None
            elif preset.get("url"):
                return [{"url": preset.get("url"), "title": preset.get("title")}], None

        return [], None

    def get_next_shuffle_index(self, category_name: str, playlist_len: int, current_index: Optional[int] = None) -> int:
        """
        Draws the next track index from a non-repeating shuffle deck.
        Guarantees all tracks in the playlist play before any repeats,
        and never plays the same track twice in a row across deck resets.
        """
        if playlist_len <= 1:
            return 0

        deck_file = os.path.join(BASE_DIR, f"shuffle_deck_{category_name.lower()}.json")
        deck: List[int] = []
        last_played: Optional[int] = current_index

        if os.path.exists(deck_file):
            try:
                with open(deck_file, "r") as df:
                    data = json.load(df)
                    deck = [i for i in data.get("remaining", []) if 0 <= i < playlist_len]
                    if last_played is None:
                        last_played = data.get("last_played")
            except Exception:
                deck = []

        if not deck:
            all_indices = list(range(playlist_len))
            random.shuffle(all_indices)
            # Guarantee the first track of the new deck doesn't repeat the last played track
            if last_played is not None and all_indices[0] == last_played and len(all_indices) > 1:
                swap_idx = random.randrange(1, len(all_indices))
                all_indices[0], all_indices[swap_idx] = all_indices[swap_idx], all_indices[0]
            deck = all_indices

        chosen_idx = deck.pop(0)

        try:
            os.makedirs(os.path.dirname(deck_file), exist_ok=True)
            with open(deck_file, "w") as df:
                json.dump({"remaining": deck, "last_played": chosen_idx}, df)
        except Exception:
            pass

        return chosen_idx

    def play_preset(self, preset_name: str, start_index: Optional[int] = None, standalone: bool = False) -> Optional[StreamState]:
        self.stop()
        time.sleep(0.1)

        preset_key = preset_name.lower()
        playlist, _ = self.get_playlist_for_category(preset_key)
        if not playlist:
            return None

        # Determine starting track with true non-repeating shuffle
        prev_idx = None
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r") as f:
                    prev_idx = json.load(f).get("index")
            except Exception:
                pass

        if start_index is not None and 0 <= start_index < len(playlist):
            chosen_idx = start_index
        else:
            chosen_idx = self.get_next_shuffle_index(preset_key, len(playlist), current_index=prev_idx)

        target_pid = get_first_active_agy_pid()

        # Spawn detached worker
        cli_bin = shutil.which("alvarez-stream") or sys.executable
        if cli_bin.endswith(".py") or "python" in cli_bin:
            cmd = [sys.executable, "-m", "alvarez.cli.stream", "--worker", "playlist", preset_key, str(chosen_idx)]
        else:
            cmd = [cli_bin, "--worker", "playlist", preset_key, str(chosen_idx)]

        if target_pid:
            cmd.append(str(target_pid))
        if standalone:
            cmd.append("--standalone")

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True
        )

        # Wait briefly for worker to save state
        for _ in range(25):
            time.sleep(0.08)
            cur = self.get_state()
            if cur.status == "playing":
                return cur

        return StreamState(status="playing", preset=preset_key, title=f"Loading {preset_key.capitalize()}...", runner_pid=proc.pid, resume_on_boot=True)

    def play_url(self, url: str, title: Optional[str] = None, standalone: bool = False) -> Optional[StreamState]:
        self.stop()
        time.sleep(0.1)

        target_pid = get_first_active_agy_pid()
        clean_title = title or "Custom Stream"

        cli_bin = shutil.which("alvarez-stream") or sys.executable
        if cli_bin.endswith(".py") or "python" in cli_bin:
            cmd = [sys.executable, "-m", "alvarez.cli.stream", "--worker", "direct", url, clean_title]
        else:
            cmd = [cli_bin, "--worker", "direct", url, clean_title]

        if target_pid:
            cmd.append(str(target_pid))
        if standalone:
            cmd.append("--standalone")

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True
        )

        for _ in range(25):
            time.sleep(0.08)
            cur = self.get_state()
            if cur.status == "playing":
                return cur

        return StreamState(status="playing", preset="custom", title=clean_title, runner_pid=proc.pid, resume_on_boot=True)

    def next_track(self) -> bool:
        state = self.get_state()
        if state.status != "playing" or not state.preset:
            return False
        playlist, _ = self.get_playlist_for_category(state.preset)
        if not playlist:
            return False
        new_idx = self.get_next_shuffle_index(state.preset, len(playlist), current_index=state.index)
        state.index = new_idx
        self.save_state(state)
        # Kill the child ffplay so worker advances immediately
        if state.pid:
            try:
                os.kill(state.pid, signal.SIGTERM)
                return True
            except OSError:
                pass
        return False

    def prev_track(self) -> bool:
        state = self.get_state()
        if state.status != "playing" or not state.preset:
            return False
        playlist, _ = self.get_playlist_for_category(state.preset)
        if not playlist:
            return False
        new_idx = (state.index - 1) % len(playlist)
        state.index = new_idx
        self.save_state(state)
        if state.pid:
            try:
                os.kill(state.pid, signal.SIGTERM)
                return True
            except OSError:
                pass
        return False

    def set_volume(self, volume_pct: int) -> bool:
        vol = max(0, min(100, volume_pct))
        try:
            subprocess.run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{vol/100:.2f}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            state = self.get_state()
            state.volume = vol
            self.save_state(state)
            return True
        except Exception:
            return False

    def run_playlist_worker(self, category_name: str, start_index: Optional[int] = None, target_pid: Optional[int] = None, standalone: bool = False):
        """Detached background runner for cycling playlist tracks with lifecycle watchdog and shuffle."""
        player_bin = shutil.which("ffplay") or shutil.which("mpv")
        if not player_bin:
            return

        playlist, _ = self.get_playlist_for_category(category_name)
        if not playlist:
            return

        if start_index is not None and 0 <= start_index < len(playlist):
            idx = start_index
        elif len(playlist) > 1:
            idx = random.randrange(len(playlist))
        else:
            idx = 0

        while True:
            if not standalone and target_pid and not is_agy_active(target_pid):
                self.save_state(StreamState(
                    status="stopped",
                    title="None",
                    preset=category_name,
                    index=idx,
                    resume_on_boot=True,
                    timestamp=time.time()
                ))
                return

            playlist, _ = self.get_playlist_for_category(category_name)
            if not playlist:
                time.sleep(2)
                continue

            idx = idx % len(playlist)
            track = playlist[idx]
            fallback_title = track.get("title")

            stream_url, real_title, src_type = extract_media_info(track["url"], fallback_title)
            if not standalone and target_pid and not is_agy_active(target_pid):
                self.save_state(StreamState(
                    status="stopped",
                    title=fallback_title or "Audio Stream",
                    preset=category_name,
                    url=track.get("url", ""),
                    source=src_type,
                    index=idx,
                    resume_on_boot=True,
                    timestamp=time.time()
                ))
                return

            if not stream_url:
                time.sleep(2)
                if len(playlist) > 1:
                    choices = [i for i in range(len(playlist)) if i != idx]
                    idx = random.choice(choices)
                else:
                    idx = 0
                continue

            title = f"{real_title} [{idx+1}/{len(playlist)}]"

            if "ffplay" in player_bin:
                cmd = [player_bin, "-nodisp", "-autoexit", "-loglevel", "quiet", stream_url]
            else:
                cmd = [player_bin, "--no-video", "--really-quiet", stream_url]

            try:
                player = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL
                )
            except Exception:
                self.stop()
                return

            state = StreamState(
                status="playing",
                pid=player.pid,
                runner_pid=os.getpid(),
                title=title,
                preset=category_name,
                source=src_type,
                url=track.get("url", ""),
                index=idx,
                timestamp=time.time(),
                resume_on_boot=True
            )
            self.save_state(state)

            while player.poll() is None:
                if not standalone and target_pid and not is_agy_active(target_pid):
                    try:
                        player.terminate()
                    except Exception:
                        pass
                    self.save_state(StreamState(
                        status="stopped",
                        title=title,
                        preset=category_name,
                        source=src_type,
                        url=track.get("url", ""),
                        index=idx,
                        resume_on_boot=True,
                        timestamp=time.time()
                    ))
                    return

                curr = self.get_state()
                if curr.status != "playing" or curr.runner_pid != os.getpid():
                    try:
                        player.terminate()
                    except Exception:
                        pass
                    return

                time.sleep(0.25)

            curr = self.get_state()
            if curr.status != "playing" or curr.runner_pid != os.getpid():
                break

            cur_pl, _ = self.get_playlist_for_category(category_name)
            pl_len = len(cur_pl) if cur_pl else len(playlist)
            curr_idx = curr.index
            if curr_idx != idx:
                idx = curr_idx % pl_len
            else:
                idx = self.get_next_shuffle_index(category_name, pl_len, current_index=idx)

    def run_direct_worker(self, url: str, title: str, target_pid: Optional[int] = None, standalone: bool = False):
        player_bin = shutil.which("ffplay") or shutil.which("mpv")
        if not player_bin:
            return

        direct_url, real_title, src = extract_media_info(url, fallback_title=title)
        if not direct_url:
            self.stop()
            return
        actual_title = real_title or title

        if "ffplay" in player_bin:
            cmd = [player_bin, "-nodisp", "-autoexit", "-loglevel", "quiet", direct_url]
        else:
            cmd = [player_bin, "--no-video", "--really-quiet", direct_url]

        try:
            player = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL
            )
        except Exception:
            self.stop()
            return

        state = StreamState(
            status="playing",
            pid=player.pid,
            runner_pid=os.getpid(),
            title=actual_title,
            preset="custom",
            source=src,
            url=url,
            index=0,
            timestamp=time.time(),
            resume_on_boot=True
        )
        self.save_state(state)

        while player.poll() is None:
            if not standalone and target_pid and not is_agy_active(target_pid):
                try:
                    player.terminate()
                except Exception:
                    pass
                self.save_state(StreamState(
                    status="stopped",
                    title=actual_title,
                    preset="custom",
                    source=src,
                    url=url,
                    index=0,
                    resume_on_boot=True,
                    timestamp=time.time()
                ))
                return

            curr = self.get_state()
            if curr.status != "playing" or curr.runner_pid != os.getpid():
                try:
                    player.terminate()
                except Exception:
                    pass
                return

            time.sleep(0.25)
