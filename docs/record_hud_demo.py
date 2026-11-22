"""
Record a demo GIF of the JARVIS Web HUD.

Drives a headless Microsoft Edge through the Chrome DevTools Protocol, types
commands into the HUD chat, and captures only the HUD page (never the rest of
your desktop), then assembles docs/jarvis_demo.gif.

Usage (JARVIS must already be running, e.g. via start_jarvis.bat):
    python docs/record_hud_demo.py

Tip: start JARVIS with JARVIS_USE_GEMINI_LIVE=0 so the always-on microphone
can't act on background noise while recording.
"""

import base64
import io
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

from PIL import Image
from websockets.sync.client import connect

HUD_URL = "http://localhost:8080"
OUT = Path(__file__).resolve().parent / "jarvis_demo.gif"
SIZE = (1280, 720)
GIF_WIDTH = 960
PORT = 9333

# (command, seconds to wait for the reply)
SCRIPT = [
    ("what time is it", 4),
    ("tell me a joke", 8),
    ("restart my PC", 4),
    ("cancel", 4),
    ("tell me the news", 8),
]

EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    shutil.which("msedge") or "",
    shutil.which("chrome") or "",
]


class CDP:
    def __init__(self, ws_url):
        self.ws = connect(ws_url, max_size=None, open_timeout=20)
        self.next_id = 0

    def send(self, method, **params):
        self.next_id += 1
        msg_id = self.next_id
        self.ws.send(json.dumps({"id": msg_id, "method": method, "params": params}))
        while True:
            reply = json.loads(self.ws.recv(timeout=60))
            if reply.get("id") == msg_id:
                if "error" in reply:
                    raise RuntimeError(f"{method}: {reply['error']}")
                return reply.get("result", {})

    def js(self, expression):
        res = self.send("Runtime.evaluate", expression=expression, awaitPromise=True,
                        returnByValue=True)
        return res.get("result", {}).get("value")

    def frame(self):
        data = self.send("Page.captureScreenshot", format="png")["data"]
        img = Image.open(io.BytesIO(base64.b64decode(data))).convert("RGB")
        h = round(img.height * GIF_WIDTH / img.width)
        return img.resize((GIF_WIDTH, h), Image.LANCZOS)


def main():
    edge = next((p for p in EDGE_CANDIDATES if p and os.path.exists(p)), None)
    if not edge:
        raise SystemExit("Microsoft Edge or Chrome not found")
    profile = tempfile.mkdtemp(prefix="jarvis-demo-")
    proc = subprocess.Popen([edge, "--headless=new", f"--remote-debugging-port={PORT}",
                             f"--user-data-dir={profile}", f"--window-size={SIZE[0]},{SIZE[1]}",
                             "--hide-scrollbars", "--mute-audio", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    frames = []  # (image, duration_ms)
    try:
        for _ in range(50):
            try:
                pages = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json", timeout=2))
                page = next(p for p in pages if p.get("type") == "page")
                break
            except Exception:
                time.sleep(0.3)
        else:
            raise SystemExit("Could not reach the headless browser")

        cdp = CDP(page["webSocketDebuggerUrl"])
        cdp.send("Emulation.setDeviceMetricsOverride", width=SIZE[0], height=SIZE[1],
                 deviceScaleFactor=1, mobile=False)
        cdp.send("Page.enable")
        cdp.send("Page.navigate", url=HUD_URL)

        # Wait for the HUD to connect and show its boot greeting
        deadline = time.time() + 30
        while time.time() < deadline:
            ready = cdp.js("document.getElementById('wsStatusText')?.textContent === 'ONLINE'"
                           " && document.querySelectorAll('#chatMessages .chat-message').length >= 2")
            if ready:
                break
            time.sleep(0.5)
        time.sleep(3)
        # Pull the camera back to a whole-globe view (the HUD's signature look);
        # zoomed in, bright map tiles fill the screen behind the glass panels.
        cdp.js("typeof viewer !== 'undefined' && viewer && viewer.camera.flyTo({"
               "destination: Cesium.Cartesian3.fromDegrees(78, 18, 16000000), duration: 0})")
        time.sleep(5)  # let map tiles, news and stats settle
        frames.append((cdp.frame(), 3500))

        for command, wait in SCRIPT:
            count = cdp.js("document.querySelectorAll('#chatMessages .chat-message').length")
            # Type it out so the GIF shows the command being entered
            for i in range(0, len(command) + 1, max(1, len(command) // 4)):
                cdp.js(f"document.getElementById('chatInput').value = {json.dumps(command[:i])}")
                frames.append((cdp.frame(), 120))
            cdp.js(f"document.getElementById('chatInput').value = {json.dumps(command)}")
            frames.append((cdp.frame(), 600))
            cdp.js("sendMessage()")
            # Wait for JARVIS's reply (user message + reply = 2 new bubbles)
            deadline = time.time() + wait + 10
            while time.time() < deadline:
                n = cdp.js("document.querySelectorAll('#chatMessages .chat-message').length")
                if n >= count + 2:
                    break
                time.sleep(0.4)
            time.sleep(1.2)
            frames.append((cdp.frame(), 2800))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(profile, ignore_errors=True)

    images = [f.quantize(colors=128, method=Image.Quantize.MEDIANCUT) for f, _ in frames]
    images[0].save(OUT, save_all=True, append_images=images[1:],
                   duration=[d for _, d in frames], loop=0, optimize=True)
    print(f"Saved {OUT} ({len(frames)} frames, {OUT.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
