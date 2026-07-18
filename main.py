import asyncio
import math
import os
import random
import re
import sys
import socketio
from aiohttp import web
import config
from osc_client import OSCClient
from events import EventBus
from stages import STAGES

# Force UTF-8 stdout/stderr so print()ing event payloads that contain non-ASCII
# (stage labels use "→"/"·", texts use "—"/"…") never crashes on a Windows
# cp1252 console — a UnicodeEncodeError in a broadcast's print would otherwise
# abort the rest of a stage change. No-op on Linux (production).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8')
    except Exception:
        pass

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
finished_clients = set()    # finale stage: phones that have swiped to end their show

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
# vote instead of double-counting. `responses` (optional, one per option) is the
# personal message each voter gets back the moment they answer.
poll_state = {'active': False, 'question': '', 'options': [], 'votes': {}, 'responses': []}

# Snapshotted poll results, keyed by the stage id that ran the poll — captured
# when that poll ends, so a *later* stage can derive its behavior from an
# earlier vote (e.g. the collective-doomscroll threshold = the share of the
# room who voted "poor" in poll2). See collective_threshold().
poll_results = {}
poll_owner_stage = None  # stage id that started the active poll (None = ad-hoc admin poll)

# One-at-a-time "solo scroll" mode (see stages.py "solo" field). Independent of
# the collective threshold logic above — a stage uses exactly one of the two.
# phase: 'select' (waiting for the chosen phone to swipe) or 'result' (just
# swiped, holding its reward line before the next phone is chosen).
solo_state = {'active': False, 'phase': 'select', 'chosen_sid': None,
             'cfg': {}, 'timer_task': None}

# Event bus — the single fan-out point to phones, TouchDesigner (raw WS + Socket.IO)
# and OSC. Add new triggers by calling bus.broadcast('event_name', {...}).
bus = EventBus(sio, active_websockets, osc_client)


def current_stage():
    return STAGES[current_stage_index]


# --- Dynamic media (finale slideshow images + ending sound) ----------------
# Enumerated live from the static/ folders so the performer can swap the files
# freely without touching stages.py. A stage asks for this by setting an "auto"
# media field (screen.images / finale.sound); resolve_stage_config fills it in.

_IMAGE_EXTS = ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.avif')
_AUDIO_EXTS = ('.mp3', '.ogg', '.wav', '.m4a', '.aac')


def _natural_key(name):
    # "2.jpg" before "10.jpg": sort numeric chunks as numbers, not text.
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', name)]


def _list_media(subdir, exts):
    d = os.path.join('static', subdir)
    try:
        files = [f for f in os.listdir(d) if f.lower().endswith(exts)]
    except FileNotFoundError:
        return []
    files.sort(key=_natural_key)
    return [f'static/{subdir}/{f}' for f in files]


def resolve_stage_config(s):
    """Return the stage config with any 'auto' media fields filled from disk."""
    screen = s.get('screen') or {}
    fin = s.get('finale')
    wants_images = screen.get('mode') == 'slideshow' and screen.get('images') == 'auto'
    wants_sound = bool(fin) and fin.get('sound') == 'auto'
    if not (wants_images or wants_sound):
        return s
    s = dict(s)
    if wants_images:
        s['screen'] = dict(screen, images=_list_media('images', _IMAGE_EXTS))
    if wants_sound:
        sounds = _list_media('sound', _AUDIO_EXTS)
        s['finale'] = dict(fin, sound=sounds[0] if sounds else None)
    return s


def stage_payload():
    s = current_stage()
    return {'stage': s['id'], 'index': current_stage_index,
            'config': resolve_stage_config(s)}


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


async def start_poll(question, options, responses=None, owner=None):
    global poll_owner_stage
    poll_owner_stage = owner
    poll_state.update(active=True, question=question,
                      options=list(options), votes={},
                      responses=list(responses or []))
    await bus.broadcast('poll_start', {'question': question, 'options': list(options)})
    await emit_poll_update()


async def end_poll():
    global poll_owner_stage
    if not poll_state['active']:
        return
    poll_state['active'] = False
    # Preserve the final tally so a later stage can read it (keyed by the stage
    # that owned the poll). Ad-hoc admin polls (owner=None) aren't recorded.
    if poll_owner_stage:
        poll_results[poll_owner_stage] = poll_counts()
    await bus.broadcast('poll_end', poll_payload())
    await emit_poll_update()
    poll_owner_stage = None


async def emit_poll_update():
    """Live vote tally — admins only."""
    await sio.emit('poll_update', poll_payload(), room='admins')


