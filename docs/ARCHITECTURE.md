# JARVIS Architecture

## High-Level System Diagram

```mermaid
flowchart TD
    subgraph Input["🎤 Input Layer"]
        USER[User Voice/Text]
        PERCEPTION[Perception Module]
    end

    subgraph Understanding["🧠 Understanding Layer"]
        CONTEXT[Context Memory]
        EMOTION[Emotion Router]
        INTENT[Intent Model<br/>kNN + Centroid]
        ENTITY[Entity Extractor<br/>spaCy + Regex]
    end

    subgraph State["📊 State Layer"]
        STATE[State Manager<br/>Single Source of Truth]
        DECISION[Decision Engine<br/>Reasoning Layer]
    end

    subgraph Action["⚡ Action Layer"]
        ROUTER[Intent Router]
        PERSONALITY[JARVIS Personality<br/>Iron Man Style]
        HANDLERS[Handlers]
    end

    subgraph Memory["💾 Memory Layer"]
        WORKING[Working Memory<br/>Auto-Summarization]
        LONGTERM[Long-Term Memory<br/>Semantic Embeddings]
        PROACTIVE[Proactive Assistant<br/>Pattern Learning]
    end

    subgraph Output["🔊 Output Layer"]
        TTS[Text-to-Speech]
        RESPONSE[Response]
    end

    USER --> PERCEPTION
    PERCEPTION --> CONTEXT
    CONTEXT --> |Pronoun Resolution| EMOTION
    EMOTION --> |Mood Update| INTENT
    INTENT --> |Classification| ENTITY
    ENTITY --> STATE
    STATE --> DECISION
    DECISION --> |PROCEED/WARN/CLARIFY| ROUTER
    ROUTER --> HANDLERS
    HANDLERS --> PERSONALITY
    PERSONALITY --> TTS
    TTS --> RESPONSE

    STATE --> WORKING
    STATE --> LONGTERM
    ROUTER --> PROACTIVE
```

## Pipeline Flow

```mermaid
sequenceDiagram
    participant U as User
    participant P as Perception
    participant CM as Context Memory
    participant ER as Emotion Router
    participant IM as Intent Model
    participant EE as Entity Extractor
    participant SM as State Manager
    participant DE as Decision Engine
    participant IR as Intent Router
    participant H as Handler
    participant PY as Personality
    participant M as Memory

    U->>P: "play blinding lights on spotify"
    P->>CM: resolve_pronoun(text)
    CM-->>ER: resolved text
    ER->>SM: set user_mood
    ER->>IM: classify(text)
    IM-->>IM: kNN + centroid scoring
    IM-->>ER: (play_music, 0.95)
    ER->>EE: extract(text, intent)
    EE-->>SM: {song, app}
    SM->>DE: decide(intent, entities)
    DE-->>IR: PROCEED
    IR->>H: handle_play(entities)
    H-->>PY: "Playing Blinding Lights"
    PY-->>U: styled response + challenge
    IR->>M: add_exchange()
```

## Module Responsibilities

| Module | Responsibility |
|--------|----------------|
| **Perception** | Voice recognition, TTS output |
| **Context Memory** | Pronoun resolution, working memory, summarization |
| **Emotion Router** | Detect user mood, update state |
| **Intent Model** | Classify intent (kNN + centroid + rejection) |
| **Entity Extractor** | Extract entities (spaCy + regex hybrid) |
| **State Manager** | Single source of truth for all state |
| **Decision Engine** | Reason about HOW to handle (warn/clarify/refuse) |
| **Intent Router** | Dispatch to correct handler |
| **Personality** | Iron Man style, challenges, wit |
| **Handlers** | Music, Alarm, Apps, Search, etc. |
| **Proactive Assistant** | Pattern learning, suggestions |

## Decision Engine Flow

```mermaid
flowchart LR
    subgraph Decisions
        A[Intent + Entities] --> B{Check Safety}
        B --> |Shutdown / restart| C[CONFIRM within 30 s]
        B --> |Safe| D{Check Context}
        D --> |Late Night| E[WARN_THEN_PROCEED]
        D --> |Normal| F{Low-risk intent?}
        F --> |greeting, time, weather, help…| I[PROCEED]
        F --> |side effects| G{Confidence}
        G --> |< 0.65 and keyword layer disagrees| H[CLARIFY: remembered, 'yes' runs it]
        G --> |>= 0.65 or keyword layer agrees| I
    end
```

