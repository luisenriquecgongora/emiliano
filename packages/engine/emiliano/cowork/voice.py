"""
Voice Transcription and Audio Engine for Emiliano Desktop Cowork.
Handles push-to-talk audio transcription for hands-free desktop coworking.
Supports local Whisper (whisper.cpp / local models) and cloud speech-to-text fallbacks.
Licensed under PolyForm Shield 1.0.0. Uses open-source MIT/Apache 2.0 primitives.
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import tempfile
from typing import Optional
from loguru import logger


def find_whisper_cpp_binary() -> Optional[str]:
    """Finds a local whisper.cpp executable on system PATH or standard directories."""
    candidate_names = ["whisper-cli.exe", "whisper.exe", "main.exe", "whisper-cli", "whisper"]
    for name in candidate_names:
        p = shutil.which(name)
        if p:
            return p

    search_dirs = [
        os.path.expanduser("~/.emiliano/whisper"),
        os.path.expanduser("~/.local/bin"),
        r"C:\Program Files\whisper.cpp",
    ]
    for d in search_dirs:
        for name in candidate_names:
            p = os.path.join(d, name)
            if os.path.exists(p):
                return p
    return None


class VoiceTranscriber:
    """
    Transcribes audio bytes into text.
    Uses local whisper.cpp if available, falling back to direct cloud speech models.
    """

    def __init__(self, whisper_binary: Optional[str] = None):
        self.whisper_binary = whisper_binary or find_whisper_cpp_binary()

    @property
    def is_local_available(self) -> bool:
        return self.whisper_binary is not None

    def transcribe(
        self,
        audio_bytes: bytes,
        language: Optional[str] = None,
        format_hint: str = "wav",
    ) -> str:
        """
        Transcribes audio data into text.
        """
        if not audio_bytes:
            return ""

        # 1. Attempt local whisper.cpp if installed
        if self.whisper_binary and os.path.exists(self.whisper_binary):
            try:
                return self._transcribe_local_whisper(audio_bytes, language=language)
            except Exception as e:
                logger.warning(f"[Voice] Local whisper transcription failed: {e}")

        # 2. Direct Cloud Fallback (OpenAI/Groq Whisper if configured)
        api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("GROQ_API_KEY")
        if api_key:
            try:
                return self._transcribe_cloud_api(audio_bytes, api_key=api_key, language=language)
            except Exception as e:
                logger.warning(f"[Voice] Cloud transcription failed: {e}")

        # 3. Informative fallback when no engine is configured
        logger.info(f"[Voice] Received {len(audio_bytes)} bytes of audio; no speech engine active.")
        return ""

    def _transcribe_local_whisper(self, audio_bytes: bytes, language: Optional[str] = None) -> str:
        """Runs local whisper.cpp binary against temporary WAV file."""
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(audio_bytes)
            tmp_path = f.name

        try:
            cmd = [self.whisper_binary, "-f", tmp_path, "--no-timestamps"]
            if language:
                cmd.extend(["-l", language])

            res = subprocess.run(cmd, capture_output=True, text=True, timeout=30.0)
            if res.returncode == 0:
                text = res.stdout.strip()
                logger.info(f"[Voice] Transcribed via whisper.cpp: '{text[:50]}...'")
                return text
            else:
                logger.warning(f"[Voice] whisper.cpp exited with code {res.returncode}: {res.stderr}")
                return ""
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def _transcribe_cloud_api(self, audio_bytes: bytes, api_key: str, language: Optional[str] = None) -> str:
        """Transcribes via OpenAI/Groq compatible Whisper HTTP API using urllib."""
        import urllib.request
        import uuid

        boundary = f"----WebKitFormBoundary{uuid.uuid4().hex}"
        body = io.BytesIO()

        # Part 1: file
        body.write(f"--{boundary}\r\n".encode("utf-8"))
        body.write(b'Content-Disposition: form-data; name="file"; filename="audio.wav"\r\n')
        body.write(b"Content-Type: audio/wav\r\n\r\n")
        body.write(audio_bytes)
        body.write(b"\r\n")

        # Part 2: model
        body.write(f"--{boundary}\r\n".encode("utf-8"))
        body.write(b'Content-Disposition: form-data; name="model"\r\n\r\n')
        body.write(b"whisper-1\r\n")

        if language:
            body.write(f"--{boundary}\r\n".encode("utf-8"))
            body.write(b'Content-Disposition: form-data; name="language"\r\n\r\n')
            body.write(language.encode("utf-8"))
            body.write(b"\r\n")

        body.write(f"--{boundary}--\r\n".encode("utf-8"))

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        }

        endpoint = "https://api.openai.com/v1/audio/transcriptions"
        if os.environ.get("GROQ_API_KEY") and not os.environ.get("OPENAI_API_KEY"):
            endpoint = "https://api.groq.com/openai/v1/audio/transcriptions"

        req = urllib.request.Request(endpoint, data=body.getvalue(), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=20.0) as resp:
            import json
            data = json.loads(resp.read().decode("utf-8"))
            return str(data.get("text", "")).strip()
