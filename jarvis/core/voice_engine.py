"""
Voice Engine - Unified TTS/STT abstraction
==========================================
Provides Edge TTS (natural voices) + Whisper (accurate STT).
Falls back to pyttsx3 + Google STT if either dependency is missing.

Usage:
    engine = VoiceEngine()
    engine.speak("Hello sir")            # Uses Edge TTS (async, natural)
    text = engine.listen(timeout=10)      # Uses Whisper STT
"""

import os
import io
import queue
import tempfile
import threading
import time
import asyncio
from pathlib import Path
from typing import Optional


# ═══════════════════════════════════════════════════════════════════
# TTS Backend: Edge TTS (Microsoft Edge natural voices)
# ═══════════════════════════════════════════════════════════════════

class EdgeTTSBackend:
    """High-quality TTS using Microsoft Edge voices (free, no API key)."""

    # Voice presets — Iron Man JARVIS = British accent (Paul Bettany)
    VOICES = {
        "jarvis": "en-GB-RyanNeural",       # British male — closest to Iron Man JARVIS
        "friday": "en-US-JennyNeural",      # Female, warm, professional (Scarlett Johansson style)
        "jarvis_us": "en-US-GuyNeural",     # American male alternative
        "friday_uk": "en-GB-SoniaNeural",   # British female alternative
    }

    def __init__(self):
        self.available = False
        self._voice = self.VOICES["jarvis"]
        self._rate = "+10%"        # Slightly faster than default
        self._volume = "+0%"
        self._loop = None
        self._loop_thread = None
        self._cache_dir = Path(tempfile.gettempdir()) / "jarvis_tts_cache"
        self._cache_dir.mkdir(exist_ok=True)

        try:
            import edge_tts
            self._edge_tts = edge_tts
            self.available = True
            print("[VOICE ENGINE] Edge TTS available")
        except ImportError:
            print("[VOICE ENGINE] Edge TTS not available (pip install edge-tts)")

        # Start a persistent event loop for async edge-tts
        if self.available:
            self._start_event_loop()

        # C-01: Start cache cleanup thread to prevent disk fill
        self._cleanup_thread = threading.Thread(
            target=self._cache_cleanup_loop, daemon=True
        )
        self._cleanup_thread.start()

    def _start_event_loop(self):
        """Start a background event loop for async TTS."""
        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(
            target=self._loop.run_forever, daemon=True
        )
        self._loop_thread.start()

    def _cache_cleanup_loop(self):
        """C-01: Periodically delete old TTS cache files to prevent disk fill."""
        import time as _ct
        while True:
            _ct.sleep(300)  # Run every 5 minutes
            try:
                now = _ct.time()
                for f in self._cache_dir.glob("*.mp3"):
                    try:
                        age = now - f.stat().st_mtime
                        if age > 300:  # Older than 5 minutes
                            f.unlink()
                    except (OSError, PermissionError):
                        pass  # File in use or already deleted
            except Exception:
                pass

    def set_voice(self, voice_key: str):
        """Set voice by key (jarvis, friday, jarvis_uk, friday_uk)."""
        if voice_key in self.VOICES:
            self._voice = self.VOICES[voice_key]
        else:
            self._voice = voice_key  # Allow direct voice ID

    def set_rate(self, wpm: int):
        """Set speech rate from WPM to Edge TTS percentage."""
        # Edge TTS default is ~170 WPM. Map to percentage offset.
        pct = int(((wpm - 170) / 170) * 100)
        self._rate = f"{pct:+d}%"

    def set_volume(self, vol: float):
        """Set volume (0.0 to 1.0) -> Edge TTS percentage."""
        pct = int((vol - 1.0) * 100)
        self._volume = f"{pct:+d}%"

    async def _synthesize(self, text: str) -> bytes:
        """Synthesize text to raw audio bytes (MP3)."""
        communicate = self._edge_tts.Communicate(
            text, self._voice,
            rate=self._rate,
            volume=self._volume
        )
        buffer = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                buffer.write(chunk["data"])
        return buffer.getvalue()

    def speak_to_file(self, text: str) -> Optional[str]:
        """Synthesize text and save to a temp MP3 file. Returns file path."""
        if not self.available:
            return None
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._synthesize(text), self._loop
            )
            audio_data = future.result(timeout=30)

            # Write to temp file
            tmp = tempfile.NamedTemporaryFile(
                suffix=".mp3", dir=str(self._cache_dir),
                delete=False
            )
            tmp.write(audio_data)
            tmp.close()
            return tmp.name
        except Exception as e:
            print(f"[VOICE ENGINE] Edge TTS error: {e}")
            return None

    def speak_blocking(self, text: str) -> bool:
        """Speak text synchronously using pygame for playback."""
        audio_path = self.speak_to_file(text)
        if not audio_path:
            return False
        try:
            self._play_audio(audio_path)
            return True
        finally:
            # Clean up temp file
            try:
                os.unlink(audio_path)
            except:
                pass

    def _play_audio(self, path: str):
        """Play an MP3 file using pygame.mixer (already in the project)."""
        try:
            import pygame
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=24000)
            pygame.mixer.music.load(path)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                time.sleep(0.05)
        except ImportError:
            # Fallback: use system player
            import platform
            system = platform.system()
            if system == "Windows":
                os.startfile(path)
            elif system == "Darwin":
                # m-05: Removed dead subprocess import/pass
                os.system(f'open "{path}"')
            else:
                os.system(f'xdg-open "{path}"')
            time.sleep(3)
        except Exception as e:
            print(f"[VOICE ENGINE] Playback error: {e}")

    def stop(self):
        """Stop current playback."""
        try:
            import pygame
            if pygame.mixer.get_init():
                pygame.mixer.music.stop()
        except:
            pass


