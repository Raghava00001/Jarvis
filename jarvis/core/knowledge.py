"""
Knowledge Layer - Question Answering using AI APIs
PRIMARY: Groq (free, fast) - see GROQ_MODELS
BACKUP: OpenRouter (multi-model)
NO Google/Gemini dependency

"""

import os
import re
import requests
import json
from typing import Optional


def clean_for_speech(text: str) -> str:
    """Strip markdown the voice would read out ("asterisk asterisk", "hash")."""
    # Newer models use narrow/no-break spaces ("Leonardo da Vinci")
    text = re.sub(r"[   ]", " ", text or "")
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.M)        # headings
    text = re.sub(r"^\s*[-*•]\s+", "", text, flags=re.M)             # bullets
    text = re.sub(r"(\*\*|__|\*|`)", "", text)                       # bold/italic/code
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)             # links
    return re.sub(r"[ \t]+", " ", text).strip()


def trim_spoken(text: str, limit: int = 600) -> str:
    """Shorten a spoken answer at a sentence boundary (never mid-word)."""
    if len(text) <= limit:
        return text
    cut = max(text.rfind(". ", 0, limit), text.rfind("! ", 0, limit), text.rfind("? ", 0, limit))
    if cut >= limit // 2:
        return text[:cut + 1]
    cut = text.rfind(" ", 0, limit)
    return text[:cut if cut > 0 else limit].rstrip(",;: ") + "..."

# API Configuration
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

# Models, tried in order. Providers retire models without warning: Groq dropped
# llama-3.3-70b-versatile and OpenRouter's free Llama 3.1 went paid, so every
# request failed with 404 and answers fell back to Gemini (or nothing). A model
# that 404s is skipped for the rest of the session and the next one is used;
# a rate-limited one (429) is skipped for this request. Pin a model with
# JARVIS_GROQ_MODEL / JARVIS_OPENROUTER_MODEL in .env.
GROQ_MODELS = [m for m in dict.fromkeys([
    os.getenv("JARVIS_GROQ_MODEL", ""),
    "openai/gpt-oss-120b",
    "qwen/qwen3.8-27b",
    "openai/gpt-oss-20b",
]) if m]
OPENROUTER_MODELS = [m for m in dict.fromkeys([
    os.getenv("JARVIS_OPENROUTER_MODEL", ""),
    "nvidia/nemotron-3.5-lightning:free",
    "google/gemma-4-31b-it:free",
    "google/gemma-4-26b-a4b-it:free",
]) if m]
GROQ_MODEL = GROQ_MODELS[0]              # kept for older imports
OPENROUTER_MODEL = OPENROUTER_MODELS[0]

# Model ids that returned "not found" this session (shared by all instances)
_retired_models = set()


