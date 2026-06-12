import threading
import time
import uvicorn
import webview
from fast_app import app

def start_server():
    # Start the FastAPI backend server quietly in the background
    uvicorn.run(app, host="127.0.0.1", port=8502, log_level="error")

if __name__ == '__main__':
    print("Starting backend server...")
    # 1. Launch the server in a background thread
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()
    
    # 2. Give the server a second to initialize
    time.sleep(1.5)
    
    print("Launching native desktop window...")
    # 3. Create a native OS window that points to our local server
    webview.create_window(
        title='Research Copilot', 
        url='http://127.0.0.1:8502', 
        width=1280, 
        height=850,
        min_size=(800, 600),
        text_select=True
    )
    
    # 4. Start the desktop window event loop (this blocks until you close the app)
    webview.start()
