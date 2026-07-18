import json

TARGET      = 'button1'     # your Button COMP to pulse on trigger_scroll
STAGE_CHOP  = 'constant1'   # a Constant CHOP:
                            #   value0 = current stage index (state number)
                            #   value1 = finale fade-to-black amount (0..1)
                            #   value2 = live online-audience count

# Stage index written to STAGE_CHOP value0 (data.index on every stage_update):
#   0 intro · 1 lost · 2 poll1 · 3 scroll1 · 4 poll2 · 5 collective1 ·
#   6 collective2 · 7 finale · 8 idle · 9 scroll · 10 poll · 11 image ·
#   12 black · 13 end

def onConnect(dat):
    debug('WebSocket connected')
    return

def onDisconnect(dat):
    # Auto-reconnect on any drop (network blip, server restart).
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
        try:
            dat.sendText('{"type":"pong"}')   # pong back for stability
        except Exception:
            pass
        return
    if event == 'trigger_scroll':
        op(TARGET).click()                    # advance to next reel
        return
    if event == 'stage_update':
        idx = data.get('index')
        if idx is not None:
            op(STAGE_CHOP).par.value0 = idx   # current stage / state number
            debug(f"stage -> {data.get('stage')} (index {idx})")
        return
    if event == 'finale_progress':
        # Stage 8: live fraction (0..1) of the audience who ended their show.
        # Use as the fade-to-black amount. Sent on entry (0) and on every change.
        op(STAGE_CHOP).par.value1 = data.get('percent', 0.0)
        return
    if event == 'audience_update':
        # Live count of currently-connected phones. Sent every time someone
        # joins, leaves, or a phone registers as an admin (admins don't count).
        op(STAGE_CHOP).par.value2 = data.get('online', 0)
        return
    return

def onReceivePing(dat, contents):
    try:
        dat.sendPong(contents)
    except Exception:
        pass
    return