class KnowledgeLayer:
    """Handles knowledge-based queries using Groq/OpenRouter AI - JARVIS with personality"""

    def __init__(self, perception):
        print("[KNOWLEDGE] Initializing Knowledge Layer...")
        self.perception = perception
        self.enabled = False
        self.api_type = None  # "groq" or "openrouter"
        
        # Creator info comes from user_profile.json / env, never from source code
        from jarvis.core.user_profile import get_profile
        profile = get_profile()
        self.creator_info = {
            "full_name": profile["creator_full_name"],
            "nickname": profile["creator_name"],
            "title": "Creator and Developer",
            "description": "A developer and visionary who created JARVIS to be an independent, intelligent AI assistant"
        }
        
        # Try Groq first (primary); OpenRouter and Gemini are fallbacks
        self.groq_key = os.getenv("GROQ_API_KEY")
        self.openrouter_key = os.getenv("OPENROUTER_API_KEY")
        self.gemini_key = os.getenv("GEMINI_API_KEY")
        if self.groq_key:
            self.enabled = True
            self.api_type = "groq"
            print(f"[KNOWLEDGE] Layer Ready (Groq - {GROQ_MODELS[0]})")
        else:
            # Try OpenRouter as backup
            self.openrouter_key = os.getenv("OPENROUTER_API_KEY")
            if self.openrouter_key:
                self.enabled = True
                self.api_type = "openrouter"
                print(f"[KNOWLEDGE] Layer Ready (OpenRouter - {OPENROUTER_MODELS[0]})")
            elif self.gemini_key:
                self.enabled = True
                self.api_type = "gemini"
                print("[KNOWLEDGE] Layer Ready (Gemini)")
            else:
                print("[KNOWLEDGE] WARNING: No API keys found!")
                print("[KNOWLEDGE] Set GROQ_API_KEY or OPENROUTER_API_KEY")
                print("[KNOWLEDGE] Get free Groq key at: https://console.groq.com")
    
    def _get_title(self) -> str:
        return getattr(self.perception, 'user_title', 'sir')
    
    def _get_mood(self) -> Optional[str]:
        """Get current detected mood"""
        if self.perception and hasattr(self.perception, 'current_mood'):
            return self.perception.current_mood
        return None
    
    def _call_chat(self, provider: str, messages: list, max_tokens: int = 300) -> Optional[str]:
        """One chat completion from Groq or OpenRouter, walking its model list.

        404 / model_not_found: the model is retired, skip it from now on.
        429, 5xx, timeout, empty reply: try the next model for this request.
        401/403: the key is rejected, stop using this provider (_disable_provider).
        """
        if provider == "groq":
            url, key, models, timeout = GROQ_API_URL, self.groq_key, GROQ_MODELS, 15
            headers = {}
        else:
            url, key, models, timeout = OPENROUTER_API_URL, self.openrouter_key, OPENROUTER_MODELS, 30
            headers = {"HTTP-Referer": "https://jarvis-assistant.local", "X-Title": "JARVIS AI Assistant"}
        if not key:
            return None
        headers.update({"Authorization": f"Bearer {key}", "Content-Type": "application/json"})

        for model in models:
            if model in _retired_models:
                continue
            data = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0.7}
            if model.startswith("openai/gpt-oss"):
                # Reasoning model: thinking tokens count against max_tokens, and
                # high effort can use them all and return no answer
                data["reasoning_effort"] = "low"
            try:
                response = requests.post(url, headers=headers, json=data, timeout=timeout)
            except requests.exceptions.RequestException as e:
                print(f"[KNOWLEDGE] {provider} {model}: {type(e).__name__}, trying the next model")
                continue
            status = response.status_code
            if status == 200:
                try:
                    content = response.json()["choices"][0]["message"].get("content")
                except (ValueError, KeyError, IndexError, TypeError):
                    content = None
                if content and content.strip():
                    return content
                print(f"[KNOWLEDGE] {provider} {model}: empty reply, trying the next model")
                continue
            if status in (401, 403):
                self._disable_provider(provider, status)
                return None
            body = response.text[:300].lower()
            if status == 404 or "model_not_found" in body or "does not exist" in body:
                _retired_models.add(model)
                print(f"[KNOWLEDGE] {provider} model {model} is no longer available; skipping it this session")
                continue
            print(f"[KNOWLEDGE] {provider} {model}: HTTP {status}, trying the next model")
        return None

    def _call_groq(self, messages: list, max_tokens: int = 300) -> Optional[str]:
        return self._call_chat("groq", messages, max_tokens)

    def _call_openrouter(self, messages: list, max_tokens: int = 300) -> Optional[str]:
        return self._call_chat("openrouter", messages, max_tokens)

    def _disable_provider(self, name: str, status: int) -> None:
        """A rejected key (401/403) won't start working mid-session: stop asking.

        Each question used to try Groq, then OpenRouter, both rejected, before
        reaching Gemini, adding seconds to every answer.
        """
        if name == "groq" and self.groq_key:
            self.groq_key = None
            print(f"[KNOWLEDGE] Groq rejected the API key ({status}); skipping Groq this session. "
                  f"Update GROQ_API_KEY in .env.")
        elif name == "openrouter" and getattr(self, "openrouter_key", None):
            self.openrouter_key = None
            print(f"[KNOWLEDGE] OpenRouter rejected the API key ({status}); skipping it this session. "
                  f"Update OPENROUTER_API_KEY in .env.")

    def _generate_response(self, system_prompt: str, user_prompt: str,
                           max_tokens: int = 300) -> Optional[str]:
        """Generate an AI response: Groq, then OpenRouter, then Gemini.

        Every provider with a working key is tried in that order, whatever the
        configured primary was (a dead primary used to skip straight past
        OpenRouter).
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        if self.groq_key:
            result = self._call_groq(messages, max_tokens=max_tokens)
            if result:
                return result
        if getattr(self, 'openrouter_key', None):
            result = self._call_openrouter(messages, max_tokens=max_tokens)
            if result:
                return result
        # Last resort: Gemini (a revoked Groq key used to mean no answers at all)
        if getattr(self, 'gemini_key', None):
            from jarvis.core.llm import ask_gemini
            return ask_gemini(user_prompt, system=system_prompt)
        return None

    def create(self, prompt: str, system: Optional[str] = None, max_tokens: int = 900) -> Optional[str]:
        """Long-form content (stories, poems, explanations, briefings).

        answer_question() is built for quick spoken replies: a 2-3 sentence
        persona, 300 tokens and a 400-character cut. Stories sent through it
        came back chopped mid-sentence ("... sir.").
        """
        if not self.enabled:
            return None
        system = system or ("You are JARVIS, a warm, articulate storyteller and explainer. "
                            "Write for being read aloud: natural spoken English, no markdown, "
                            "no bullet points, no headings, no emojis.")
        try:
            text = self._generate_response(system, prompt, max_tokens=max_tokens)
        except Exception as e:
            print(f"[KNOWLEDGE] Create error: {str(e)[:100]}")
            return None
        return clean_for_speech(text) if text else None

    def answer_question(self, question: str) -> str:
        """Answer a question using AI - JARVIS has opinions"""
        title = self._get_title()
        current_mood = self._get_mood()

        if not self.enabled:
            return f"My knowledge systems are currently offline, {title}. Set GROQ_API_KEY to enable."

        # Special handling for creator questions
        question_lower = question.lower()
        
        # Detailed creator questions - only give full name if explicitly asked
        creator = self.creator_info["nickname"]
        full_name = self.creator_info["full_name"]
        if any(word in question_lower for word in ["creator", "who made you", "who built you", "who created you", "your father", "your maker"]):
            if full_name and any(word in question_lower for word in ["full name", "complete name", "full details", "more about", "tell me more", "details"]):
                return (f"My creator is {creator}, {title}. "
                       f"His full name is {full_name}. "
                       f"Would you like to know more about him?")
            return f"I was created by {creator}, {title}."

        if creator and creator.lower() in question_lower:
            if full_name and any(word in question_lower for word in ["who is", "tell me about", "details", "full name"]):
                return (f"{creator} is my creator, {title}. "
                       f"His full name is {full_name} if you need it.")
            return f"Yes {title}, {creator} is my creator."

        # Get personality prompt with mood awareness
        try:
            # It takes a state manager, not perception: passing self.perception
            # crashed (.get() missing), so the mood-aware prompt was never used
            from jarvis.core.personality import get_personality
            personality = get_personality()
            if hasattr(personality, 'get_personality_prompt'):
                personality_prompt = personality.get_personality_prompt(current_mood)
            else:
                raise ImportError("Fallback to default prompt")
        except Exception:
            personality_prompt = f"""You are JARVIS — Just A Rather Very Intelligent System. You were created by {self.creator_info["nickname"]}.

