import socketio
import time

# Force pure websocket to match what we want TD to do
sio = socketio.Client(reconnection=True, request_timeout=5)

@sio.event
def connect():
    print("[TD Emulator] Connected! (Transport: Websocket)")

@sio.event
def connect_error(data):
    print(f"[TD Emulator] Connection Error: {data}")

@sio.event
def disconnect():
    print("[TD Emulator] Disconnected")

@sio.on('connection_ack')
def on_ack(data):
    print(f"[TD Emulator] SUCCESS: Received ACK from Server -> {data}")

@sio.on('trigger_scroll')
def on_trigger(data):
    print(f"[TD Emulator] RECEIVED TRIGGER: {data}")

@sio.on('stats_update')
def on_stats(data):
    # reduce spam, only print sometimes or just dot
    print(f"[TD Emulator] Stats Update: {data}")

if __name__ == '__main__':
    try:
        url = 'http://localhost:8080'
        print(f"[TD Emulator] Connecting to {url}...")
        # Force websocket to avoid polling issues
        sio.connect(url, transports=['websocket'])
        sio.wait()
    except KeyboardInterrupt:
        print("Stopping...")
    except Exception as e:
        print(f"CRASH: {e}")
