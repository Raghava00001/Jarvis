"""
Tests for the v2.2 efficiency/robustness upgrades:
  * BrainAdapter intent names are translated to HANDLER_MAP names
    (before: 11/29 everyday commands reached a handler; after: 27/29)
  * intent embedding cache: no pickle, invalidated when examples change
  * TTS never goes silent: Edge TTS circuit breaker + offline fallback
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ─── Intent name translation ─────────────────────────────────────────────

class TestBrainIntentAliases:
    def test_every_alias_targets_a_real_handler(self):
        from jarvis.core.intent_handlers import BRAIN_INTENT_ALIASES, HANDLER_MAP
        missing = {k: v[0] for k, v in BRAIN_INTENT_ALIASES.items() if v[0] not in HANDLER_MAP}
        assert missing == {}

    def test_aliases_only_rename_known_classifier_intents(self):
        from jarvis.core.intent_definitions import INTENT_EXAMPLES
        from jarvis.core.intent_handlers import BRAIN_INTENT_ALIASES
        assert set(BRAIN_INTENT_ALIASES) <= set(INTENT_EXAMPLES)

    def test_every_classifier_intent_is_routable_or_deliberately_excluded(self):
        from jarvis.core.intent_definitions import INTENT_EXAMPLES
        from jarvis.core.intent_handlers import BRAIN_INTENT_ALIASES, HANDLER_MAP
        deliberate = {"shutdown", "restart", "close_app", "lock_screen",
                      "cancel_alarm", "play_youtube", "list_alarms"}
        unroutable = {i for i in INTENT_EXAMPLES
                      if i not in HANDLER_MAP and i not in BRAIN_INTENT_ALIASES and i not in deliberate}
        assert unroutable == set()

    @pytest.mark.parametrize("intent,handler,action", [
        ("volume_up", "volume", "up"), ("volume_down", "volume", "down"),
        ("mute", "volume", "mute"), ("brightness_up", "brightness", "up"),
        ("brightness_down", "brightness", "down"),
    ])
    def test_direction_is_filled_in(self, intent, handler, action):
        """Without this, 'mute' would reach the volume handler with no action and turn it UP."""
        from jarvis.core.intent_handlers import resolve_brain_intent
        name, entities = resolve_brain_intent(intent, {})
        assert (name, entities["action"]) == (handler, action)

    def test_extractor_entities_win_over_defaults(self):
        from jarvis.core.intent_handlers import resolve_brain_intent
        _, entities = resolve_brain_intent("volume_up", {"action": "set", "level": 40})
        assert entities == {"action": "set", "level": 40}

    def test_power_intents_are_never_aliased(self):
        from jarvis.core.intent_handlers import BRAIN_INTENT_ALIASES
        assert "shutdown" not in BRAIN_INTENT_ALIASES
        assert "restart" not in BRAIN_INTENT_ALIASES


# ─── Embedding cache ──────────────────────────────────────────────────────

class TestEmbeddingCache:
    def _model(self, tmp_path, monkeypatch, examples):
        import jarvis.core.intent_model as im
        monkeypatch.setattr(im, "INTENT_EXAMPLES", examples)
        m = im.IntentModel(lazy=True)
        m.cache_path = tmp_path / "cache.npz"
        return m

    def test_round_trip_without_pickle(self, tmp_path, monkeypatch):
        ex = {"greet": ["hi", "hello"], "bye": ["bye"]}
        m = self._model(tmp_path, monkeypatch, ex)
        m.intent_embeddings = {"greet": np.ones(4), "bye": np.zeros(4)}
        m.example_embeddings = {"greet": [np.ones(4), np.ones(4)], "bye": [np.zeros(4)]}
        m._save_cache()
        with np.load(m.cache_path, allow_pickle=False) as data:  # must not need pickle
            assert "__fingerprint__" in data.files
        fresh = self._model(tmp_path, monkeypatch, ex)
        assert fresh._load_cache() is True
        assert set(fresh.intent_embeddings) == {"greet", "bye"}
        assert len(fresh.example_embeddings["greet"]) == 2

    def test_editing_examples_invalidates_cache(self, tmp_path, monkeypatch):
        m = self._model(tmp_path, monkeypatch, {"greet": ["hi"]})
        m.intent_embeddings = {"greet": np.ones(4)}
        m.example_embeddings = {"greet": [np.ones(4)]}
        m._save_cache()
        edited = self._model(tmp_path, monkeypatch, {"greet": ["hi", "hey there"]})
        assert edited._load_cache() is False

    def test_pickled_cache_is_rejected(self, tmp_path, monkeypatch):
        m = self._model(tmp_path, monkeypatch, {"greet": ["hi"]})
        np.savez(m.cache_path, centroids=np.array({"greet": np.ones(4)}, dtype=object))
        assert m._load_cache() is False

    def test_committed_cache_matches_current_examples(self):
        """The shipped cache must be fresh, or every first boot recomputes it."""
        import jarvis.core.intent_model as im
        m = im.IntentModel(lazy=True)
        assert m.cache_path.name == "intent_embeddings_v3.npz"
        assert m._load_cache() is True


# ─── TTS fallback ─────────────────────────────────────────────────────────

class TestTTSFallback:
    def _engine(self):
        from jarvis.core.voice_engine import VoiceEngine
        eng = object.__new__(VoiceEngine)
        eng.edge_tts = MagicMock()
        eng.use_edge_tts = True
        eng.is_speaking = False
        eng.stop_flag = False
        eng._edge_failures = 0
        return eng

    def test_circuit_breaker_disables_failing_edge_tts(self):
        eng = self._engine()
        eng.edge_tts.speak_blocking.return_value = False
        for _ in range(eng.EDGE_FAILURE_LIMIT):
            assert eng.speak("hi") is False
        assert eng.use_edge_tts is False
        eng.speak("hi")
        assert eng.edge_tts.speak_blocking.call_count == eng.EDGE_FAILURE_LIMIT

    def test_success_resets_failure_count(self):
        eng = self._engine()
        eng.edge_tts.speak_blocking.side_effect = [False, False, True, False, False]
        for _ in range(5):
            eng.speak("hi")
        assert eng.use_edge_tts is True

    def test_falls_back_to_pyttsx3(self):
        eng = self._engine()
        eng.edge_tts.speak_blocking.return_value = False
        fake = MagicMock()
        with patch.dict(sys.modules, {"pyttsx3": MagicMock(init=MagicMock(return_value=fake))}):
            assert eng.speak_with_fallback("hello") == "pyttsx3"
        fake.say.assert_called_once_with("hello")

    def test_hud_uses_fallback_path(self):
        src = (ROOT / "jarvis/gui/hud_types.py").read_text(encoding="utf-8")
        assert "target=engine.speak_with_fallback" in src


# ─── Boot briefing ────────────────────────────────────────────────────────

def test_boot_briefing_names_tasks(tmp_path):
    """Tasks are saved under "task"; the briefing used to read "description"
    and greeted the user with 'You have 11 pending tasks: Unknown, Unknown …'."""
    import json
    from jarvis.core.startup_orchestrator import StartupOrchestrator
    (tmp_path / "tasks.json").write_text(json.dumps({"tasks": [
        {"task": "buy milk", "completed": False},
        {"task": "call mom", "completed": False},
        {"task": "done already", "completed": True},
        {"description": "legacy format", "completed": False},
        {"task": "fourth", "completed": False},
    ]}), encoding="utf-8")
    orch = object.__new__(StartupOrchestrator)
    orch.data_dir = tmp_path
    text = orch._generate_task_summary()
    assert "Unknown" not in text
    assert "buy milk, call mom, legacy format and 1 more" in text
