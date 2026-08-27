# config.py — Fully Portable USB Path Resolution, Session Routing & Hardware Auto-Detection
import os
import sys
import subprocess

def get_base_dir() -> str:
    r"""
    Returns the true root directory where the .exe or script resides.
    Ensures USB portability across different drive letters (e.g., E:\, F:\).
    """
    if getattr(sys, "frozen", False):
        # Running as compiled PyInstaller executable
        return os.path.dirname(sys.executable)
    else:
        # Running as raw Python script
        return os.path.dirname(os.path.abspath(__file__))

BASE_DIR = get_base_dir()
ROOT_DIR = BASE_DIR  # Alias for pathlib / cross-compatibility

# --- Core Directories ---
BIN_DIR = os.path.join(BASE_DIR, "bin")
MODELS_DIR = os.path.join(BASE_DIR, "models")
DATA_DIR = os.path.join(BASE_DIR, "data")
AUDIO_CACHE_DIR = os.path.join(DATA_DIR, "audio_cache")
SESSIONS_DIR = os.path.join(DATA_DIR, "sessions")

# --- Session Index Registry ---
SESSIONS_FILE = os.path.join(SESSIONS_DIR, "sessions.json")
SESSIONS_INDEX_FILE = SESSIONS_FILE  # Alias

# --- Global Fallback Vault Directories (Backward Compatibility) ---
VAULTS_DIR = os.path.join(DATA_DIR, "vaults")
VAULT_DIR = VAULTS_DIR  # Alias for backward compatibility across modules
EMBEDDINGS_DIR = os.path.join(VAULTS_DIR, "embeddings")

# --- Theme Configuration Files ---
SKIN_FILE = os.path.join(BASE_DIR, "skin.json")
DAEMON_SKIN_FILE = os.path.join(BASE_DIR, "daemon_skin.json")

# --- Default Global Vault JSON File Paths ---
WORKING_MEMORY_FILE = os.path.join(VAULTS_DIR, "working_memory.json")
DEEP_MEMORY_FILE = os.path.join(VAULTS_DIR, "deep_memory.json")
INTENT_MEMORY_FILE = os.path.join(VAULTS_DIR, "intent_memory.json")
TASK_MEMORY_FILE = os.path.join(VAULTS_DIR, "task_memory.json")
FACTUAL_MEMORY_FILE = os.path.join(VAULTS_DIR, "factual_memory.json")
CONTINUATION_MEMORY_FILE = os.path.join(VAULTS_DIR, "continuation_memory.json")
RESET_MEMORY_FILE = os.path.join(VAULTS_DIR, "reset_memory.json")
PRUNE_TELEMETRY_FILE = os.path.join(VAULTS_DIR, "prune_telemetry.json")
JOURNAL_FILE = os.path.join(VAULTS_DIR, "journal_vault.json")
EMBEDDING_STORE_FILE = os.path.join(EMBEDDINGS_DIR, "embeddings.json")
STATE_MATRIX_FILE = os.path.join(VAULTS_DIR, "state_matrix.json")

# --- Primary LLM Server Defaults (llama-server Engine) ---
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8080
DEFAULT_CONTEXT = 16384
DEFAULT_N_GPU_LAYERS = 99

# --- Capacity Bounds ---
WORKING_MAX_ENTRIES = 800
DEEP_MAX_ENTRIES = 1000


def get_session_vault_dir(session_id: str) -> str:
    """Return a session-scoped vault directory without allowing path escape."""
    sid = str(session_id or "").strip()
    if not sid or sid in {".", ".."} or os.path.isabs(sid) or any(sep and sep in sid for sep in {os.sep, os.altsep, "/", "\\"}):
        raise ValueError("Invalid session id path component")
    base = os.path.realpath(SESSIONS_DIR)
    session_dir = os.path.realpath(os.path.join(base, sid))
    try:
        inside = os.path.commonpath([base, session_dir]) == base
    except ValueError:
        inside = False
    if not inside:
        raise ValueError("Session id escapes sessions directory")
    vault_dir = os.path.join(session_dir, "vaults")
    os.makedirs(vault_dir, exist_ok=True)
    return vault_dir


def get_session_vault_paths(session_id: str) -> dict:
    """
    Returns a dictionary of all vault file paths mapped strictly inside 
    the active session folder (e.g., data/sessions/<session_id>/vaults/).
    """
    v_dir = get_session_vault_dir(session_id)
    return {
        "vault_dir": v_dir,
        "working_memory": os.path.join(v_dir, "working_memory.json"),
        "deep_memory": os.path.join(v_dir, "deep_memory.json"),
        "journal_memory": os.path.join(v_dir, "journal_vault.json"),
        "intent_memory": os.path.join(v_dir, "intent_memory.json"),
        "task_memory": os.path.join(v_dir, "task_memory.json"),
        "factual_memory": os.path.join(v_dir, "factual_memory.json"),
        "superseded_memory": os.path.join(v_dir, "superseded_memory.json"),
        "continuation_memory": os.path.join(v_dir, "continuation_memory.json"),
        "reset_memory": os.path.join(v_dir, "reset_memory.json"),
        "prune_telemetry": os.path.join(v_dir, "prune_telemetry.json"),
        "embeddings": os.path.join(v_dir, "embeddings.json"),
    }


def detect_hardware_backend() -> str:
    """
    Detects active GPU hardware vendor for CUDA vs. Vulkan vs. DirectML fallback.
    Returns: 'cuda', 'vulkan', or 'cpu'
    """
    try:
        cmd = [
            "powershell", "-NoProfile", "-Command",
            "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name",
        ]
        output = subprocess.check_output(cmd, shell=False, text=True, errors="ignore").strip().upper()
        
        if "NVIDIA" in output:
            return "cuda"
        elif any(vendor in output for vendor in ["AMD", "RADEON", "INTEL", "ARC"]):
            return "vulkan"
    except Exception:
        pass
    return "cpu"


ACTIVE_HARDWARE_BACKEND = detect_hardware_backend()


def ensure_dirs():
    """Ensure all required base and data directories exist."""
    os.makedirs(BIN_DIR, exist_ok=True)
    os.makedirs(MODELS_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(AUDIO_CACHE_DIR, exist_ok=True)
    os.makedirs(SESSIONS_DIR, exist_ok=True)


ensure_dirs()