"""
v2.5: fast boot.

Importing the server used to take ~15 s because understanding.py,
context_memory.py, voice_engine.py and gesture_controller.py imported
sentence-transformers / torch / Whisper / MediaPipe (+TensorFlow) at module
load just to check they were installed. The HUD now comes online in ~5 s;
models still load in the Phase 2 background thread.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HEAVY = ("torch", "tensorflow", "transformers", "sentence_transformers", "whisper", "mediapipe")


def test_server_import_and_init_load_no_heavy_ml():
    """Run in a fresh interpreter so other tests' imports can't hide a regression."""
    code = (
        "import sys, os; sys.path.insert(0, '.'); os.environ['JARVIS_USE_GEMINI_LIVE'] = '0'\n"
        "import jarvis.gui.websocket_server as w\n"
        "w.JARVISWebSocketServer()\n"
        f"print('HEAVY=' + ','.join(m for m in {HEAVY!r} if m in sys.modules))\n"
    )
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True,
                         text=True, encoding="utf-8", errors="replace", timeout=180)
    line = next((l for l in out.stdout.splitlines() if l.startswith("HEAVY=")), None)
    assert line is not None, out.stdout[-2000:] + out.stderr[-2000:]
    assert line == "HEAVY=", f"heavy ML imported at startup: {line}"


def test_availability_flags_still_detect_installed_packages():
    import importlib.util
    from jarvis.core import understanding, context_memory, gesture_controller
    st = importlib.util.find_spec("sentence_transformers") is not None
    assert understanding.SENTENCE_TRANSFORMERS_AVAILABLE == st
    assert context_memory.EMBEDDINGS_AVAILABLE == st
    assert gesture_controller.MP_AVAILABLE == (importlib.util.find_spec("mediapipe") is not None)


def test_whisper_backend_reports_available_without_importing():
    import importlib.util
    from jarvis.core.voice_engine import WhisperSTTBackend
    backend = WhisperSTTBackend("base")
    assert backend.available == (importlib.util.find_spec("whisper") is not None)
    assert backend._model is None  # model still loads lazily on first transcription


def test_gesture_controller_loads_mediapipe_on_first_use():
    src = (ROOT / "jarvis/core/gesture_controller.py").read_text(encoding="utf-8")
    assert "if _load_mediapipe():" in src
    assert "\nimport mediapipe" not in src and "\ntry:\n    import mediapipe" not in src
