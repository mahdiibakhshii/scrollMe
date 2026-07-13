from pythonosc import udp_client

class OSCClient:
    def __init__(self, ip, port):
        self.ip = ip
        self.port = port
        self.client = udp_client.SimpleUDPClient(ip, port)

    def send_message(self, address, value):
        try:
            self.client.send_message(address, value)
            print(f"OSC Sent: {address} -> {value}")
        except Exception as e:
            print(f"OSC Error: {e}")
