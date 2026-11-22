"""
One place for JARVIS's text LLM calls.

Google retired `gemini-2.0-flash`, which was hard-coded in three places, so every
typed question and Gemini Live's "what's on my screen" failed with 404. The model
now lives here, defaults to the `gemini-flash-latest` alias (kept current by
Google), and can be pinned with the JARVIS_GEMINI_TEXT_MODEL environment variable.
"""

import os
import threading
from typing import Optional

GEMINI_TEXT_MODEL = os.getenv("JARVIS_GEMINI_TEXT_MODEL", "gemini-flash-latest")

JARVIS_STYLE = ("You are JARVIS, a witty AI assistant. Keep replies to 1-2 sentences. "
                "Address user as 'sir'. Never break character.")

REQUEST_TIMEOUT_MS = int(os.getenv("JARVIS_LLM_TIMEOUT_MS", "15000"))

_clients = {}
_lock = threading.Lock()


def gemini_client(api_key: Optional[str] = None):
    """A cached google-genai client for the key (GEMINI_API_KEY by default), or None."""
    key = api_key or os.getenv("GEMINI_API_KEY", "")
    if not key:
        return None
    with _lock:
        if key not in _clients:
            from google import genai
            from google.genai import types
            # Without a timeout the client waits forever: under heavy demand a
            # request never returned and froze the whole server.
            _clients[key] = genai.Client(api_key=key,
                                         http_options=types.HttpOptions(timeout=REQUEST_TIMEOUT_MS))
        return _clients[key]


# Tried in order when a model is overloaded (503), rate-limited (429) or retired (404).
FALLBACK_MODELS = [m for m in dict.fromkeys(
    [GEMINI_TEXT_MODEL, "gemini-flash-latest", "gemini-2.5-flash", "gemini-flash-lite-latest"]) if m]
_RETRYABLE = ("503", "UNAVAILABLE", "504", "DEADLINE_EXCEEDED", "429", "RESOURCE_EXHAUSTED",
              "404", "NOT_FOUND", "timed out", "Timeout", "ReadTimeout")


def ask_gemini(user_text: str, system: str = JARVIS_STYLE, api_key: Optional[str] = None) -> Optional[str]:
    """Ask the text model, falling back through FALLBACK_MODELS when one is
    unavailable. Returns the reply, or None if every model failed (logged)."""
    client = gemini_client(api_key)
    if client is None:
        return None
    for model in FALLBACK_MODELS:
        try:
            resp = client.models.generate_content(model=model,
                                                  contents=f"{system}\n\nUser says: {user_text}")
            text = getattr(resp, "text", None)
            if text:
                return text.strip()
        except Exception as e:
            print(f"[LLM] Gemini ({model}) error: {str(e)[:120]}")
            if not any(code in str(e) for code in _RETRYABLE):
                return None  # e.g. bad key: other models won't help
    return None
