"""
Spotify playlist history tracker (core + command line).

Each check fetches the current state of a playlist, compares it with the previous
snapshot and records added, removed and unplayable tracks with a timestamp in
history.db. For the graphical interface run: python app.py

Command line usage:
    python tracker.py login                          Log in with your Spotify account (once)
    python tracker.py check <playlist url> [...]     Check playlists and record changes
    python tracker.py history [playlist url]         Show the recorded change history
    python tracker.py export [file.csv]              Export the full history to CSV

Requires config.json with CLIENT_ID and CLIENT_SECRET (see config.example.json).
"""

from __future__ import annotations

import base64
import csv
import json
import re
import secrets
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "history.db"
CONFIG_PATH = BASE_DIR / "config.json"

DEFAULT_MARKET = "TR"
REDIRECT_URI = "http://127.0.0.1:8888/callback"
SCOPES = "playlist-read-private playlist-read-collaborative"
API_URL = "https://api.spotify.com/v1"
AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"

EVENT_ADDED = "ADDED"
EVENT_REMOVED = "REMOVED"
EVENT_UNPLAYABLE = "UNPLAYABLE"
EVENT_PLAYABLE = "PLAYABLE_AGAIN"
EVENT_INITIAL = "INITIAL_SNAPSHOT"


class SpotifyError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class LoginRequired(SpotifyError):
    pass


def load_config() -> dict:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return {}


