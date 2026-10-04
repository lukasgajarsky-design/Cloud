import subprocess
import sys
import shutil

def check_requirements():
    print("🎵 [1/3] Kontrola systémových závislostí...")

    # 1. Kontrola FFmpeg
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        print(f"✅ FFmpeg je nainštalovaný: {ffmpeg_path}")
    else:
        print("❌ Chyba: FFmpeg nebol nájdený v systéme! Bez neho Demucs nedokáže spracovať audio.")
        print("💡 Tip: Nainštaluj FFmpeg (cez 'brew install ffmpeg' na Macu, 'winget install -e --id Gyan.FFmpeg' na Windows, alebo cez apt na Linuxe).")
        return False

    # 2. Kontrola verzií
    # PyTorch, sphn and lameenc publish no wheels for Python 3.15 yet (October 2026); raise the bound once they do
    if not (3, 10) <= sys.version_info[:2] <= (3, 14):
        print(f"❌ Chyba: Python {sys.version.split()[0]} nie je podporovaný. Demucs a PyTorch potrebujú Python 3.10 až 3.14.")
        print("💡 Tip: Zmaž priečinok .venv a vytvor ho s Pythonom 3.12: uv venv --python 3.12 --seed .venv")
        return False
    print(f"✅ Python verzia: {sys.version.split()[0]}")
    return True

def install_packages():
    print("\n📦 [2/3] Inštalácia hudobných balíčkov (Demucs & audio knižnice)...")
    # librosa, pyloudnorm and soundfile are needed by analyze_audio.py (BPM, key, LUFS)
    packages = ["demucs", "numpy", "scipy", "librosa", "pyloudnorm", "soundfile"]

    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "pip"])
        subprocess.check_call([sys.executable, "-m", "pip", "install"] + packages)
        print("✅ Všetky balíčky boli úspešne nainštalované.")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Chyba pri inštalácii balíčkov: {e}")
        return False

def verify_demucs():
    print("\n🚀 [3/3] Finálne overenie Demucs...")
    try:
        import demucs
        # torch and numba (via librosa) load compiled libraries, which is where broken installs show up
        import torch, librosa, pyloudnorm, soundfile
        print("🎉 Výborne! Demucs je pripravený na separáciu vokálov.")
        return True
    except (ImportError, OSError) as e:
        print(f"❌ Demucs sa nepodarilo správne naimportovať: {e}")
        return False

if __name__ == "__main__":
    # Windows pipes default to a legacy code page that can't encode the emoji below
    for stream in (sys.stdout, sys.stderr):
        if stream.encoding.lower().replace("-", "") != "utf8":
            stream.reconfigure(encoding="utf-8", errors="replace")
    ok = check_requirements() and install_packages() and verify_demucs()
    sys.exit(0 if ok else 1)
