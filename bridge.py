# bridge.py — Dynamic LM Studio Bridge Engine
import requests
import threading

LM_STUDIO_URL = "http://127.0.0.1:1234/v1/chat/completions"
MODELS_URL = "http://127.0.0.1:1234/v1/models"


_reply_state = threading.local()

def reset_last_finish_reason() -> None:
    """Clear transport completion metadata for the current inference thread."""
    _reply_state.finish_reason = None

def get_last_finish_reason():
    """Return LM Studio's finish_reason for the current inference thread, if available."""
    return getattr(_reply_state, "finish_reason", None)


class LMStudioOfflineError(Exception):
    """Raised when the LM Studio local server cannot be reached."""
    pass


def get_active_model_name() -> str:
    """Queries LM Studio for the currently loaded model ID."""
    try:
        resp = requests.get(MODELS_URL, timeout=2)
        if resp.status_code == 200:
            data = resp.json()
            models = data.get("data", [])
            if models:
                return models[0].get("id", "local-model")
    except Exception:
        pass
    return "local-model"


def lmstudio_reply(system_prompt: str, user_text: str, history: list = None) -> str:
    reset_last_finish_reason()
    """
    Sends structured prompt packet to LM Studio with full history context,
    dynamic model detection, and an extended 90-second timeout.
    """
    active_model = get_active_model_name()

    messages = [{"role": "system", "content": system_prompt}]
    
    # Append past conversation history turns if present
    if history and isinstance(history, list):
        for h in history:
            if isinstance(h, dict) and "role" in h and "content" in h:
                messages.append(h)

    # Append current user prompt
    messages.append({"role": "user", "content": user_text})

    payload = {
        "model": active_model,
        "stream": False,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 2048,
    }

    try:
        response = requests.post(LM_STUDIO_URL, json=payload, timeout=90)
        response.raise_for_status()
        data = response.json()
        
        choices = data.get("choices", [])
        if choices:
            try:
                _reply_state.finish_reason = choices[0].get("finish_reason")
            except Exception:
                _reply_state.finish_reason = None

        if choices and "message" in choices[0]:
            content = choices[0]["message"].get("content", "").strip()
            if content:
                return content

        return "(Model completed turn, but returned an empty response.)"

    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
        raise LMStudioOfflineError("LM Studio server is offline or timed out.") from e
    except Exception as e:
        return f"(LM Studio API Error: {e})"