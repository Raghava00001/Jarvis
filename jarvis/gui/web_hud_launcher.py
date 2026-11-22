"""
JARVIS Web HUD Launcher
Opens the Iron Man style holographic HUD with WebSocket backend
"""

import http.server
import socketserver
import webbrowser
import os
import sys
import threading
import asyncio
from pathlib import Path

# Fix module imports by adding project root to path
current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent.parent
jarvis_root = current_dir.parent

sys.path.insert(0, str(project_root))
sys.path.insert(0, str(jarvis_root))



class HUDRequestHandler(http.server.SimpleHTTPRequestHandler):
    """Serves web_hud/, injecting the per-session WebSocket token into index.html.

    The token sits inside the HTML, which other websites cannot read
    cross-origin, so only the real HUD page can open the WebSocket.
    """

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            from jarvis.gui.session_token import get_ws_token
            html = (Path(self.directory) / "index.html").read_text(encoding="utf-8")
            body = html.replace("__JARVIS_WS_TOKEN__", get_ws_token()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()


def start_http_server(port=8080):
    """Start a simple HTTP server to serve the web HUD"""
    web_dir = Path(__file__).parent / "web_hud"
    
    if not web_dir.exists():
        print(f"[ERROR] Web HUD directory not found: {web_dir}")
        return None
    
    # Serve web_hud/ without os.chdir() (which changed the CWD of the whole
    # JARVIS process) and bind to loopback only so the HUD isn't exposed on the LAN.
    import functools
    handler = functools.partial(HUDRequestHandler, directory=str(web_dir))
    httpd = socketserver.TCPServer(("127.0.0.1", port), handler)
    
    # Run in background thread
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    
    print(f"[HTTP] Serving at http://localhost:{port}")
    return httpd


def start_websocket_server():
    """Start the WebSocket server for backend communication"""
    try:
        from jarvis.gui.websocket_server import JARVISWebSocketServer
        server = JARVISWebSocketServer()
        server.run_in_thread()
        print("[WebSocket] Server started on ws://localhost:8765")
        return server
    except ImportError as e:
        print(f"[WebSocket] Could not start server: {e}")
        print("[WebSocket] Install websockets: pip install websockets")
        return None
    except Exception as e:
        print(f"[WebSocket] Error starting server: {e}")
        return None


def main():
    """Main entry point"""
    print("=" * 60)
    print("       J.A.R.V.I.S. HOLOGRAPHIC HUD")
    print("=" * 60)
    print()
    
    # Start HTTP server
    http_port = 8080
    httpd = start_http_server(http_port)
    
    if not httpd:
        print("[ERROR] Could not start HTTP server")
        return
    
    # Start WebSocket server
    ws_server = start_websocket_server()
    
    print()
    print("=" * 60)
    print("  JARVIS HUD ONLINE")
    print("=" * 60)
    print(f"  Web Interface: http://localhost:{http_port}")
    print(f"  WebSocket:     ws://localhost:8765")
    print()
    print("  Press Ctrl+C to stop all servers")
    print("=" * 60)
    print()
    
    # Open browser (Chrome preferred — Brave blocks location)
    try:
        chrome = webbrowser.get('chrome')
        chrome.open(f"http://localhost:{http_port}")
    except webbrowser.Error:
        try:
            # Try explicit Chrome path on Windows
            chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
            if os.path.exists(chrome_path):
                webbrowser.register('chrome', None, webbrowser.BackgroundBrowser(chrome_path))
                webbrowser.get('chrome').open(f"http://localhost:{http_port}")
            else:
                webbrowser.open(f"http://localhost:{http_port}")
        except Exception:
            webbrowser.open(f"http://localhost:{http_port}")
    
    # Keep running
    try:
        while True:
            import time
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[JARVIS] Shutting down...")
        httpd.shutdown()


if __name__ == "__main__":
    main()
