"""
MyDrop – Application Entry Point
Starts discovery, HTTP server, and GUI.

Usage:
    python app.py               # GUI mode on default port
    python app.py --port 53318  # alternate port (for testing 2 instances)
    python app.py --no-gui      # headless / console mode
"""

import argparse
import logging
import signal
import sys
import time

import discovery
import server
import client
from main import MyDropGUI

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-20s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("mydrop")


def parse_args():
    p = argparse.ArgumentParser(description="MyDrop – LAN file sharing")
    p.add_argument("--port", type=int, default=53317, help="TCP/UDP port (default 53317)")
    p.add_argument("--name", type=str, default=None, help="Device display name")
    p.add_argument("--no-gui", action="store_true", help="Run without GUI (console only)")
    p.add_argument("--download-dir", type=str, default=None, help="Directory for received files")
    return p.parse_args()


def console_mode(disc, state):
    """Simple console loop for headless testing."""
    print("\n✦ MyDrop (console mode)")
    print(f"  Device : {disc.device_name}")
    print(f"  IP     : {disc.local_ip}:{disc.port}")
    print(f"  ID     : {disc.device_id[:8]}…")
    print("  Waiting for peers… (Ctrl+C to quit)\n")

    def on_received(sid, fid, path):
        print(f"  📥 Received: {path}")

    state.completed_callback = on_received

    try:
        while True:
            peers = disc.get_peers()
            if peers:
                print(f"  📡 {len(peers)} peer(s):")
                for p in peers:
                    print(f"     • {p['name']}  {p['ip']}:{p['port']}")

                # Simple interactive send
                ans = input("\n  Send file? (path or Enter to skip): ").strip()
                if ans and len(peers) > 0:
                    pin = input("  PIN [1234]: ").strip() or "1234"
                    target = peers[0]  # first peer
                    print(f"  Sending to {target['name']}…")
                    result = client.send_file_chunked(
                        target["ip"], target["port"], ans, pin,
                        progress_callback=lambda s, t: print(f"\r  {s/t*100:.0f}%", end="", flush=True),
                    )
                    print(f"\n  {'✔' if result.success else '✘'} {result.message}")
            else:
                print("  …no peers yet")

            time.sleep(5)
    except KeyboardInterrupt:
        print("\n  Shutting down…")


def main():
    args = parse_args()

    from pathlib import Path
    download_dir = Path(args.download_dir) if args.download_dir else None

    # 1. Discovery
    disc = discovery.DiscoveryService(port=args.port, device_name=args.name)
    disc.start()

    # 2. HTTP Server
    state = server.TransferState(disc, download_dir=download_dir)
    http_server = server.start_server(state, port=args.port)

    # 3. Graceful shutdown
    def shutdown(sig=None, frame=None):
        log.info("Shutting down…")
        disc.stop()
        http_server.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)

    # 4. GUI or console
    if args.no_gui:
        console_mode(disc, state)
    else:
        gui = MyDropGUI(disc, state, client, port=args.port)
        state.completed_callback = gui.on_file_received
        gui.run()

    shutdown()


if __name__ == "__main__":
    main()
