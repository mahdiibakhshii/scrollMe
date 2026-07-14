import asyncio
import socketio
from aiohttp import web
import config
from osc_client import OSCClient
from events import EventBus
from stages import STAGES

# Initialize Socket.IO Server
sio = socketio.AsyncServer(async_mode='aiohttp', cors_allowed_origins='*')
app = web.Application()
sio.attach(app)

# Initialize OSC Client (local fallback only; disabled on the server via OSC_ENABLED=0)
osc_client = OSCClient(config.OSC_IP, config.OSC_PORT) if config.OSC_ENABLED else None

# State
connected_clients = set()   # audience phones (Socket.IO sids)
triggered_clients = set()   # phones that swiped in the current round
admins = set()              # performer console sids (excluded from audience counts)
active_websockets = set()   # raw WS connections (TouchDesigner)

# Performance stage — index into STAGES. The performer drives this from /admin;
# every change is broadcast to phones + TD as `stage_update` (TD writes the
# index into a Constant CHOP as its "state number"). Boot into the first stage
# (intro / gather) — that's step 1 of the show.
current_stage_index = 0

# Stable per-phone label: the Nth person to open the page. Monotonic and never
# reused — person 5 stays "5" for the whole show even if others leave, and a new
# joiner always gets a fresh higher number. Used by the intro/gather screen.
next_person_number = 1
client_person = {}   # sid -> assigned number

# Live poll — one at a time. Votes are keyed by sid so a re-tap changes the
# vote instead of double-counting.
poll_state = {'active': False, 'question': '', 'options': [], 'votes': {}}

# Event bus — the single fan-out point to phones, TouchDesigner (raw WS + Socket.IO)
# and OSC. Add new triggers by calling bus.broadcast('event_name', {...}).
bus = EventBus(sio, active_websockets, osc_client)


def current_stage():
    return STAGES[current_stage_index]


def stage_payload():
    s = current_stage()
    return {'stage': s['id'], 'index': current_stage_index, 'config': s}


def poll_counts():
    counts = [0] * len(poll_state['options'])
    for idx in poll_state['votes'].values():
        if 0 <= idx < len(counts):
            counts[idx] += 1
    return counts


def poll_payload():
    return {
        'active': poll_state['active'],
        'question': poll_state['question'],
        'options': poll_state['options'],
        'counts': poll_counts(),
        'total': len(poll_state['votes']),
    }


async def start_poll(question, options):
    poll_state.update(active=True, question=question,
                      options=list(options), votes={})
    await bus.broadcast('poll_start', {'question': question, 'options': list(options)})
    await emit_poll_update()


async def end_poll():
    if not poll_state['active']:
        return
    poll_state['active'] = False
    await bus.broadcast('poll_end', poll_payload())
    await emit_poll_update()


async def emit_poll_update():
    """Live vote tally — admins only."""
    await sio.emit('poll_update', poll_payload(), room='admins')


async def apply_stage(stage_id):
    """Switch the performance to a stage: broadcast to phones + TD, run the
    stage's side effects (vibrate on entry, start/stop its poll)."""
    global current_stage_index
    for i, s in enumerate(STAGES):
        if s['id'] == stage_id:
            current_stage_index = i
            break
    else:
        return False

    s = current_stage()
    triggered_clients.clear()  # each stage starts a fresh swipe round

    # A running poll doesn't survive into a stage that doesn't declare one.
    if poll_state['active'] and not s.get('poll'):
        await end_poll()

    await bus.broadcast('stage_update', stage_payload())

    if s.get('vibrate_ms'):
        await bus.broadcast('vibrate', {'pattern': [s['vibrate_ms']]})

    if s.get('poll'):
        await start_poll(s['poll']['question'], s['poll']['options'])

    await broadcast_stats()
    return True


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
    """Send current progress to all clients (admins listen too)."""
    active_count = len(connected_clients)
    trigger_count = len(triggered_clients)
    percentage = trigger_count / active_count if active_count > 0 else 0.0
    percentage = min(percentage, 1.0)

    await sio.emit('stats_update', {
        'active_users': active_count,
        'joined': next_person_number - 1,
        'triggered': trigger_count,
        'progress': percentage,
        'threshold': config.AUDIENCE_PERCENTAGE_THRESHOLD,
        'stage': current_stage()['id'],
        'td_connected': len(active_websockets),
    })


@sio.event
async def connect(sid, environ):
    # Universal Welcome Message (Debug)
    await sio.emit('connection_ack', {'message': 'Welcome to Doom Server'}, room=sid)

    # Treat everyone as a client (Simplification requested by user)
    print(f"--> Client connected: {sid}")
    connected_clients.add(sid)

    # Sync the newcomer to where the performance currently is.
    await sio.emit('stage_update', stage_payload(), room=sid)
    if poll_state['active']:
        await sio.emit('poll_start', {'question': poll_state['question'],
                                      'options': poll_state['options']}, room=sid)
    await broadcast_stats()
    # The phone follows up with `hello` (carrying any number it already holds
    # from a reload) so we can hand back a stable person label.


