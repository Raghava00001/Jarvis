"""
Subsystems that load on first use (camera features, knowledge, OCR...), each built once through the service registry.
"""

import logging

from jarvis.core.services import shared
from jarvis.gui.server.features import CHAT_HISTORY_AVAILABLE
from jarvis.gui.server.features import CLIPBOARD_AVAILABLE
from jarvis.gui.server.features import CONTEXT_MEMORY_AVAILABLE
from jarvis.gui.server.features import ChatHistory
from jarvis.gui.server.features import ContextMemory
from jarvis.gui.server.features import EMOTION_AVAILABLE
from jarvis.gui.server.features import EmotionDetector
from jarvis.gui.server.features import FACE_AVAILABLE
from jarvis.gui.server.features import FaceRecognition
from jarvis.gui.server.features import GESTURE_AVAILABLE
from jarvis.gui.server.features import GestureController
from jarvis.gui.server.features import KNOWLEDGE_AVAILABLE
from jarvis.gui.server.features import KnowledgeLayer
from jarvis.gui.server.features import OCRHandler
from jarvis.gui.server.features import OCR_AVAILABLE
from jarvis.gui.server.features import PDFHandler
from jarvis.gui.server.features import PDF_AVAILABLE
from jarvis.gui.server.features import YOUTUBE_AVAILABLE
from jarvis.gui.server.features import YouTubeDownloader

_log = logging.getLogger(__name__)


class ServicesMixin:
    """Subsystems that load on first use (camera features, knowledge, OCR...), each built once through the service registry.

    Part of JARVISWebSocketServer (see jarvis/gui/websocket_server.py).
    """

    @property
    def emotion_detector(self):
        if getattr(self, 'jarvis', None):
            try: return self.jarvis.emotion_detector
            except Exception as e: _log.warning(f"[LAZY LOAD ERROR] jarvis.emotion_detector: {e}")
        if getattr(self, '_emotion_detector', None) is None and EMOTION_AVAILABLE:
            try: self._emotion_detector = shared(EmotionDetector)
            except Exception as e:
                _log.warning(f"[LAZY LOAD ERROR] emotion_detector: {e}")
                return None
        return getattr(self, '_emotion_detector', None)


    @property
    def face_recognition(self):
        if getattr(self, 'jarvis', None) and hasattr(self.jarvis, 'face_auth'):
            try: return self.jarvis.face_auth
            except Exception as e: _log.warning(f"[LAZY LOAD ERROR] jarvis.face_auth: {e}")
        if getattr(self, '_face_recognition', None) is None and FACE_AVAILABLE:
            try: self._face_recognition = shared(FaceRecognition, lambda: FaceRecognition(self.hud_perception))
            except Exception as e:
                _log.warning(f"[LAZY LOAD ERROR] face_recognition: {e}")
                return None
        return getattr(self, '_face_recognition', None)


    @property
    def gesture_controller(self):
        if getattr(self, 'jarvis', None) and hasattr(self.jarvis, 'gesture'):
            try: return self.jarvis.gesture
            except Exception as e: _log.warning(f"[LAZY LOAD ERROR] jarvis.gesture: {e}")
        if getattr(self, '_gesture_controller', None) is None and GESTURE_AVAILABLE:
            try: self._gesture_controller = shared(GestureController, lambda: GestureController(self.hud_perception))
            except Exception as e:
                _log.warning(f"[LAZY LOAD ERROR] gesture_controller: {e}")
                return None
        return getattr(self, '_gesture_controller', None)


    @property
    def chat_history(self):
        if getattr(self, 'jarvis', None):
            try: return self.jarvis.chat_history
            except Exception as e: _log.warning(f"[LAZY LOAD ERROR] jarvis.chat_history: {e}")
        if getattr(self, '_chat_history', None) is None and CHAT_HISTORY_AVAILABLE:
            try: self._chat_history = shared(ChatHistory, lambda: ChatHistory(self.hud_perception))
            except Exception as e:
                _log.warning(f"[LAZY LOAD ERROR] chat_history: {e}")
                return None
        return getattr(self, '_chat_history', None)


    @property
    def context_memory(self):
        if getattr(self, 'jarvis', None):
            try: return self.jarvis.context_memory
            except Exception as e: _log.warning(f"[LAZY LOAD ERROR] jarvis.context_memory: {e}")
        if getattr(self, '_context_memory', None) is None and CONTEXT_MEMORY_AVAILABLE:
            try: self._context_memory = shared(ContextMemory)
            except Exception as e:
                _log.warning(f"[LAZY LOAD ERROR] context_memory: {e}")
                return None
        return getattr(self, '_context_memory', None)


    @property
    def knowledge(self):
        if getattr(self, 'jarvis', None):
            try: return self.jarvis.knowledge
            except Exception as e: _log.warning(f"[LAZY LOAD ERROR] jarvis.knowledge: {e}")
        if getattr(self, '_knowledge', None) is None and KNOWLEDGE_AVAILABLE:
            try: self._knowledge = shared(KnowledgeLayer, lambda: KnowledgeLayer(self.hud_perception))
            except Exception as e:
                _log.warning(f"[LAZY LOAD ERROR] knowledge: {e}")
                return None
        return getattr(self, '_knowledge', None)


    @property
    def ocr_handler(self):
        if getattr(self, 'jarvis', None):
            try: return self.jarvis.ocr
            except Exception as e: _log.warning(f"[LAZY LOAD ERROR] jarvis.ocr: {e}")
        if getattr(self, '_ocr_handler', None) is None and OCR_AVAILABLE:
            try: self._ocr_handler = shared(OCRHandler, lambda: OCRHandler(self.hud_perception))
            except Exception as e:
                _log.warning(f"[LAZY LOAD ERROR] ocr_handler: {e}")
                return None
        return getattr(self, '_ocr_handler', None)


    @property
    def pdf_handler(self):
        if getattr(self, 'jarvis', None):
            try: return self.jarvis.pdf
            except Exception as e: _log.warning(f"[LAZY LOAD ERROR] jarvis.pdf: {e}")
        if getattr(self, '_pdf_handler', None) is None and PDF_AVAILABLE:
            try: self._pdf_handler = shared(PDFHandler, lambda: PDFHandler(self.hud_perception, self.knowledge))
            except Exception as e:
                _log.warning(f"[LAZY LOAD ERROR] pdf_handler: {e}")
                return None
        return getattr(self, '_pdf_handler', None)


    @property
    def youtube_downloader(self):
        if getattr(self, 'jarvis', None):
            try: return self.jarvis.youtube
            except Exception as e: _log.warning(f"[LAZY LOAD ERROR] jarvis.youtube: {e}")
        if getattr(self, '_youtube_downloader', None) is None and YOUTUBE_AVAILABLE:
            try: self._youtube_downloader = shared(YouTubeDownloader, lambda: YouTubeDownloader(self.hud_perception))
            except Exception as e:
                _log.warning(f"[LAZY LOAD ERROR] youtube_downloader: {e}")
                return None
        return getattr(self, '_youtube_downloader', None)


    @property
    def clipboard_intelligence(self):
        if getattr(self, 'jarvis', None):
            try: return self.jarvis.clipboard
            except Exception as e: _log.warning(f"[LAZY LOAD ERROR] jarvis.clipboard: {e}")
        if getattr(self, '_clipboard_intelligence', None) is None and CLIPBOARD_AVAILABLE:
            try: self._init_clipboard()
            except Exception as e:
                _log.warning(f"[LAZY LOAD ERROR] clipboard_intelligence: {e}")
                return None
        return getattr(self, '_clipboard_intelligence', None)