# ═══════════════════════════════════════════════════════════════════
# STT Backend: Whisper (OpenAI, local, fast, accurate)
# ═══════════════════════════════════════════════════════════════════

class WhisperSTTBackend:
    """Local speech-to-text using OpenAI Whisper (runs on GPU if available)."""

    def __init__(self, model_size: str = "base"):
        self.available = False
        self._model = None
        self._model_size = model_size

        # Check only: importing whisper loads torch (~seconds). Import on first use.
        import importlib.util
        if importlib.util.find_spec("whisper") is not None:
            self.available = True
            print(f"[VOICE ENGINE] Whisper STT available (model: {model_size})")
        else:
            print("[VOICE ENGINE] Whisper not available (pip install openai-whisper)")

    def load_model(self):
        """Lazy-load the Whisper model (saves startup time)."""
        if self._model is None and self.available:
            print(f"[VOICE ENGINE] Loading Whisper {self._model_size} model...")
            import whisper
            self._model = whisper.load_model(self._model_size)
            print("[VOICE ENGINE] Whisper model loaded")

    def transcribe_file(self, audio_path: str) -> Optional[str]:
        """Transcribe an audio file to text."""
        if not self.available:
            return None
        self.load_model()
        try:
            result = self._model.transcribe(
                audio_path,
                language="en",
                fp16=False  # CPU-safe
            )
            return result["text"].strip()
        except Exception as e:
            print(f"[VOICE ENGINE] Whisper error: {e}")
            return None

    def transcribe_audio_data(self, audio_data: bytes, sample_rate: int = 16000) -> Optional[str]:
        """Transcribe raw audio bytes (WAV) to text."""
        if not self.available:
            return None
        self.load_model()
        try:
            import numpy as np
            # Convert bytes to numpy array
            audio_np = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0
            result = self._model.transcribe(
                audio_np,
                language="en",
                fp16=False
            )
            return result["text"].strip()
        except Exception as e:
            print(f"[VOICE ENGINE] Whisper transcribe error: {e}")
            return None


# ═══════════════════════════════════════════════════════════════════
# Unified Voice Engine
# ═══════════════════════════════════════════════════════════════════

