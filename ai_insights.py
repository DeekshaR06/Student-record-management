"""AI course insights using a free AI API.

Default provider: Google Gemini (uses Google Search grounding when the free tier allows it,
otherwise falls back to the model's own knowledge). Alternative: Groq (AI_PROVIDER=groq).
Only the course NAME is ever sent to the provider - never student data.
Uses only the Python standard library, so there is nothing extra to install.
"""
import json
import logging
import os
import re
import urllib.error
import urllib.request

log = logging.getLogger("ai_insights")


def _timeout():
    return float(os.getenv("AI_TIMEOUT", "40"))

GEMINI_BASE = os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta")
GROQ_BASE = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
HEADINGS = ["What it covers", "Key topics", "Skills and careers", "Relevance today", "Next courses to take"]


class AIError(Exception):
    """Carries a message that is safe to show to users (never contains the API key)."""

    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def clean_name(name):
    cleaned = re.sub(r"[^\w\s\-+.&,()/#]", "", name or "")
    return re.sub(r"\s+", " ", cleaned).strip()[:100]  # one line only


def build_prompt(course_name):
    return (
        f'Write a short, factual overview of the university course "{clean_name(course_name)}" '
        "for a student information system.\n"
        "Use exactly these five headings, each on its own line, followed by one to three short "
        "sentences or a few short comma-separated items:\n"
        + "\n".join(f"{h}:" for h in HEADINGS)
        + "\nKeep the whole answer under 200 words. Use plain text only: no markdown symbols, no "
        "bullet characters, no bold. Be accurate; if you are unsure about something, say so "
        "briefly. Mention recent developments only when you are confident about them."
    )


def _post(url, headers, payload, timeout):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "student-record-app/1.0", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = json.loads(e.read().decode("utf-8")).get("error", {}).get("message", "")
        except Exception:
            pass
        log.warning("AI API HTTP %s: %s", e.code, detail[:300])
        if e.code == 429:
            raise AIError("The free AI quota is used up for now. Please try again later.", 429)
        if e.code == 404:
            raise AIError("The AI model is not available any more. The admin needs to update GEMINI_MODEL in the server settings.", 404)
        if e.code in (401, 403) or "api key" in detail.lower():
            raise AIError("The AI service rejected the API key. Check the key in the server settings.", e.code)
        raise AIError(f"The AI service returned an error ({e.code}).", e.code)
    except TimeoutError:
        raise AIError("The AI service took too long to answer. Please try again.")
    except (urllib.error.URLError, OSError) as e:
        if isinstance(getattr(e, "reason", None), TimeoutError):
            raise AIError("The AI service took too long to answer. Please try again.")
        log.warning("AI API connection problem: %s", e)
        raise AIError("Could not reach the AI service. Please try again.")
    except ValueError:
        raise AIError("The AI service sent an unreadable reply.")


def _gemini(prompt, grounded):
    key = os.getenv("GEMINI_API_KEY", "")
    if not key:
        raise AIError("AI is not set up yet: the server has no API key.")
    model = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
    payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.3}}
    if grounded:
        payload["tools"] = [{"google_search": {}}]
    data = _post(f"{GEMINI_BASE}/models/{model}:generateContent", {"x-goog-api-key": key}, payload, _timeout())
    cand = (data.get("candidates") or [{}])[0]
    text = "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts", [])).strip()
    if not text:
        raise AIError("The AI returned an empty answer. Please try again.")
    chunks = (cand.get("groundingMetadata") or {}).get("groundingChunks") or []
    sources = []
    for c in chunks:
        web = c.get("web") or {}
        url = str(web.get("uri") or "")
        if url.startswith(("https://", "http://")):
            sources.append({"title": str(web.get("title") or "source")[:80], "url": url})
    return text, sources[:6], model


def _groq(prompt):
    key = os.getenv("GROQ_API_KEY", "")
    if not key:
        raise AIError("AI is not set up yet: the server has no API key.")
    model = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
    data = _post(f"{GROQ_BASE}/chat/completions", {"Authorization": f"Bearer {key}"},
                 {"model": model, "temperature": 0.3, "messages": [{"role": "user", "content": prompt}]}, _timeout())
    try:
        text = data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, AttributeError):
        raise AIError("The AI service sent an unreadable reply.")
    if not text:
        raise AIError("The AI returned an empty answer. Please try again.")
    return text, [], model


def generate_insight(course_name):
    """Returns {"text", "sources", "model", "grounded"}; raises AIError with a user-safe message."""
    provider = os.getenv("AI_PROVIDER", "gemini").lower()
    prompt = build_prompt(course_name)
    if provider == "groq":
        text, sources, model = _groq(prompt)
    elif provider == "gemini":
        try:
            text, sources, model = _gemini(prompt, True)
        except AIError as first:
            log.info("Grounded request failed (%s); retrying without web search", first)
            text, sources, model = _gemini(prompt, False)
    else:
        raise AIError("AI_PROVIDER must be 'gemini' or 'groq'.")
    return {"text": text, "sources": sources, "model": model, "grounded": bool(sources)}


def parse_sections(text):
    """Split the answer into (heading, body) blocks for display; tolerant of stray markdown."""
    sections, current = [], None
    for line in (text or "").splitlines():
        clean = line.strip().lstrip("*#- ").replace("**", "").strip()
        if not clean:
            continue
        head = next((h for h in HEADINGS if clean.lower().startswith(h.lower())), None)
        if head:
            current = {"title": head, "body": clean[len(head):].lstrip(" :-").strip()}
            sections.append(current)
        elif current is not None:
            current["body"] = (current["body"] + " " + clean).strip()
        else:
            current = {"title": "", "body": clean}
            sections.append(current)
    return sections