def solo_payload():
    cfg = solo_state.get('cfg') or {}
    return {
        'active': solo_state['active'],
        'phase': solo_state['phase'],
        'chosen_sid': solo_state['chosen_sid'],
        'texts': {
            'chosen': cfg.get('chosen_text', 'You are the chosen one. Scroll for us.'),
            'result': cfg.get('result_text', ''),
            'not_chosen': cfg.get('not_chosen_text', 'You are not the selected one.'),
        },
    }


async def broadcast_solo_state():
    await bus.broadcast('solo_update', solo_payload())


async def pick_new_chosen():
    """Randomly hand the swipe privilege to one currently-online phone."""
    candidates = list(connected_clients)
    solo_state['chosen_sid'] = random.choice(candidates) if candidates else None
    solo_state['phase'] = 'select'
    await broadcast_solo_state()


async def start_solo_scroll(cfg):
    solo_state.update(active=True, cfg=cfg or {})
    await pick_new_chosen()


async def stop_solo_scroll():
    task = solo_state.get('timer_task')
    if task:
        task.cancel()
    solo_state.update(active=False, phase='select', chosen_sid=None, timer_task=None)


async def _solo_rotate_after(ms):
    try:
        await asyncio.sleep(ms / 1000)
    except asyncio.CancelledError:
        return
    if solo_state['active']:
        await pick_new_chosen()


async def solo_scroll_success():
    """The chosen phone swiped (or the admin manually credited it — see
    manual_next_reel): advance the reel, hold its reward line, then hand the
    privilege to a new random phone."""
    task = solo_state.get('timer_task')
    if task:
        task.cancel()  # don't let an earlier rotation fire on top of this one
    solo_state['phase'] = 'result'
    await broadcast_solo_state()
    await trigger_collective_action()
    hold_ms = (solo_state.get('cfg') or {}).get('result_hold_ms', 4000)
    solo_state['timer_task'] = asyncio.create_task(_solo_rotate_after(hold_ms))


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
    finished_clients.clear()   # finale "who ended the show" tally is per-entry

    # A running poll doesn't survive into a stage that doesn't declare one.
    if poll_state['active'] and not s.get('poll'):
        await end_poll()

    # Same for solo-scroll mode — it only runs while the current stage declares it.
    if solo_state['active'] and not s.get('solo'):
        await stop_solo_scroll()

    await bus.broadcast('stage_update', stage_payload())

    if s.get('vibrate_ms'):
        await bus.broadcast('vibrate', {'pattern': [s['vibrate_ms']]})

    if s.get('poll'):
        await start_poll(s['poll']['question'], s['poll']['options'],
                         s['poll'].get('responses'), owner=s['id'])

    if s.get('solo'):
        await start_solo_scroll(s['solo'])

    if s.get('finale'):
        await broadcast_finale_progress()  # seed TD's value1 at 0% on entry

    await broadcast_stats()
    await broadcast_scroll_count()  # fresh stage = fresh round → TD value3 = 0
    return True


async def reset_performance():
    """Admin 'Reset performance' — wipe everything that would otherwise carry
    over from a finished show into the next one: join numbering (so the next
    audience starts counting from 1 again), poll history/tallies (including
    the snapshots that drive poll-derived thresholds), and swipe/finale round
    state, then return to stage 0 (intro). Currently-connected phones are NOT
    disconnected — this clears counters/history, not sockets."""
    global next_person_number
    if poll_state['active']:
        await end_poll()
    poll_state.update(question='', options=[], votes={}, responses=[])
    poll_results.clear()
    next_person_number = 1
    client_person.clear()
    await apply_stage(STAGES[0]['id'])  # clears triggered/finished, stops solo, broadcasts stage_update + stats


async def trigger_collective_action():
    print("!!! COLLECTIVE SCROLL TRIGGERED !!!")

    # Fan the reel-advance event out to everyone (phones react + TD advances).
    await bus.broadcast('trigger_scroll', {'action': 'next_reel'})

    # Backward-compat OSC address for existing TD patches expecting /scroll_next.
    if osc_client:
        osc_client.send_message('/scroll_next', 1.0)

    # Reset state — the round is over, so the "who scrolled" count goes to 0.
    triggered_clients.clear()
    await broadcast_stats()
    await broadcast_scroll_count()   # -> TD constant1 value3 = 0


async def manual_next_reel():
    """Admin's "Next reel now" button — the performer forcing a reel change
    rather than the audience earning it by swiping. Every phone also gets a
    brief vibrate + pulse line ("Something is happening inside the tent.")
    that holds until the vibration ends, then reverts to whatever the current
    stage shows.

    In a solo-scroll stage this is treated as if the currently-chosen phone
    had swiped: the reel still advances, but the round also continues on
    schedule (reward line, hold, then a new phone is chosen) instead of
    leaving the old chosen phone stuck waiting forever."""
    print("!!! MANUAL NEXT REEL (admin) !!!")
    await bus.broadcast('manual_pulse', {
        'pattern': [config.ADMIN_PULSE_MS],
        'ms': config.ADMIN_PULSE_MS,
        'text': config.ADMIN_PULSE_TEXT,
    })
    if solo_state['active']:
        await solo_scroll_success()
    else:
        await trigger_collective_action()