class VoiceEngine:
    """
    Unified voice engine with swappable TTS/STT backends.
    
    Priority:
        TTS: Edge TTS > pyttsx3
        STT: Whisper > Google STT (via SpeechRecognition)
    """

    def __init__(self, use_edge_tts: bool = True, use_whisper: bool = True,
                 whisper_model: str = "base"):
        print("[VOICE ENGINE] Initializing Voice Engine...")

        # Allow disabling Edge TTS via env var (set JARVIS_USE_EDGE_TTS=0 to revert to pyttsx3)
        env_edge = os.environ.get("JARVIS_USE_EDGE_TTS", "1")
        if env_edge == "0":
            use_edge_tts = False
            print("[VOICE ENGINE] Edge TTS disabled via JARVIS_USE_EDGE_TTS=0")

        # TTS
        self.edge_tts = EdgeTTSBackend() if use_edge_tts else None
        self.use_edge_tts = use_edge_tts and self.edge_tts and self.edge_tts.available

        # STT
        self.whisper_stt = WhisperSTTBackend(whisper_model) if use_whisper else None
        self.use_whisper = use_whisper and self.whisper_stt and self.whisper_stt.available

        # State
        self.is_speaking = False
        self.stop_flag = False
        # Circuit breaker: stop calling a failing cloud TTS after a few errors
        # in a row, so each reply doesn't wait on a dead service.
        self._edge_failures = 0
        # Speech is serialised: one worker thread speaks queued lines in order,
        # and audio_lock guards every playback path. Before, each HUD reply spawned
        # its own thread, so several threads drove pygame.mixer / pyttsx3 (SAPI COM)
        # at once, which is not thread-safe and crashed the process (0xC0000005).
        self.audio_lock = threading.RLock()
        self._speech_queue = queue.Queue()
        self._speech_worker = None

        tts_name = "Edge TTS" if self.use_edge_tts else "pyttsx3"
        stt_name = "Whisper" if self.use_whisper else "Google STT"
        print(f"[VOICE ENGINE] Ready | TTS: {tts_name} | STT: {stt_name}")

    def set_voice(self, voice_key: str):
        """Set the TTS voice (jarvis, friday, jarvis_uk, friday_uk)."""
        if self.edge_tts:
            self.edge_tts.set_voice(voice_key)

    def set_rate(self, wpm: int):
        """Set speech rate in WPM."""
        if self.edge_tts:
            self.edge_tts.set_rate(wpm)

    def set_volume(self, vol: float):
        """Set speech volume (0.0 - 1.0)."""
        if self.edge_tts:
            self.edge_tts.set_volume(vol)

    EDGE_FAILURE_LIMIT = 3

    def say(self, text: str) -> None:
        """Queue text to be spoken (non-blocking). Lines are spoken one at a time, in order."""
        if not text:
            return
        with self.audio_lock:
            if self._speech_worker is None or not self._speech_worker.is_alive():
                self._speech_worker = threading.Thread(target=self._speech_loop, daemon=True,
                                                       name="JARVISSpeech")
                self._speech_worker.start()
        self._speech_queue.put(text)

    def _speech_loop(self):
        while True:
            text = self._speech_queue.get()
            if text is None:
                return
            try:
                self.speak_with_fallback(text)
            except Exception as e:
                print(f"[VOICE ENGINE] Speech error: {e}")

    def clear_queue(self) -> None:
        """Drop lines that haven't been spoken yet."""
        try:
            while True:
                self._speech_queue.get_nowait()
        except queue.Empty:
            pass

    def speak(self, text: str) -> bool:
        """Speak text using the best available TTS. Returns True if Edge TTS was used."""
        with self.audio_lock:
            return self._speak_edge(text)

    def _speak_edge(self, text: str) -> bool:
        if self.use_edge_tts:
            self.is_speaking = True
            self.stop_flag = False
            try:
                ok = self.edge_tts.speak_blocking(text)
            finally:
                self.is_speaking = False
            if ok:
                self._edge_failures = 0
                return True
            self._record_edge_failure()
        return False  # Caller should fall back to pyttsx3

    def _record_edge_failure(self):
        self._edge_failures += 1
        if self._edge_failures >= self.EDGE_FAILURE_LIMIT and self.use_edge_tts:
            self.use_edge_tts = False
            print(f"[VOICE ENGINE] Edge TTS failed {self._edge_failures} times in a row; "
                  f"switching to offline pyttsx3 for this session")

    def speak_with_fallback(self, text: str) -> str:
        """Speak with Edge TTS, falling back to offline pyttsx3. Returns the backend used."""
        with self.audio_lock:
            return self._speak_with_fallback_locked(text)

    def _speak_with_fallback_locked(self, text: str) -> str:
        if self._speak_edge(text):
            return "edge"
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.say(text)
            engine.runAndWait()
            engine.stop()
            return "pyttsx3"
        except Exception as e:
            print(f"[VOICE ENGINE] pyttsx3 fallback failed: {e}")
            return "none"

    def speak_to_file(self, text: str) -> Optional[str]:
        """Generate speech audio file (for WebSocket/browser playback). Returns MP3 path."""
        if self.use_edge_tts:
            return self.edge_tts.speak_to_file(text)
        return None

    def stop(self):
        """Stop current speech and drop queued lines."""
        self.clear_queue()
        self.stop_flag = True
        if self.edge_tts:
            self.edge_tts.stop()
        self.is_speaking = False

    def transcribe(self, audio_path: str) -> Optional[str]:
        """Transcribe audio file using Whisper. Returns None if unavailable."""
        if self.use_whisper:
            return self.whisper_stt.transcribe_file(audio_path)
        return None

    @property
    def has_edge_tts(self) -> bool:
        return self.use_edge_tts

    @property
    def has_whisper(self) -> bool:
        return self.use_whisper


# ═══════════════════════════════════════════════════════════════════
# Module-level singleton
# ═══════════════════════════════════════════════════════════════════

_voice_engine: Optional[VoiceEngine] = None

def get_voice_engine(**kwargs) -> VoiceEngine:
    """Get or create the global VoiceEngine singleton."""
    global _voice_engine
    if _voice_engine is None:
        _voice_engine = VoiceEngine(**kwargs)
    return _voice_engine


if __name__ == "__main__":
    # Quick test
    engine = VoiceEngine()
    print(f"\nEdge TTS: {engine.has_edge_tts}")
    print(f"Whisper:  {engine.has_whisper}")
    
    if engine.has_edge_tts:
        print("\nTesting Edge TTS...")
        engine.speak("Hello sir. JARVIS voice engine online. All systems nominal.")
        print("Done!")
