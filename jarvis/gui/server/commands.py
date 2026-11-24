"""
Local commands: one command is a turn; the named steps of process_command (voice control, pending answers, power, apps, tasks...).
"""

import asyncio
import logging
import os
import re
import subprocess
import time
from datetime import datetime

from jarvis.core.errors import recovered
from jarvis.core.services import shared
from jarvis.gui.command_processor import split_compound_command as _split_compound_command
from jarvis.gui.command_rules import CANCEL_RE
from jarvis.gui.command_rules import CONFIRM_RE
from jarvis.gui.command_rules import detect_pc_power_action
from jarvis.gui.command_rules import is_jarvis_exit_command
from jarvis.gui.command_rules import is_stop_speaking_command
from jarvis.gui.command_rules import normalize_command
from jarvis.gui.data_providers import maybe_title
from jarvis.gui.fast_path import try_fast_path
from jarvis.gui.hud_types import command_turn
from jarvis.gui.server.features import HANDLER_MAP
from jarvis.gui.server.features import ROUTER_AVAILABLE
from jarvis.gui.server.tables import DIRECT_APPS
from jarvis.gui.server.tables import RESUME_PHRASES
from jarvis.gui.server.tables import STORY_PHRASES
from jarvis.gui.server.tables import WEB_APPS

from jarvis.core.screen_control import is_tab_command
from jarvis.core.typo_fix import fix_typos

_log = logging.getLogger(__name__)


