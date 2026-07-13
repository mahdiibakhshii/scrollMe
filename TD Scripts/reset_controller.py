import sys

def reset_controller():
    """Reset and reconnect to Chrome"""
    print("🔄 Resetting controller...")
    
    if 'instagram_state' in sys.modules:
        state = sys.modules['instagram_state']
        
        # Close old connection
        if state.controller:
            try:
                state.controller.close()
                print("✅ Old connection closed")
            except:
                pass
        
        # Clear controller
        state.controller = None
        print("✅ Controller cleared")
    
    # Reinitialize with new connection
    try:
        op('trigger_clicker').module.init_controller()
        print("✅ Controller reconnected!")
        return True
    except Exception as e:
        print(f"❌ Error reinitializing: {e}")
        return False
