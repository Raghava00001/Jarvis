"""
Sending to HUD clients: per-client queues with backpressure, channels, thread-safe dispatch, and running blocking work off the event loop.
"""

import asyncio
import contextvars
import functools
import json
import logging
import websockets

from jarvis.core.errors import recovered
from jarvis.gui.hud_types import Action

_log = logging.getLogger(__name__)


class TransportMixin:
    """Sending to HUD clients: per-client queues with backpressure, channels, thread-safe dispatch, and running blocking work off the event loop.

    Part of JARVISWebSocketServer (see jarvis/gui/websocket_server.py).
    """

    # ═══════════════════════════════════════════════════════════════
    # UNIFIED DISPATCH LAYER — all sends go through here
    # ═══════════════════════════════════════════════════════════════

    # Priority levels for backpressure (higher = more important)
    _CHANNEL_PRIORITY = {'command': 3, 'live': 2, 'sensors': 1, 'stats': 0}

    async def broadcast(self, message, channel=None):
        """Broadcast to clients subscribed to a specific channel.

        If channel is None, sends to ALL clients (legacy behavior).
        If channel is specified, only sends to clients subscribed to that channel.

        Now routes through per-client queues for backpressure.
        """
        await self.dispatch(channel, message)


    async def dispatch(self, channel, message):
        """Single authoritative dispatcher — ALL sends go through here.

        Enqueues to per-client asyncio.Queue. If queue is full:
          - Drop low-priority messages (stats, sensors)
          - Force-enqueue high-priority (command, live)
        """
        if not self.clients:
            return

        # Tag message with channel
        if channel and isinstance(message, dict):
            message['channel'] = channel

        msg_str = json.dumps(message) if isinstance(message, dict) else message
        priority = self._CHANNEL_PRIORITY.get(channel, 1)

        if channel:
            targets = [
                c for c in list(self.clients)
                if channel in self._client_channels.get(c, {'command', 'stats', 'live', 'sensors'})
            ]
        else:
            targets = list(self.clients)

        for client in targets:
            q = self._client_queues.get(client)
            if q is None:
                continue
            try:
                q.put_nowait(msg_str)
            except asyncio.QueueFull:
                if priority >= 2:
                    # High priority: drop oldest to make room
                    try:
                        q.get_nowait()
                    except asyncio.QueueEmpty:
                        _log.debug("Ignored error", exc_info=True)
                    try:
                        q.put_nowait(msg_str)
                    except asyncio.QueueFull:
                        _log.debug("Ignored error", exc_info=True)

                # else: silently drop low-priority message (stats/sensors spam)

    async def _send_to(self, websocket, message):
        """Point-to-point send via queue (for request-response within process_message).

        Use this instead of `await self._send_to(websocket, json.dumps(...))`.
        """
        msg_str = json.dumps(message) if isinstance(message, dict) else message
        q = self._client_queues.get(websocket)
        if q is None:
            # Fallback: direct send if queue not set up (shouldn't happen)
            try:
                await websocket.send(msg_str)
            except Exception as _err:
                recovered("WebSocket", _err)
            return
        try:
            q.put_nowait(msg_str)
        except asyncio.QueueFull:
            # For point-to-point, always force (these are user-facing responses)
            try:
                q.get_nowait()
            except asyncio.QueueEmpty:
                _log.debug("Ignored error", exc_info=True)
            try:
                q.put_nowait(msg_str)
            except asyncio.QueueFull:
                _log.debug("Ignored error", exc_info=True)


    def _dispatch_from_thread(self, channel, message):
        """Thread-safe bridge: background threads call this instead of sending to a socket.

        Schedules dispatch() on the server's event loop (works from the loop
        thread too).
        """
        if not self.clients:
            return
        self._run_on_loop(self.dispatch(channel, message))


    async def _client_sender(self, websocket):
        """Per-client drain loop — pops from queue and sends.

        Runs as a task for the lifetime of the connection.
        Never blocks the event loop waiting on a slow client.
        """
        q = self._client_queues.get(websocket)
        if q is None:
            return
        try:
            while True:
                msg = await q.get()
                try:
                    await websocket.send(msg)
                except websockets.exceptions.ConnectionClosed:
                    break
                except Exception:
                    _log.debug("Ignored error", exc_info=True)
        except asyncio.CancelledError:
            _log.debug("Ignored error", exc_info=True)


    def push_live_transcription(self, text: str, role: str = 'jarvis', source: str = None, stream: str = None, kind: str = None, turn_id: int = None):
        """Central gateway for Gemini Live transcription messages.

        This is the SINGLE authoritative path for live transcriptions to reach clients.
        Handles cross-pipeline deduplication: if a 'result' message was just sent with
        similar text, this skips to prevent duplicates.
        """
        if not text or not text.strip():
            return
        text = text.strip()

        safe_text = text[:60].encode('ascii', errors='replace').decode()
        _log.info(f"[TRANSCRIPT] src={source} stream={stream} kind={kind} turn={turn_id} | {safe_text}")

        if getattr(self, "live_engine", None):
            if source != "gemini_live" or stream != "live" or kind != "transcript":
                return

        # Cross-pipeline dedup: check if command pipeline just sent this
        import time as _plt
        now = _plt.time()
        if self._recent_result_text and (now - self._recent_result_time) < 3:
            # Check word overlap between live transcription and recent result
            result_words = set(self._recent_result_text.lower().split())
            live_words = set(text.lower().split())
            if result_words and live_words:
                overlap = len(result_words & live_words) / max(len(live_words), 1)
                if overlap > 0.5:
                    return  # Skip — command pipeline already sent this

        msg = json.dumps({
            'type': 'live_transcription',
            'text': text,
            'role': role,
            'speak': False,
            'source': source if source else 'gemini_live',
            'channel': 'live'
        })

        # Through dispatch(): per-client queues with backpressure. This used a
        # blocking `await q.put()` per chunk, so a client that fell behind (tab in
        # the background, slow machine) parked one coroutine per transcript
        # fragment on the event loop, without limit.
        self._dispatch_from_thread('live', msg)


    def _run_on_loop(self, coro):
        """Schedule a coroutine on the server's event loop from any thread."""
        try:
            asyncio.get_running_loop()
            return asyncio.ensure_future(coro)
        except RuntimeError:
            loop = getattr(self, '_voice_loop', None)
            if loop and loop.is_running():
                return asyncio.run_coroutine_threadsafe(coro, loop)
            coro.close()  # no loop to run it on (e.g. tests)


    async def _run_blocking(self, fn, *args, **kwargs):
        """Run blocking work (handlers, LLM, weather, news) in a worker thread.

        The current context is copied into the thread so speech recorded by a
        handler lands in this command's turn (see hud_types.command_turn). The
        event loop stays free to serve other clients and keepalive pings.
        """
        ctx = contextvars.copy_context()
        call = functools.partial(fn, *args, **kwargs)
        return await asyncio.get_running_loop().run_in_executor(None, ctx.run, call)


    async def apply_action(self, websocket, action: Action):
        """Single point for all WebSocket responses - PREVENTS LOOPS"""
        if action.type == "SPEAK":
            text = action.payload.get("text", "")
            if not text:
                return

            # CRITICAL: Duplicate response check
            if self.state_manager.is_duplicate_response(text):
                _log.info(f"[WebSocket] Skipping duplicate response")
                return

            _should_speak = action.payload.get("speak", True) and not self._live_ready()
            if _should_speak and self._voice_reply(text):
                _should_speak = False  # the server spoke it; the browser must not repeat it

            await self._send_to(websocket, json.dumps({
                "type": "response",
                "text": text,
                "speak": _should_speak,
                "mood": action.payload.get("mood", "neutral")
            }))
        elif action.type == "UPDATE_UI":
            await self._send_to(websocket, json.dumps({
                "type": action.payload.get("ui_type", "update"),
                **{k: v for k, v in action.payload.items() if k != "ui_type"}
            }))


    async def send_periodic_updates(self, websocket):
        """Send updates periodically with delta compression"""
        counter = 0
        while True:
            try:
                await asyncio.sleep(10)  # 10s instead of 3s

                # Only send stats if values changed (delta compression)
                stats = await self._run_blocking(self.get_system_stats)
                stats_hash = str(stats.get('cpu', 0)) + str(stats.get('ram', 0)) + str(stats.get('battery', 0))
                if stats_hash != self._last_stats_hash:
                    self._last_stats_hash = stats_hash
                    stats['channel'] = 'stats'
                    await self._send_to(websocket, json.dumps(stats))

                counter += 1
                if counter >= 18:  # Every 3 minutes (18 * 10s)
                    counter = 0
                    weather = await self._run_blocking(self.get_weather_data)
                    weather['channel'] = 'stats'
                    await self._send_to(websocket, json.dumps(weather))
                    news = await self._run_blocking(self.get_news_data)
                    news['channel'] = 'stats'
                    await self._send_to(websocket, json.dumps(news))
            except asyncio.CancelledError:
                break
            except Exception as e:
                # One failed refresh (network blip) used to end this client's
                # updates for good: the bare except broke out of the loop.
                _log.warning(f"[WebSocket] Periodic update error: {e}")


    # ── C-01: Push text into Gemini Live session ──
    def _push_live_text(self, text, wake=True):
        """Inject user text directly into the active Gemini Live session.
        This prevents dual-response clashing by using a single audio path.

        wake=False for system announcements: they must not open the wake-word
        window (that would send the next 20 s of room audio to Gemini).
        """
        le = getattr(self, 'live_engine', None)
        if not le or not le._running or not le.session:
            raise RuntimeError("Gemini Live session not available")

        # Typing in the HUD is always deliberate: open the wake-word window
        if wake and hasattr(le, 'wake'):
            le.wake("typed in HUD")

        # Push into the live session's event loop
        async def _inject():
            await le.session.send_client_content(
                turns=[{"role": "user", "parts": [{"text": text}]}],
                turn_complete=True
            )

        asyncio.run_coroutine_threadsafe(_inject(), le._loop)
