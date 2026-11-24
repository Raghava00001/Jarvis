"""
Intent Model - Embedding-Based Classification (v2)
===================================================
Uses sentence-transformers with:
- kNN + threshold for better accuracy
- Ambiguity detection
- Lazy loading for fast startup
- Domain weighting
"""

import logging
_log = logging.getLogger(__name__)

import numpy as np
from pathlib import Path
from typing import Tuple, Optional, Dict, List, Union
import json
import re

from .intent_definitions import INTENT_EXAMPLES, get_category

# Try to import sentence-transformers (lazy loaded)
EMBEDDINGS_AVAILABLE = False
_ST_MODEL = None

def _get_model():
    """Lazy load sentence-transformers model"""
    global EMBEDDINGS_AVAILABLE, _ST_MODEL
    if _ST_MODEL is not None:
        return _ST_MODEL
        
    try:
        from jarvis.core.shared_embeddings import get_shared_embedding_model
        EMBEDDINGS_AVAILABLE = True
        _ST_MODEL = get_shared_embedding_model("all-MiniLM-L6-v2")
        return _ST_MODEL
    except ImportError as e:
        _log.warning(f"[INTENT] sentence-transformers not available: {e}")
        return None


def _model_load_error() -> str:
    try:
        from jarvis.core.shared_embeddings import get_embedding_load_error
        err = get_embedding_load_error()
    except ImportError as e:
        err = f"ImportError: {e}"
    return err or "sentence-transformers model unavailable"


class IntentModelUnavailable(RuntimeError):
    """The embedding model could not be loaded, so ML classification is impossible.

    Raised instead of quietly returning (None, 0.0), so a broken install is
    visible. Callers that want degraded behaviour use classify_keyword().
    """


class IntentClassification:
    """Result of intent classification"""
    def __init__(self, intent: str, confidence: float, 
                 is_ambiguous: bool = False, alternatives: List[Tuple[str, float]] = None):
        self.intent = intent
        self.confidence = confidence
        self.is_ambiguous = is_ambiguous
        self.alternatives = alternatives or []
        
    def __repr__(self):
        return f"Intent({self.intent}, {self.confidence:.2f}, ambig={self.is_ambiguous})"


