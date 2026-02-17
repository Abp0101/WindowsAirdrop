# MyDrop – Local Network File Sharing

A cross-platform, AirDrop-like file sharing tool for Windows (expandable to mobile).  
Devices on the same WiFi/LAN discover each other automatically — no central server needed.

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run the app
python app.py

# 3. (Optional) Run in console-only mode
python app.py --no-gui
```

## Firewall

Open **TCP + UDP port 53317** on every machine:

| Protocol | Port  | Purpose            |
|----------|-------|--------------------|
| UDP      | 53317 | Device discovery   |
| TCP      | 53317 | HTTP file transfer |

**Windows (PowerShell, run as Admin):**

```powershell
New-NetFirewallRule -DisplayName "MyDrop UDP" -Direction Inbound -Protocol UDP -LocalPort 53317 -Action Allow
New-NetFirewallRule -DisplayName "MyDrop TCP" -Direction Inbound -Protocol TCP -LocalPort 53317 -Action Allow
```

## Architecture

| File           | Role                                 |
|----------------|--------------------------------------|
| `discovery.py` | UDP multicast + mDNS peer discovery  |
| `server.py`    | HTTP server (upload / download)      |
| `client.py`    | Client logic (send / receive files)  |
| `main.py`      | Tkinter GUI                          |
| `app.py`       | Entry-point, wires everything up     |

## Testing

Run two instances on separate terminals (or PCs on the same LAN):

```bash
# Terminal 1
python app.py --port 53317

# Terminal 2
python app.py --port 53318
```

Send a file from one to the other and verify the transfer.

## License

MIT