@sio.event
async def hello(sid, data):
    """Phone announces itself and (re)claims its person number. On a fresh open
    it has none, so we mint the next one; on a reload it sends the number it
    cached, and we honor it so the label never changes mid-show."""
    global next_person_number
    if sid not in connected_clients:
        return
    prior = (data or {}).get('number')
    if isinstance(prior, int) and prior > 0:
        number = prior
        next_person_number = max(next_person_number, prior + 1)
    else:
        number = next_person_number
        next_person_number += 1
    client_person[sid] = number
    await sio.emit('you_are', {'number': number}, room=sid)


@sio.event
async def disconnect(sid):
    if sid in admins:
        admins.discard(sid)
        print(f"Admin disconnected: {sid}")
        return
    if sid in connected_clients:
        print(f"Audience received disconnect: {sid}")
        connected_clients.remove(sid)
        triggered_clients.discard(sid)
        client_person.pop(sid, None)  # number is never reused; just stop tracking
        await broadcast_stats()
    else:
        print(f"Device disconnected: {sid}")


@sio.event
async def swipe(sid, data):
    """
    Event received when a user swipes up.
    Only counts while the current stage has scrolling enabled.
    """
    if sid not in connected_clients:
        return
    if not current_stage().get('scroll_enabled'):
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


@sio.event
async def vote(sid, data):
    """Audience vote in the active poll. Re-voting replaces the previous vote."""
    if not poll_state['active']:
        return
    option = (data or {}).get('option')
    if not isinstance(option, int) or not (0 <= option < len(poll_state['options'])):
        return
    poll_state['votes'][sid] = option
    await sio.emit('vote_ack', {'option': option}, room=sid)
    await emit_poll_update()


# --- Admin (performer console) over Socket.IO --------------------------------

def _admin_ok(sid, data):
    if sid in admins:
        return True
    if config.ADMIN_TOKEN:
        return (data or {}).get('token', '') == config.ADMIN_TOKEN
    return True


def admin_snapshot():
    return {
        'stages': [{'id': s['id'], 'label': s['label'],
                    'scroll_enabled': s['scroll_enabled'],
                    'vibrate_ms': s.get('vibrate_ms', 0),
                    'has_poll': bool(s.get('poll'))} for s in STAGES],
        'stage': stage_payload(),
        'poll': poll_payload(),
        'active_users': len(connected_clients),
        'joined': next_person_number - 1,   # total phones that ever opened the page
        'triggered': len(triggered_clients),
        'threshold': config.AUDIENCE_PERCENTAGE_THRESHOLD,
        'td_connected': len(active_websockets),
    }


@sio.event
async def register_admin(sid, data):
    """The /admin page identifies itself so it's not counted as audience."""
    if not _admin_ok(sid, data):
        await sio.emit('admin_denied', {}, room=sid)
        return
    connected_clients.discard(sid)
    triggered_clients.discard(sid)
    admins.add(sid)
    await sio.enter_room(sid, 'admins')
    print(f"--> Admin registered: {sid}")
    await sio.emit('admin_state', admin_snapshot(), room=sid)
    await broadcast_stats()


@sio.event
async def admin_cmd(sid, data):
    """All performer actions arrive here: {cmd: ..., ...args}."""
    if sid not in admins:
        return
    data = data or {}
    cmd = data.get('cmd')

    if cmd == 'set_stage':
        await apply_stage(data.get('stage', ''))
    elif cmd == 'vibrate':
        ms = int(data.get('ms', 300))
        await bus.broadcast('vibrate', {'pattern': [max(1, min(ms, 5000))]})
    elif cmd == 'trigger_scroll':
        await trigger_collective_action()
    elif cmd == 'reset_round':
        triggered_clients.clear()
        await broadcast_stats()
    elif cmd == 'start_poll':
        question = (data.get('question') or '').strip()
        options = [o for o in (data.get('options') or []) if str(o).strip()]
        if question and len(options) >= 2:
            await start_poll(question, options[:2])
    elif cmd == 'end_poll':
        await end_poll()
    elif cmd == 'event':
        # Escape hatch: fire any named event with any payload (same as POST /admin/event).
        if data.get('type'):
            await bus.broadcast(data['type'], data.get('payload') or {})

    await sio.emit('admin_state', admin_snapshot(), room='admins')


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
        'stage': current_stage()['id'],
        'poll': poll_payload(),
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

    # Tell TD where the performance currently is the moment it connects.
    try:
        await ws.send_json({'event': 'stage_update', 'data': stage_payload()})
    except Exception:
        pass

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
                # Protocol-level ping too. Unlike aiohttp's heartbeat=, this does
                # NOT force-close on a missing pong, so it's safe even if a client
                # never pongs — it just adds a liveness probe for clients that do.
                await ws.ping()
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
