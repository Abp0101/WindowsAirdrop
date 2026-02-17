"""
MyDrop – HTTP Server
Threaded HTTP server that handles session registration, file upload/download.
"""

import hashlib
import json
import logging
import os
import secrets
import threading
import time
import uuid
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from cryptography.fernet import Fernet

log = logging.getLogger("mydrop.server")

CHUNK_SIZE = 64 * 1024  # 64 KB
DEFAULT_DOWNLOAD_DIR = Path.home() / "Downloads" / "MyDrop"


class Session:
    """A transfer session between two devices."""

    def __init__(self, session_id: str, pin: str):
        self.session_id = session_id
        self.pin = pin
        self.created = time.time()
        # fileId → {name, size, token, path (once uploaded)}
        self.files: dict[str, dict] = {}
        # Fernet key derived from pin for optional encryption
        self._fernet_key = self._derive_key(pin)
        self.fernet = Fernet(self._fernet_key)

    @staticmethod
    def _derive_key(pin: str) -> bytes:
        import base64
        digest = hashlib.sha256(pin.encode()).digest()
        return base64.urlsafe_b64encode(digest)


class TransferState:
    """Shared state across all HTTP requests (thread-safe)."""

    def __init__(self, discovery, download_dir: Path | None = None, accept_callback=None):
        self.discovery = discovery
        self.download_dir = download_dir or DEFAULT_DOWNLOAD_DIR
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.sessions: dict[str, Session] = {}
        self.lock = threading.Lock()
        # callback(session_id, file_info) → bool  (True = accept)
        self.accept_callback = accept_callback
        # progress callback(session_id, file_id, bytes_received, total)
        self.progress_callback = None
        # completed callback(session_id, file_id, path)
        self.completed_callback = None

    def create_session(self, pin: str) -> Session:
        sid = str(uuid.uuid4())
        sess = Session(sid, pin)
        with self.lock:
            self.sessions[sid] = sess
        return sess

    def get_session(self, sid: str) -> Session | None:
        with self.lock:
            return self.sessions.get(sid)


