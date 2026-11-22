# Experimental modules

These modules are complete pieces of JARVIS that the running app does **not** use yet.
They were moved here from `jarvis/core/` (v2.6) so `core/` contains only code that runs,
without throwing the work away.

| Module | What it does | How to wire it in |
|---|---|---|
| `world_monitor.py` | Parallel world news from BBC, Reuters, NYT and Al Jazeera; DuckDuckGo search; page fetch, all as LLM-ready text | Register a `world_news` handler in `core/intent_handlers.py` and add example phrases in `core/intent_definitions.py` |
| `ai_search_handler.py` | Web/news/Reddit search with BM25-style ranking, deduplication, retries and citations | Back the `ai_search` handler with it instead of `KnowledgeLayer` |
| `unified_perception.py` | One sensory layer combining voice, vision (face, gesture, emotion) and text | Feed its events to `BrainAdapter.start_perception_consumer()` |
| `multimodal_emotion.py` | Fuses face (DeepFace), voice (librosa) and text emotion into one mood | Used by `unified_perception.py`; needs `requirements-optional.txt` |

Create long-lived objects through `jarvis.core.services.shared(...)` so they exist once.
