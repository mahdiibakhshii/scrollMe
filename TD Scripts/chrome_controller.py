import json
import websocket
import time
import threading

class PersistentChromeController:
    def __init__(self, ws_url):
        self.ws_url = ws_url
        self.ws = None
        self.message_id = 0
        self.responses = {}
        self.connected = False
        self.lock = threading.Lock()
    
    def connect(self, timeout=3.0):
        """Connect to Chrome and keep connection alive"""
        if self.connected:
            return True
        
        try:
            print("🔗 Connecting to Chrome...")
            self.ws = websocket.WebSocketApp(
                self.ws_url,
                on_open=self._on_open,
                on_message=self._on_message,
                on_error=self._on_error,
                on_close=self._on_close
            )
            
            t = threading.Thread(target=self.ws.run_forever, daemon=True)
            t.start()
            
            start = time.time()
            while not self.connected and time.time() - start < timeout:
                time.sleep(0.01)
            
            if self.connected:
                print("✅ Connected successfully!")
                return True
            else:
                print("❌ Connection timeout")
                return False
                
        except Exception as e:
            print(f"❌ Connection error: {e}")
            return False
    
    def _on_open(self, ws):
        self.connected = True
        print("📡 WebSocket opened")
    
    def _on_close(self, ws, close_status_code, close_msg):
        self.connected = False
        print("📡 WebSocket closed")
    
    def _on_message(self, ws, message):
        try:
            data = json.loads(message)
            if 'id' in data:
                with self.lock:
                    self.responses[data['id']] = data
        except:
            pass
    
    def _on_error(self, ws, error):
        print(f"⚠️  WebSocket error: {error}")
    
    def is_connected(self):
        return self.connected
    
    def send_command(self, method, params=None, timeout=0.5):
        if not self.connected:
            return None
        
        with self.lock:
            self.message_id += 1
            msg_id = self.message_id
        
        command = {
            'id': msg_id,
            'method': method,
            'params': params or {}
        }
        
        try:
            self.ws.send(json.dumps(command))
            
            start = time.time()
            while msg_id not in self.responses:
                if time.time() - start > timeout:
                    return None
                time.sleep(0.01)
            
            with self.lock:
                response = self.responses.pop(msg_id)
            return response
            
        except Exception as e:
            return None
    
    def click_by_aria_label(self, label):
        if not self.connected:
            return False
        
        script = f"""
        (function() {{
            const element = document.querySelector('[aria-label="{label}"]');
            if (!element) {{
                return {{success: false}};
            }}
            
            const clickEvent = new MouseEvent('click', {{
                bubbles: true,
                cancelable: true,
                view: window
            }});
            element.dispatchEvent(clickEvent);
            
            return {{success: true}};
        }})()
        """
        
        response = self.send_command('Runtime.evaluate', {
            'expression': script,
            'returnByValue': True
        }, timeout=0.3)
        
        if response and 'result' in response:
            result = response['result'].get('value', {})
            return result.get('success', False)
        return False
    
    def close(self):
        if self.ws:
            self.ws.close()
            self.connected = False
