"""
MyDrop – Discovery Service
UDP multicast broadcast/listen + mDNS fallback via zeroconf.
"""

import json
import socket
import struct
import threading
import time
import uuid
import platform
import logging

from zeroconf import ServiceBrowser, ServiceInfo, Zeroconf, IPVersion

log = logging.getLogger("mydrop.discovery")

MULTICAST_GROUP = "224.0.0.167"
MULTICAST_PORT = 53317
BROADCAST_INTERVAL = 5  # seconds
PEER_TIMEOUT = 15  # seconds without heartbeat → offline
MDNS_SERVICE_TYPE = "_mydrop._tcp.local."


def _local_ip() -> str:
    """Best-effort LAN IP (not 127.x)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


class DiscoveryService:
    """Manages peer discovery via UDP multicast and mDNS."""

    def __init__(self, port: int = MULTICAST_PORT, device_name: str | None = None):
        self.port = port
        self.device_id = str(uuid.uuid4())
        self.device_name = device_name or platform.node()
        self.local_ip = _local_ip()

        # {ip: {"name": str, "device_id": str, "port": int, "last_seen": float}}
        self.peers: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._running = False

        # Threads
        self._sender_thread: threading.Thread | None = None
        self._listener_thread: threading.Thread | None = None

        # mDNS
        self._zeroconf: Zeroconf | None = None
        self._browser: ServiceBrowser | None = None
        self._mdns_info: ServiceInfo | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def start(self):
        """Start broadcasting + listening on multicast, and register mDNS."""
        self._running = True

        self._sender_thread = threading.Thread(target=self._broadcast_loop, daemon=True)
        self._listener_thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._sender_thread.start()
        self._listener_thread.start()

        self._register_mdns()
        log.info("Discovery started  id=%s  name=%s  ip=%s  port=%d",
                 self.device_id[:8], self.device_name, self.local_ip, self.port)

    def stop(self):
        """Gracefully shut down."""
        self._running = False
        self._unregister_mdns()
        log.info("Discovery stopped")

    def get_peers(self) -> list[dict]:
        """Return list of online peers (not self)."""
        now = time.time()
        with self._lock:
            alive = []
            for ip, info in list(self.peers.items()):
                if now - info["last_seen"] > PEER_TIMEOUT:
                    del self.peers[ip]
                    continue
                alive.append({
                    "ip": ip,
                    "port": info["port"],
                    "name": info["name"],
                    "device_id": info["device_id"],
                })
            return alive

    # ------------------------------------------------------------------
    # UDP Multicast – sender
    # ------------------------------------------------------------------
    def _make_payload(self) -> bytes:
        msg = {
            "deviceId": self.device_id,
            "name": self.device_name,
            "ip": self.local_ip,
            "port": self.port,
        }
        return json.dumps(msg).encode("utf-8")

    def _broadcast_loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        # Allow multiple instances on same machine
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        payload = self._make_payload()
        while self._running:
            try:
                sock.sendto(payload, (MULTICAST_GROUP, MULTICAST_PORT))
            except Exception as exc:
                log.debug("broadcast error: %s", exc)
            time.sleep(BROADCAST_INTERVAL)
        sock.close()

    # ------------------------------------------------------------------
    # UDP Multicast – listener
    # ------------------------------------------------------------------
    def _listen_loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            # Windows requires binding to '' for multicast
            sock.bind(("", MULTICAST_PORT))
        except OSError as exc:
            log.error("Cannot bind multicast listener: %s", exc)
            return

        mreq = struct.pack(
            "4s4s",
            socket.inet_aton(MULTICAST_GROUP),
            socket.inet_aton("0.0.0.0"),
        )
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        sock.settimeout(2.0)

        while self._running:
            try:
                data, addr = sock.recvfrom(4096)
            except socket.timeout:
                continue
            except Exception as exc:
                log.debug("listen error: %s", exc)
                continue

            try:
                msg = json.loads(data.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue

            # Ignore self
            if msg.get("deviceId") == self.device_id:
                continue

            peer_ip = msg.get("ip", addr[0])
            with self._lock:
                self.peers[peer_ip] = {
                    "name": msg.get("name", "unknown"),
                    "device_id": msg.get("deviceId", ""),
                    "port": msg.get("port", MULTICAST_PORT),
                    "last_seen": time.time(),
                }
            log.debug("Discovered peer %s @ %s", msg.get("name"), peer_ip)

        sock.close()

    # ------------------------------------------------------------------
    # mDNS (zeroconf) fallback
    # ------------------------------------------------------------------
    def _register_mdns(self):
        try:
            self._zeroconf = Zeroconf(ip_version=IPVersion.V4Only)
            self._mdns_info = ServiceInfo(
                MDNS_SERVICE_TYPE,
                f"{self.device_name}.{MDNS_SERVICE_TYPE}",
                addresses=[socket.inet_aton(self.local_ip)],
                port=self.port,
                properties={"id": self.device_id, "name": self.device_name},
            )
            self._zeroconf.register_service(self._mdns_info)
            self._browser = ServiceBrowser(
                self._zeroconf, MDNS_SERVICE_TYPE, handlers=[self._on_mdns_change]
            )
            log.info("mDNS registered: %s", self._mdns_info.name)
        except Exception as exc:
            log.warning("mDNS registration failed (non-fatal): %s", exc)

    def _unregister_mdns(self):
        try:
            if self._zeroconf and self._mdns_info:
                self._zeroconf.unregister_service(self._mdns_info)
            if self._zeroconf:
                self._zeroconf.close()
        except Exception:
            pass

    def _on_mdns_change(self, zeroconf: Zeroconf, service_type: str,
                        name: str, state_change):
        info = zeroconf.get_service_info(service_type, name)
        if info is None:
            return
        props = {k.decode(): v.decode() for k, v in info.properties.items()}
        if props.get("id") == self.device_id:
            return  # self
        for addr in info.parsed_addresses(IPVersion.V4Only):
            with self._lock:
                self.peers[addr] = {
                    "name": props.get("name", name),
                    "device_id": props.get("id", ""),
                    "port": info.port,
                    "last_seen": time.time(),
                }
            log.debug("mDNS peer %s @ %s", props.get("name"), addr)