## How the design is implemented (v2.6)

### One request, end to end

```
HUD text / voice
   │
   ├─ Gemini Live on? ── wake word gate (gemini_live_engine) ── Gemini tools ─┐
   │                                                                          │
   ▼                                                                          │
command_rules.py   wake word, exit JARVIS, PC power → always confirmed        │
fast_path.py       instant rules: open/close app, volume, screenshot, time    │
process_command    pending confirmations, keyword overrides                   │
   ▼                                                                          │
Understanding      BrainAdapter: IntentModel (embeddings + whole-word         │
                   keyword fallback) → EntityExtractor → DecisionEngine       │
                   + keyword classifier: corroborates, fills missing entities │
   ▼                                                                          │
Action             HANDLER_MAP in intent_handlers.py  ◄───────────────────────┘
   ▼
Output             HUDPerception → HUD chat + TTS (Edge TTS, offline fallback)
```

### Service registry: one instance of every subsystem

`jarvis/core/services.py` is the composition root. Long-lived subsystems (perception,
alarms, reminders, hotkeys, chat history, news, weather …) are created with
`shared(Class, factory)` and exist **exactly once**, whether the WebSocket server,
`JARVISUltimate`, a handler or a Gemini tool asks for them.

Before v2.6 the server and `JARVISUltimate` each built their own copy of ~25
subsystems, and 37 modules were loaded twice (as `core.X` and `jarvis.core.X`). One
running JARVIS had two state managers, two reminder checkers on the same database
and two hotkey registrations.

### Rules the tests enforce

| Invariant | Test |
|---|---|
| Every subsystem exists once; server and core share them | `tests/test_architecture.py` |
| No module is loaded under two names; always import `jarvis.*` | `tests/test_architecture.py` |
| No function re-imports a module-level name (UnboundLocalError trap) | `tests/test_architecture.py` |
| No undefined names (pyflakes) | `tests/test_architecture.py` |
| No heavy ML library is imported on the startup path | `tests/test_fast_boot.py` |
| Everyday commands reach the right handler (real pipeline, side effects stubbed) | `tests/test_routing_corpus.py` |
| Security rules (WebSocket origin + token, shell injection, power confirmation) | `tests/test_security_regressions.py` |

### Adding a feature

1. Write the handler in `jarvis/core/intent_handlers.py` and register it in `HANDLER_MAP`.
2. Add example phrases under the **same name** in `jarvis/core/intent_definitions.py`.
   The embedding cache rebuilds itself when examples change.
3. If it needs a long-lived object, get it with `shared(MyClass, lambda: MyClass(...))`.
4. If Gemini Live should use it, call the handler from its tool in `gemini_live_engine.py`.
5. Add a line to `tests/test_routing_corpus.py`.

## File Structure

```
jarvis/
├── __init__.py               # one module identity (maps legacy core.X imports)
├── core/
│   ├── services.py           # service registry (composition root)
│   ├── brain_adapter.py      # understanding pipeline
│   ├── intent_model.py       # embeddings kNN + centroid, keyword fallback
│   ├── intent_definitions.py # example phrases per intent (= handler names)
│   ├── intent_classifier.py  # rule-based classifier + entities
│   ├── entity_extractor.py   # ML entities
│   ├── decision_engine.py    # proceed / warn / clarify / refuse
│   ├── intent_handlers.py    # HANDLER_MAP: one implementation per feature
│   ├── gemini_live_engine.py # full-duplex voice, wake-word gate, tools
│   ├── jarvis_ultimate.py    # core layers + subsystems (also CLI entry)
│   ├── state_manager.py      # single source of truth
│   ├── personality.py, context_memory.py, proactive_assistant.py, …
│   └── safe_exec.py, rss.py, user_profile.py
├── gui/
│   ├── websocket_server.py   # transport + orchestration
│   ├── command_rules.py      # wake / exit / power rules, WebSocket access
│   ├── fast_path.py          # instant-command rules
│   ├── web_hud/index.html    # the HUD
│   └── desktop_gui.py        # launcher window
├── experimental/             # built but not wired in (see its README)
└── data/                     # intent cache, small JSON state
```
