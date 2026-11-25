"""
Hotkey System - Wake Word & Global Hotkeys
Handles wake word detection and global hotkeys including Ctrl+R+S for shutdown
"""

import logging
_log = logging.getLogger(__name__)

import threading
import speech_recognition as sr

# Try to import keyboard library for global hotkeys
KEYBOARD_AVAILABLE = False
try:
    import keyboard
    KEYBOARD_AVAILABLE = True
except ImportError:
    _log.info("[HOTKEYS] keyboard not installed. Run: pip install keyboard")


class HotkeySystem:
    """Handles wake word and hotkey detection"""

    def __init__(self, perception, jarvis_callback=None):
        _log.info("[HOTKEYS] Initializing Hotkey System...")
        self.perception = perception
        self.jarvis_callback = jarvis_callback
        self.listening = False
        self.recognizer = sr.Recognizer()
        self.wake_word = "jarvis"
        self.running = True
        
        # Setup hotkeys
        if KEYBOARD_AVAILABLE:
            self.setup_hotkeys()
        else:
            _log.info("[HOTKEYS] Global hotkeys disabled (install keyboard package)")
        
        _log.info("[HOTKEYS] System Ready")

    def setup_hotkeys(self):
        """Setup global hotkeys"""
        if not KEYBOARD_AVAILABLE:
            return
        
        try:
            # Ctrl+Alt+J = Activate JARVIS (start listening)
            keyboard.add_hotkey('ctrl+alt+j', self._on_activate_jarvis)
            _log.info("[HOTKEYS] Registered: Ctrl+Alt+J = Activate JARVIS")
            
            # Ctrl+Alt+S = Stop/Shutdown JARVIS
            keyboard.add_hotkey('ctrl+alt+s', self._on_shutdown_jarvis)
            _log.info("[HOTKEYS] Registered: Ctrl+Alt+S = Shutdown JARVIS")
            
            # Ctrl+Alt+M = Mute/Unmute
            keyboard.add_hotkey('ctrl+alt+m', self._on_mute_toggle)
            _log.info("[HOTKEYS] Registered: Ctrl+Alt+M = Mute toggle")
            
        except Exception as e:
            _log.warning(f"[HOTKEYS] Error setting up hotkeys: {e}")
            _log.info("[HOTKEYS] Note: Global hotkeys may require admin privileges on Windows")

    def _on_activate_jarvis(self):
        """Called when Ctrl+Alt+J is pressed"""
        _log.info("\n[HOTKEY] Ctrl+Alt+J pressed - Activating JARVIS")
        if self.jarvis_callback:
            self.jarvis_callback("activate")
        else:
            self.perception.speak("Yes sir, I'm here.")

    def _on_shutdown_jarvis(self):
        """Called when Ctrl+Alt+S is pressed — M-02: respects Gemini Live gate"""
        _log.info("\n[HOTKEY] Ctrl+Alt+S pressed - Shutting down JARVIS")
        # Only speak via legacy TTS if Gemini Live is NOT active
        _live = getattr(self.perception, '_gemini_live_active', False) if self.perception else False
        if not _live and self.perception:
            self.perception.speak("Shutting down, sir.")
        self.running = False
        if self.jarvis_callback:
            self.jarvis_callback("shutdown")

    def _on_mute_toggle(self):
        """Called when Ctrl+Alt+M is pressed"""
        _log.info("\n[HOTKEY] Ctrl+Alt+M pressed - Mute toggle")
        # Toggle mute using system control
        try:
            import subprocess
            subprocess.run(
                ['powershell', '-Command', 
                 '$wshell = New-Object -ComObject WScript.Shell; $wshell.SendKeys([char]173)'
                ],
                capture_output=True, timeout=5
            )
        except Exception:
            _log.debug("Ignored error", exc_info=True)

    def start_wake_word_listening(self, callback):
        """Start listening for wake word"""
        if self.listening:
            return
        
        self.listening = True
        
        def listen_loop():
            """Background listening loop"""
            with sr.Microphone() as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
            
            while self.listening and self.running:
                try:
                    with sr.Microphone() as source:
                        audio = self.recognizer.listen(source, timeout=1, phrase_time_limit=2)
                    
                    try:
                        text = self.recognizer.recognize_google(audio).lower()
                        if self.wake_word in text or "hey jarvis" in text:
                            _log.info(f"\n[WAKE WORD] Detected: {text}")
                            callback()
                    except sr.UnknownValueError:
                        _log.debug("Ignored error", exc_info=True)
                    except sr.RequestError:
                        _log.debug("Ignored error", exc_info=True)
                except sr.WaitTimeoutError:
                    _log.debug("Ignored error", exc_info=True)
                except Exception:
                    if self.listening:
                        pass  # Suppress errors during normal operation
        
        thread = threading.Thread(target=listen_loop, daemon=True)
        thread.start()

    def stop(self):
        """Stop listening and cleanup"""
        self.listening = False
        self.running = False
        
        if KEYBOARD_AVAILABLE:
            try:
                keyboard.unhook_all()
            except Exception:
                _log.debug("Ignored error", exc_info=True)