def save_config(config: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def market() -> str:
    return load_config().get("MARKET") or DEFAULT_MARKET


class SpotifyClient:
    def __init__(self, client_id: str | None, client_secret: str | None):
        if not client_id or not client_secret:
            raise SpotifyError("CLIENT_ID and CLIENT_SECRET are not set.")
        self.client_id = client_id
        self.client_secret = client_secret
        self._token: str | None = None
        self._token_expires = 0.0

    def _request_token(self, payload: dict) -> dict:
        credentials = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        request = urllib.request.Request(
            TOKEN_URL,
            data=urllib.parse.urlencode(payload).encode(),
            headers={"Authorization": f"Basic {credentials}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            body = error.read().decode(errors="replace")
            if "invalid_client" in body:
                raise SpotifyError("Invalid Client ID / Client Secret. Check them in Settings.")
            if "invalid_grant" in body:
                config = load_config()
                config.pop("REFRESH_TOKEN", None)
                save_config(config)
                raise LoginRequired("Your Spotify session has expired. Please log in again.")
            raise SpotifyError(f"Spotify login failed ({error.code}): {body}", error.code)
        except urllib.error.URLError as error:
            raise SpotifyError(f"Could not connect to Spotify: {error.reason}")

    def _store_token(self, data: dict) -> None:
        self._token = data["access_token"]
        self._token_expires = time.time() + data.get("expires_in", 3600) - 60

    def _access_token(self) -> str:
        if self._token and time.time() < self._token_expires:
            return self._token
        config = load_config()
        refresh_token = config.get("REFRESH_TOKEN")
        if not refresh_token:
            raise LoginRequired("Please log in with the “Log in with Spotify” button first.")
        data = self._request_token({"grant_type": "refresh_token", "refresh_token": refresh_token})
        if data.get("refresh_token") and data["refresh_token"] != refresh_token:
            config["REFRESH_TOKEN"] = data["refresh_token"]
            save_config(config)
        self._store_token(data)
        return self._token

    def login(self, timeout: int = 180) -> str:
        """Run the OAuth authorization code flow through the browser and store the session."""
        state = secrets.token_urlsafe(16)
        params: dict[str, str] = {}

        class CallbackHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                url = urllib.parse.urlparse(self.path)
                if url.path != "/callback":
                    self.send_response(404)
                    self.end_headers()
                    return
                params.update({k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()})
                message = ("Login complete. You can close this tab and return to the app." if "code" in params
                           else "Login was cancelled or failed.")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(f"<html><body style='font-family:sans-serif;padding:40px'>"
                                 f"<h2>{message}</h2></body></html>".encode("utf-8"))

            def log_message(self, *args):
                pass

        try:
            server = HTTPServer(("127.0.0.1", 8888), CallbackHandler)
        except OSError:
            raise SpotifyError("Port 8888 is in use. Close any other open login window and try again.")
        server.timeout = 1
        webbrowser.open(AUTH_URL + "?" + urllib.parse.urlencode({
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": REDIRECT_URI,
            "scope": SCOPES,
            "state": state,
        }))
        deadline = time.time() + timeout
        try:
            while "code" not in params and "error" not in params and time.time() < deadline:
                server.handle_request()
        finally:
            server.server_close()

        if "error" in params:
            if params["error"] == "access_denied":
                raise SpotifyError("Login was cancelled.")
            raise SpotifyError(f"Spotify login failed: {params['error']}")
        if "code" not in params:
            raise SpotifyError("Login timed out. If the authorization page did not open, make sure the "
                               f"Redirect URI in the Dashboard is exactly {REDIRECT_URI}")
        if params.get("state") != state:
            raise SpotifyError("Login could not be verified. Please try again.")

        data = self._request_token({
            "grant_type": "authorization_code",
            "code": params["code"],
            "redirect_uri": REDIRECT_URI,
        })
        self._store_token(data)
        me = self.get("/me")
        config = load_config()
        config["REFRESH_TOKEN"] = data["refresh_token"]
        config["USER"] = me.get("display_name") or me.get("id")
        save_config(config)
        return config["USER"]

    def get(self, url: str, retries: int = 3) -> dict:
        if not url.startswith("http"):
            url = API_URL + url
        for attempt in range(retries):
            request = urllib.request.Request(url, headers={"Authorization": f"Bearer {self._access_token()}"})
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    return json.load(response)
            except urllib.error.HTTPError as error:
                if error.code == 429 and attempt < retries - 1:
                    time.sleep(int(error.headers.get("Retry-After", "2")))
                    continue
                body = error.read().decode(errors="replace")
                raise SpotifyError(f"Spotify API error {error.code}: {body}", error.code) from error
            except urllib.error.URLError as error:
                raise SpotifyError(f"Could not connect to Spotify: {error.reason}")

    def my_playlists(self) -> tuple[list[dict], list[dict]]:
        """Return (readable, others) playlists of the logged-in user.

        Spotify only exposes tracks of playlists the user owns or collaborates on,
        so followed playlists of other users are returned separately.
        """
        me = self.get("/me")
        readable, others = [], []
        url = "/me/playlists?limit=50"
        while url:
            page = self.get(url)
            for item in page.get("items") or []:
                if not item or not item.get("id"):
                    continue
                owner = item.get("owner") or {}
                total = (item.get("items") or item.get("tracks") or {}).get("total")
                playlist = {
                    "id": item["id"],
                    "name": item.get("name") or item["id"],
                    "owner": owner.get("display_name") or owner.get("id") or "",
                    "track_count": total if total is not None else "",
                }
                is_readable = owner.get("id") == me.get("id") or item.get("collaborative")
                (readable if is_readable else others).append(playlist)
            url = page.get("next")
        return readable, others

    def playlist_name(self, playlist_id: str) -> str:
        try:
            return self.get(f"/playlists/{playlist_id}?fields=name").get("name") or playlist_id
        except SpotifyError as error:
            if error.status == 404:
                raise SpotifyError("Playlist not found. Is the link correct?", 404)
            raise

    def playlist_tracks(self, playlist_id: str) -> list[dict]:
        query = urllib.parse.urlencode({"limit": 100, "market": market()})
        try:
            page = self.get(f"/playlists/{playlist_id}/items?{query}")
        except SpotifyError as error:
            if error.status == 403:
                raise SpotifyError("Spotify does not expose the tracks of this playlist: only playlists you "
                                   "own or collaborate on can be checked.", 403)
            raise
        tracks = []
        while True:
            for entry in page.get("items") or []:
                track = entry.get("track") or entry.get("item")
                if not track or not track.get("uri"):
                    continue
                tracks.append({
                    # added_at changes when a track is removed and re-added, so it is part of the key
                    "key": f"{track['uri']}|{entry.get('added_at')}",
                    "uri": track["uri"],
                    "name": track.get("name") or "(untitled)",
                    "artist": ", ".join(a["name"] for a in track.get("artists") or [] if a.get("name")),
                    "album": (track.get("album") or {}).get("name") or "",
                    "added_at": entry.get("added_at") or "",
                    "added_by": (entry.get("added_by") or {}).get("id") or "",
                    "playable": 0 if track.get("is_playable") is False else 1,
                })
            if not page.get("next"):
                return tracks
            page = self.get(page["next"])


def connect() -> SpotifyClient:
    config = load_config()
    return SpotifyClient(config.get("CLIENT_ID"), config.get("CLIENT_SECRET"))


def parse_playlist_id(link: str) -> str:
    match = re.search(r"playlist[/:]([A-Za-z0-9]{22})", link)
    if match:
        return match.group(1)
    if re.fullmatch(r"[A-Za-z0-9]{22}", link.strip()):
        return link.strip()
    raise SpotifyError(f"Not a valid Spotify playlist link: {link}")


SCHEMA = """
CREATE TABLE IF NOT EXISTS playlists (
    playlist_id TEXT PRIMARY KEY,
    name TEXT,
    last_checked TEXT,
    tracked INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS tracks (
    playlist_id TEXT,
    key TEXT,
    uri TEXT, name TEXT, artist TEXT, album TEXT,
    added_at TEXT, added_by TEXT,
    playable INTEGER,
    first_seen TEXT,
    last_seen TEXT,
    in_playlist INTEGER,
    PRIMARY KEY (playlist_id, key)
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    playlist_id TEXT,
    checked_at TEXT,
    event TEXT,
    uri TEXT, name TEXT, artist TEXT, album TEXT,
    added_at TEXT
);
"""


def open_db() -> sqlite3.Connection:
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    return db


def tracked_playlists() -> list[dict]:
    with open_db() as db:
        return [dict(r) for r in db.execute("SELECT * FROM playlists WHERE tracked = 1 ORDER BY name")]


def set_tracked(playlist_id: str, name: str, tracked: bool) -> None:
    with open_db() as db:
        db.execute(
            "INSERT INTO playlists (playlist_id, name, tracked) VALUES (?, ?, ?) "
            "ON CONFLICT(playlist_id) DO UPDATE SET name = excluded.name, tracked = excluded.tracked",
            (playlist_id, name, int(tracked)),
        )


def _write_event(db: sqlite3.Connection, playlist_id: str, checked_at: str, event: str, track: dict) -> None:
    db.execute(
        "INSERT INTO events (playlist_id, checked_at, event, uri, name, artist, album, added_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (playlist_id, checked_at, event, track.get("uri", ""), track.get("name", ""),
         track.get("artist", ""), track.get("album", ""), track.get("added_at", "")),
    )


def get_events(playlist_id: str | None = None) -> list[dict]:
    query = "SELECT e.*, p.name AS playlist FROM events e LEFT JOIN playlists p USING (playlist_id)"
    params: tuple = ()
    if playlist_id:
        query += " WHERE e.playlist_id = ?"
        params = (playlist_id,)
    with open_db() as db:
        return [dict(r) for r in db.execute(query + " ORDER BY e.id DESC", params)]


def format_date(iso: str | None) -> str:
    """Convert an ISO timestamp to a readable local time."""
    if not iso:
        return ""
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return iso


def track_label(track: dict) -> str:
    return f"{track['artist']} - {track['name']}" if track.get("artist") else track.get("name", "")


def check_playlist(client: SpotifyClient, playlist_id: str) -> dict:
    """Fetch a playlist, diff it against the previous snapshot, record events and return the result."""
    name = client.playlist_name(playlist_id)
    current = client.playlist_tracks(playlist_id)
    now = datetime.now().astimezone().isoformat(timespec="seconds")

    with open_db() as db:
        row = db.execute("SELECT last_checked FROM playlists WHERE playlist_id = ?", (playlist_id,)).fetchone()
        first_check = row is None or row["last_checked"] is None
        db.execute(
            "INSERT INTO playlists (playlist_id, name, last_checked) VALUES (?, ?, ?) "
            "ON CONFLICT(playlist_id) DO UPDATE SET name = excluded.name, last_checked = excluded.last_checked",
            (playlist_id, name, now),
        )

        previous = {
            r["key"]: dict(r)
            for r in db.execute("SELECT * FROM tracks WHERE playlist_id = ? AND in_playlist = 1", (playlist_id,))
        }
        current_by_key = {t["key"]: t for t in current}
        kept = [(previous[k], t) for k, t in current_by_key.items() if k in previous]

        result = {
            "playlist_id": playlist_id,
            "name": name,
            "total": len(current),
            "checked_at": now,
            "first_check": first_check,
            "added": [t for k, t in current_by_key.items() if k not in previous],
            "removed": [t for k, t in previous.items() if k not in current_by_key],
            "unplayable": [t for old, t in kept if old["playable"] and not t["playable"]],
            "playable_again": [t for old, t in kept if not old["playable"] and t["playable"]],
            "unavailable": [t for t in current if not t["playable"]],
        }

        for t in current:
            db.execute(
                "INSERT INTO tracks (playlist_id, key, uri, name, artist, album, added_at, added_by, "
                "playable, first_seen, last_seen, in_playlist) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1) "
                "ON CONFLICT(playlist_id, key) DO UPDATE SET name = excluded.name, artist = excluded.artist, "
                "album = excluded.album, playable = excluded.playable, "
                "last_seen = excluded.last_seen, in_playlist = 1",
                (playlist_id, t["key"], t["uri"], t["name"], t["artist"], t["album"], t["added_at"],
                 t["added_by"], t["playable"], now, now),
            )
        for t in result["removed"]:
            db.execute("UPDATE tracks SET in_playlist = 0 WHERE playlist_id = ? AND key = ?",
                       (playlist_id, t["key"]))

        if first_check:
            _write_event(db, playlist_id, now, EVENT_INITIAL, {"name": f"{len(current)} tracks recorded"})
            result.update(added=[], removed=[], unplayable=[], playable_again=[])
        else:
            for event, field in ((EVENT_ADDED, "added"), (EVENT_REMOVED, "removed"),
                                 (EVENT_UNPLAYABLE, "unplayable"), (EVENT_PLAYABLE, "playable_again")):
                for t in result[field]:
                    _write_event(db, playlist_id, now, event, t)
    return result


def export_csv(path: str = "history.csv") -> int:
    rows = list(reversed(get_events()))
    # utf-8-sig and ';' let Excel open the file directly with correct encoding in most locales
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(["Checked at", "Playlist", "Event", "Artist", "Track", "Album", "Added to playlist", "URI"])
        for r in rows:
            writer.writerow([format_date(r["checked_at"]), r["playlist"], r["event"], r["artist"], r["name"],
                             r["album"], format_date(r["added_at"]), r["uri"]])
    return len(rows)


def _print_result(result: dict) -> None:
    print(f"Playlist: {result['name']}  ({result['total']} tracks)")
    if result["first_check"]:
        print("Initial snapshot recorded. Changes will be tracked from the next check on.")
        for t in result["unavailable"]:
            print(f"   ! Not playable in {market()}: {track_label(t)}")
        return
    if not any(result[k] for k in ("added", "removed", "unplayable", "playable_again")):
        print("No changes.")
    for t in result["added"]:
        print(f"  + ADDED        {track_label(t)}   (added: {format_date(t['added_at'])})")
    for t in result["removed"]:
        print(f"  - REMOVED      {track_label(t)}   (added: {format_date(t['added_at'])}, "
              f"last seen: {format_date(t['last_seen'])})")
    for t in result["unplayable"]:
        print(f"  ! UNPLAYABLE   {track_label(t)}")
    for t in result["playable_again"]:
        print(f"  ✓ PLAYABLE      {track_label(t)}")


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        return
    command, args = sys.argv[1].lower(), sys.argv[2:]
    try:
        if command == "login":
            print(f"Logged in as: {connect().login()}")
        elif command == "check" and args:
            client = connect()
            for link in args:
                _print_result(check_playlist(client, parse_playlist_id(link)))
        elif command == "history":
            playlist_id = parse_playlist_id(args[0]) if args else None
            for r in reversed(get_events(playlist_id)):
                added = f"  (added: {format_date(r['added_at'])})" if r["added_at"] else ""
                print(f"{format_date(r['checked_at'])}  [{r['playlist']}]  {r['event']:<18} {track_label(r)}{added}")
        elif command == "export":
            path = args[0] if args else "history.csv"
            print(f"{export_csv(path)} records written to '{path}'.")
        else:
            print(__doc__)
    except SpotifyError as error:
        sys.exit(str(error))


if __name__ == "__main__":
    main()
