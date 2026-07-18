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

Runs on the shared CityLeaks Hetzner box, public on **http://167.233.102.255**
(port 80 — exhibition/guest Wi-Fi blocks odd ports like 8080; port 80 is also
served, and 8080 still works on permissive networks),
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
2. **Network Address:** `167.233.102.255`
   **Network Port:** `80`  **Active:** `On`. Use **80** (not 8080) — venue/guest
   networks block odd ports. No path needed — the server accepts the WebSocket on
   the **root path**, which is all the DAT can target. (`/ws` also works, as does
   `8080` on permissive networks.)
3. In its callbacks DAT, parse the JSON envelope `{"event": ..., "data": ...}`.
   The canonical, up-to-date copy of this script lives at
   [`td_websocket_callbacks.py`](td_websocket_callbacks.py) — paste it in
   directly rather than retyping from here:

```python
import json

TARGET      = 'button1'     # your Button COMP to pulse on trigger_scroll
STAGE_CHOP  = 'constant1'   # a Constant CHOP:
                            #   value0 = current stage index (state number)
                            #   value1 = finale fade-to-black amount (0..1)
                            #   value2 = live online-audience count
                            #   value3 = live count of phones that swiped this
                            #            round (resets to 0 when the reel advances)

# Stage index (the "state number" written to STAGE_CHOP value0). Position in the
# server's stages.py list, sent as data.index on every stage_update:
#   0 intro · 1 lost · 2 collective1 · 3 collective2 · 4 step5 · 5 step6 ·
#   6 step7 · 7 step8 · 8 step9 · 9 finale
# (Poll 1 / Scroll 1 / Poll 2 + old placeholders were archived out of the show.
#  step5..step9 are bare placeholders -- no mechanic yet, just their own index,
#  each with its own admin-rail button that advances TD to its next action.)
# (Keep this comment in sync with stages.py if you reorder the show.)

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
    data  = msg.get('data') or {}
    if event == 'keepalive':
        # Pong back so there's live traffic in BOTH directions (keeps the link
        # and any NAT mapping fresh). Purely for stability; the server does not
        # require it.
        try:
            dat.sendText('{"type":"pong"}')
        except Exception:
            pass
        return
    if event == 'trigger_scroll':
        op(TARGET).click()           # advance to the next reel
        return
    if event == 'stage_update':
        # The performer switched the show to a new stage (also fires once right
        # after TD connects, so the CHOP is always current). Store its index as
        # the state number; drive the rest of the patch off this Constant CHOP.
        idx = data.get('index')
        if idx is not None:
            op(STAGE_CHOP).par.value0 = idx
            debug(f"stage -> {data.get('stage')} (index {idx})")
        return
    if event == 'finale_progress':
        # Stage 8 only: live fraction (0..1) of the audience who have swiped to
        # end their show. Use it as your fade-to-black amount. Sent on entry
        # (seeded at 0) and again every time someone finishes or drops.
        op(STAGE_CHOP).par.value1 = data.get('percent', 0.0)
        return
    if event == 'audience_update':
        # Live count of currently-connected phones. Sent every time someone
        # joins, leaves, or a phone registers as an admin (admins don't count).
        op(STAGE_CHOP).par.value2 = data.get('online', 0)
        return
    if event == 'scroll_update':
        # Live count of phones that have swiped in the current round — drive a
        # visual of "how many people scrolled" off this. Resets to 0 when the
        # reel advances (also on stage change / admin reset). Sent on every swipe
        # and every reset, and seeded once when TD connects.
        op(STAGE_CHOP).par.value3 = data.get('scrolled', 0)
        return
    # future events arrive here too — just switch on `event`
    return

# Optional: if your TD build delivers protocol-level pings to a callback, answer
# them too. Harmless if this callback is never called.
def onReceivePing(dat, contents):
    try:
        dat.sendPong(contents)
    except Exception:
        pass
    return
```

> **Constant CHOP setup:** add a **Constant CHOP** named `constant1` with four
> channels (`value0`–`value3`). The callback writes the current stage index into
> `value0` on every `stage_update`, the finale fade-to-black fraction into
> `value1` on every `finale_progress`, the live online-audience count into
> `value2` on every `audience_update`, and the live "how many people scrolled
> this round" count into `value3` on every `scroll_update` (which resets to 0
> when the reel advances) — so anything downstream (a Switch TOP/SOP, `Select`,
> timeline logic) can react to any of the four by reading one number each. The
> server seeds stage + audience + scroll counts the moment TD connects, so the
> CHOP is correct even if TD starts mid-show.

> The server sends a `keepalive` (+ a protocol ping) every ~15s so the connection
> never idles out — that's what fixed the earlier ~30s disconnects (TD's
> WebSocket DAT doesn't auto-pong protocol pings). The `sendText` pong above adds
> upstream traffic for extra stability, and `onDisconnect` covers real drops.

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
