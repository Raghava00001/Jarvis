"""
GUI Package for JARVIS
Contains holographic interface components.

The pygame HUD classes are exported lazily (PEP 562): importing anything from
jarvis.gui, e.g. the WebSocket server, no longer loads pygame and five legacy
HUD modules (~1 s) that the Web HUD never uses.
"""

import importlib

_EXPORTS = {
    "HolographicGlobe": ".earth_globe",
    "JARVISState": ".earth_globe",
    "GlobeController": ".globe_controller",
    "ChatPanel": ".chat_panel",
    "ChatPanelWithInput": ".chat_panel",
    "HUD": ".advanced_hud",
    "InteractiveGlobeHUD": ".advanced_hud",  # alias kept for backwards compatibility
    "AudioWaveformVisualizer": ".waveform_visualizer",
    "CircularWaveform": ".waveform_visualizer",
    "IntegratedJARVISHUD": ".integrated_hud",
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(_EXPORTS[name], __name__)
    value = getattr(module, "HUD" if name == "InteractiveGlobeHUD" else name)
    globals()[name] = value
    return value
