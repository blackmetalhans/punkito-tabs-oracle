# -*- coding: utf-8 -*-
"""
Detector de tono (Pitch Tracker) usando librosa.pyin con fallback YIN.
- Registro objetivo: 30-400 Hz (según especificación)
- Ventana: frame_length=2048, hop_length=512, sr=22050
- Umbral de silencio por RMS normalizado: 0.05 -> forzar f0=0.0
- Fallback YIN si confianza pYIN < 5%
- Beat tracking y cuantización temporal para legibilidad musical

Comentarios en español.
"""
import sys
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
import librosa


class PitchTracker:
    """Estimador de f0 mediante pYIN con fallback YIN y beat quantization.

    Parámetros opcionales para facilitar pruebas y reutilización.
    """

    def __init__(self, sr: int = 22050, frame_length: int = 2048, hop_length: int = 512, fmin: float = 30.0, fmax: float = 400.0):
        self.sr = sr
        self.frame_length = frame_length
        self.hop_length = hop_length
        self.fmin = fmin
        self.fmax = fmax

    def estimar_f0(self, audio_path: Path) -> np.ndarray:
        """Carga el archivo WAV y estima f0 por frame en Hz.

        - Retorna un array numpy 1D con f0 por frame.
        - Un valor de 0.0 indica silencio / no-voz.
        - Implementa fallback YIN si confianza pYIN < 5%.
        """
        # Cargar audio (mono)
        y, sr = librosa.load(str(audio_path), sr=self.sr, mono=True)

        # Ejecutar pYIN
        # librosa.pyin devuelve un array con NaNs donde no hay estimación
        f0, voiced_flag, voiced_prob = librosa.pyin(
            y,
            fmin=self.fmin,
            fmax=self.fmax,
            sr=self.sr,
            frame_length=self.frame_length,
            hop_length=self.hop_length,
        )

        # Garantizar vector numpy y reemplazar NaN por 0.0 (no-voz)
        f0 = np.asarray(f0, dtype=float)
        f0[np.isnan(f0)] = 0.0

        # Verificar proporción de frames voiceados
        num_voiced = np.sum(f0 > 0)
        total_frames = len(f0)
        voiced_ratio = num_voiced / total_frames if total_frames > 0 else 0.0

        # Fallback YIN si menos del 5% de confianza
        if voiced_ratio < 0.05:
            print(
                f"[WARN] pYIN confidence low ({voiced_ratio:.2%}). Falling back to YIN algorithm.",
                file=sys.stderr
            )
            try:
                f0_yin = librosa.yin(
                    y,
                    fmin=self.fmin,
                    fmax=self.fmax,
                    sr=self.sr,
                    frame_length=self.frame_length,
                    hop_length=self.hop_length,
                )
                f0_yin = np.asarray(f0_yin, dtype=float)
                f0_yin[np.isnan(f0_yin)] = 0.0
                f0 = f0_yin
                print("[INFO] YIN fallback completed successfully.", file=sys.stderr)
            except Exception as e:
                print(f"[WARN] YIN fallback failed: {e}. Using pYIN results.", file=sys.stderr)

        # Calcular RMS por frame con mismo frame/hop
        rms = librosa.feature.rms(y=y, frame_length=self.frame_length, hop_length=self.hop_length)[0]
        # Normalizar RMS al máximo (siempre proteger contra división por cero)
        max_rms = float(np.max(rms)) if rms.size > 0 else 0.0
        if max_rms > 0:
            rms_norm = rms / max_rms
        else:
            rms_norm = rms

        # Si RMS normalizado por frame cae por debajo del umbral, forzar f0=0.0
        # Alinear longitudes: librosa.pyin puede devolver más o menos frames, pero usando mismos frame/hop deben coincidir
        n_frames = min(len(f0), len(rms_norm))
        if n_frames > 0:
            mask_silence = rms_norm[:n_frames] < 0.05
            f0[:n_frames][mask_silence] = 0.0

        return f0

    def obtener_f0_por_pulso(self, ruta_bajo: Path) -> Tuple[np.ndarray, float]:
        """Estima f0, detecta tempo, y cuantiza por pulsos/beats.

        Retorna:
        - f0_pulsos: array con mediana de f0 por beat (0.0 para silencio/rest)
        - bpm: tempo detectado en pulsos por minuto
        """
        # 1. Estimar f0 crudo
        y, sr = librosa.load(str(ruta_bajo), sr=self.sr, mono=True)
        f0_raw = self.estimar_f0(ruta_bajo)

        if len(f0_raw) == 0:
            return np.array([], dtype=float), 120.0

        # 2. Detectar tempo
        tempo = librosa.beat.tempo(y=y, sr=self.sr)
        bpm = float(tempo[0]) if len(tempo) > 0 else 120.0

        # 3. Detectar beats o usar fallback
        try:
            _, beat_frames = librosa.beat.beat_track(y=y, sr=self.sr)
            if len(beat_frames) == 0:
                raise ValueError("No beats detected")
            beat_frames = np.concatenate([[0], beat_frames])
        except Exception:
            # Fallback: segmentar en N beats según BPM estimado
            # Aproximadamente 22050 frames por segundo / 512 hop_length = ~43 frames/segundo
            # A 120 BPM, 1 beat = 0.5 segundos = ~21.5 frames
            frames_per_beat = int((self.sr / self.hop_length) * (60.0 / bpm))
            frames_per_beat = max(1, frames_per_beat)  # Al menos 1 frame por beat
            beat_frames = np.arange(0, len(f0_raw), frames_per_beat)
            if beat_frames[-1] < len(f0_raw) - 1:
                beat_frames = np.concatenate([beat_frames, [len(f0_raw)]])

        # 4. Cuantizar f0 por intervalos de beat
        f0_pulsos = []
        for i in range(len(beat_frames) - 1):
            start_frame = int(beat_frames[i])
            end_frame = int(beat_frames[i + 1])
            # Asegurar límites válidos
            start_frame = max(0, min(start_frame, len(f0_raw) - 1))
            end_frame = max(start_frame + 1, min(end_frame, len(f0_raw)))

            # Extraer frames de f0 en este intervalo de beat
            f0_interval = f0_raw[start_frame:end_frame]
            # Contar voiceados
            voiced = f0_interval[f0_interval > 0]
            # Si > 50% son voiced, usar mediana; si no, rest (0.0)
            if len(voiced) > 0 and len(voiced) > len(f0_interval) * 0.5:
                f0_pulsos.append(float(np.median(voiced)))
            else:
                f0_pulsos.append(0.0)

        return np.array(f0_pulsos, dtype=float), bpm
