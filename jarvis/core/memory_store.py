"""
Facts the user asked JARVIS to remember ("remember that my favourite colour is
blue"), and finding them again ("what is my favourite colour").

The remember handler used to call knowledge.remember(), which doesn't exist, so
nothing was ever saved. Facts are kept in jarvis_data/memory.json (the same
file and format the old fallback used), and recall matches by shared keywords,
so the question doesn't have to repeat the fact word for word.
"""

import json
import logging
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import List, Optional

_log = logging.getLogger(__name__)

MEMORY_FILE = Path(__file__).resolve().parents[2] / "jarvis_data" / "memory.json"

_STOP = {"what", "whats", "what's", "is", "are", "was", "my", "the", "a", "an", "do", "you", "remember",
         "that", "i", "me", "about", "tell", "did", "know", "of", "to", "it", "your", "please", "jarvis",
         "recall", "which", "who", "where", "when", "how", "and", "for", "in", "on", "s"}

_lock = threading.Lock()


def _words(text: str) -> set:
    out = set()
    for w in re.findall(r"[a-z0-9']+", (text or "").lower()):
        w = w.strip("'")
        if w and w not in _STOP:
            out.add(w[:-1] if len(w) > 3 and w.endswith("s") else w)   # crude singular
    return out


class MemoryStore:
    def __init__(self, path: Path = MEMORY_FILE):
        self.path = Path(path)

    def _load(self) -> List[dict]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return [m for m in data if isinstance(m, dict) and m.get("fact")]
        except FileNotFoundError:
            return []
        except (ValueError, OSError) as e:
            _log.warning(f"[MEMORY] Couldn't read {self.path.name}: {e}")
            return []

    def remember(self, fact: str) -> None:
        fact = (fact or "").strip().rstrip(".")
        if not fact:
            raise ValueError("empty fact")
        with _lock:
            facts = [m for m in self._load() if m["fact"].lower() != fact.lower()]
            facts.append({"fact": fact, "timestamp": datetime.now().isoformat(timespec="seconds")})
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(facts, indent=2), encoding="utf-8")
            tmp.replace(self.path)

    def recall(self, query: str, limit: int = 3) -> List[str]:
        """Facts sharing keywords with the query, best match (then newest) first."""
        want = _words(query)
        scored = []
        for i, m in enumerate(self._load()):
            have = _words(m["fact"])
            score = len(want & have)
            if score and (score >= 2 or score == len(want)):
                scored.append((score, i, m["fact"]))
        scored.sort(reverse=True)
        return [f for _, _, f in scored[:limit]]

    def all_facts(self) -> List[str]:
        return [m["fact"] for m in self._load()]


def fact_from(cmd: str) -> Optional[str]:
    """'remember that my favourite colour is blue' -> 'my favourite colour is blue'."""
    m = re.search(r"\b(?:remember|note|memorize|memorise|don'?t forget)\s+(?:that\s+)?(.+)", cmd or "", re.I)
    return m.group(1).strip().rstrip(".") if m else None
