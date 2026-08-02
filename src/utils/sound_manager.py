"""Sound manager - Gestion des bips de notification thread-safe."""
from __future__ import annotations

import os
import json
import struct
import tempfile
import logging
from typing import Optional

from PySide6.QtCore import QObject, QUrl, Slot, QMetaObject, Qt
from PySide6.QtMultimedia import QSoundEffect

logger = logging.getLogger(__name__)

SETTINGS_PATH = os.path.join(
    os.path.expanduser("~"), ".application_mesure", "settings.json"
)


def _load_settings() -> dict:
    try:
        from src.utils.file_crypto import decrypt_json
        data = decrypt_json(SETTINGS_PATH)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _generate_wav(frequency: int, duration_ms: int) -> bytes:
    """Genere un fichier WAV monaural 16-bit PCM."""
    sample_rate = 22050
    num_samples = int(sample_rate * duration_ms / 1000)
    # Generer une onde sinusoidale
    samples = []
    for i in range(num_samples):
        t = i / sample_rate
        value = int(16384 * __import__('math').sin(2 * __import__('math').pi * frequency * t))
        samples.append(struct.pack('<h', value))

    data = b''.join(samples)
    data_size = len(data)
    # En-tete WAV
    header = struct.pack(
        '<4sI4s4sIHHIIHH4sI',
        b'RIFF', 36 + data_size, b'WAVE',
        b'fmt ', 16, 1, 1, sample_rate,
        sample_rate * 2, 2, 16,
        b'data', data_size
    )
    return header + data


class SoundManager(QObject):
    """Gere les effets sonores de notification - Thread-safe singleton.
    
    Utilise QSoundEffect qui doit vivre dans le thread Qt principal.
    Les appels depuis d'autres threads passent par QMetaObject.invokeMethod.
    """
    
    _instance: Optional['SoundManager'] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    @classmethod
    def instance(cls) -> 'SoundManager':
        """Retourne le singleton, le cree si necessaire."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        super().__init__()
        self._initialized = True
        
        self._reception_sound: Optional[QSoundEffect] = None
        self._error_sound: Optional[QSoundEffect] = None
        self._init_sounds()
    
    def _init_sounds(self):
        """Cree les fichiers WAV temporaires et initialise les sons."""
        try:
            # Generer les fichiers WAV dans un repertoire temporaire
            temp_dir = tempfile.gettempdir()
            reception_path = os.path.join(temp_dir, "opencode_reception.wav")
            error_path = os.path.join(temp_dir, "opencode_error.wav")

            # Reception : beep aigu court
            if not os.path.exists(reception_path):
                with open(reception_path, "wb") as f:
                    f.write(_generate_wav(1047, 150))  # Do6, 150ms

            # Erreur : beep grave long
            if not os.path.exists(error_path):
                with open(error_path, "wb") as f:
                    f.write(_generate_wav(262, 400))  # Do4, 400ms

            self._reception_sound = QSoundEffect(self)
            self._reception_sound.setSource(QUrl.fromLocalFile(reception_path))
            self._reception_sound.setVolume(0.7)

            self._error_sound = QSoundEffect(self)
            self._error_sound.setSource(QUrl.fromLocalFile(error_path))
            self._error_sound.setVolume(0.8)

            logger.info("Sons de notification initialises")
        except Exception as e:
            logger.warning("Impossible d'initialiser les sons: %s", e)
    
    @Slot()
    def play_reception(self):
        """Joue le bip de reception de donnees (slot appele dans thread Qt principal)."""
        if self._reception_sound and self._is_enabled("sound_reception"):
            self._reception_sound.play()
    
    @Slot()
    def play_error(self):
        """Joue le bip d'erreur generique (slot appele dans thread Qt principal)."""
        if self._error_sound and self._is_enabled("sound_error"):
            self._error_sound.play()
    
    def play_reception_async(self, force: bool = False):
        """Joue le bip de reception depuis n'importe quel thread (thread-safe)."""
        if force or self._is_enabled("sound_reception"):
            QMetaObject.invokeMethod(self, "play_reception", Qt.ConnectionType.QueuedConnection)
    
    def play_error_async(self, force: bool = False):
        """Joue le bip d'erreur depuis n'importe quel thread (thread-safe)."""
        if force or self._is_enabled("sound_error"):
            QMetaObject.invokeMethod(self, "play_error", Qt.ConnectionType.QueuedConnection)
    
    _settings_cache: Optional[dict] = None
    _settings_cache_time: float = 0.0
    _CACHE_TTL: float = 30.0  # Recharger les settings au max toutes les 30s

    @classmethod
    def _is_enabled(cls, key: str) -> bool:
        """Verifie si un son est active dans les parametres (avec cache)."""
        import time
        now = time.time()
        if cls._settings_cache is None or (now - cls._settings_cache_time) > cls._CACHE_TTL:
            try:
                cls._settings_cache = _load_settings()
                cls._settings_cache_time = now
            except Exception:
                cls._settings_cache = {}
        return cls._settings_cache.get(key, True)