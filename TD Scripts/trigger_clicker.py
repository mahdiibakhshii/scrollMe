import sys

# Create a persistent storage dictionary
if 'instagram_state' not in sys.modules:
    sys.modules['instagram_state'] = type(sys)('instagram_state')
    sys.modules['instagram_state'].controller = None

def init_controller():
    """Initialize controller if not already done"""
    state = sys.modules['instagram_state']
    
    if state.controller is None:
        ws_url = "ws://localhost:9222/devtools/page/9DBF15DAB5DCB6E31AD2B82FC1DFB624"
        ctrl_class = op('chrome_controller').module.PersistentChromeController
        state.controller = ctrl_class(ws_url)
        state.controller.connect(timeout=3.0)
        print("🆕 Controller initialized")
    
    return state.controller

def click_next_reel():
    """Click the next reel button"""
    try:
        ctrl = init_controller()
        
        if not ctrl.is_connected():
            print("⚠️  Reconnecting...")
            ctrl.connect()
        
        if ctrl.is_connected():
            success = ctrl.click_by_aria_label("Navigate to next Reel")
            if success:
                print("✅ Reel clicked!")
                return True
            else:
                print("❌ Element not found")
                return False
        else:
            print("❌ Not connected")
            return False
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

# Initialize on startup
init_controller()
