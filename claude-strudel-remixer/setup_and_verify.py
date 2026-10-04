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
        print("💡 Tip: Nainštaluj FFmpeg (cez 'brew install ffmpeg' na Macu, 'choco install ffmpeg' na Windows, alebo cez apt na Linuxe).")
        return False

    # 2. Kontrola verzií
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
        print("🎉 Výborne! Demucs je pripravený na separáciu vokálov.")
    except ImportError:
        print("❌ Demucs sa nepodarilo správne naimportovať.")

if __name__ == "__main__":
    if check_requirements():
        if install_packages():
            verify_demucs()
