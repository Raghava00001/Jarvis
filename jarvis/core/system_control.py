"""
System Control - Hardware Control (Windows)
Volume, Brightness, Bluetooth, and more
JARVIS takes direct control - no manual suggestions
"""

import logging
_log = logging.getLogger(__name__)

import platform
import subprocess
import os
import time

VOLUME_AVAILABLE = False
BRIGHTNESS_AVAILABLE = False

if platform.system() == "Windows":
    try:
        from ctypes import cast, POINTER
        from comtypes import CLSCTX_ALL, CoInitialize
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        VOLUME_AVAILABLE = True
    except ImportError as e:
        _log.warning(f"[SYSTEM] pycaw not available: {e}")

    try:
        import screen_brightness_control as sbc
        BRIGHTNESS_AVAILABLE = True
    except ImportError:
        _log.info("[SYSTEM] screen-brightness-control not installed")


import re

_UNMUTE_RE = re.compile(r"\bun-?mute\b", re.I)
_MUTE_RE = re.compile(r"\b(?:mute|silence)\b", re.I)
_MAX_RE = re.compile(r"\b(?:max(?:imum)?|full)\b", re.I)
_MIN_RE = re.compile(r"\b(?:min(?:imum)?|lowest)\b", re.I)
_UP_RE = re.compile(r"\b(?:up|increase\w*|raise|higher|louder|brighter|brighten|more|boost)\b", re.I)
_DOWN_RE = re.compile(r"\b(?:down|decrease\w*|lower|reduce\w*|quieter|softer|dim\w*|darker|less)\b", re.I)
_LEVEL_RE = re.compile(r"\b(\d{1,3})\s*(?:%|percent)?")


def maybe_title(title) -> str:
    return f", {title}" if title else ""


def parse_level_request(text: str = "", level=None):
    """('up'|'down'|'set'|'mute'|'unmute', value) from a request, or None.

    'turn the brightness down' -> ('down', None); 'volume_down' -> ('down', None);
    'set volume to 40' / level=40 -> ('set', 40); 'max' -> ('set', 100).
    """
    t = (text or "").replace("_", " ")
    if level not in (None, ""):
        try:
            return "set", max(0, min(100, int(float(str(level).strip().rstrip("%")))))
        except ValueError:
            _log.debug("Ignored error", exc_info=True)
    if _UNMUTE_RE.search(t):
        return "unmute", None
    if _MUTE_RE.search(t):
        return "mute", None
    m = _LEVEL_RE.search(t)
    if m:
        return "set", max(0, min(100, int(m.group(1))))
    if _MAX_RE.search(t):
        return "set", 100
    if _MIN_RE.search(t):
        return "set", 0
    if _DOWN_RE.search(t):
        return "down", None
    if _UP_RE.search(t):
        return "up", None
    return None


def _target(action: str, value, current: int, step: int) -> int:
    if action == "set":
        return max(0, min(100, int(value)))
    return max(0, min(100, current + (step if action == "up" else -step)))



