# ScrollMe — Collective Doomscroll Server

The audience-facing web page + realtime server for the SurfScroll performance.
Phones (mobile browser) swipe → the server counts → when ≥ a threshold of the
connected audience swipes, the server fires a **`trigger_scroll`** event that
TouchDesigner receives and uses to advance the projected reel.

Built so new performance triggers are trivial to add later: everything routes
through one **event bus** (`events.py`) and a generic **admin endpoint**, so a
new event is just a new `type` string — no transport code changes, no redeploy
of TD's connection.

```
phones ──swipe──▶  server (aiohttp + Socket.IO)  ──event──▶  TouchDesigner
   (mobile web)         threshold logic              ├─ raw WebSocket  /ws     ◀── primary internet path
                                                      ├─ Socket.IO (SocketIO DAT)
                                                      └─ OSC 127.0.0.1:9000     (local-only fallback)
performer ──▶ /admin console ──▶ /admin/event ──▶ (same event bus) ──▶ everyone
```

## Deployment (production)

Runs on the shared CityLeaks Hetzner box, public on **http://<server-ip>:8080**,
under PM2, behind nginx, auto-deployed by GitHub Actions on every push to `main`.
See [`deploy/README.md`](deploy/README.md) for the full runbook, ports, and
first-time bootstrap.

## Local development

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python main.py        # binds 0.0.0.0:8080
```

- Phone on the same Wi-Fi: `http://<your-PC-IP>:8080`
- Performer console: `http://<your-PC-IP>:8080/admin`
- Health: `http://<your-PC-IP>:8080/healthz`

Config is env-driven (see `config.py`): `HOST`, `PORT`,
`AUDIENCE_PERCENTAGE_THRESHOLD`, `OSC_ENABLED`, `ADMIN_TOKEN`.

## Connecting TouchDesigner

TD is a **client** of the server — it connects *out* to the public server, which
then pushes events down. This works over the internet through your home NAT
because TD initiates the connection (the server never has to reach into your
laptop).

### Option A — Raw WebSocket DAT (recommended over the internet)

1. Add a **WebSocket DAT**.
2. **Network Address:** `<server-ip>` (e.g. `167.233.102.255`)
   **Network Port:** `8080`  **Active:** `On`. No path needed — the server accepts
   the WebSocket on the **root path**, which is all the DAT can target.
   (The `/ws` path also works for clients that can set one.)
3. In its callbacks DAT, parse the JSON envelope `{"event": ..., "data": ...}`:

```python
import json

TARGET = 'button1'   # your Button COMP to pulse on trigger_scroll

def onConnect(dat):
    debug('WebSocket connected')
    return

def onDisconnect(dat):
    # Auto-reconnect: toggle Active off then back on a couple seconds later so any
    # drop (network blip, server restart) re-links itself without manual reset.
    debug('WebSocket disconnected — reconnecting')
    run(f"op({dat.path!r}).par.active = 0", delayFrames=1)
    run(f"op({dat.path!r}).par.active = 1", delayFrames=120)   # ~2s at 60fps
    return

def onReceiveText(dat, rowIndex, message):
    try:
        msg = json.loads(message)
    except Exception:
        return
    event = msg.get('event')
    if event == 'keepalive':
        return                       # server heartbeat — ignore
    if event == 'trigger_scroll':
        op(TARGET).click()           # advance to the next reel
    # future events arrive here too — just switch on `event`
    return
```

> The server sends a `keepalive` every ~15s so the connection never idles out
> (TouchDesigner's WebSocket DAT doesn't answer protocol pings, which is what
> caused earlier ~30s disconnects). `onDisconnect` above then covers real drops.

### Option B — SocketIO DAT

1. Add a **SocketIO DAT**. **Address:** `<server-ip>` **Port:** `8080` **Active:** `On`.
2. Callbacks receive the event name as `message`:

```python
def onReceiveEvent(dat, rowIndex, message, data):
    if message == 'trigger_scroll':
        # advance to the next reel
        pass
    return
```

> Textport: **Alt + T** to see `print()` output / errors in TD.

### Option C — OSC (local only)

Only works when TD runs on the *same machine* as the server. Listen with an
**OSC In DAT/CHOP** on port `9000`; `trigger_scroll` arrives as `/trigger_scroll`
(and `/scroll_next` for backward compatibility).

## Sending other events (now and future)

Any event you can name, TD can react to. Fire one from the performer console
(`/admin`) or directly:

```bash
curl -X POST http://<server-ip>:8080/admin/event \
  -H 'Content-Type: application/json' \
  -d '{"type":"trigger_scroll","payload":{"action":"next_reel"}}'
```

If `ADMIN_TOKEN` is set on the server, add `-H 'X-Admin-Token: <token>'`.
Add a new trigger by picking a new `type` (e.g. `flash`, `blackout`,
`set_intensity`) and handling it in TD's callback — nothing else changes.
