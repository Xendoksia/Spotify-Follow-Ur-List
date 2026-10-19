"""
Spotify Playlist Tracker - graphical interface.

Run with:  python app.py
(or double-click "Spotify Playlist Tracker.bat" on Windows)
"""

import threading
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox, ttk

import tracker
from tracker import LoginRequired, SpotifyError, format_date, track_label

EVENT_LABELS = {
    tracker.EVENT_ADDED: "+ Added",
    tracker.EVENT_REMOVED: "− Removed",
    tracker.EVENT_UNPLAYABLE: "! Unplayable",
    tracker.EVENT_PLAYABLE: "✓ Playable again",
    tracker.EVENT_INITIAL: "• Initial snapshot",
}
EVENT_COLORS = {
    tracker.EVENT_ADDED: "#1a7f37",
    tracker.EVENT_REMOVED: "#c62828",
    tracker.EVENT_UNPLAYABLE: "#b26a00",
    tracker.EVENT_PLAYABLE: "#1565c0",
    tracker.EVENT_INITIAL: "#666666",
}
CHECKED, UNCHECKED = "☑", "☐"
ALL = "All"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Spotify Playlist Tracker")
        self.geometry("1050x680")
        self.minsize(800, 500)

        self.playlists: dict[str, dict] = {}
        self.busy = False

        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Treeview", rowheight=24)

        self._build_ui()
        self._load_tracked()
        self._refresh_history()

        if not self._has_credentials():
            self.after(200, self._open_settings)

    # ------------------------------------------------------------ layout

    def _build_ui(self):
        header = ttk.Frame(self, padding=(10, 8, 10, 0))
        header.pack(fill="x")
        ttk.Button(header, text="⚙ Settings", command=self._open_settings).pack(side="right")
        self.login_button = ttk.Button(header, command=self._login)
        self.login_button.pack(side="right", padx=6)
        self.login_label = ttk.Label(header, foreground="#1a7f37")
        self.login_label.pack(side="right", padx=6)
        self._update_login_status()
        self.status_label = ttk.Label(header, text="Ready.", foreground="#555")
        self.status_label.pack(side="left")

        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True, padx=10, pady=8)
        self._build_playlists_tab()
        self._build_history_tab()

    def _build_playlists_tab(self):
        tab = ttk.Frame(self.tabs, padding=10)
        self.tabs.add(tab, text="  Playlists  ")

        form = ttk.Frame(tab)
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)

        self.fetch_button = ttk.Button(form, text="Load my Spotify playlists", command=self._load_my_playlists)
        self.fetch_button.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))

        ttk.Label(form, text="or playlist link:").grid(row=1, column=0, sticky="w", pady=2)
        self.link_entry = ttk.Entry(form)
        self.link_entry.grid(row=1, column=1, sticky="ew", padx=6, pady=2)
        self.link_entry.bind("<Return>", lambda e: self._add_by_link())
        self.add_button = ttk.Button(form, text="Add", command=self._add_by_link)
        self.add_button.grid(row=1, column=2, sticky="ew", pady=2)

        ttk.Label(
            tab, foreground="#666",
            text="Tick the playlists you want to track, then press “Check selected”.",
        ).pack(anchor="w", pady=(10, 4))

        table_frame = ttk.Frame(tab)
        table_frame.pack(fill="both", expand=True)
        columns = ("tracked", "name", "owner", "tracks", "last_checked")
        self.playlist_table = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")
        for column, heading, width, anchor in (
            ("tracked", "Track", 60, "center"),
            ("name", "Playlist", 380, "w"),
            ("owner", "Owner", 160, "w"),
            ("tracks", "Tracks", 70, "center"),
            ("last_checked", "Last checked", 140, "center"),
        ):
            self.playlist_table.heading(column, text=heading)
            self.playlist_table.column(column, width=width, anchor=anchor, stretch=(column == "name"))
        self.playlist_table.tag_configure("tracked", background="#e8f5e9")
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.playlist_table.yview)
        self.playlist_table.configure(yscrollcommand=scrollbar.set)
        self.playlist_table.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.playlist_table.bind("<Button-1>", self._on_row_click)
        self.playlist_table.bind("<space>", lambda e: self._toggle_selected())
        self.playlist_table.bind("<Double-1>", self._open_in_spotify)

        footer = ttk.Frame(tab)
        footer.pack(fill="x", pady=(8, 0))
        ttk.Button(footer, text="Select all", command=lambda: self._set_all(True)).pack(side="left")
        ttk.Button(footer, text="Clear selection", command=lambda: self._set_all(False)).pack(side="left", padx=6)
        self.check_button = ttk.Button(footer, text="▶  Check selected", command=self._check)
        self.check_button.pack(side="right")

        ttk.Label(tab, text="Last check result:").pack(anchor="w", pady=(10, 2))
        self.result_box = tk.Text(tab, height=9, wrap="word", font=("Segoe UI", 10),
                                  relief="solid", borderwidth=1, state="disabled")
        self.result_box.pack(fill="x")
        for event, color in EVENT_COLORS.items():
            self.result_box.tag_configure(event, foreground=color)
        self.result_box.tag_configure("heading", font=("Segoe UI", 10, "bold"))

    def _build_history_tab(self):
        tab = ttk.Frame(self.tabs, padding=10)
        self.tabs.add(tab, text="  History  ")

        toolbar = ttk.Frame(tab)
        toolbar.pack(fill="x")
        ttk.Label(toolbar, text="Playlist:").pack(side="left")
        self.playlist_filter = ttk.Combobox(toolbar, state="readonly", width=40)
        self.playlist_filter.pack(side="left", padx=6)
        self.playlist_filter.bind("<<ComboboxSelected>>", lambda e: self._refresh_history())
        ttk.Label(toolbar, text="Event:").pack(side="left", padx=(12, 0))
        self.event_filter = ttk.Combobox(toolbar, state="readonly", width=18,
                                         values=[ALL] + list(EVENT_LABELS.values()))
        self.event_filter.current(0)
        self.event_filter.pack(side="left", padx=6)
        self.event_filter.bind("<<ComboboxSelected>>", lambda e: self._refresh_history())
        ttk.Button(toolbar, text="Export CSV", command=self._export_csv).pack(side="right")
        ttk.Button(toolbar, text="Refresh", command=self._refresh_history).pack(side="right", padx=6)

        table_frame = ttk.Frame(tab)
        table_frame.pack(fill="both", expand=True, pady=(8, 0))
        columns = ("checked_at", "playlist", "event", "track", "added_at")
        self.history_table = ttk.Treeview(table_frame, columns=columns, show="headings")
        for column, heading, width in (
            ("checked_at", "Detected", 130),
            ("playlist", "Playlist", 200),
            ("event", "Event", 120),
            ("track", "Track", 400),
            ("added_at", "Added to playlist", 130),
        ):
            self.history_table.heading(column, text=heading)
            self.history_table.column(column, width=width, stretch=(column == "track"))
        for event, color in EVENT_COLORS.items():
            self.history_table.tag_configure(event, foreground=color)
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.history_table.yview)
        self.history_table.configure(yscrollcommand=scrollbar.set)
        self.history_table.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        ttk.Label(
            tab, foreground="#666",
            text="“Detected” is the time of the check that noticed the change. "
                 "The change happened between the previous check and this time.",
        ).pack(anchor="w", pady=(6, 0))

    # ------------------------------------------------------------ helpers

    def _has_credentials(self):
        config = tracker.load_config()
        return bool(config.get("CLIENT_ID") and config.get("CLIENT_SECRET"))

    def _set_status(self, text):
        self.status_label.configure(text=text)

    def _set_busy(self, busy):
        self.busy = busy
        state = "disabled" if busy else "normal"
        for button in (self.fetch_button, self.add_button, self.check_button, self.login_button):
            button.configure(state=state)
        self.configure(cursor="watch" if busy else "")

    def _run_in_background(self, task, on_success):
        """Run network work on a worker thread so the window stays responsive."""
        if self.busy:
            return
        if not self._has_credentials():
            self._open_settings()
            return
        self._set_busy(True)

        def worker():
            result, error, login_required = None, None, False
            try:
                result = task()
            except LoginRequired as e:
                error, login_required = str(e), True
            except SpotifyError as e:
                error = str(e)
            except Exception as e:
                error = f"Unexpected error: {e!r}"
            self.after(0, lambda: self._on_task_done(on_success, result, error, login_required))

        threading.Thread(target=worker, daemon=True).start()

    def _on_task_done(self, on_success, result, error, login_required):
        self._set_busy(False)
        self._update_login_status()
        if login_required:
            self._set_status("Login required.")
            if messagebox.askyesno("Login required", f"{error}\n\nLog in with Spotify now?", parent=self):
                self._login()
        elif error:
            self._set_status("Error.")
            messagebox.showerror("Error", error, parent=self)
        else:
            on_success(result)

    # ------------------------------------------------------------ playlists

    def _load_tracked(self):
        for p in tracker.tracked_playlists():
            self.playlists[p["playlist_id"]] = {
                "name": p["name"], "owner": "", "track_count": "",
                "tracked": True, "last_checked": p["last_checked"],
            }
        self._render_playlists()

    def _render_playlists(self):
        self.playlist_table.delete(*self.playlist_table.get_children())
        ordered = sorted(self.playlists.items(), key=lambda x: (not x[1]["tracked"], x[1]["name"].lower()))
        for playlist_id, p in ordered:
            self.playlist_table.insert(
                "", "end", iid=playlist_id, tags=("tracked",) if p["tracked"] else (),
                values=(CHECKED if p["tracked"] else UNCHECKED, p["name"], p["owner"],
                        p["track_count"], format_date(p["last_checked"]) or "—"),
            )
        tracked = [p["name"] for p in self.playlists.values() if p["tracked"]]
        self.playlist_filter.configure(values=[ALL] + sorted(tracked, key=str.lower))
        if not self.playlist_filter.get():
            self.playlist_filter.current(0)
        self.check_button.configure(text=f"▶  Check selected ({len(tracked)})")

    def _toggle(self, playlist_id):
        p = self.playlists[playlist_id]
        p["tracked"] = not p["tracked"]
        tracker.set_tracked(playlist_id, p["name"], p["tracked"])
        self._render_playlists()
        if self.playlist_table.exists(playlist_id):
            self.playlist_table.selection_set(playlist_id)
            self.playlist_table.see(playlist_id)

    def _on_row_click(self, event):
        if self.playlist_table.identify_region(event.x, event.y) != "cell":
            return
        playlist_id = self.playlist_table.identify_row(event.y)
        if playlist_id and self.playlist_table.identify_column(event.x) == "#1":
            self._toggle(playlist_id)
            return "break"

    def _toggle_selected(self):
        selection = self.playlist_table.selection()
        if selection:
            self._toggle(selection[0])

    def _set_all(self, tracked):
        for playlist_id, p in self.playlists.items():
            if p["tracked"] != tracked:
                p["tracked"] = tracked
                tracker.set_tracked(playlist_id, p["name"], tracked)
        self._render_playlists()

    def _open_in_spotify(self, event):
        playlist_id = self.playlist_table.identify_row(event.y)
        if playlist_id and self.playlist_table.identify_column(event.x) != "#1":
            webbrowser.open(f"https://open.spotify.com/playlist/{playlist_id}")

    def _update_login_status(self):
        config = tracker.load_config()
        if config.get("REFRESH_TOKEN"):
            self.login_label.configure(text=f"● Logged in: {config.get('USER', '')}")
            self.login_button.configure(text="Switch account")
        else:
            self.login_label.configure(text="")
            self.login_button.configure(text="Log in with Spotify")

    def _login(self):
        self._set_status("The Spotify authorization page opened in your browser, press “Agree”…")

        def on_success(user):
            self._set_status(f"Logged in as {user}")
            self._load_my_playlists()

        self._run_in_background(lambda: tracker.connect().login(), on_success)

    def _load_my_playlists(self):
        self._set_status("Loading playlists…")

        def on_success(result):
            readable, others = result
            for p in readable:
                existing = self.playlists.get(p["id"], {})
                self.playlists[p["id"]] = {
                    "name": p["name"], "owner": p["owner"], "track_count": p["track_count"],
                    "tracked": existing.get("tracked", False), "last_checked": existing.get("last_checked"),
                }
            self._render_playlists()
            note = (f" ({len(others)} followed playlists by other users are hidden: "
                    f"Spotify does not expose their tracks)") if others else ""
            self._set_status(f"{len(readable)} playlists found.{note}")

        self._run_in_background(lambda: tracker.connect().my_playlists(), on_success)

    def _add_by_link(self):
        link = self.link_entry.get().strip()
        if not link:
            return
        try:
            playlist_id = tracker.parse_playlist_id(link)
        except SpotifyError as e:
            messagebox.showerror("Error", str(e), parent=self)
            return
        self._set_status("Fetching playlist info…")

        def on_success(name):
            existing = self.playlists.get(playlist_id, {})
            self.playlists[playlist_id] = {
                "name": name, "owner": existing.get("owner", ""),
                "track_count": existing.get("track_count", ""),
                "tracked": True, "last_checked": existing.get("last_checked"),
            }
            tracker.set_tracked(playlist_id, name, True)
            self.link_entry.delete(0, "end")
            self._render_playlists()
            self._set_status(f"“{name}” is now tracked.")

        self._run_in_background(lambda: tracker.connect().playlist_name(playlist_id), on_success)

    # ------------------------------------------------------------ check

    def _check(self):
        selected = [pid for pid, p in self.playlists.items() if p["tracked"]]
        if not selected:
            messagebox.showinfo("Nothing selected", "Tick the playlists you want to track first.", parent=self)
            return

        def task():
            client = tracker.connect()
            results = []
            for i, playlist_id in enumerate(selected, 1):
                name = self.playlists[playlist_id]["name"]
                self.after(0, lambda i=i, name=name: self._set_status(f"Checking ({i}/{len(selected)}): {name}"))
                try:
                    results.append(tracker.check_playlist(client, playlist_id))
                except LoginRequired:
                    raise
                except SpotifyError as e:
                    results.append({"name": name, "error": str(e)})
            return results

        self._run_in_background(task, self._on_check_done)

    def _on_check_done(self, results):
        box = self.result_box
        box.configure(state="normal")
        box.delete("1.0", "end")
        total_changes = 0
        for r in results:
            if "error" in r:
                box.insert("end", f"{r['name']}: ", "heading")
                box.insert("end", f"ERROR – {r['error']}\n", tracker.EVENT_REMOVED)
                continue
            p = self.playlists.get(r["playlist_id"])
            if p:
                p.update(name=r["name"], track_count=r["total"], last_checked=r["checked_at"])
            box.insert("end", f"{r['name']} ({r['total']} tracks): ", "heading")
            if r["first_check"]:
                box.insert("end", "initial snapshot recorded, changes will appear from the next check on.\n",
                           tracker.EVENT_INITIAL)
                for t in r["unavailable"]:
                    box.insert("end", f"    ! Not playable in {tracker.market()}: {track_label(t)}\n",
                               tracker.EVENT_UNPLAYABLE)
                continue
            changes = (
                [(tracker.EVENT_ADDED, t) for t in r["added"]]
                + [(tracker.EVENT_REMOVED, t) for t in r["removed"]]
                + [(tracker.EVENT_UNPLAYABLE, t) for t in r["unplayable"]]
                + [(tracker.EVENT_PLAYABLE, t) for t in r["playable_again"]]
            )
            total_changes += len(changes)
            if not changes:
                box.insert("end", "no changes.\n")
                continue
            box.insert("end", f"{len(changes)} changes\n")
            for event, t in changes:
                added = f"   (added: {format_date(t['added_at'])})" if t.get("added_at") else ""
                box.insert("end", f"    {EVENT_LABELS[event]:<18} {track_label(t)}{added}\n", event)
        box.configure(state="disabled")
        self._render_playlists()
        self._refresh_history()
        self._set_status(f"Check complete: {len(results)} playlists, {total_changes} changes.")

    # ------------------------------------------------------------ history

    def _refresh_history(self):
        selected_playlist = self.playlist_filter.get()
        playlist_id = None
        if selected_playlist and selected_playlist != ALL:
            playlist_id = next((k for k, v in self.playlists.items() if v["name"] == selected_playlist), None)
        selected_event = self.event_filter.get()
        event_code = next((k for k, v in EVENT_LABELS.items() if v == selected_event), None)

        self.history_table.delete(*self.history_table.get_children())
        for r in tracker.get_events(playlist_id):
            if event_code and r["event"] != event_code:
                continue
            self.history_table.insert("", "end", tags=(r["event"],), values=(
                format_date(r["checked_at"]), r["playlist"] or "", EVENT_LABELS.get(r["event"], r["event"]),
                track_label(r), format_date(r["added_at"]),
            ))

    def _export_csv(self):
        path = filedialog.asksaveasfilename(
            parent=self, defaultextension=".csv", initialfile="spotify_history.csv",
            filetypes=[("CSV (Excel)", "*.csv")],
        )
        if path:
            count = tracker.export_csv(path)
            self._set_status(f"{count} records exported to {path}")

    # ------------------------------------------------------------ settings

    def _open_settings(self):
        window = tk.Toplevel(self)
        window.title("Spotify API settings")
        window.transient(self)
        window.resizable(False, False)
        frame = ttk.Frame(window, padding=14)
        frame.pack(fill="both")

        ttk.Label(frame, justify="left", text=(
            "1) Log in at developer.spotify.com/dashboard with your Spotify account\n"
            f"2) “Create app” → enter a name, Redirect URI: {tracker.REDIRECT_URI}\n"
            "3) Tick “Web API”, save → copy the Client ID and Client Secret from Settings"
        )).grid(row=0, column=0, columnspan=2, sticky="w")
        link = ttk.Label(frame, text="Open Dashboard", foreground="#1565c0", cursor="hand2")
        link.grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 10))
        link.bind("<Button-1>", lambda e: webbrowser.open("https://developer.spotify.com/dashboard"))

        config = tracker.load_config()
        ttk.Label(frame, text="Client ID:").grid(row=2, column=0, sticky="w", pady=3)
        id_entry = ttk.Entry(frame, width=45)
        id_entry.insert(0, config.get("CLIENT_ID", ""))
        id_entry.grid(row=2, column=1, pady=3)
        ttk.Label(frame, text="Client Secret:").grid(row=3, column=0, sticky="w", pady=3)
        secret_entry = ttk.Entry(frame, width=45, show="•")
        secret_entry.insert(0, config.get("CLIENT_SECRET", ""))
        secret_entry.grid(row=3, column=1, pady=3)

        def save():
            updated = tracker.load_config()
            updated["CLIENT_ID"] = id_entry.get().strip()
            updated["CLIENT_SECRET"] = secret_entry.get().strip()
            if not (updated["CLIENT_ID"] and updated["CLIENT_SECRET"]):
                messagebox.showwarning("Missing values", "Both fields are required.", parent=window)
                return
            if (updated["CLIENT_ID"], updated["CLIENT_SECRET"]) != (config.get("CLIENT_ID"), config.get("CLIENT_SECRET")):
                # A session issued for different app credentials is no longer valid
                updated.pop("REFRESH_TOKEN", None)
            tracker.save_config(updated)
            window.destroy()
            self._update_login_status()
            self._set_status("Settings saved.")

        ttk.Button(frame, text="Save", command=save).grid(row=4, column=1, sticky="e", pady=(10, 0))
        window.grab_set()
        id_entry.focus_set()


if __name__ == "__main__":
    App().mainloop()