class IntentModel:
    """
    Embedding-based intent classifier with:
    - kNN scoring (not just centroid)
    - Ambiguity detection
    - Confidence thresholds
    - Domain weighting
    - Lazy loading
    """
    
    # Thresholds
    CONFIDENCE_THRESHOLD = 0.55      # Below this = unknown
    AMBIGUITY_MARGIN = 0.08          # If top two within this = ambiguous
    HIGH_CONFIDENCE = 0.75           # Above this = very confident
    
    # Domain weights (some intents are more common)
    DOMAIN_WEIGHTS = {
        "open_app": 1.15,       # Boost app opening
        "play_music": 1.10,
        "search_web": 1.05,
        "greeting": 0.95,      # Slightly lower (less action-oriented)
        "goodbye": 0.95,
    }
    
    def __init__(self, model_name: str = "all-MiniLM-L6-v2", lazy: bool = True):
        _log.info("[INTENT] Initializing Intent Model...")
        
        self.model_name = model_name
        self.model = None
        self.intent_embeddings: Dict[str, np.ndarray] = {}
        self.example_embeddings: Dict[str, List[np.ndarray]] = {}  # For kNN
        # v3: plain numeric arrays (loaded with allow_pickle=False) plus a
        # fingerprint of the model + examples, so edited examples rebuild the cache.
        self.cache_path = Path(__file__).parent.parent / "data" / "intent_embeddings_v3.npz"
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        
        self._loaded = False
        
        if not lazy:
            self._ensure_loaded()
            
        _log.info("[INTENT] Intent Model Ready (lazy mode)")
        
    def _ensure_loaded(self):
        """Ensure model and embeddings are loaded"""
        if self._loaded:
            return True
            
        self.model = _get_model()
        
        if self.model:
            if not self._load_cache():
                self._compute_embeddings()
            self._loaded = True
            return True
            
        return False
        
    def _compute_embeddings(self):
        """Compute embeddings for all intents"""
        _log.info("[INTENT] Computing intent embeddings...")
        
        for intent, examples in INTENT_EXAMPLES.items():
            # Store all example embeddings for kNN
            embeddings = self.model.encode(examples)
            self.example_embeddings[intent] = list(embeddings)
            
            # Also store centroid for fast initial screening
            self.intent_embeddings[intent] = np.mean(embeddings, axis=0)
            
        self._save_cache()
        _log.info(f"[INTENT] Computed {len(self.intent_embeddings)} intent embeddings")
        
    def _cache_fingerprint(self) -> str:
        """Hash of the model name and every example, so any edit invalidates the cache."""
        import hashlib
        payload = json.dumps({"model": self.model_name, "examples": INTENT_EXAMPLES},
                             sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _load_cache(self) -> bool:
        """Load cached embeddings (no pickle; rejected if stale)."""
        if not self.cache_path.exists():
            return False
        try:
            with np.load(str(self.cache_path), allow_pickle=False) as data:
                if str(data["__fingerprint__"]) != self._cache_fingerprint():
                    _log.info("[INTENT] Embedding cache is stale; recomputing")
                    return False
                centroids, examples = {}, {}
                for key in data.files:
                    if key.startswith("c::"):
                        centroids[key[3:]] = data[key]
                    elif key.startswith("e::"):
                        examples[key[3:]] = list(data[key])
        except Exception as e:
            _log.info(f"[INTENT] Embedding cache unreadable ({type(e).__name__}); recomputing")
            return False
        if set(centroids) != set(INTENT_EXAMPLES):
            return False
        self.intent_embeddings, self.example_embeddings = centroids, examples
        _log.info("[INTENT] Loaded cached embeddings")
        return True

    def _save_cache(self):
        """Save embeddings as plain float arrays (safe to load without pickle)."""
        try:
            arrays = {"__fingerprint__": np.array(self._cache_fingerprint())}
            for intent, centroid in self.intent_embeddings.items():
                arrays[f"c::{intent}"] = np.asarray(centroid, dtype=np.float32)
                arrays[f"e::{intent}"] = np.asarray(self.example_embeddings[intent], dtype=np.float32)
            np.savez_compressed(str(self.cache_path), **arrays)
        except Exception as e:
            _log.warning(f"[INTENT] Cache save error: {e}")
            
    def embed(self, text: str) -> Optional[np.ndarray]:
        """Get embedding for text"""
        self._ensure_loaded()
        if self.model:
            return self.model.encode(text)
        return None
        
    def classify(self, text: str) -> Tuple[Optional[str], float]:
        """
        Classify intent from text.
        Returns (intent, confidence) or (None, confidence) if below threshold.
        For ambiguous cases, returns ("AMBIGUOUS", confidence).
        """
        if not self._ensure_loaded():
            raise IntentModelUnavailable(_model_load_error())

        # Get all scores
        scores = self._score_all_intents(text)
        
        if not scores:
            return None, 0.0
            
        # Sort by score
        scores.sort(key=lambda x: -x[1])
        
        top_intent, top_score = scores[0]
        second_intent, second_score = scores[1] if len(scores) > 1 else (None, 0)
        
        # Apply domain weight
        top_score_weighted = top_score * self.DOMAIN_WEIGHTS.get(top_intent, 1.0)
        
        # Check thresholds
        if top_score < self.CONFIDENCE_THRESHOLD:
            kw_intent, kw_conf = self._classify_keyword(text)
            if kw_intent:
                return kw_intent, kw_conf
            return None, top_score
            
        # Check for ambiguity
        if len(scores) > 1:
            margin = top_score - second_score
            if margin < self.AMBIGUITY_MARGIN and second_score > self.CONFIDENCE_THRESHOLD:
                # Ambiguous - top two are too close
                return "AMBIGUOUS", top_score
                
        return top_intent, top_score_weighted
        
    def classify_detailed(self, text: str) -> IntentClassification:
        """Get detailed classification with alternatives"""
        if not self._ensure_loaded():
            raise IntentModelUnavailable(_model_load_error())
            
        scores = self._score_all_intents(text)
        scores.sort(key=lambda x: -x[1])
        
        if not scores:
            return IntentClassification(None, 0.0)
            
        top_intent, top_score = scores[0]
        
        # Check for ambiguity
        is_ambiguous = False
        if len(scores) > 1:
            margin = top_score - scores[1][1]
            is_ambiguous = margin < self.AMBIGUITY_MARGIN and scores[1][1] > self.CONFIDENCE_THRESHOLD
            
        # Get alternatives
        alternatives = scores[1:4]  # Top 3 alternatives
        
        if top_score < self.CONFIDENCE_THRESHOLD:
            kw_intent, kw_conf = self._classify_keyword(text)
            if kw_intent:
                return IntentClassification(kw_intent, kw_conf, False, alternatives)
            return IntentClassification(None, top_score, is_ambiguous, alternatives)
            
        return IntentClassification(top_intent, top_score, is_ambiguous, alternatives)
        
    def _score_all_intents(self, text: str) -> List[Tuple[str, float]]:
        """Score text against all intents using kNN approach"""
        query_vec = self.model.encode(text)
        
        scores = []
        for intent, examples in self.example_embeddings.items():
            # kNN: find similarity to each example
            example_scores = []
            for ex_emb in examples:
                score = np.dot(query_vec, ex_emb) / (
                    np.linalg.norm(query_vec) * np.linalg.norm(ex_emb)
                )
                example_scores.append(score)
                
            # Take mean of top-k examples (k=3)
            example_scores.sort(reverse=True)
            k = min(3, len(example_scores))
            knn_score = np.mean(example_scores[:k])
            
            scores.append((intent, float(knn_score)))
            
        return scores
        
    def classify_keyword(self, text: str) -> Tuple[Optional[str], float]:
        """Keyword-only classification (works without the embedding model)."""
        return self._classify_keyword(text)

    # Keyword fallback, used when the embedding score is below threshold.
    # Patterns are whole-word regexes. It used to match substrings anywhere, so
    # "sometimes" was a time request, "brunch" ran an app, "translate hello to
    # spanish" was a greeting and "remind me" set an alarm. Greetings/goodbyes
    # now only count at the start of the sentence.
    _KEYWORD_RULES = [
        ("set_timer", r"\b(?:timer|count\s*down)\b"),
        ("set_reminder", r"\bremind\s+me\b"),
        ("set_alarm", r"\b(?:alarm|wake\s+me)\b"),
        ("volume_up", r"\b(?:volume\s+up|louder|(?:increase|turn\s+up|raise)\s+(?:the\s+)?volume|turn\s+(?:the\s+)?volume\s+up)\b"),
        ("volume_down", r"\b(?:volume\s+down|quieter|(?:decrease|turn\s+down|lower)\s+(?:the\s+)?volume|turn\s+(?:the\s+)?volume\s+down)\b"),
        ("pause_music", r"\b(?:pause|stop\s+(?:the\s+)?(?:music|song))\b"),
        ("play_music", r"\b(?:play\s+(?:some\s+)?(?:music|songs?)|start\s+spotify|listen\s+to)\b"),
        ("weather", r"\b(?:weather|forecast|temperature)\b"),
        ("news", r"\b(?:news|headlines)\b"),
        ("get_time", r"\bwhat(?:'?s|\s+is)?\s+(?:the\s+)?time\b|\btime\s+is\s+it\b|\bcurrent\s+time\b"),
        ("get_date", r"\bwhat(?:'?s|\s+is)?\s+(?:the\s+|today'?s\s+)?date\b|\bwhat\s+day\s+is\b"),
        ("open_app", r"^(?:please\s+)?(?:open|launch|start|run)\s+\w"),
        ("close_app", r"^(?:please\s+)?(?:close|quit|terminate)\s+\w"),
        ("search_web", r"^(?:please\s+)?(?:search|google|look\s+up|find)\b|\bwhat\s+is\b"),
        ("greeting", r"^(?:hello|hi|hey|good\s+(?:morning|afternoon|evening))\b"),
        ("goodbye", r"^(?:bye|goodbye|good\s+night|see\s+you)\b"),
    ]

    def _classify_keyword(self, text: str) -> Tuple[Optional[str], float]:
        """Fallback: whole-word keyword classification."""
        text_lower = text.lower().strip()
        for intent, pattern in self._KEYWORD_RULES:
            if re.search(pattern, text_lower):
                return intent, 0.75
        return None, 0.0

    def get_top_intents(self, text: str, top_k: int = 3) -> List[Tuple[str, float]]:
        """Get top K most likely intents with scores"""
        if not self._ensure_loaded():
            raise IntentModelUnavailable(_model_load_error())
            
        scores = self._score_all_intents(text)
        scores.sort(key=lambda x: -x[1])
        return scores[:top_k]
        
    def add_example(self, intent: str, example: str):
        """Add a new example to an intent (runtime learning)"""
        if not self._ensure_loaded():
            return
            
        if intent not in INTENT_EXAMPLES:
            INTENT_EXAMPLES[intent] = []
            self.example_embeddings[intent] = []
            
        INTENT_EXAMPLES[intent].append(example)
        
        # Add to example embeddings
        new_emb = self.model.encode(example)
        self.example_embeddings[intent].append(new_emb)
        
        # Recompute centroid
        self.intent_embeddings[intent] = np.mean(
            self.example_embeddings[intent], axis=0
        )
        
    def get_disambiguation_options(self, text: str) -> List[str]:
        """Get human-readable options for ambiguous input"""
        result = self.classify_detailed(text)
        
        if not result.is_ambiguous:
            return []
            
        options = []
        intent_descriptions = {
            "play_music": "Play music",
            "open_app": "Open an app",
            "search_web": "Search the web",
            "set_alarm": "Set an alarm",
            # Add more as needed
        }
        
        if result.intent:
            desc = intent_descriptions.get(result.intent, result.intent)
            options.append(f"1. {desc}")
            
        for i, (alt_intent, _) in enumerate(result.alternatives[:2], 2):
            desc = intent_descriptions.get(alt_intent, alt_intent)
            options.append(f"{i}. {desc}")
            
        return options


# Singleton (lazy loaded)
_model = None

def get_intent_model() -> IntentModel:
    global _model
    if _model is None:
        _model = IntentModel(lazy=True)
    return _model
