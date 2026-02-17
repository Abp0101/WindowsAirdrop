"""
MyDrop – Tkinter GUI
Tabs: Peers · Send · Received
"""

import logging
import os
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path

log = logging.getLogger("mydrop.gui")


class MyDropGUI:
    """Main application window built with Tkinter."""

    REFRESH_MS = 3000  # peer-list refresh interval

    def __init__(self, discovery, state, client_module, port: int = 53317):
        self.discovery = discovery
        self.state = state
        self.client = client_module
        self.port = port

        self.root = tk.Tk()
        self.root.title("MyDrop")
        self.root.geometry("680x520")
        self.root.minsize(520, 400)
        self.root.configure(bg="#1e1e2e")

        self._style()
        self._build_ui()
        self._schedule_refresh()

    # ------------------------------------------------------------------
    # Theming
    # ------------------------------------------------------------------
    def _style(self):
        s = ttk.Style(self.root)
        s.theme_use("clam")

        BG = "#1e1e2e"
        FG = "#cdd6f4"
        ACCENT = "#89b4fa"
        SURFACE = "#313244"
        SURFACE2 = "#45475a"
        GREEN = "#a6e3a1"
        RED = "#f38ba8"

        self.root.option_add("*TCombobox*Listbox.background", SURFACE)
        self.root.option_add("*TCombobox*Listbox.foreground", FG)

        s.configure(".", background=BG, foreground=FG, borderwidth=0, font=("Segoe UI", 10))
        s.configure("TNotebook", background=BG, borderwidth=0)
        s.configure("TNotebook.Tab", background=SURFACE, foreground=FG,
                     padding=[14, 6], font=("Segoe UI", 10, "bold"))
        s.map("TNotebook.Tab",
              background=[("selected", ACCENT)],
              foreground=[("selected", BG)])

        s.configure("TFrame", background=BG)
        s.configure("TLabel", background=BG, foreground=FG, font=("Segoe UI", 10))
        s.configure("Title.TLabel", font=("Segoe UI", 13, "bold"), foreground=ACCENT)
        s.configure("TButton", background=ACCENT, foreground=BG,
                     font=("Segoe UI", 10, "bold"), padding=[12, 6])
        s.map("TButton", background=[("active", "#74c7ec")])

        s.configure("Green.TLabel", foreground=GREEN)
        s.configure("Red.TLabel", foreground=RED)
        s.configure("TEntry", fieldbackground=SURFACE, foreground=FG,
                     insertcolor=FG, font=("Segoe UI", 10))
        s.configure("TCombobox", fieldbackground=SURFACE, foreground=FG,
                     font=("Segoe UI", 10))

        s.configure("Horizontal.TProgressbar", troughcolor=SURFACE2,
                     background=ACCENT, thickness=18)

        s.configure("Treeview", background=SURFACE, foreground=FG,
                     fieldbackground=SURFACE, rowheight=28,
                     font=("Segoe UI", 10))
        s.configure("Treeview.Heading", background=SURFACE2, foreground=FG,
                     font=("Segoe UI", 10, "bold"))
        s.map("Treeview", background=[("selected", ACCENT)],
              foreground=[("selected", BG)])

        self._colors = {
            "bg": BG, "fg": FG, "accent": ACCENT,
            "surface": SURFACE, "green": GREEN, "red": RED
        }

    # ------------------------------------------------------------------
    # Build UI
    # ------------------------------------------------------------------
    def _build_ui(self):
        # Status bar
        status_frame = ttk.Frame(self.root)
        status_frame.pack(fill="x", padx=12, pady=(10, 0))

        self.lbl_status = ttk.Label(status_frame, text=f"● MyDrop  |  {self.discovery.device_name}  |  {self.discovery.local_ip}:{self.port}",
                                    style="Title.TLabel")
        self.lbl_status.pack(side="left")

        self.lbl_peers_count = ttk.Label(status_frame, text="0 peers online", style="Green.TLabel")
        self.lbl_peers_count.pack(side="right")

        # Notebook (tabs)
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=12, pady=10)

        self._build_peers_tab()
        self._build_send_tab()
        self._build_received_tab()

    # -- Peers Tab --
    def _build_peers_tab(self):
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text="  📡  Peers  ")

        top = ttk.Frame(frame)
        top.pack(fill="x", padx=10, pady=(10, 4))
        ttk.Label(top, text="Nearby Devices", style="Title.TLabel").pack(side="left")
        ttk.Button(top, text="⟳ Refresh", command=self._refresh_peers).pack(side="right")

        cols = ("name", "ip", "port")
        self.peer_tree = ttk.Treeview(frame, columns=cols, show="headings", height=10)
        self.peer_tree.heading("name", text="Device Name")
        self.peer_tree.heading("ip", text="IP Address")
        self.peer_tree.heading("port", text="Port")
        self.peer_tree.column("name", width=220)
        self.peer_tree.column("ip", width=160)
        self.peer_tree.column("port", width=80)
        self.peer_tree.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    # -- Send Tab --
    def _build_send_tab(self):
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text="  📤  Send  ")

        inner = ttk.Frame(frame)
        inner.pack(fill="both", expand=True, padx=20, pady=20)

        # File picker
        ttk.Label(inner, text="File to Send", style="Title.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 4))
        file_row = ttk.Frame(inner)
        file_row.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        self.entry_file = ttk.Entry(file_row, width=48)
        self.entry_file.pack(side="left", fill="x", expand=True)
        ttk.Button(file_row, text="Browse…", command=self._browse_file).pack(side="right", padx=(8, 0))

        # Recipient dropdown
        ttk.Label(inner, text="Recipient").grid(row=2, column=0, sticky="w", pady=(0, 4))
        self.combo_peer = ttk.Combobox(inner, state="readonly", width=45)
        self.combo_peer.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 12))

        # PIN
        ttk.Label(inner, text="Session PIN").grid(row=4, column=0, sticky="w", pady=(0, 4))
        self.entry_pin = ttk.Entry(inner, width=20)
        self.entry_pin.insert(0, "1234")
        self.entry_pin.grid(row=5, column=0, sticky="w", pady=(0, 16))

        # Send button
        self.btn_send = ttk.Button(inner, text="▶  Send File", command=self._on_send)
        self.btn_send.grid(row=6, column=0, sticky="w")

        # Progress
        self.progress = ttk.Progressbar(inner, orient="horizontal", mode="determinate",
                                        style="Horizontal.TProgressbar")
        self.progress.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(16, 4))
        self.lbl_progress = ttk.Label(inner, text="")
        self.lbl_progress.grid(row=8, column=0, sticky="w")

        inner.columnconfigure(0, weight=1)

    # -- Received Tab --
    def _build_received_tab(self):
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text="  📥  Received  ")

        top = ttk.Frame(frame)
        top.pack(fill="x", padx=10, pady=(10, 4))
        ttk.Label(top, text="Received Files", style="Title.TLabel").pack(side="left")
        ttk.Button(top, text="Open Folder",
                   command=lambda: os.startfile(str(self.state.download_dir))).pack(side="right")

        cols = ("file", "size", "status")
        self.recv_tree = ttk.Treeview(frame, columns=cols, show="headings", height=10)
        self.recv_tree.heading("file", text="Filename")
        self.recv_tree.heading("size", text="Size")
        self.recv_tree.heading("status", text="Status")
        self.recv_tree.column("file", width=280)
        self.recv_tree.column("size", width=100)
        self.recv_tree.column("status", width=120)
        self.recv_tree.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _browse_file(self):
        path = filedialog.askopenfilename()
        if path:
            self.entry_file.delete(0, tk.END)
            self.entry_file.insert(0, path)

    def _refresh_peers(self):
        peers = self.discovery.get_peers()
        # Update tree
        self.peer_tree.delete(*self.peer_tree.get_children())
        for p in peers:
            self.peer_tree.insert("", "end", values=(p["name"], p["ip"], p["port"]))
        # Update combo
        self._peer_list = peers
        self.combo_peer["values"] = [f'{p["name"]}  ({p["ip"]}:{p["port"]})' for p in peers]
        # Update count
        self.lbl_peers_count.config(text=f"{len(peers)} peer{'s' if len(peers) != 1 else ''} online")

    def _on_send(self):
        file_path = self.entry_file.get().strip()
        if not file_path or not os.path.isfile(file_path):
            messagebox.showwarning("MyDrop", "Please select a valid file.")
            return

        idx = self.combo_peer.current()
        if idx < 0 or idx >= len(getattr(self, "_peer_list", [])):
            messagebox.showwarning("MyDrop", "Please select a recipient.")
            return

        peer = self._peer_list[idx]
        pin = self.entry_pin.get().strip() or "1234"
        file_size = os.path.getsize(file_path)

        self.btn_send.config(state="disabled")
        self.progress["value"] = 0
        self.progress["maximum"] = file_size
        self.lbl_progress.config(text="Sending…")

        def progress_cb(sent, total):
            self.root.after(0, self._update_progress, sent, total)

        def do_send():
            result = self.client.send_file_chunked(
                peer["ip"], peer["port"], file_path, pin,
                progress_callback=progress_cb,
            )
            self.root.after(0, self._send_done, result)

        threading.Thread(target=do_send, daemon=True).start()

    def _update_progress(self, sent, total):
        self.progress["value"] = sent
        pct = int(sent / total * 100) if total else 0
        mb_sent = sent / (1024 * 1024)
        mb_total = total / (1024 * 1024)
        self.lbl_progress.config(text=f"{pct}%  ({mb_sent:.1f} / {mb_total:.1f} MB)")

    def _send_done(self, result):
        self.btn_send.config(state="normal")
        if result.success:
            self.lbl_progress.config(text="✔ Sent successfully!")
            messagebox.showinfo("MyDrop", "File sent successfully!")
        else:
            self.lbl_progress.config(text=f"✘ {result.message}")
            messagebox.showerror("MyDrop", f"Send failed:\n{result.message}")

    # ------------------------------------------------------------------
    # Callbacks for incoming files
    # ------------------------------------------------------------------
    def on_file_received(self, session_id, file_id, path):
        """Called by server when a file finishes uploading."""
        fpath = Path(path)
        size = fpath.stat().st_size if fpath.exists() else 0
        size_str = f"{size / (1024*1024):.1f} MB" if size > 1024*1024 else f"{size / 1024:.1f} KB"
        self.root.after(0, lambda: self.recv_tree.insert(
            "", "end", values=(fpath.name, size_str, "✔ Complete")))

    # ------------------------------------------------------------------
    # Periodic refresh
    # ------------------------------------------------------------------
    def _schedule_refresh(self):
        self._refresh_peers()
        self.root.after(self.REFRESH_MS, self._schedule_refresh)

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------
    def run(self):
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.mainloop()

    def _on_close(self):
        self.root.destroy()
