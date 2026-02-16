import tempfile
from pathlib import Path

from pydub import AudioSegment


def ogg_to_mp3(ogg_path: str) -> str:
    """Convert OGG/OPUS to MP3. Returns path to temp MP3 file (caller must clean up)."""
    audio = AudioSegment.from_ogg(ogg_path)
    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    audio.export(tmp.name, format="mp3")
    tmp.close()
    return tmp.name


def mp3_to_ogg(mp3_path: str) -> str:
    """Convert MP3 to OGG/OPUS. Returns path to temp OGG file (caller must clean up)."""
    audio = AudioSegment.from_mp3(mp3_path)
    # Pad with 300ms silence to prevent libopus from truncating the tail
    silence = AudioSegment.silent(duration=300)
    audio = audio + silence
    tmp = tempfile.NamedTemporaryFile(suffix=".ogg", delete=False)
    audio.export(tmp.name, format="ogg", codec="libopus")
    tmp.close()
    return tmp.name
