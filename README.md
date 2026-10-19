# Spotify Playlist Tracker

Are tracks silently disappearing from your Spotify playlists? This app keeps a history of your playlists:
which track was **added when**, which one was **removed when**, and which one became **unplayable**.

Spotify does not record when a track leaves a playlist. On every check the app saves a snapshot of the playlist
and compares it with the previous one, so the title, artist and original add date of every vanished track stay on record.

## Features

- Log in with your Spotify account and load your playlists (including private ones) with one click
- Select the playlists you want to track
- A change report on every check:
  - **+ Added**: new tracks and when they were added
  - **− Removed**: tracks that disappeared, when they were added and when they were last seen
  - **! Unplayable**: tracks still in the playlist but no longer playable in your market (expired licenses are greyed out or hidden by Spotify; most "vanished" tracks are actually these)
  - **✓ Playable again**: tracks that became playable again
- History view filterable by playlist and event type
- Export the history to a CSV file that opens in Excel
- No dependencies: only the Python standard library is used

## Requirements

- Windows, macOS or Linux
- [Python 3.9+](https://www.python.org/downloads/). On Windows, tick "Add Python to PATH" during installation.
- A Spotify account. Spotify requires the account that creates a developer app to be **Premium**.

## Setup

### 1. Get the code

```
git clone https://github.com/Xendoksia/Spotify-Follow-Ur-List.git
```

or download it via **Code → Download ZIP** on GitHub and extract it.

### 2. Create a Spotify developer app (one time)

1. Log in at https://developer.spotify.com/dashboard with your Spotify account.
2. Click **Create app** and fill in the form:
   - **App name / description:** anything you like
   - **Redirect URI:** enter `http://127.0.0.1:8888/callback` and click **Add**. It must match exactly.
   - **Which API/SDKs:** tick **Web API**
3. Save, then copy the **Client ID** and **Client Secret** from the app's **Settings** page.

### 3. Run the app

```
python app.py
```

On Windows you can also double-click **`Spotify Playlist Tracker.bat`**.

On first launch, enter your Client ID and Client Secret in the settings window. Then click **Log in with Spotify**
and approve access in the browser. You only need to do this once; the app remembers your session.

## Usage

1. Click **Load my Spotify playlists**.
2. Click the **☐** box of each playlist you want to track. Double-click a playlist to open it in Spotify.
3. Click **▶ Check selected**.
4. See the results in the **History** tab and optionally **Export CSV**.

The first check of each playlist records an initial snapshot. Changes appear from the second check on.
The more often you check, the more precisely you know when a track was removed.

### Command line

```
python tracker.py login                                          # log in with Spotify
python tracker.py check https://open.spotify.com/playlist/...    # check a playlist
python tracker.py history                                        # print the history
python tracker.py export history.csv                             # export the history to CSV
```

To use the command line without the GUI, copy `config.example.json` to `config.json` and fill in
your Client ID and Client Secret.

### Configuration

| Key | Description |
|---|---|
| `CLIENT_ID` | Client ID of your Spotify developer app |
| `CLIENT_SECRET` | Client Secret of your Spotify developer app |
| `MARKET` | Country code used to check playability (optional, default `TR`) |

## Limitations

- **Your own playlists only:** under Spotify's 2026 API rules the app can only read tracks of playlists you
  **own or collaborate on**. Playlists of other users cannot be checked, even if you follow them.
- **Check frequency:** the app only checks when you run it. A removal is reported as having happened
  "between the previous check and this one".
- **User limit:** in development mode, at most 5 users can log in to a Spotify app, so everyone should
  create their own Client ID.

## Data and privacy

All data stays on your computer, in the app folder:

| File | Contents |
|---|---|
| `config.json` | Client ID, Client Secret and Spotify session. **Do not share it.** |
| `history.db` | History of your playlists and changes (SQLite) |

Both are listed in `.gitignore` and are never committed. The app does not connect to anything other than Spotify.

## Files

| File | Description |
|---|---|
| `app.py` | Graphical interface (tkinter) |
| `tracker.py` | Spotify client, diff logic, database and command line |
| `Spotify Playlist Tracker.bat` | Double-click launcher for Windows |
| `config.example.json` | Sample configuration file |
