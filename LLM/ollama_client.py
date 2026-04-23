import json
import requests

OLLAMA_BASE = "http://localhost:11434"
DEFAULT_TIMEOUT = 180


def is_ollama_running():
    try:
        resp = requests.get(OLLAMA_BASE + "/api/tags", timeout=3)
        return resp.status_code == 200
    except Exception:
        return False


_EMBED_KEYWORDS   = ("embed", "nomic", "mxbai", "all-minilm", "bge-")
# Prefer smaller/faster models — large models (12b+) are too slow for interactive use
_PREFER_KEYWORDS   = ("1.5b", "3b", "7b", "8b", "qwen", "phi", "gemma2:2b", "mistral:7b")
_DEPRIORI_KEYWORDS = ("12b", "13b", "14b", "33b", "70b", "starcoder", "codellama")


def list_models():
    """Return chat-capable models sorted: preferred general models first."""
    try:
        resp = requests.get(OLLAMA_BASE + "/api/tags", timeout=5)
        resp.raise_for_status()
        all_models = [m["name"] for m in resp.json().get("models", [])]
        chat_models = [
            m for m in all_models
            if not any(kw in m.lower() for kw in _EMBED_KEYWORDS)
        ]
        models = chat_models if chat_models else all_models

        def _rank(name):
            low = name.lower()
            if any(kw in low for kw in _PREFER_KEYWORDS):
                return 0
            if any(kw in low for kw in _DEPRIORI_KEYWORDS):
                return 2
            return 1

        return sorted(models, key=_rank)
    except Exception:
        return []


def chat_complete(model, messages):
    """Non-streaming POST to Ollama /api/chat. Returns full response string."""
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0.1, "num_ctx": 4096},
    }
    try:
        resp = requests.post(OLLAMA_BASE + "/api/chat", json=payload, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        return resp.json().get("message", {}).get("content", "")
    except requests.exceptions.ConnectionError:
        return "❌ Ollama not reachable."
    except requests.exceptions.Timeout:
        return "⏱ Request timed out."
    except Exception as e:
        return "❌ Error: {}".format(str(e))


def chat_stream(model, messages):
    """POST to Ollama /api/chat with streaming. Yields string chunks."""
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "options": {
            "temperature": 0.2,
            "num_ctx": 4096,
            "top_p": 0.9,
        },
    }
    try:
        with requests.post(
            OLLAMA_BASE + "/api/chat",
            json=payload,
            stream=True,
            timeout=DEFAULT_TIMEOUT,
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    content = data.get("message", {}).get("content", "")
                    if content:
                        yield content
                    if data.get("done"):
                        break
                except (json.JSONDecodeError, KeyError):
                    continue
    except requests.exceptions.ConnectionError:
        yield "\n\n❌ **Ollama not reachable.** Run `ollama serve` in a terminal, then reload this page."
    except requests.exceptions.Timeout:
        yield "\n\n⏱ **Response timed out** after {}s. Try a smaller/faster model.".format(DEFAULT_TIMEOUT)
    except Exception as e:
        yield "\n\n❌ **Error:** {}".format(str(e))
