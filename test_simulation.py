import socketio
import time
import sys

# Standard synchronous client for testing
sio = socketio.Client()

client_name = "TEST_CLIENT_1"

@sio.event
def connect():
    print(f"[{client_name}] Connected!")

@sio.event
def connect_error(data):
    print(f"[{client_name}] Connection Error: {data}")

@sio.event
def disconnect():
    print(f"[{client_name}] Disconnected from server")

@sio.on('stats_update')
def on_stats_update(data):
    # data expects: {'active_users': int, 'progress': float, 'threshold': float}
    print(f"[{client_name}] RECEIVED BROADCAST: Active Users: {data.get('active_users')} | Progress: {data.get('progress'):.0%} | Threshold: {data.get('threshold')}")

def run_test():
    server_url = 'http://localhost:8080'
    print(f"[{client_name}] Attempting to connect to {server_url}...")
    
    try:
        sio.connect(server_url)
    except Exception as e:
        print(f"Failed to connect: {e}")
        return

    # Keep connection open for a few seconds to receive updates
    print(f"[{client_name}] Waiting 5 seconds to observe other checks...")
    time.sleep(5)
    
    print(f"[{client_name}] Disconnecting...")
    sio.disconnect()

if __name__ == '__main__':
    run_test()