class SystemControl:
    """Controls system hardware (Windows) - JARVIS takes control"""

    def __init__(self, perception):
        _log.info("[SYSTEM] Initializing System Control...")
        self.perception = perception
        self.platform = platform.system()
        
        # Initialize volume interface (using pycaw with robust API handling)
        self.volume_interface = None
        if VOLUME_AVAILABLE:
            try:
                CoInitialize()
                devices = AudioUtilities.GetSpeakers()
                # Try the standard Activate method
                interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                self.volume_interface = cast(interface, POINTER(IAudioEndpointVolume))
                _log.info("[SYSTEM] Volume control ready (pycaw)")
            except AttributeError:
                # Newer pycaw: AudioDevice wrapper doesn't expose Activate directly
                try:
                    # Access the underlying IMMDevice
                    device = devices
                    if hasattr(device, '_dev'):
                        interface = device._dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                    elif hasattr(device, 'ActivateInterface'):
                        interface = device.ActivateInterface(IAudioEndpointVolume._iid_)
                    else:
                        # Try getting the endpoint volume directly
                        interface = device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                    self.volume_interface = cast(interface, POINTER(IAudioEndpointVolume))
                    _log.info("[SYSTEM] Volume control ready (pycaw compat)")
                except Exception as e2:
                    _log.warning(f"[SYSTEM] Volume init pycaw compat error: {e2}")
                    self.volume_interface = None
            except Exception as e:
                _log.warning(f"[SYSTEM] Volume init pycaw error: {e}")
                # Fallback: try with CoInitializeEx for STA threading
                try:
                    import comtypes
                    comtypes.CoInitializeEx(comtypes.COINIT_APARTMENTTHREADED)
                    devices = AudioUtilities.GetSpeakers()
                    interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                    self.volume_interface = cast(interface, POINTER(IAudioEndpointVolume))
                    _log.info("[SYSTEM] Volume control ready (pycaw CoInitializeEx)")
                except Exception as e2:
                    _log.warning(f"[SYSTEM] Volume init fallback error: {e2}")
                    self.volume_interface = None
        
        if not self.volume_interface:
            _log.info("[SYSTEM] Volume will use pyautogui keyboard fallback")
        
        _log.info("[SYSTEM] Control Ready")

    def _get_title(self):
        return getattr(self.perception, 'user_title', 'sir')

    # ---------- VOLUME & BRIGHTNESS: one honest entry point ----------
    #
    # Every path (voice tools, router, fast path, fallback) used to call these
    # methods and then say "Brightness decreased" whatever happened: the
    # methods spoke for themselves (a second voice next to Gemini's) and
    # returned True even when every way of changing the level had failed.
    # Gemini's tools also called the handler without saying up or down, so
    # nothing happened at all. Now adjust() parses the request, changes the
    # level, reads it back, and returns what is really true. It never speaks.

    def adjust(self, kind: str, text: str = "", level=None) -> str:
        """kind 'volume' or 'brightness'; text like 'turn it down', 'set to 40',
        'mute'. Returns the reply to speak: the real outcome."""
        title = self._get_title()
        t = maybe_title(title)
        request = parse_level_request(text, level)
        if request is None:
            return f"Should I turn the {kind} up or down{t}?"
        action, value = request
        if kind == "volume":
            return self._adjust_volume(action, value, t)
        if kind == "brightness":
            return self._adjust_brightness(action, value, t)
        raise ValueError(kind)

    # volume
    def _endpoint(self):
        """The speaker volume control, made in the calling thread (a COM
        object made in another thread can't be used here)."""
        if not VOLUME_AVAILABLE:
            return None
        try:
            CoInitialize()
        except Exception:
            _log.debug("Ignored error", exc_info=True)
        try:
            dev = AudioUtilities.GetSpeakers()
            if hasattr(dev, "EndpointVolume"):          # pycaw >= 2024
                return dev.EndpointVolume
            raw = getattr(dev, "_dev", dev)
            iface = raw.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            return cast(iface, POINTER(IAudioEndpointVolume))
        except Exception as e:
            _log.warning(f"[SYSTEM] Volume control unavailable: {e}")
            return None

    def get_volume(self):
        ep = self._endpoint()
        if ep is None:
            return None
        try:
            return round(ep.GetMasterVolumeLevelScalar() * 100)
        except Exception as e:
            _log.warning(f"[SYSTEM] Volume read error: {e}")
            return None

    def _adjust_volume(self, action: str, value, t: str) -> str:
        ep = self._endpoint()
        if ep is not None:
            try:
                if action in ("mute", "unmute"):
                    ep.SetMute(action == "mute", None)
                    return f"Sound {'muted' if ep.GetMute() else 'unmuted'}{t}."
                current = round(ep.GetMasterVolumeLevelScalar() * 100)
                target = _target(action, value, current, step=10)
                if target == current and action in ("up", "down"):
                    return f"The volume is already at {current}%{t}."
                if ep.GetMute() and target > 0:
                    ep.SetMute(False, None)
                ep.SetMasterVolumeLevelScalar(target / 100.0, None)
                now = round(ep.GetMasterVolumeLevelScalar() * 100)
                return f"Volume is now {now}%{t}."
            except Exception as e:
                _log.warning(f"[SYSTEM] Volume error: {e}")
        # Fallback: the keyboard's volume keys (each press is about 2%)
        try:
            import pyautogui
            if action in ("mute", "unmute"):
                pyautogui.press("volumemute")
                return f"Toggled mute{t}."
            if action == "set":
                return f"I can't set an exact volume on this computer{t}, only turn it up or down."
            key = "volumeup" if action == "up" else "volumedown"
            for _ in range(5):
                pyautogui.press(key)
            return f"Turned the volume {action}{t}."
        except Exception as e:
            _log.warning(f"[SYSTEM] Volume keys error: {e}")
        return f"I couldn't change the volume{t}."

    # brightness
    def get_brightness(self):
        if BRIGHTNESS_AVAILABLE:
            try:
                b = sbc.get_brightness()
                return b[0] if isinstance(b, list) else b
            except Exception as e:
                _log.warning(f"[SYSTEM] Brightness read error: {e}")
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-Command",
                                "(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness"
                                " | Select-Object -First 1).CurrentBrightness"],
                               capture_output=True, text=True, timeout=10)
            return int(r.stdout.strip()) if r.stdout.strip().isdigit() else None
        except Exception as e:
            _log.warning(f"[SYSTEM] Brightness read (WMI) error: {e}")
            return None

    def _write_brightness(self, level: int) -> None:
        if BRIGHTNESS_AVAILABLE:
            try:
                sbc.set_brightness(level)
                return
            except Exception as e:
                _log.warning(f"[SYSTEM] Brightness (sbc) error: {e}")
        subprocess.run(["powershell", "-NoProfile", "-Command",
                        "(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods)"
                        f".WmiSetBrightness(1, {int(level)})"],
                       capture_output=True, timeout=10)

    def _adjust_brightness(self, action: str, value, t: str) -> str:
        current = self.get_brightness()
        if current is None:
            return f"I can't control the brightness of this display{t}."
        if action in ("mute", "unmute"):
            return f"Should I turn the brightness up or down{t}?"
        target = _target(action, value, current, step=20)
        if target == current:
            return f"The brightness is already at {current}%{t}."
        try:
            self._write_brightness(target)
        except Exception as e:
            _log.warning(f"[SYSTEM] Brightness error: {e}")
        time.sleep(0.3)  # some displays apply the change a moment later
        now = self.get_brightness()
        if now is None or abs(now - target) > 5:
            return f"I tried, but the display didn't change its brightness{t}. It's at {now if now is not None else current}%."
        return f"Brightness is now {now}%{t}."

    # Old entry points (other modules call these): same honest result, no speech
    def set_volume(self, level: int):
        return self.adjust("volume", level=level)

    def volume_up(self, amount=10):
        return self.adjust("volume", "up")

    def volume_down(self, amount=10):
        return self.adjust("volume", "down")

    def mute_volume(self):
        return self.adjust("volume", "mute")

    def set_brightness(self, level: int):
        return self.adjust("brightness", level=level)

    def brightness_up(self, amount=20):
        return self.adjust("brightness", "up")

    def brightness_down(self, amount=20):
        return self.adjust("brightness", "down")

    # ---------- BLUETOOTH ----------

    def bluetooth_on(self):
        """Turn Bluetooth on"""
        title = self._get_title()
        try:
            # Try to actually toggle Bluetooth via PowerShell
            ps_cmd = '''
            Add-Type -AssemblyName System.Runtime.WindowsRuntime
            $asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | ? { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
            Function Await($WinRtTask, $ResultType) {
                $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
                $netTask = $asTask.Invoke($null, @($WinRtTask))
                $netTask.Wait(-1) | Out-Null
                $netTask.Result
            }
            [Windows.Devices.Radios.Radio,Windows.System.Devices,ContentType=WindowsRuntime] | Out-Null
            [Windows.Devices.Radios.RadioState,Windows.System.Devices,ContentType=WindowsRuntime] | Out-Null
            $radios = Await ([Windows.Devices.Radios.Radio]::GetRadiosAsync()) ([System.Collections.Generic.IReadOnlyList[Windows.Devices.Radios.Radio]])
            $bluetooth = $radios | ? { $_.Kind -eq 'Bluetooth' }
            [void](Await ($bluetooth.SetStateAsync('On')) ([Windows.Devices.Radios.RadioAccessStatus]))
            '''
            result = subprocess.run(['powershell', '-Command', ps_cmd], capture_output=True, timeout=15)
            # BUG FIX: Check returncode before claiming success
            if result.returncode == 0:
                self._is_bt_on = True
                self.perception.speak(f"Bluetooth turned on, {title}.")
            else:
                _log.warning(f"[SYSTEM] Bluetooth PS error: {result.stderr.decode(errors='ignore')}")
                self.perception.speak(f"Bluetooth may not have turned on, {title}. Opening settings.")
                subprocess.Popen("ms-settings:bluetooth", shell=True)
            return True
        except Exception as e:
            _log.warning(f"[SYSTEM] Bluetooth on error: {e}")
            # Fallback: open settings
            subprocess.Popen("ms-settings:bluetooth", shell=True)
            self.perception.speak(f"Opening Bluetooth settings, {title}.")
            return True

    def bluetooth_off(self):
        """Turn Bluetooth off"""
        title = self._get_title()
        try:
            ps_cmd = '''
            Add-Type -AssemblyName System.Runtime.WindowsRuntime
            $asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | ? { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
            Function Await($WinRtTask, $ResultType) {
                $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
                $netTask = $asTask.Invoke($null, @($WinRtTask))
                $netTask.Wait(-1) | Out-Null
                $netTask.Result
            }
            [Windows.Devices.Radios.Radio,Windows.System.Devices,ContentType=WindowsRuntime] | Out-Null
            [Windows.Devices.Radios.RadioState,Windows.System.Devices,ContentType=WindowsRuntime] | Out-Null
            $radios = Await ([Windows.Devices.Radios.Radio]::GetRadiosAsync()) ([System.Collections.Generic.IReadOnlyList[Windows.Devices.Radios.Radio]])
            $bluetooth = $radios | ? { $_.Kind -eq 'Bluetooth' }
            [void](Await ($bluetooth.SetStateAsync('Off')) ([Windows.Devices.Radios.RadioAccessStatus]))
            '''
            result = subprocess.run(['powershell', '-Command', ps_cmd], capture_output=True, timeout=15)
            # BUG FIX: Check returncode before claiming success
            if result.returncode == 0:
                self.perception.speak(f"Bluetooth turned off, {title}.")
            else:
                _log.warning(f"[SYSTEM] Bluetooth PS error: {result.stderr.decode(errors='ignore')}")
                self.perception.speak(f"Bluetooth may not have turned off, {title}. Opening settings.")
                subprocess.Popen("ms-settings:bluetooth", shell=True)
            return True
        except Exception as e:
            _log.warning(f"[SYSTEM] Bluetooth off error: {e}")
            subprocess.Popen("ms-settings:bluetooth", shell=True)
            self.perception.speak(f"Opening Bluetooth settings, {title}.")
            return True

    def toggle_bluetooth(self):
        """Toggle Bluetooth — checks current state first"""
        try:
            # Query current Bluetooth state
            ps_check = '''
            Add-Type -AssemblyName System.Runtime.WindowsRuntime
            $asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | ? { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
            Function Await($WinRtTask, $ResultType) {
                $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
                $netTask = $asTask.Invoke($null, @($WinRtTask))
                $netTask.Wait(-1) | Out-Null
                $netTask.Result
            }
            [Windows.Devices.Radios.Radio,Windows.System.Devices,ContentType=WindowsRuntime] | Out-Null
            $radios = Await ([Windows.Devices.Radios.Radio]::GetRadiosAsync()) ([System.Collections.Generic.IReadOnlyList[Windows.Devices.Radios.Radio]])
            $bt = $radios | ? { $_.Kind -eq 'Bluetooth' }
            $bt.State.ToString()
            '''
            result = subprocess.run(['powershell', '-Command', ps_check],
                                    capture_output=True, text=True, timeout=10)
            if 'On' in result.stdout:
                return self.bluetooth_off()
            else:
                return self.bluetooth_off() if getattr(self, "_is_bt_on", False) else self.bluetooth_on()
        except Exception:
            # Can't determine state — default to turning on
            return self.bluetooth_off() if getattr(self, "_is_bt_on", False) else self.bluetooth_on()

    # ---------- SLEEP / SHUTDOWN ----------

    def sleep_system(self, confirm: bool = False):
        """Put system to sleep"""
        title = self._get_title()
        
        if not confirm:
            self.perception.speak(f"Say 'sleep confirm' to put the system to sleep, {title}.")
            return False

        try:
            self.perception.speak(f"Putting system to sleep now, {title}.")
            os.system("rundll32.exe powrprof.dll,SetSuspendState 0,1,0")
            return True
        except Exception as e:
            _log.warning(f"[SYSTEM] Sleep error: {e}")
            self.perception.speak(f"Failed to put system to sleep, {title}.")
            return False
    
    def shutdown_system(self, confirm: bool = False):
        """Shutdown the system"""
        title = self._get_title()
        
        if not confirm:
            self.perception.speak(f"Say 'shutdown confirm' to shut down, {title}.")
            return False
        
        try:
            self.perception.speak(f"Shutting down in 5 seconds, {title}.")
            os.system("shutdown /s /t 5")
            return True
        except Exception as e:
            self.perception.speak(f"Failed to shutdown, {title}.")
            return False
    
    def restart_system(self, confirm: bool = False):
        """Restart the system"""
        title = self._get_title()
        
        if not confirm:
            self.perception.speak(f"Say 'restart confirm' to restart, {title}.")
            return False
        
        try:
            self.perception.speak(f"Restarting in 5 seconds, {title}.")
            os.system("shutdown /r /t 5")
            return True
        except Exception as e:
            self.perception.speak(f"Failed to restart, {title}.")
            return False
