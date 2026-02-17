"""
MyDrop – Client Logic
Sending files to a peer: register session → prepare → upload chunks.
"""

import json
import logging
import os
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

log = logging.getLogger("mydrop.client")

CHUNK_SIZE = 64 * 1024  # 64 KB


class SendResult:
    """Outcome of a file send operation."""

    def __init__(self, success: bool, message: str = "", path: str = ""):
        self.success = success
        self.message = message
        self.path = path

    def __repr__(self):
        return f"SendResult(ok={self.success}, msg={self.message!r})"


def _post_json(url: str, data: dict, timeout: int = 10) -> dict:
    """POST JSON and return parsed response."""
    body = json.dumps(data).encode("utf-8")
    req = Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _get_json(url: str, timeout: int = 10) -> dict:
    """GET and return parsed JSON response."""
    req = Request(url, method="GET")
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def get_peer_info(ip: str, port: int) -> dict | None:
    """Fetch /info from a peer."""
    try:
        return _get_json(f"http://{ip}:{port}/info")
    except Exception as exc:
        log.warning("Cannot reach peer %s:%d – %s", ip, port, exc)
        return None


def send_file(
    peer_ip: str,
    peer_port: int,
    file_path: str,
    pin: str,
    progress_callback=None,
    encrypt: bool = False,
) -> SendResult:
    """
    Send a single file to a peer.

    Args:
        peer_ip: Target device IP.
        peer_port: Target device HTTP port.
        file_path: Local path of the file to send.
        pin: Shared session PIN.
        progress_callback: Optional callable(bytes_sent, total_bytes).
        encrypt: If True, encrypt chunks with Fernet (pin-derived key).

    Returns:
        SendResult with success status and message.
    """
    base = f"http://{peer_ip}:{peer_port}"
    fpath = Path(file_path)

    if not fpath.is_file():
        return SendResult(False, f"File not found: {file_path}")

    file_size = fpath.stat().st_size
    file_name = fpath.name

    # 1. Register session
    try:
        resp = _post_json(f"{base}/register", {"pin": pin})
        session_id = resp["sessionId"]
    except Exception as exc:
        return SendResult(False, f"Register failed: {exc}")

    # 2. Prepare upload
    try:
        resp = _post_json(
            f"{base}/prepare-upload?sessionId={session_id}",
            {
                "pin": pin,
                "files": [{"name": file_name, "size": file_size}],
            },
        )
        files_info = resp.get("files", [])
        if not files_info:
            return SendResult(False, "Receiver rejected the file")
        file_id = files_info[0]["fileId"]
        token = files_info[0]["token"]
    except Exception as exc:
        return SendResult(False, f"Prepare failed: {exc}")

    # 3. Upload file
    try:
        upload_url = (
            f"{base}/upload?sessionId={session_id}&fileId={file_id}&token={token}"
        )

        # Build encryption helper if needed
        fernet = None
        if encrypt:
            import base64
            import hashlib
            from cryptography.fernet import Fernet

            key = base64.urlsafe_b64encode(hashlib.sha256(pin.encode()).digest())
            fernet = Fernet(key)

        # We read the entire file to compute the body length.
        # For very large files a streaming approach would be better, but
        # stdlib urllib doesn't support chunked-transfer-encoding easily.
        # This keeps it simple and compatible.
        raw_data = fpath.read_bytes()
        if fernet:
            # Encrypt in one shot (Fernet adds ~overhead)
            raw_data = fernet.encrypt(raw_data)

        req = Request(upload_url, data=raw_data, method="POST")
        req.add_header("Content-Type", "application/octet-stream")
        req.add_header("Content-Length", str(len(raw_data)))
        if encrypt:
            req.add_header("X-Encrypted", "true")

        with urlopen(req, timeout=300) as resp:
            result = json.loads(resp.read())

        if progress_callback:
            progress_callback(file_size, file_size)  # 100 %

        return SendResult(True, "Upload complete", result.get("path", ""))

    except Exception as exc:
        return SendResult(False, f"Upload failed: {exc}")


def send_file_chunked(
    peer_ip: str,
    peer_port: int,
    file_path: str,
    pin: str,
    progress_callback=None,
) -> SendResult:
    """
    Send a file using streaming chunks (better for large files).
    No encryption in this path to keep it simple; use send_file(encrypt=True) for small secure files.
    """
    import http.client

    base = f"{peer_ip}:{peer_port}"
    fpath = Path(file_path)

    if not fpath.is_file():
        return SendResult(False, f"File not found: {file_path}")

    file_size = fpath.stat().st_size
    file_name = fpath.name

    # 1. Register
    try:
        resp = _post_json(f"http://{base}/register", {"pin": pin})
        session_id = resp["sessionId"]
    except Exception as exc:
        return SendResult(False, f"Register failed: {exc}")

    # 2. Prepare
    try:
        resp = _post_json(
            f"http://{base}/prepare-upload?sessionId={session_id}",
            {"pin": pin, "files": [{"name": file_name, "size": file_size}]},
        )
        files_info = resp.get("files", [])
        if not files_info:
            return SendResult(False, "Receiver rejected the file")
        file_id = files_info[0]["fileId"]
        token = files_info[0]["token"]
    except Exception as exc:
        return SendResult(False, f"Prepare failed: {exc}")

    # 3. Stream upload via http.client (supports Content-Length + manual chunking)
    try:
        conn = http.client.HTTPConnection(peer_ip, peer_port, timeout=300)
        path = f"/upload?sessionId={session_id}&fileId={file_id}&token={token}"
        conn.putrequest("POST", path)
        conn.putheader("Content-Type", "application/octet-stream")
        conn.putheader("Content-Length", str(file_size))
        conn.endheaders()

        sent = 0
        with open(fpath, "rb") as fp:
            while True:
                chunk = fp.read(CHUNK_SIZE)
                if not chunk:
                    break
                conn.send(chunk)
                sent += len(chunk)
                if progress_callback:
                    progress_callback(sent, file_size)

        resp = conn.getresponse()
        body = json.loads(resp.read())
        conn.close()

        if resp.status == 200:
            return SendResult(True, "Upload complete", body.get("path", ""))
        else:
            return SendResult(False, f"Server error {resp.status}: {body}")

    except Exception as exc:
        return SendResult(False, f"Chunked upload failed: {exc}")
