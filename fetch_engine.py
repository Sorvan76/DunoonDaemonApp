# fetch_engine.py — Universal C++ Binary & Hardware Fallback Fetcher
import os
import sys
import io
import zipfile
import requests
import shutil

from config import BIN_DIR, ACTIVE_HARDWARE_BACKEND

def fetch_native_engine():
    os.makedirs(BIN_DIR, exist_ok=True)

    exe_path = os.path.join(BIN_DIR, "llama-server.exe")
    if os.path.exists(exe_path):
        print(f"[FetchEngine] Native binary already present in bin/ (Backend: {ACTIVE_HARDWARE_BACKEND.upper()}).")
        return

    print(f"[FetchEngine] Hardware detected: {ACTIVE_HARDWARE_BACKEND.upper()}")
    print("[FetchEngine] Querying latest official llama.cpp C++ releases on GitHub...")

    headers = {"User-Agent": "DunoonDaemonApp/1.0"}
    try:
        res = requests.get("https://api.github.com/repos/ggml-org/llama.cpp/releases/latest", headers=headers, timeout=10)
        res.raise_for_status()
        data = res.json()
    except Exception as e:
        print(f"[FetchEngine Warning] Could not query GitHub API: {e}. Attempting fallback...")
        data = {}

    target_pattern = "bin-win-cuda" if ACTIVE_HARDWARE_BACKEND == "cuda" else "bin-win-vulkan"
    download_url = None

    for asset in data.get("assets", []):
        name = asset.get("name", "").lower()
        # Strictly ignore runtime-only DLL packages (cudart-*)
        if name.startswith("cudart-"):
            continue
        if target_pattern in name and "x64" in name and name.endswith(".zip"):
            download_url = asset.get("browser_download_url")
            print(f"[FetchEngine] Selected asset: {asset.get('name')}")
            break

    # Pinned bleeding-edge b10425 fallbacks (with Gemma-4 MoE & Blackwell support)
    if not download_url:
        if ACTIVE_HARDWARE_BACKEND == "cuda":
            download_url = "https://github.com/ggml-org/llama.cpp/releases/download/b10425/llama-b10425-bin-win-cuda-cu12.4-x64.zip"
        else:
            download_url = "https://github.com/ggml-org/llama.cpp/releases/download/b10425/llama-b10425-bin-win-vulkan-x64.zip"

    print(f"[FetchEngine] Downloading and extracting {ACTIVE_HARDWARE_BACKEND.upper()} binaries directly to bin/...")
    try:
        dl_res = requests.get(download_url, stream=True, timeout=120)
        dl_res.raise_for_status()

        with zipfile.ZipFile(io.BytesIO(dl_res.content)) as z:
            for item in z.namelist():
                fname = os.path.basename(item)
                if fname:
                    with z.open(item) as src, open(os.path.join(BIN_DIR, fname), "wb") as dst:
                        shutil.copyfileobj(src, dst)

        print(f"[FetchEngine Success] Installed native C++ engine into bin/!")
    except Exception as e:
        print(f"[FetchEngine Error] Failed to download or extract binaries: {e}")

if __name__ == "__main__":
    fetch_native_engine()