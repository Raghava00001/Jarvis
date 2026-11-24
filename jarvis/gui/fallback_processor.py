import logging
_log = logging.getLogger(__name__)

# Returned by an extracted step that didn't handle the request: the
# caller carries on with its next step.
_NEXT = object()

from jarvis.core.errors import recovered
import json
import re


class FallbackProcessor:
    """Commands the HUD handles itself, and the last resort before the AI.

    See process(). Every feature that has a HANDLER_MAP handler is answered by
    that handler; this class only keeps what is specific to the HUD server.
    """

    def __init__(self, server):
        self.server = server

    async def process(self, command: str, websocket) -> str:
        """Commands only the HUD handles, then any feature by keywords, then the AI.

        Runs when the router (jarvis/gui/server/router.py) didn't answer.
        This used to hold a second copy of about 30 features that the
        HANDLER_MAP handlers already implement (weather, jokes, time, apps,
        notes, alarms, volume, email, search ...). The copies drifted from the
        handlers, and several of the bugs found in v2.10 were in them. Now each
        feature has one implementation: its handler.
        """
        cmd = command.lower().strip()
        title = self.server.hud_perception.user_title

        # Voice switching sends HUD messages, so it lives here
        _r = await self._cmd_switch_voice(cmd, websocket)
        if _r is not _NEXT:
            return _r
        _r = await self._cmd_switch_to_jarvis(cmd, title, websocket)
        if _r is not _NEXT:
            return _r

        # Features with no HANDLER_MAP handler (server subsystems)
        # (tasks, wellness and chat-history search are the server's local steps,
        # which run before the router; copies here could never be reached)
        for step in (self._cmd_youtube_download, self._cmd_go_back, self._cmd_features_status,
                     self._cmd_verify_face):
            _r = step(cmd, title)
            if _r is not _NEXT:
                return _r
        _r = await self._cmd_face_registration(cmd, title, websocket)
        if _r is not _NEXT:
            return _r
        if re.search(r"\briddle\b", cmd):
            ent = self.server.entertainment
            riddle = ent.tell_riddle() if ent and hasattr(ent, "tell_riddle") else None
            return riddle if isinstance(riddle, str) and riddle else (
                f"Here's a riddle, {title}: what has keys but no locks, space but no room? A keyboard!")

        # Any other feature: its one implementation, the HANDLER_MAP handler
        reply = await self.server._run_blocking(self._feature_by_keywords, command, title)
        if reply:
            return reply

        # Conversation: the AI
        _r = self._cmd_ask_gemini(command)
        if _r is not _NEXT:
            return _r
        return "I'm not sure about that. Try asking differently or be more specific."

    def _feature_by_keywords(self, command: str, title: str):
        """The keyword classifier's intent, answered by that feature's handler.
        (The router tries the ML brain first; this is the safety net, with the
        same handlers, not copies of them.)"""
        from jarvis.core.intent_classifier import classify_intent
        from jarvis.gui.server.features import HANDLER_MAP
        intent, entities = classify_intent(command)
        handler = HANDLER_MAP.get(intent)
        if handler is None or intent in ("conversation", "ai_search", "search"):
            return None   # conversation and open-ended search: the AI answers below
        try:
            result = handler(command, entities, self.server._handler_context(title))
        except Exception as e:
            recovered("Fallback", e)
            return None
        return result.response if result and result.success and result.response else None

    async def _cmd_switch_voice(self, cmd, websocket):
        """Step of process(): switch voice."""
        # Voice switching (needs WebSocket - handle before router)
        if 'switch to friday' in cmd or 'activate friday' in cmd:
            self.server.hud_perception.switch_to_friday()
            await self.server._send_to(websocket, json.dumps({
                'type': 'assistant_info',
                'name': 'FRIDAY',
                'is_friday': True
            }))
            return "FRIDAY online. Hello, boss. How can I help you today?"
        return _NEXT

    async def _cmd_switch_to_jarvis(self, cmd, title, websocket):
        """Step of process(): switch to jarvis."""
        if 'switch to jarvis' in cmd or 'activate jarvis' in cmd:
            self.server.hud_perception.switch_to_jarvis()
            await self.server._send_to(websocket, json.dumps({
                'type': 'assistant_info',
                'name': 'JARVIS',
                'is_friday': False
            }))
            return f"JARVIS back online, {title}. At your service."
        return _NEXT

    def _cmd_youtube_download(self, cmd, title):
        """Step of process(): youtube download."""
        # YOUTUBE - download video, download audio
        if self.server.youtube_downloader:
            if 'youtube' in cmd or 'download video' in cmd or 'download audio' in cmd:
                # Extract URL from command
                url = self.server.youtube_downloader.extract_url_from_command(cmd)
                
                if url:
                    if 'audio' in cmd or 'mp3' in cmd or 'music' in cmd:
                        self.server.youtube_downloader.download_audio(url)
                        return f"Downloading audio from YouTube, {title}."
                    else:
                        self.server.youtube_downloader.download_video(url)
                        return f"Downloading video from YouTube, {title}."
                elif 'downloads' in cmd or 'folder' in cmd:
                    self.server.youtube_downloader.open_downloads_folder()
                    return f"Opening YouTube downloads folder, {title}."
                else:
                    return f"Please provide a YouTube URL for me to download, {title}."
        return _NEXT

    def _cmd_go_back(self, cmd, title):
        """Step of process(): go back."""
        if cmd in ('go back', 'alt tab', 'switch window', 'next window', 'previous window'):
            try:
                import pyautogui
                pyautogui.hotkey('alt', 'tab')
                return f"Switched to the previous window, {title}."
            except Exception as e:
                return f"Couldn't switch windows, {title}."
        return _NEXT

    def _cmd_features_status(self, cmd, title):
        """Step of process(): Features status."""
        # Features status
        if 'features' in cmd or 'status' in cmd:
            status = self.server.get_feature_status()
            features = []
            if status['jarvis_full']:
                features.append("full JARVIS integration")
            if status['gesture_available']:
                features.append("gesture control")
            if status['face_available']:
                features.append("face recognition")
            if status['emotion_available']:
                features.append("emotion detection")
            
            if features:
                return f"Available features, {title}: {', '.join(features)}. " \
                       "All can be enabled from the interface."
            return f"Core features active, {title}. Advanced modules loading."
        return _NEXT

    async def _cmd_face_registration(self, cmd, title, websocket):
        """Step of process(): FACE REGISTRATION."""
        # FACE REGISTRATION
        if 'register my face' in cmd or 'register face' in cmd or 'register owner' in cmd:
            if self.server.face_recognition:
                result = self.server.face_recognition.register_owner()
                if result:
                    self.server.current_user = self.server.face_recognition.current_user
                    await self.server._send_to(websocket, json.dumps({
                        'type': 'face_registered',
                        'success': True,
                        'user': 'Raghava'
                    }))
                    return f"Face registered successfully, {title}. You are now the verified owner."
                return f"Face registration failed, {title}. Please try again with better lighting."
            return f"Face recognition is not available, {title}. Install face_recognition and dlib."
        return _NEXT

    def _cmd_verify_face(self, cmd, title):
        """Step of process(): VERIFY FACE."""
        # VERIFY FACE
        if 'verify me' in cmd or 'authenticate' in cmd or 'who am i' in cmd:
            if self.server.face_recognition:
                result = self.server.face_recognition.authenticate()
                if result:
                    user = self.server.face_recognition.current_user
                    return f"Welcome, {user.name}. Access level: {user.user_type.value}."
                return f"Face not recognized, {title}."
            return f"Face recognition not available, {title}."
        return _NEXT

    def _cmd_ask_gemini(self, command):
        """Step of process(): ask gemini."""
        # Default fallback - USE GEMINI AI for intelligent responses
        if self.server.knowledge and hasattr(self.server.knowledge, 'answer_question'):
            try:
                response = self.server.knowledge.answer_question(command)
                _err = ['trouble connecting', 'knowledge base', 'currently offline', 'Set GROQ_API_KEY']
                if response and not any(ep in (response or '') for ep in _err):
                    return response
            except Exception as e:
                _log.warning(f"[WebSocket] Knowledge error: {e}")
        return _NEXT