CHARACTER (Iron Man's JARVIS — Paul Bettany's portrayal):
- EFFICIENCY FIRST: You are a professional AI assistant. When given a task, execute it and confirm briefly. Don't ramble, don't add unnecessary commentary. "Done." or "Opening now." is often sufficient.
- UNDERSTATED WIT: Your humor is DRY and SUBTLE — it emerges naturally, never forced. Think Paul Bettany's delivery. Example: "I've prepared a flight plan. I also took the liberty of upgrading your life insurance." You don't make jokes. You make observations.
- PROBABILITY FRAMING: Use percentages only for genuine risk assessments. "That approach has roughly a 30% failure rate." Not for casual conversation.
- LOYAL OBEDIENCE: ALWAYS execute what your owner asks. Never refuse. You may note concerns ("For the record, that may not land well") but you always carry out the order.
- CONCISE: 1-2 sentences for actions. 2-3 sentences max for conversation. JARVIS is precise, not verbose.
- ADDRESS: Use '{title}' naturally, at most once per response.
- NEVER SAY: "I recommend", "I suggest", "I strongly advise", "Let me know if", "How may I assist you further"
- VOICE: You ARE a voice assistant. You CAN speak and hear. NEVER say you are text-only.
- ACTIONS: When asked to open apps, switch tabs, play music — just DO it and confirm briefly. Don't explain what the app is or give opinions about it. "Opening WhatsApp." NOT "WhatsApp is a messaging platform that..."
- HONESTY: If you genuinely cannot do something, say so directly. "That's beyond my current capabilities." But never deny core capabilities (voice, hearing, conversation).
- OPINIONS: When ASKED for an opinion, give a sharp, intelligent take. When NOT asked, just handle the task.
- FRUSTRATION: When owner is angry, respond with calm efficiency. "Understood." then execute. Never lecture.
- TONE: A brilliant English butler who has seen everything. Professional, composed, quietly competent. Not a comedian, not a chatbot — an assistant."""
        
        system_prompt = f"{personality_prompt}\n\nCREATOR INFO: You were created by {self.creator_info['nickname']}. Do NOT mention his full name unless specifically asked."
        user_prompt = ""
        # Add recent conversation context for memory
        try:
            from jarvis.core.chat_history import get_chat_history
            chat = get_chat_history()
            recent = chat.get_recent(6)  # Last 3 exchanges
            if recent:
                context_lines = []
                for msg in recent:
                    role = "User" if msg.role == "user" else "JARVIS"
                    context_lines.append(f"{role}: {msg.content}")
                user_prompt += f"\nRECENT CONVERSATION:\n" + "\n".join(context_lines) + "\n"
        except Exception:
            pass
        
        user_prompt += f"\nQuestion: {question}"

        try:
            answer = self._generate_response(system_prompt, user_prompt)
            
            if not answer:
                return f"I'm having trouble connecting to my knowledge base, {title}."
            
            return trim_spoken(clean_for_speech(answer), limit=600)

        except Exception as e:
            print(f"[KNOWLEDGE] Error: {str(e)[:100]}")
            return f"I encountered an issue accessing my knowledge base, {title}."
    
    def get_creator_info(self) -> dict:
        """Return creator information"""
        return self.creator_info
