"""Optional local LLM via Ollama (http://localhost:11434).

EchoMe never calls a cloud LLM. If Ollama is not installed or is slow, every caller
falls back to built-in rules, so the app always works.
"""
import json
import os
import urllib.request

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("ECHOME_MODEL", "gemma3:4b")
TIMEOUT = float(os.environ.get("ECHOME_LLM_TIMEOUT", "20"))

_status = {"checked": False, "available": False}


def available() -> bool:
    if _status["checked"]:
        return _status["available"]
    _status["checked"] = True
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=1.5) as r:
            tags = json.loads(r.read().decode())
            names = [m.get("name", "") for m in tags.get("models", [])]
            _status["available"] = any(n.split(":")[0] == OLLAMA_MODEL.split(":")[0] for n in names)
    except Exception:
        _status["available"] = False
    return _status["available"]


def generate(prompt: str, want_json: bool = False):
    """Return the model's text (or parsed JSON), or None if the local model is unavailable."""
    if not available():
        return None
    body = {"model": OLLAMA_MODEL, "prompt": prompt, "stream": False,
            "options": {"temperature": 0.4, "num_predict": 200}}
    if want_json:
        body["format"] = "json"
    try:
        req = urllib.request.Request(f"{OLLAMA_URL}/api/generate", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            text = json.loads(r.read().decode()).get("response", "").strip()
        if want_json:
            return json.loads(text)
        return text or None
    except Exception:
        return None
