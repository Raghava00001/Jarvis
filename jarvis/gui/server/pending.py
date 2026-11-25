"""
Questions waiting for an answer: PC power confirmation and WhatsApp drafts.
"""

import logging
import subprocess
import time

from jarvis.gui.command_rules import POWER_CONFIRM_WINDOW_S
from jarvis.gui.data_providers import maybe_title

_log = logging.getLogger(__name__)


class PendingMixin:
    """Questions waiting for an answer: PC power confirmation and WhatsApp drafts.

    Part of JARVISWebSocketServer (see jarvis/gui/websocket_server.py).
    """

    # ── WhatsApp drafts (sent only after the user confirms) ──────────────
    def _whatsapp_with_draft(self):
        """The WhatsApp handler if it has an unsent draft waiting, else None."""
        try:
            from jarvis.core.services import peek
            from jarvis.core.whatsapp_handler import WhatsAppHandler
        except Exception:
            return None
        wa = getattr(self, 'whatsapp_handler', None) or peek(WhatsAppHandler)
        return wa if wa is not None and wa.pending_draft() else None


    def _answers_whatsapp_draft(self, cmd: str) -> bool:
        """'send' / 'cancel' while a draft waits: handled locally, never by the LLM."""
        if not self._whatsapp_with_draft():
            return False
        from jarvis.core.whatsapp_handler import SEND_CONFIRM_RE, DRAFT_CANCEL_RE
        return bool(SEND_CONFIRM_RE.match(cmd) or DRAFT_CANCEL_RE.match(cmd))


    # ── PC power actions (always confirmed) ──────────────────────────────
    def _get_pending_power_action(self):
        pending = getattr(self, '_pending_power_action', None)
        if not pending:
            return None
        action, expires_at = pending
        if time.time() > expires_at:
            self._pending_power_action = None
            return None
        return action


    def request_power_action(self, action: str, title: str = None) -> str:
        """Arm a PC shutdown/restart; it only runs after the user confirms."""
        if action not in ('shutdown', 'restart'):
            raise ValueError(action)
        if title is None:
            title = getattr(getattr(self, 'hud_perception', None), 'user_title', '')
        self._pending_power_action = (action, time.time() + POWER_CONFIRM_WINDOW_S)
        verb = 'shut down' if action == 'shutdown' else 'restart'
        return (f"Are you sure you want me to {verb} the computer{maybe_title(title)}? "
                f"Say 'confirm' within {POWER_CONFIRM_WINDOW_S} seconds, or 'cancel'.")


    def _execute_power_action(self, action: str, title: str) -> str:
        flag = '/s' if action == 'shutdown' else '/r'
        subprocess.Popen(['shutdown', flag, '/t', '5'])
        if action == 'shutdown':
            return f"Shutting down the computer in 5 seconds{maybe_title(title)}. Save your work."
        return f"Restarting the computer in 5 seconds{maybe_title(title)}."