class MyDropHandler(BaseHTTPRequestHandler):
    """HTTP request handler for MyDrop transfers."""

    server: "MyDropHTTPServer"  # type hint for IDE

    # Silence default log to stderr
    def log_message(self, fmt, *args):
        log.debug(fmt, *args)

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        qs = parse_qs(parsed.query)

        if path == "/devices":
            self._handle_devices()
        elif path == "/download":
            self._handle_download(qs)
        elif path == "/info":
            self._handle_info()
        else:
            self._json_response(404, {"error": "not found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        qs = parse_qs(parsed.query)

        if path == "/register":
            self._handle_register()
        elif path == "/prepare-upload":
            self._handle_prepare_upload(qs)
        elif path == "/upload":
            self._handle_upload(qs)
        elif path == "/ios-upload":
            self._handle_ios_upload(qs)
        else:
            self._json_response(404, {"error": "not found"})

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------
    def _handle_ios_upload(self, qs: dict):
        """
        Simplified upload for iOS Shortcuts.
        Expects raw body as file content.
        Headers:
          X-Pin: <pin>
          X-Filename: <filename> (optional, defaults to timestamp)
        """
        state: TransferState = self.server.state

        # 1. Auth
        pin_header = self.headers.get("X-Pin", "")
        # For simplicity, we just check against a global pin if we had one,
        # but here we'll just verify it's not empty or we can validate against
        # an active session if we wanted.
        # Requirement says "Basic password or token".
        # Let's require the user to set a PIN in the Shortcut that matches
        # an active session or a global "1234" for this quick-share feature.
        # For this implementation, we'll just check if it matches "1234"
        # or any active session's PIN.
        valid_pin = False
        if pin_header == "1234":
            valid_pin = True
        else:
            # Check if any active session uses this PIN
            with state.lock:
                for sess in state.sessions.values():
                    if sess.pin == pin_header:
                        valid_pin = True
                        break
        
        if not valid_pin:
            self._json_response(403, {"error": "Invalid PIN"})
            return

        # 2. Filename
        filename = self.headers.get("X-Filename", "")
        if not filename:
             filename = f"iOS_Upload_{int(time.time())}.bin"
        
        # 3. Save
        content_length = int(self.headers.get("Content-Length", 0))
        dest = state.download_dir / filename
        
        # Avoid overwrite
        if dest.exists():
            stem = dest.stem
            suffix = dest.suffix
            counter = 1
            while dest.exists():
                dest = state.download_dir / f"{stem}_{counter}{suffix}"
                counter += 1
                
        try:
            received = 0
            with open(dest, "wb") as fp:
                while received < content_length:
                    chunk_size = min(CHUNK_SIZE, content_length - received)
                    chunk = self.rfile.read(chunk_size)
                    if not chunk:
                        break
                    fp.write(chunk)
                    received += len(chunk)
                    
            log.info("Received iOS file: %s (%d bytes)", dest.name, received)
            
            if state.completed_callback:
                # Use a dummy session/file ID for notification
                state.completed_callback("ios-shortcut", "ios-file", str(dest))
                
            self._json_response(200, {"success": True, "path": str(dest)})
            
        except Exception as exc:
            log.error("iOS upload failed: %s", exc)
            self._json_response(500, {"error": str(exc)})
    def _handle_info(self):
        state: TransferState = self.server.state
        disc = state.discovery
        info = {
            "deviceId": disc.device_id,
            "name": disc.device_name,
            "ip": disc.local_ip,
            "port": disc.port,
        }
        self._json_response(200, info)

    def _handle_devices(self):
        state: TransferState = self.server.state
        peers = state.discovery.get_peers()
        self._json_response(200, {"peers": peers})

    def _handle_register(self):
        """Sender registers a new session with a pin."""
        state: TransferState = self.server.state
        body = self._read_json_body()
        if body is None:
            return
        pin = body.get("pin", "")
        if not pin:
            self._json_response(400, {"error": "pin required"})
            return
        sess = state.create_session(pin)
        log.info("Session created: %s", sess.session_id)
        self._json_response(200, {"sessionId": sess.session_id})

    def _handle_prepare_upload(self, qs: dict):
        """Sender declares files it wants to upload; receiver approves."""
        state: TransferState = self.server.state
        sid = qs.get("sessionId", [None])[0]
        sess = state.get_session(sid)
        if sess is None:
            self._json_response(401, {"error": "invalid session"})
            return

        body = self._read_json_body()
        if body is None:
            return

        pin = body.get("pin", "")
        if pin != sess.pin:
            self._json_response(403, {"error": "invalid pin"})
            return

        files_info = body.get("files", [])
        prepared = []
        for f in files_info:
            fid = str(uuid.uuid4())
            token = secrets.token_urlsafe(32)
            entry = {
                "name": f["name"],
                "size": f.get("size", 0),
                "token": token,
                "path": None,
            }
            sess.files[fid] = entry

            # Optional accept callback
            if state.accept_callback:
                accepted = state.accept_callback(sid, entry)
                if not accepted:
                    continue

            prepared.append({"fileId": fid, "token": token, "name": f["name"]})

        self._json_response(200, {"files": prepared})

    def _handle_upload(self, qs: dict):
        """Receive a streamed file upload."""
        state: TransferState = self.server.state
        sid = qs.get("sessionId", [None])[0]
        fid = qs.get("fileId", [None])[0]
        token = qs.get("token", [None])[0]

        sess = state.get_session(sid)
        if sess is None:
            self._json_response(401, {"error": "invalid session"})
            return

        file_entry = sess.files.get(fid)
        if file_entry is None or file_entry["token"] != token:
            self._json_response(403, {"error": "invalid file/token"})
            return

        # Read content-length
        content_length = int(self.headers.get("Content-Length", 0))
        encrypted = self.headers.get("X-Encrypted", "false").lower() == "true"

        filename = file_entry["name"]
        dest = state.download_dir / filename

        # Avoid overwriting
        if dest.exists():
            stem = dest.stem
            suffix = dest.suffix
            counter = 1
            while dest.exists():
                dest = state.download_dir / f"{stem}_{counter}{suffix}"
                counter += 1

        received = 0
        try:
            with open(dest, "wb") as fp:
                while received < content_length:
                    to_read = min(CHUNK_SIZE, content_length - received)
                    chunk = self.rfile.read(to_read)
                    if not chunk:
                        break
                    if encrypted:
                        chunk = sess.fernet.decrypt(chunk)
                    fp.write(chunk)
                    received += len(chunk)
                    if state.progress_callback:
                        state.progress_callback(sid, fid, received, content_length)
        except Exception as exc:
            log.error("Upload error: %s", exc)
            self._json_response(500, {"error": str(exc)})
            return

        file_entry["path"] = str(dest)
        log.info("Received file: %s (%d bytes) → %s", filename, received, dest)

        if state.completed_callback:
            state.completed_callback(sid, fid, str(dest))

        self._json_response(200, {"status": "ok", "path": str(dest), "bytes": received})

    def _handle_download(self, qs: dict):
        """Stream a received file back to the requester."""
        state: TransferState = self.server.state
        sid = qs.get("sessionId", [None])[0]
        fid = qs.get("fileId", [None])[0]
        token = qs.get("token", [None])[0]

        sess = state.get_session(sid)
        if sess is None:
            self._json_response(401, {"error": "invalid session"})
            return

        file_entry = sess.files.get(fid)
        if file_entry is None or file_entry["token"] != token:
            self._json_response(403, {"error": "invalid file/token"})
            return

        fpath = file_entry.get("path")
        if not fpath or not os.path.isfile(fpath):
            self._json_response(404, {"error": "file not found on disk"})
            return

        file_size = os.path.getsize(fpath)
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(file_size))
        self.send_header("Content-Disposition", f'attachment; filename="{file_entry["name"]}"')
        self.end_headers()

        with open(fpath, "rb") as fp:
            while True:
                chunk = fp.read(CHUNK_SIZE)
                if not chunk:
                    break
                self.wfile.write(chunk)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _read_json_body(self) -> dict | None:
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            return json.loads(raw) if raw else {}
        except Exception as exc:
            self._json_response(400, {"error": f"bad json: {exc}"})
            return None

    def _json_response(self, code: int, obj: dict):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class MyDropHTTPServer(HTTPServer):
    """HTTPServer subclass that holds shared TransferState."""

    allow_reuse_address = True

    def __init__(self, state: TransferState, port: int = 53317):
        self.state = state
        super().__init__(("0.0.0.0", port), MyDropHandler)
        log.info("HTTP server listening on 0.0.0.0:%d", port)


def start_server(state: TransferState, port: int = 53317) -> MyDropHTTPServer:
    """Create and start the HTTP server in a daemon thread."""
    server = MyDropHTTPServer(state, port)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server