def finale_progress_payload():
    """Fraction of the online audience that has ended the show (swiped in the
    finale stage). 0.0 → 1.0 — TD uses it as a fade-to-black amount."""
    online = len(connected_clients)
    finished = len(finished_clients)
    percent = (finished / online) if online > 0 else 0.0
    return {'finished': finished, 'online': online, 'percent': round(min(percent, 1.0), 4)}


async def broadcast_finale_progress():
    """Push the live finale percentage to TD (constant1 value1) + admin."""
    await bus.broadcast('finale_progress', finale_progress_payload())


def collective_threshold():
    """The swipe ratio the room must reach to advance the reel in the CURRENT
    stage. Normally the fixed config value (AUDIENCE_PERCENTAGE_THRESHOLD).

    A stage may instead declare `threshold_from_poll` = {stage, option} to
    derive the bar dynamically from an earlier vote: the threshold becomes the
    share of the online audience that picked that option (e.g. stage 6 sets its
    bar to the fraction who voted "poor" in poll2 — the room then has to
    collectively out-swipe that fraction to move the reel). Clamped to <= 1.0;
    if nobody's online the bar is 1.0 (unreachable)."""
    tfp = current_stage().get('threshold_from_poll')
    if not tfp:
        return config.AUDIENCE_PERCENTAGE_THRESHOLD
    counts = poll_results.get(tfp.get('stage'), [])
    opt = tfp.get('option', 0)
    votes = counts[opt] if 0 <= opt < len(counts) else 0
    online = len(connected_clients)
    if online <= 0:
        return 1.0
    return min(votes / online, 1.0)


def scrolls_needed():
    """How many swipes total are required to advance the reel right now."""
    active = len(connected_clients)
    return max(1, math.ceil(active * collective_threshold()))


async def emit_scroll_feedback():
    """In a collective stage with `scroll_feedback`, tell every phone that has
    already swiped this round how many MORE swipes are still needed. Sent to
    each swiper individually (their own room) and refreshed on every new swipe,
    so the number ticks down live. Non-swipers never get it — they keep the
    normal 'Scroll me' screen."""
    cfg = current_stage().get('scroll_feedback')
    if not cfg or not triggered_clients:
        return
    remaining = max(1, scrolls_needed() - len(triggered_clients))
    template = (cfg.get('waiting_text') if isinstance(cfg, dict) else None) \
        or 'Got it — waiting on {n} more to scroll…'
    text = template.replace('{n}', str(remaining))
    for target in list(triggered_clients):
        await sio.emit('scroll_wait', {'remaining': remaining, 'text': text}, room=target)


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
        'threshold': collective_threshold(),
        'stage': current_stage()['id'],
        'td_connected': len(active_websockets),
    })


async def broadcast_audience():
    """Push the live online-audience count to TD (constant1 value2) too —
    unlike stats_update above (Socket.IO only, phones + admin), this goes
    through the event bus so TD's raw WS gets it live as well. Call only from
    the three places connected_clients actually changes size (a phone joining,
    leaving, or a phone re-registering as an admin) — no need to spam it on
    every swipe/stage change where the online count itself didn't move."""
    await bus.broadcast('audience_update', {'online': len(connected_clients)})


async def broadcast_scroll_count():
    """Push the live count of phones that have swiped in the CURRENT round to TD
    (constant1 value3) so the projection can show how many people have scrolled.
    Goes through the event bus (not just stats_update, which is Socket.IO-only)
    so TD's raw WS gets it. Call wherever triggered_clients changes size — on a
    swipe, and on every reset (reel triggers, stage change, admin reset round, a
    swiper dropping): the count returns to 0 the instant the round resets."""
    await bus.broadcast('scroll_update', {'scrolled': len(triggered_clients)})


@sio.event
async def connect(sid, environ):
    # Universal Welcome Message (Debug)
    await sio.emit('connection_ack', {'message': 'Welcome to Doom Server'}, room=sid)

    # Treat everyone as a client (Simplification requested by user)
    print(f"--> Client connected: {sid}")
    connected_clients.add(sid)
    await broadcast_audience()

    # Sync the newcomer to where the performance currently is.
    await sio.emit('stage_update', stage_payload(), room=sid)
    if poll_state['active']:
        await sio.emit('poll_start', {'question': poll_state['question'],
                                      'options': poll_state['options']}, room=sid)
    if solo_state['active']:
        if solo_state['chosen_sid'] is None:
            await pick_new_chosen()  # nobody was online to choose from yet
        else:
            await sio.emit('solo_update', solo_payload(), room=sid)
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
        finished_clients.discard(sid)
        client_person.pop(sid, None)  # number is never reused; just stop tracking
        # Don't leave the show stalled waiting on a swipe that can never come.
        if solo_state['active'] and solo_state['phase'] == 'select' and solo_state['chosen_sid'] == sid:
            await pick_new_chosen()
        if current_stage().get('finale'):
            await broadcast_finale_progress()  # online count changed → new %
        await broadcast_audience()
        await broadcast_stats()
        await broadcast_scroll_count()  # a swiper leaving changes the count → TD value3
    else:
        print(f"Device disconnected: {sid}")


