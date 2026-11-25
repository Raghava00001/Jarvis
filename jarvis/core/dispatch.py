"""
One way to answer a command with a feature handler, for every front end.

The HUD router, the HUD fallback and console mode all reach features through
this: the keyword classifier picks the intent, and that feature's one
implementation, its HANDLER_MAP handler, answers. (Console mode used to have
its own classifier and its own copies of alarms, volume, weather, notes ...)
"""

import logging
from typing import Any, Dict, Optional

from jarvis.core.errors import recovered

_log = logging.getLogger(__name__)

# Answered by the AI, not a feature handler, when nothing more specific matched
OPEN_ENDED = ("conversation", "ai_search", "search")

# Keyword-classifier intents that come from exact patterns with their own
# entities. When one fires, it is more specific than the ML brain's guess.
PRECISE_RULE_INTENTS = {
    'search_news',      # "news about X", "the latest on X" (topic)
    'screen_question',  # "what is this", "explain this error"
    'set_timer',        # "set a timer for 10 minutes"
    'take_note', 'list_notes', 'read_clipboard', 'ocr',
    'calculate',        # "25 times 4" (the brain guessed get_time from "times")
    'remember', 'recall',  # "remember that ...", "what is my ..." (falls through if nothing is stored)
}

# Intent names the HUD router answers itself (context-dependent keys), outside HANDLER_MAP
ROUTER_NATIVE = {'next', 'previous', 'scroll'}


def is_precise_rule(kw_intent, command: str) -> bool:
    if kw_intent in PRECISE_RULE_INTENTS:
        return True
    # Tab commands only: other screen_control words ("copy", "type") also
    # appear in ordinary questions ("how do I copy a file in linux").
    if kw_intent == 'screen_control':
        from jarvis.core.screen_control import is_tab_command
        return is_tab_command(command)
    return False


def merge_brain_and_rules(brain_intent: str, brain_entities: dict, command: str):
    """The ML brain's guess (already mapped to handler names) checked against the
    keyword rules -> (intent, entities). Used by the HUD router and console mode,
    so a command means the same thing in both.

    - a precise keyword rule beats the brain ("news about diabetes" keeps its topic)
    - if the brain's intent has no handler, the keyword rule's does
    - if both agree, the rules fill entities the ML extractor missed (for
      messages the rule parse wins: it reads contact and text from the sentence)
    """
    from jarvis.core.intent_classifier import classify_intent
    from jarvis.core.intent_handlers import HANDLER_MAP
    kw_intent, kw_entities = classify_intent(command)
    intent, entities = brain_intent, brain_entities
    if kw_intent != intent and is_precise_rule(kw_intent, command):
        return kw_intent, kw_entities
    if intent not in HANDLER_MAP and intent not in ROUTER_NATIVE:
        return (kw_intent, kw_entities) if kw_intent in HANDLER_MAP else (intent, entities)
    if kw_intent == intent and kw_entities:
        entities = {**entities, **kw_entities} if intent == 'send_message' else {**kw_entities, **entities}
    return intent, entities


def choose_intent(command: str, brain=None):
    """(intent, entities) for a command: the brain when it is confident, checked
    against the keyword rules; the keyword rules alone otherwise."""
    from jarvis.core.intent_classifier import classify_intent
    from jarvis.core.intent_handlers import resolve_brain_intent
    result = None
    if brain is not None:
        try:
            result = brain.process(command, source="text")
        except Exception as e:
            recovered("Dispatch", e)
    if result is not None and getattr(result, "is_valid", False) and result.decision_type != "clarify":
        intent, entities = resolve_brain_intent(result.action, result.entities, command)
        return merge_brain_and_rules(intent, entities, command)
    return classify_intent(command)


def answer(command: str, context: Dict[str, Any], brain=None, skip=OPEN_ENDED) -> Optional[str]:
    """Typo correction, intent (brain + keyword rules), then that feature's handler.
    None if no handler answers (the caller asks the AI)."""
    from jarvis.core.intent_handlers import HANDLER_MAP
    from jarvis.core.typo_fix import fix_typos
    command = fix_typos(command)
    intent, entities = choose_intent(command, brain)
    return run_handler(HANDLER_MAP.get(intent), intent, command, entities, context, skip)


class SpeechRecorder:
    """Wraps a perception layer: speak() is recorded instead of played, so a
    handler that speaks its answer is heard once, through the caller.
    Everything else is passed through."""

    def __init__(self, perception):
        self._perception = perception
        self.lines = []

    def speak(self, text, *args, **kwargs):
        if text and text not in self.lines:
            self.lines.append(str(text))

    def __getattr__(self, name):
        return getattr(self._perception, name)


def answer_by_keywords(command: str, context: Dict[str, Any], skip=OPEN_ENDED) -> Optional[str]:
    """The reply of the handler the keyword classifier picks, or None
    (no handler, an open-ended question, or the handler couldn't answer)."""
    from jarvis.core.intent_classifier import classify_intent
    from jarvis.core.intent_handlers import HANDLER_MAP
    intent, entities = classify_intent(command)
    return run_handler(HANDLER_MAP.get(intent), intent, command, entities, context, skip)


def run_handler(handler, intent, command, entities, context, skip=OPEN_ENDED) -> Optional[str]:
    """Call one handler with speech captured (so it is heard once, by the caller)."""
    if handler is None or intent in skip:
        return None
    recorder = SpeechRecorder(context.get("perception"))
    try:
        result = handler(command, entities, {**context, "perception": recorder})
    except Exception as e:
        recovered("Dispatch", e)
        return None
    if not (result and result.success):
        return None
    reply = result.response or " ".join(recorder.lines)
    _log.info(f"[DISPATCH] {intent} -> {reply[:60]!r}")
    return reply or None