class CommandsMixin:
    """Local commands: one command is a turn; the named steps of process_command (voice control, pending answers, power, apps, tasks...).

    Part of JARVISWebSocketServer (see jarvis/gui/websocket_server.py).
    """

    async def _run_turn(self, command: str, websocket) -> str:
        """Process one command as a turn: whatever handlers said becomes the reply
        when they return no text, so it is spoken once and never re-asked of the AI."""
        with command_turn() as said:
            reply = await self.process_command(command, websocket)
        return reply or " ".join(said)


    SWITCH_PREFIXES = ('switch to ', 'switch with ', 'switch tab to ', 'go to ', 'switch tab ')


    def switch_to_app_command(self, cmd: str, title: str = 'sir'):
        """Handle 'switch to <app>' / 'go to <app>'. Returns the reply, or None
        if cmd isn't an app switch (e.g. "switch to the next tab", "switch to
        friday"). Uses AppSwitcher (Win32): the old code pasted the spoken name
        into a PowerShell script, a shell-injection risk."""
        prefix = next((p for p in self.SWITCH_PREFIXES if cmd.startswith(p)), None)
        if prefix is None or cmd.split()[-1] in ('friday', 'jarvis') or is_tab_command(cmd):
            return None
        target = re.sub(r"^(?:the|my)\s+", "", cmd[len(prefix):].strip())
        if not target:
            return None
        try:
            from jarvis.core.app_switcher import AppSwitcher
            switcher = shared(AppSwitcher, lambda: AppSwitcher(self.hud_perception))
            if switcher.find_window(target) is None:
                return f"I can't find {target} running. Say 'open {target}' to start it."
            with command_turn():  # its own spoken line is replaced by ours
                switched = switcher.switch_to(target)
            if switched:
                self.state_manager.active_app = target.lower()
                self.state_manager._active_app_time = time.time()
                return f"Switched to {target}{maybe_title(title)}."
        except Exception as e:
            _log.warning(f"[WebSocket] App switch error: {e}")
        return f"Couldn't switch to {target}, {title}."


    def _try_fast_path(self, text: str):
        """Instant execution for common commands (see fast_path.py)."""
        return try_fast_path(self, text)


    def _split_compound_command(self, text: str) -> list:
        """Split compound commands — delegates to command_processor module."""
        return _split_compound_command(text)


    async def process_command(self, command: str, websocket) -> str:
        """Answer one command. Steps run in order; the first that answers wins.

        1. Voice control, pending questions, PC power and exit (on the loop:
           they change server state or schedule the exit).
        2. Local commands (Bluetooth, stories, windows, reminders, apps, habits,
           tasks, wellness, email, PDF), in a worker thread: several block
           (PowerShell for up to 10 s, email over the network) and used to
           freeze every HUD client while they ran.
        3. The intent router, HUD feature commands, then the AI.

        This was one 475-line function.
        """
        command = fix_typos(command)   # every entry point: HUD, the server's mic, sub-commands
        cmd = normalize_command(command.lower().strip())
        title = self.hud_perception.user_title
        if not cmd:
            hour = datetime.now().hour
            greeting = ("Good morning" if hour < 12 else "Good afternoon" if hour < 17
                        else "Good evening" if hour < 21 else "Hey there")
            return f"{greeting}, {title}. How may I help?"

        for step in (self._cmd_voice_control, self._cmd_answer_pending, self._cmd_power_and_exit):
            reply = await step(cmd, title)
            if reply is not None:
                return reply

        reply = await self._run_blocking(self._local_command, cmd, command, title)
        if reply is not None:
            return reply

        return await self._cmd_route_and_answer(cmd, command, title, websocket)


    # ── step 1: on the event loop ────────────────────────────────────────
    async def _cmd_voice_control(self, cmd: str, title: str):
        """"stop"/"shut up" (interrupt, then listen only for the wake word) and "back online"."""
        if is_stop_speaking_command(cmd):
            self._stop_speaking()
            self.quiet_mode = True        # pause voice listening until the wake word
            self._silent_response = True  # don't speak the reply
            _log.info("[VOICE] Quiet mode ON - mic paused until wake word")
            return f"Understood{maybe_title(title)}. Say my name when you need me."
        if any(r in cmd for r in RESUME_PHRASES):
            self.quiet_mode = False
            _log.info("[VOICE] Quiet mode OFF - JARVIS back online")
            return f"I'm back online{maybe_title(title)}. What do you need?"
        return None


    async def _cmd_answer_pending(self, cmd: str, title: str):
        """Answers to a question JARVIS asked: a clarification, a WhatsApp draft, PC power."""
        clarify = getattr(self, '_pending_clarify', None)   # "I'm 60% sure... Should I proceed?"
        if clarify:
            self._pending_clarify = None
            original, expires_at = clarify
            if time.time() <= expires_at:
                if CONFIRM_RE.match(cmd):
                    reply = await self._run_blocking(self._route_through_router, original, force=True)
                    return reply or f"I couldn't complete that{maybe_title(title)}."
                if CANCEL_RE.match(cmd):
                    return f"Okay, never mind{maybe_title(title)}."
            # anything else: a new command

        wa = self._whatsapp_with_draft()   # typed in the chat, sent only on "send"
        if wa:
            from jarvis.core.whatsapp_handler import SEND_CONFIRM_RE, DRAFT_CANCEL_RE
            if SEND_CONFIRM_RE.match(cmd):
                return await self._run_blocking(wa.confirm_send)
            if DRAFT_CANCEL_RE.match(cmd):
                return await self._run_blocking(wa.cancel_draft)
            # anything else: a new command; the draft stays typed, unsent

        pending = self._get_pending_power_action()   # PC shutdown/restart needs a "confirm"
        if pending:
            self._pending_power_action = None
            if CONFIRM_RE.match(cmd):
                return self._execute_power_action(pending, title)
            if CANCEL_RE.match(cmd):
                return f"Cancelled the {pending}{maybe_title(title)}."
            # anything else drops the request and is processed normally
        return None


    async def _cmd_power_and_exit(self, cmd: str, title: str):
        """PC shutdown/restart (asks first) and exiting JARVIS (whole-command match only)."""
        power_action = detect_pc_power_action(cmd)
        if power_action:
            return self.request_power_action(power_action, title)
        if is_jarvis_exit_command(cmd):
            import signal
            self._silent_response = True  # don't speak the farewell

            async def _shutdown():  # after the reply has been sent
                await asyncio.sleep(3)
                self.running = False
                os.kill(os.getpid(), signal.SIGTERM)
            asyncio.ensure_future(_shutdown())
            return f"Shutting down all systems. Until next time{maybe_title(title)}."
        return None


    # ── step 2: local commands, in a worker thread ───────────────────────
    def _local_command(self, cmd: str, command: str, title: str):
        """Commands handled here before the router: explicit keyword matches the
        ML classifier gets wrong, and features with no router handler."""
        for step in (self._cmd_bluetooth, self._cmd_story, self._cmd_chat_history,
                     self._cmd_switch_window, self._cmd_reminder, self._cmd_open_app,
                     self._cmd_habit, self._cmd_task, self._cmd_wellness,
                     self._cmd_email, self._cmd_pdf):
            reply = step(cmd, command, title)
            if reply is not None:
                return reply
        return None


    def _cmd_bluetooth(self, cmd: str, command: str, title: str):
        if 'bluetooth' not in cmd:
            return None
        if any(w in cmd for w in ('off', 'disable', 'switch off', 'turn off')):
            state, word = "Off", "off"
        elif any(w in cmd for w in ('on', 'enable', 'switch on', 'turn on')):
            state, word = "On", "on"
        else:
            return None
        try:
            subprocess.run(['powershell', '-Command',
                'Add-Type -AssemblyName System.Runtime.WindowsRuntime; '
                '[Windows.Devices.Radios.Radio,Windows.System.Devices,ContentType=WindowsRuntime] | Out-Null; '
                '$radios = [Windows.Devices.Radios.Radio]::GetRadiosAsync().AsTask().Result; '
                '$bt = $radios | Where-Object { $_.Kind -eq "Bluetooth" }; '
                f'$bt.SetStateAsync("{state}").AsTask().Result'],
                capture_output=True, timeout=10)
            return f"Bluetooth is now {word}{maybe_title(title)}."
        except Exception as e:
            recovered("WebSocket", e)
            subprocess.Popen(['start', 'ms-settings:bluetooth'], shell=True)
            return f"Opening Bluetooth settings{maybe_title(title)}. Please toggle it manually."


    def _cmd_story(self, cmd: str, command: str, title: str):
        # The ML classifier reads "bedtime story" as get_time; use the one story
        # handler (topic, genre, full length)
        if not ROUTER_AVAILABLE or not any(w in cmd for w in STORY_PHRASES):
            return None
        result = HANDLER_MAP['story'](command, {}, {'title': title, 'knowledge': self.knowledge})
        return result.response if result and result.response else None


    def _cmd_chat_history(self, cmd: str, command: str, title: str):
        # The classifier thinks this is 'story'
        if not (('chat history' in cmd or 'show history' in cmd or 'conversation history' in cmd)
                and self.chat_history):
            return None
        if 'search' in cmd:
            match = re.search(r'search\s+(?:for\s+)?(.+)', cmd, re.I)
            if not match:
                return None
            query = match.group(1).strip()
            results = self.chat_history.search(query)
            if results:
                return f"Found {len(results)} conversations matching '{query}', {title}."
            return f"No conversations found matching '{query}', {title}."
        if 'clear' in cmd or 'delete' in cmd:
            self.chat_history.clear_history()
            return f"Chat history cleared, {title}."
        messages = self.chat_history.get_recent(5)
        if messages:
            summary = "; ".join(f"{m.role}: {m.content[:40]}" for m in messages[-3:])
            return f"Recent chat history, {title}: {summary}"
        return f"No chat history yet, {title}."


    def _cmd_switch_window(self, cmd: str, command: str, title: str):
        # The classifier thinks 'go back' is 'previous_track'
        if cmd in ('go back', 'alt tab', 'switch window', 'next window', 'previous window'):
            try:
                import pyautogui
                pyautogui.hotkey('alt', 'tab')
                return f"Switched to the previous window, {title}."
            except Exception as e:
                recovered("WebSocket", e)
                return f"Couldn't switch windows, {title}."
        # 'switch to [app]' / 'go to [app]' (Win32 calls in AppSwitcher). Tab
        # commands ("switch to the next tab") are screen control: the router.
        return self.switch_to_app_command(cmd, title)


    def _cmd_reminder(self, cmd: str, command: str, title: str):
        # Route directly, so it doesn't fall to the face-auth gate
        if not (('remind' in cmd or 'reminder' in cmd) and 'email' not in cmd and self.reminder_manager):
            return None
        if 'list' in cmd or 'show' in cmd or 'my' in cmd:
            result = self.reminder_manager.read_reminders()
            return result if result else f"No upcoming reminders, {title}."
        if self.reminder_manager.set_reminder_from_command(cmd):
            return f"Reminder set, {title}."
        return f"I couldn't parse that reminder. Try: 'remind me to X in 30 minutes', {title}."


    def _cmd_open_app(self, cmd: str, command: str, title: str):
        """'open X': direct map, web apps, AppFinder, then the Start menu. No ML."""
        open_match = re.match(r'^(?:open|launch|start|run)\s+(.+)', cmd, re.I)
        if not open_match or is_tab_command(cmd):
            return None   # "open a new tab" is a key press (screen control), not an app
        app_name = open_match.group(1).strip()
        app_lower = app_name.lower()

        if app_lower in DIRECT_APPS:
            target = DIRECT_APPS[app_lower]
            try:
                if target.startswith('http') or target.startswith('ms-') or target.endswith(':'):
                    os.startfile(target)
                else:
                    subprocess.Popen(target, shell=True)
                return f"Opening {app_name}, {title}."
            except Exception as e:
                return f"Error opening {app_name}: {e}"

        if app_lower in WEB_APPS:
            import webbrowser
            webbrowser.open(WEB_APPS[app_lower])
            return f"Opening {app_name} in browser, {title}."

        if self.jarvis and hasattr(self.jarvis, 'app_finder'):
            try:
                if self.jarvis.app_finder.open_app(app_lower):
                    return f"Opening {app_name}, {title}."
            except Exception as e:
                recovered("WebSocket", e)

        try:
            os.startfile(app_lower)
            return f"Opening {app_name}, {title}."
        except Exception:
            try:  # search the Start menu
                from jarvis.core.app_finder import AppManager
                if shared(AppManager, lambda: AppManager(self.hud_perception)).open_app(app_lower):
                    return f"Opening {app_name}, {title}."
            except Exception as e:
                recovered("WebSocket", e)
        return f"Couldn't find {app_name}, {title}. Try the exact name."


    def _cmd_habit(self, cmd: str, command: str, title: str):
        # The classifier thinks this is 'conversation'
        if 'habit' not in cmd or not self.habit_tracker:
            return None
        if 'create' in cmd or 'add' in cmd or 'new' in cmd:
            match = re.search(r'(?:create|add|new)\s+habit\s+(.+?)(?:\s+every\s+|\s+daily|\s+hourly|$)', cmd, re.I)
            if match:
                desc = match.group(1).strip()
                self.habit_tracker.create_habit(desc, cmd)
                return f"Habit '{desc}' created, {title}."
            return f"Please specify a habit, {title}. Say 'add habit drink water'."
        if 'list' in cmd or 'show' in cmd or 'my habits' in cmd:
            return self.habit_tracker.list_habits()
        if 'check' in cmd:
            reminders = self.habit_tracker.check_reminders()
            if reminders:
                return f"You have {len(reminders)} habit reminders, {title}."
            return f"No habit reminders due, {title}."
        return None


    def _cmd_task(self, cmd: str, command: str, title: str):
        # The classifier thinks this is 'conversation'
        if not (('task' in cmd or 'todo' in cmd or 'to do' in cmd) and self.task_manager_obj):
            return None
        tm = self.task_manager_obj
        if 'add' in cmd or 'create' in cmd or 'new' in cmd:
            match = re.search(r'(?:add|create|new)\s+(?:a\s+)?task\s+(.+)', cmd, re.I)
            if not match:
                return None
            desc = match.group(1).strip()
            if hasattr(tm, 'add_task'):
                tm.add_task(desc)
            elif hasattr(tm, 'create_task'):
                tm.create_task(desc)
            return f"Task added: '{desc}', {title}."
        if 'list' in cmd or 'show' in cmd or 'my task' in cmd:
            if hasattr(tm, 'list_tasks'):
                result = tm.list_tasks()
            elif hasattr(tm, 'get_tasks'):
                result = tm.get_tasks()
            else:
                result = None
            return result if isinstance(result, str) else f"Listing your tasks, {title}."
        return None


    def _cmd_wellness(self, cmd: str, command: str, title: str):
        # The classifier thinks this is 'conversation'
        if 'wellness' not in cmd or not self.wellness_monitor:
            return None
        if 'summary' in cmd or 'status' in cmd:
            summary = self.wellness_monitor.get_wellness_summary()
            return summary if isinstance(summary, str) else f"Your wellness looks good, {title}."
        if 'check' in cmd:
            reminder = self.wellness_monitor.check_wellness()
            return reminder if reminder else f"You're doing well, {title}."
        if 'reset' in cmd or 'took a break' in cmd:
            self.wellness_monitor.reset_session()
            return f"Session reset. Good on you for taking a break, {title}."
        return None


    def _cmd_email(self, cmd: str, command: str, title: str):
        """Send/check/read/summarise email directly, skipping the ML classifier."""
        if not (('email' in cmd or 'mail' in cmd or 'gmail' in cmd) and self.email_handler_obj):
            return None
        mail = self.email_handler_obj
        send_match = re.search(r'send\s+(?:a\s+)?(?:email|mail)\s+to\s+(\S+@\S+)\s+(?:saying|about|subject|with)?\s*(.*)', cmd, re.I)
        if send_match:
            to_email = send_match.group(1).strip()
            body = send_match.group(2).strip() or "Hello from JARVIS"
            subject = body[:50] + "..." if len(body) > 50 else body
            return mail.send_email(to_email, subject, body)
        # "send email to bob saying hi": no address. This used to fall through
        # to the default branch and check the inbox instead.
        if re.search(r'\bsend\b', cmd) and 'remind' not in cmd:
            return (f"I need an email address to send that{maybe_title(title)}. "
                    f"Try: send email to name@example.com saying hello.")
        if 'remind' in cmd and 'email' in cmd:
            reminder_text = re.sub(r'.*(?:remind|email).*?(?:to|about|that)\s+', '', cmd, flags=re.I).strip()
            if reminder_text:
                return mail.send_reminder_email(reminder_text) or f"Reminder email sent, {title}."
        if 'summarize' in cmd or 'summary' in cmd:
            result = mail.summarize_emails()
            return (f"Here's your email summary, {title}. {result}" if isinstance(result, str)
                    else f"Summarizing your emails, {title}.")
        result = mail.get_unread_emails()   # check / read / inbox, and the default
        # The handler's reply is complete ("You have 3 unread..." / "Email is not connected")
        return result if isinstance(result, str) and result else f"Checking your emails, {title}."


    def _cmd_pdf(self, cmd: str, command: str, title: str):
        if 'pdf' not in cmd or not self.pdf_handler:
            return None
        if hasattr(self.pdf_handler, 'extract_text'):
            return f"PDF handler ready, {title}. Please specify a file path."
        return f"PDF handler available, {title}."


    async def _fallback_process(self, command: str, websocket) -> str:
        """Fallback command processing delegated to fallback_processor module"""
        return await self.fallback_processor.process(command, websocket)
