"""Generic event dispatch.

One place that fans a *named* event out to every transport at once:

  - phones            -> Socket.IO event  (emit(event_type, payload))
  - TouchDesigner     -> raw WebSocket    ({"event": event_type, "data": payload})
                         and Socket.IO    (if TD uses a SocketIO DAT)
  - OSC               -> /<event_type>    (local fallback only)

To add a new performance trigger in the future you do NOT touch any transport
code — you just call `bus.broadcast("your_event", {...})` from wherever the
trigger originates (a swipe threshold, an admin button, a timer, ...). TD reacts
by switching on the `event` field of the JSON it receives on /ws.
"""


class EventBus:
    def __init__(self, sio, active_websockets, osc_client=None):
        self.sio = sio
        self.active_websockets = active_websockets  # set of raw aiohttp WebSocketResponse (TD)
        self.osc_client = osc_client                # OSCClient or None

    async def broadcast(self, event_type, payload=None):
        """Send one event to phones, TouchDesigner (raw WS + Socket.IO) and OSC."""
        payload = payload or {}

        # 1. Phones + any Socket.IO-based TD client.
        await self.sio.emit(event_type, payload)

        # 2. TouchDesigner raw WebSocket clients — uniform envelope {event, data}.
        dead = set()
        for ws in self.active_websockets:
            try:
                await ws.send_json({'event': event_type, 'data': payload})
            except Exception:
                dead.add(ws)
        for ws in dead:
            self.active_websockets.discard(ws)

        # 3. OSC local fallback (no-op when disabled / TD is remote).
        if self.osc_client:
            self.osc_client.send_message(f'/{event_type}', 1.0)

        print(f"[event] {event_type} -> phones + {len(self.active_websockets)} TD ws  {payload}")