@sio.event
async def swipe(sid, data):
    """
    Event received when a user swipes up.
    Solo-scroll stages (see stages.py "solo") only accept a swipe from the
    currently-chosen phone, during the 'select' phase, and never fall through
    to the collective-threshold logic below. Any other stage keeps the
    original scroll_enabled + percentage-threshold behavior unchanged.
    """
    if sid not in connected_clients:
        return

    if solo_state['active']:
        if sid == solo_state['chosen_sid'] and solo_state['phase'] == 'select':
            print(f"Chosen swipe received from {sid}")
            await solo_scroll_success()
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

    # One steady rule: advance the reel once at least 50% of the online audience
    # have swiped this round (collective_threshold() is the fixed config value).
    if ratio >= collective_threshold():
        await trigger_collective_action()   # clears the round + broadcasts scroll count 0
    else:
        await broadcast_stats()
        # Live count of who's scrolled so far → TD (constant1 value3).
        await broadcast_scroll_count()
        # Per-swiper feedback: "your scroll is in, N more still needed."
        await emit_scroll_feedback()


@sio.event
async def finished(sid, data):
    """Finale stage: a phone swiped to end its show. We tally these to publish a
    live fraction (finished / online) that TD uses as a fade-to-black amount.
    Idempotent (a re-announce on reconnect just re-adds the same sid)."""
    if sid not in connected_clients:
        return
    if not current_stage().get('finale'):
        return
    if sid not in finished_clients:
        finished_clients.add(sid)
        print(f"Finale: {sid} finished ({len(finished_clients)}/{len(connected_clients)})")
    await broadcast_finale_progress()


@sio.event
async def vote(sid, data):
    """Audience vote in the active poll. Re-voting replaces the previous vote."""
    if not poll_state['active']:
        return
    option = (data or {}).get('option')
    if not isinstance(option, int) or not (0 <= option < len(poll_state['options'])):
        return
    poll_state['votes'][sid] = option
    responses = poll_state.get('responses') or []
    response = responses[option] if option < len(responses) else None
    await sio.emit('vote_ack', {'option': option, 'response': response}, room=sid)
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
        'threshold': collective_threshold(),
        'threshold_info': threshold_info(),
        'finale': finale_progress_payload(),
        'td_connected': len(active_websockets),
    }


def threshold_info():
    """Human-readable note about where the current stage's threshold comes from
    (so the performer can see 'derived from poll2 Yes' in the console)."""
    tfp = current_stage().get('threshold_from_poll')
    if not tfp:
        return None
    counts = poll_results.get(tfp.get('stage'), [])
    opt = tfp.get('option', 0)
    votes = counts[opt] if 0 <= opt < len(counts) else 0
    return {'from_stage': tfp.get('stage'), 'option': opt, 'votes': votes,
            'recorded': tfp.get('stage') in poll_results}


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
    await broadcast_audience()
    await broadcast_stats()
    await broadcast_scroll_count()  # a phone becoming admin may drop it from the round


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
        await manual_next_reel()
    elif cmd == 'reset_round':
        triggered_clients.clear()
        await sio.emit('scroll_reset', {})  # clear any 'waiting' text on phones
        await broadcast_stats()
        await broadcast_scroll_count()  # round cleared → TD value3 = 0
    elif cmd == 'start_poll':
        question = (data.get('question') or '').strip()
        options = [o for o in (data.get('options') or []) if str(o).strip()]
        if question and len(options) >= 2:
            await start_poll(question, options[:2], data.get('responses'))
    elif cmd == 'end_poll':
        await end_poll()
    elif cmd == 'reset_performance':
        await reset_performance()
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
        'threshold': collective_threshold(),
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

    # Tell TD where the performance currently is the moment it connects, and seed
    # the live audience + scroll counts so its CHOP is correct even mid-show.
    try:
        await ws.send_json({'event': 'stage_update', 'data': stage_payload()})
        await ws.send_json({'event': 'audience_update', 'data': {'online': len(connected_clients)}})
        await ws.send_json({'event': 'scroll_update', 'data': {'scrolled': len(triggered_clients)}})
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
