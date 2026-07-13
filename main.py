import asyncio
import socketio
from aiohttp import web
import config
from osc_client import OSCClient
from events import EventBus

# Initialize Socket.IO Server
sio = socketio.AsyncServer(async_mode='aiohttp', cors_allowed_origins='*')
app = web.Application()
sio.attach(app)

# Initialize OSC Client (local fallback only; disabled on the server via OSC_ENABLED=0)
osc_client = OSCClient(config.OSC_IP, config.OSC_PORT) if config.OSC_ENABLED else None

# State
connected_clients = set()
triggered_clients = set()
active_websockets = set()

# Event bus — the single fan-out point to phones, TouchDesigner (raw WS + Socket.IO)
# and OSC. Add new triggers by calling bus.broadcast('event_name', {...}).
bus = EventBus(sio, active_websockets, osc_client)


async def trigger_collective_action():
    print("!!! COLLECTIVE SCROLL TRIGGERED !!!")

    # Fan the reel-advance event out to everyone (phones react + TD advances).
    await bus.broadcast('trigger_scroll', {'action': 'next_reel'})

    # Backward-compat OSC address for existing TD patches expecting /scroll_next.
    if osc_client:
        osc_client.send_message('/scroll_next', 1.0)

    # Reset state
    triggered_clients.clear()
    await broadcast_stats()


async def broadcast_stats():
    """Send current progress to all clients"""
    if not connected_clients:
        return

    active_count = len(connected_clients)
    trigger_count = len(triggered_clients)
    percentage = trigger_count / active_count if active_count > 0 else 0.0
    percentage = min(percentage, 1.0)

    await sio.emit('stats_update', {
        'active_users': active_count,
        'progress': percentage,
        'threshold': config.AUDIENCE_PERCENTAGE_THRESHOLD
    })


@sio.event
async def connect(sid, environ):
    # Universal Welcome Message (Debug)
    await sio.emit('connection_ack', {'message': 'Welcome to Doom Server'}, room=sid)

    # Treat everyone as a client (Simplification requested by user)
    print(f"--> Client connected: {sid}")
    connected_clients.add(sid)
    await broadcast_stats()


@sio.event
async def disconnect(sid):
    if sid in connected_clients:
        print(f"Audience received disconnect: {sid}")
        connected_clients.remove(sid)
        if sid in triggered_clients:
            triggered_clients.remove(sid)
        await broadcast_stats()
    else:
        print(f"Device disconnected: {sid}")


@sio.event
async def swipe(sid, data):
    """
    Event received when a user swipes up.
    """
    if sid not in connected_clients:
        return

    print(f"Swipe received from {sid}")

    # Add to triggered set
    triggered_clients.add(sid)

    # Check Threshold
    active_count = len(connected_clients)
    if active_count == 0:
        return

    ratio = len(triggered_clients) / active_count

    if ratio >= config.AUDIENCE_PERCENTAGE_THRESHOLD:
        await trigger_collective_action()
    else:
        await broadcast_stats()


# --- HTTP routes -----------------------------------------------------------

async def index(request):
    # TouchDesigner's WebSocket DAT connects to the ROOT path (it exposes only
    # Network Address + Network Port, no path field), so accept a WebSocket
    # upgrade here too. Normal browsers still get the phone page.
    if request.headers.get('Upgrade', '').lower() == 'websocket':
        return await websocket_handler(request)
    return web.FileResponse('./static/index.html')


async def admin_page(request):
    return web.FileResponse('./static/admin.html')


async def healthz(request):
    """Liveness + quick state snapshot (used by deploy/monitoring)."""
    return web.json_response({
        'status': 'ok',
        'connected_clients': len(connected_clients),
        'triggered_clients': len(triggered_clients),
        'td_websockets': len(active_websockets),
        'threshold': config.AUDIENCE_PERCENTAGE_THRESHOLD,
    })


async def admin_event(request):
    """Fire an arbitrary event at TD (and phones) on demand.

    POST /admin/event   { "type": "trigger_scroll", "payload": { ... } }
    Auth: header 'X-Admin-Token' or query '?token=' must match config.ADMIN_TOKEN
    (skipped when ADMIN_TOKEN is empty). This is how future triggers are sent
    without any code change — pick a `type`, TD switches on it.
    """
    if config.ADMIN_TOKEN:
        token = request.headers.get('X-Admin-Token') or request.query.get('token', '')
        if token != config.ADMIN_TOKEN:
            return web.json_response({'error': 'unauthorized'}, status=401)

    try:
        data = await request.json()
    except Exception:
        data = {}

    event_type = data.get('type') or request.query.get('type')
    if not event_type:
        return web.json_response({'error': 'missing event type'}, status=400)

    payload = data.get('payload') or {}
    await bus.broadcast(event_type, payload)
    return web.json_response({'ok': True, 'type': event_type, 'payload': payload})


async def websocket_handler(request):
    """Raw WebSocket for TouchDesigner. TD connects OUT to ws://<host>/ws (or the
    root path) and the server pushes events down as JSON:
    {"event": <type>, "data": <payload>}.

    No aiohttp `heartbeat=` here on purpose: it pings and then CLOSES the socket
    if no pong comes back, and TouchDesigner's WebSocket DAT doesn't reliably
    pong — that caused the ~30s disconnects. Instead the keepalive_task below
    sends an app-level {"event":"keepalive"} every few seconds, which keeps the
    connection warm through TD + NAT + nginx without needing a pong."""
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    print("--> TouchDesigner (Raw WS) connected")
    active_websockets.add(ws)

    try:
        async for msg in ws:
            pass  # We only send data to TD, we don't expect it to send data back
    except Exception as e:
        print(f"WS Error: {e}")
    finally:
        print("TouchDesigner (Raw WS) disconnected")
        active_websockets.discard(ws)

    return ws


async def keepalive_task(app):
    """Push a lightweight keepalive to every TD WebSocket on a fixed interval so
    the connection never sits idle long enough for TD / NAT / nginx to drop it,
    and prune any socket that has quietly died."""
    while True:
        await asyncio.sleep(config.KEEPALIVE_INTERVAL)
        dead = set()
        for ws in list(active_websockets):
            try:
                await ws.send_json({'event': 'keepalive', 'data': {}})
            except Exception:
                dead.add(ws)
        for ws in dead:
            active_websockets.discard(ws)


async def _on_startup(app):
    app['keepalive'] = asyncio.create_task(keepalive_task(app))


async def _on_cleanup(app):
    task = app.get('keepalive')
    if task:
        task.cancel()


app.on_startup.append(_on_startup)
app.on_cleanup.append(_on_cleanup)

app.router.add_get('/', index)
app.router.add_get('/admin', admin_page)
app.router.add_get('/healthz', healthz)
app.router.add_post('/admin/event', admin_event)
app.router.add_get('/ws', websocket_handler)
app.router.add_static('/static/', path='static', name='static')

if __name__ == '__main__':
    print(f"ScrollMe server on {config.HOST}:{config.PORT} "
          f"(OSC {'on' if osc_client else 'off'}, admin {'token-protected' if config.ADMIN_TOKEN else 'OPEN'})")
    web.run_app(app, host=config.HOST, port=config.PORT)
