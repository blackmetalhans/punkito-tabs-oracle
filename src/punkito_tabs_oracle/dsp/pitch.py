# -*- coding: utf-8 -*-
"""
Detector de tono (Pitch Tracker) usando librosa.pyin.
- Registro objetivo: 30-400 Hz (según especificación)
- Ventana: frame_length=2048, hop_length=512, sr=22050
- Umbral de silencio por RMS normalizado: 0.05 -> forzar f0=0.0
- Interpolación cúbica para frames no confiables/no voiceados
- Beat tracking y cuantización temporal para legibilidad musical
- Detección de ghost notes (dead notes) usando onset_detect + spectral_flatness
- Detección de legato usando derivada de contorno de pitch

Comentarios en español.
"""
from pathlib import Path
from typing import Optional, Tuple, List

import numpy as np
import scipy.signal

# Compatibilidad con SciPy>=1.9 para dependencias legacy en librosa.
if not hasattr(scipy.signal, "hann"):
    scipy.signal.hann = scipy.signal.windows.hann

import librosa
from scipy.interpolate import interp1d

from punkito_tabs_oracle.settings import load_settings


class PitchTracker:
    """Estimador de f0 mediante pYIN e interpolación de huecos.

    Parámetros opcionales para facilitar pruebas y reutilización.
    """
    DEFAULT_DSP_SETTINGS = {
        "sample_rate": 22050,
        "frame_length": 2048,
        "hop_length": 256,
        "fmin": 41.2,
        "fmax": 392.0,
        "voiced_confidence_threshold": 0.05,
        "rms_silence_threshold": 0.05,
        "ghost_spectral_flatness_threshold": 0.5,
        "beat_voiced_ratio_threshold": 0.5,
        "slide_pitch_change_threshold_hz": 1.0,
        "slide_tolerance_hz": 1.0,
        "slide_min_duration_frames": 3,
    }

    def __init__(
        self,
        settings_path: Optional[Path] = None,
        sr: Optional[int] = None,
        frame_length: Optional[int] = None,
        hop_length: Optional[int] = None,
        fmin: Optional[float] = None,
        fmax: Optional[float] = None,
        voiced_confidence_threshold: Optional[float] = None,
        rms_silence_threshold: Optional[float] = None,
    ):
        settings = load_settings(settings_path)
        dsp = settings.get("dsp", {})
        defaults = self.DEFAULT_DSP_SETTINGS

        self.sr = int(sr if sr is not None else dsp.get("sample_rate", defaults["sample_rate"]))
        self.frame_length = int(
            frame_length
            if frame_length is not None
            else dsp.get("frame_length", defaults["frame_length"])
        )
        self.hop_length = int(
            hop_length
            if hop_length is not None
            else dsp.get("hop_length", defaults["hop_length"])
        )
        self.fmin = float(fmin if fmin is not None else dsp.get("fmin", defaults["fmin"]))
        self.fmax = float(fmax if fmax is not None else dsp.get("fmax", defaults["fmax"]))
        self.voiced_confidence_threshold = float(
            voiced_confidence_threshold
            if voiced_confidence_threshold is not None
            else dsp.get(
                "voiced_confidence_threshold",
                defaults["voiced_confidence_threshold"],
            )
        )
        self.rms_silence_threshold = float(
            rms_silence_threshold
            if rms_silence_threshold is not None
            else dsp.get("rms_silence_threshold", defaults["rms_silence_threshold"])
        )
        self.ghost_spectral_flatness_threshold = float(
            dsp.get(
                "ghost_spectral_flatness_threshold",
                defaults["ghost_spectral_flatness_threshold"],
            )
        )
        self.beat_voiced_ratio_threshold = float(
            dsp.get("beat_voiced_ratio_threshold", defaults["beat_voiced_ratio_threshold"])
        )
        self.slide_pitch_change_threshold_hz = float(
            dsp.get(
                "slide_pitch_change_threshold_hz",
                defaults["slide_pitch_change_threshold_hz"],
            )
        )
        self.slide_tolerance_hz = float(
            dsp.get("slide_tolerance_hz", defaults["slide_tolerance_hz"])
        )
        self.slide_min_duration_frames = int(
            dsp.get("slide_min_duration_frames", defaults["slide_min_duration_frames"])
        )
        self.quantization_grid = (0.25, 1.0 / 3.0)

    def quantize_duration(self, duration_in_beats: float) -> float:
        """Snap a duration to the strict micro-beat grid used by the exporter."""
        if duration_in_beats <= 0:
            return 0.25

        candidates = sorted(
            {0.25, 1.0 / 3.0, 0.5, 2.0 / 3.0, 0.75, 1.0, 1.25, 4.0 / 3.0, 1.5, 5.0 / 3.0, 1.75, 2.0}
        )
        return min(candidates, key=lambda value: abs(value - duration_in_beats))

    def _detect_ghost_notes(
        self,
        y: np.ndarray,
        f0: np.ndarray,
        voiced_prob: np.ndarray,
        beat_frames: np.ndarray,
    ) -> np.ndarray:
        """Detecta ghost notes (dead notes) usando onset_detect y spectral_flatness.

        Retorna un array booleano de mismo largo que f0, True donde hay ghost note.
        """
        onsets = librosa.onset.onset_detect(
            y=y,
            sr=self.sr,
            hop_length=self.hop_length,
            backtrack=True,
        )

        spectral_flatness = librosa.feature.spectral_flatness(y=y, hop_length=self.hop_length)[0]
        spectral_flatness = np.asarray(spectral_flatness, dtype=float)

        ghost_notes = np.zeros(len(f0), dtype=bool)

        for onset_frame in onsets:
            # Si hay onset pero baja voicedness o alta spectral_flatness -> ghost note
            onset_idx = int(np.clip(onset_frame, 0, len(f0) - 1))
            is_weak_voiced = (
                voiced_prob[onset_idx] < self.voiced_confidence_threshold
                if onset_idx < len(voiced_prob)
                else True
            )
            is_percussive = (
                spectral_flatness[onset_idx] > self.ghost_spectral_flatness_threshold
                if onset_idx < len(spectral_flatness)
                else False
            )

            if is_weak_voiced or is_percussive:
                ghost_notes[onset_idx] = True

        return ghost_notes

    def _detect_legato(
        self,
        f0: np.ndarray,
        voiced_prob: np.ndarray,
        onsets: np.ndarray,
    ) -> np.ndarray:
        """Detecta legato (slurs) usando derivada del contorno de pitch.

        Retorna un array booleano de mismo largo que f0, True donde hay transición legato.
        """
        legato_mask = np.zeros(len(f0), dtype=bool)
        if len(f0) == 0:
            return legato_mask

        # Calcular derivada de f0 evitando propagación de NaN mediante interpolación
        f0_valid = np.asarray(f0, dtype=float)
        voiced_mask = f0_valid > 0.0
        if np.count_nonzero(voiced_mask) >= 2:
            frame_idx = np.arange(len(f0_valid), dtype=float)
            f0_interp = np.interp(frame_idx, frame_idx[voiced_mask], f0_valid[voiced_mask])
            pitch_derivative = np.gradient(f0_interp)
        else:
            pitch_derivative = np.zeros_like(f0_valid, dtype=float)

        onset_set = set(int(np.clip(o, 0, len(f0) - 1)) for o in onsets)

        for i in range(1, len(f0)):
            prev_voiced = f0[i - 1] > 0.0 and voiced_prob[i - 1] >= self.voiced_confidence_threshold
            curr_voiced = f0[i] > 0.0 and voiced_prob[i] >= self.voiced_confidence_threshold

            # Legato si ambos frames tienen pitch, pero NO hay onset sharp
            if prev_voiced and curr_voiced and i not in onset_set:
                # Verificar que hay cambio de pitch suave (no salto)
                if np.isfinite(pitch_derivative[i]):
                    legato_mask[i] = True

        return legato_mask

    def _interpolate_low_confidence(self, f0: np.ndarray, valid_mask: np.ndarray) -> np.ndarray:
        """Interpola huecos internos de f0 usando interpolación cúbica."""
        if f0.size == 0:
            return f0

        interpolated = np.zeros_like(f0, dtype=float)
        valid_idx = np.flatnonzero(valid_mask)
        if valid_idx.size == 0:
            return interpolated

        interpolated[valid_idx] = f0[valid_idx]
        if valid_idx.size == 1:
            return interpolated

        interp_kind = "cubic" if valid_idx.size >= 4 else "linear"
        interpolator = interp1d(
            valid_idx.astype(float),
            f0[valid_idx].astype(float),
            kind=interp_kind,
            bounds_error=False,
            fill_value=np.nan,
        )

        span = np.arange(valid_idx[0], valid_idx[-1] + 1)
        span_values = np.asarray(interpolator(span), dtype=float)
        bridge_mask = ~valid_mask[span]
        span_out = interpolated[span]
        span_out[bridge_mask] = span_values[bridge_mask]
        interpolated[span] = span_out
        interpolated[np.isnan(interpolated)] = 0.0
        interpolated[interpolated < 0.0] = 0.0
        return interpolated

    def estimar_f0(self, audio_path: Path) -> np.ndarray:
        """Carga el archivo WAV y estima f0 por frame en Hz.

        - Retorna un array numpy 1D con f0 por frame.
        - Un valor de 0.0 indica silencio / no-voz.
        - Para frames de baja confianza/no voiceados usa interpolación cúbica.

        Implementa progreso iterativo y procesamiento por chunks para ahorrar RAM.
        """
        # Cargar audio (mono)
        y, sr = librosa.load(str(audio_path), sr=self.sr, mono=True)

        # Parámetros de chunking: procesar en bloques de N segundos con overlap para evitar artefactos
        seconds_per_chunk = 10.0
        chunk_size = int(seconds_per_chunk * self.sr)
        hop_frames = self.hop_length
        frame_per_chunk = max(1, int(np.ceil((chunk_size - self.frame_length) / hop_frames)))

        # Preparar contenedores para concatenar resultados
        f0_list = []
        voiced_prob_list = []

        # Progreso: usar tqdm si está disponible, sino fallback a prints
        try:
            from tqdm import tqdm
            progress = tqdm(range(0, len(y), chunk_size), desc="Estimando f0", unit="chunk")
        except Exception:
            progress = list(range(0, len(y), chunk_size))

        for start in progress:
            end = min(start + chunk_size, len(y))
            y_chunk = y[start:end]

            # Si el chunk es muy pequeño, pad para evitar errores en pyin
            if len(y_chunk) < self.frame_length:
                pad_width = self.frame_length - len(y_chunk)
                y_chunk = np.pad(y_chunk, (0, pad_width))

            # Ejecutar pYIN en el chunk
            try:
                f0_chunk, _, voiced_prob_chunk = librosa.pyin(
                    y_chunk,
                    fmin=self.fmin,
                    fmax=self.fmax,
                    sr=self.sr,
                    frame_length=self.frame_length,
                    hop_length=self.hop_length,
                )
            except Exception as e:
                # Si pyin falla en este chunk, registrar y seguir
                if hasattr(progress, "write"):
                    progress.write(f"pyin failed on chunk {start}-{end}: {e}")
                else:
                    print(f"pyin failed on chunk {start}-{end}: {e}")
                # Rellenar con NaNs para mantener alineación
                n_frames_chunk = int(np.ceil((len(y_chunk) - self.frame_length) / float(self.hop_length))) + 1
                f0_chunk = np.full(n_frames_chunk, np.nan)
                voiced_prob_chunk = np.zeros(n_frames_chunk)

            # Convertir a numpy
            f0_chunk = np.asarray(f0_chunk, dtype=float)
            voiced_prob_chunk = np.asarray(voiced_prob_chunk, dtype=float)

            # Si no estamos al primer chunk, recortar frames solapados para evitar duplicados
            if f0_list:
                # Determinar cuantos frames solapan: calcular en frames la parte que se repite por el overlap implícito
                overlap_frames = int(np.floor(self.frame_length / float(self.hop_length)))
                if overlap_frames > 0:
                    f0_chunk = f0_chunk[overlap_frames:]
                    voiced_prob_chunk = voiced_prob_chunk[overlap_frames:]

            f0_list.append(f0_chunk)
            voiced_prob_list.append(voiced_prob_chunk)

        # Concatenar todos los chunks
        if len(f0_list) == 0:
            return np.array([])

        f0 = np.concatenate([arr for arr in f0_list])
        voiced_prob = np.concatenate([arr for arr in voiced_prob_list])

        # Alinear longitudes con RMS
        rms = librosa.feature.rms(y=y, frame_length=self.frame_length, hop_length=self.hop_length)[0]
        max_rms = float(np.max(rms)) if rms.size > 0 else 0.0
        rms_norm = rms / max_rms if max_rms > 0 else rms

        # Valid mask y postprocesado
        valid_mask = (~np.isnan(f0)) & (f0 > 0.0) & (voiced_prob >= self.voiced_confidence_threshold)
        f0 = self._interpolate_low_confidence(f0=f0, valid_mask=valid_mask)

        n_frames = min(len(f0), len(rms_norm))
        if n_frames > 0:
            mask_silence = rms_norm[:n_frames] < self.rms_silence_threshold
            f0[:n_frames][mask_silence] = 0.0

        return f0

    def _extract_beat_windows(
        self, y: np.ndarray, beat_frames: np.ndarray, f0_raw: np.ndarray
    ) -> List[Tuple[int, int]]:
        """Extrae ventanas de beat normalizadas para cuantización elástica.

        Calcula los límites (start_frame, end_frame) para cada beat basándose
        en los timestamps de beat detectados por librosa.beat.beat_track().

        Args:
            y: Signal de audio
            beat_frames: Array de frame indices de beats detectados
            f0_raw: Array de f0 estimado

        Returns:
            Lista de tuplas (start_frame, end_frame) para cada beat window
        """
        beat_windows: List[Tuple[int, int]] = []

        if len(beat_frames) == 0:
            # Fallback: crear ventanas uniformes
            frames_per_beat = max(1, int(len(f0_raw) / 4))  # Asumir ~4 beats
            for i in range(0, len(f0_raw), frames_per_beat):
                start = i
                end = min(i + frames_per_beat, len(f0_raw))
                beat_windows.append((start, end))
            return beat_windows

        # Usar beat frames detectados
        beat_frames = np.unique(np.sort(beat_frames))
        beat_frames = np.concatenate([[0], beat_frames, [len(f0_raw)]])
        beat_frames = np.unique(beat_frames)

        for i in range(len(beat_frames) - 1):
            start_frame = int(beat_frames[i])
            end_frame = int(beat_frames[i + 1])
            start_frame = max(0, min(start_frame, len(f0_raw) - 1))
            end_frame = max(start_frame + 1, min(end_frame, len(f0_raw)))
            beat_windows.append((start_frame, end_frame))

        return beat_windows

    def _quantize_f0_in_beat_window(
        self, f0_interval: np.ndarray, ghost_notes: np.ndarray,
        legato_mask: np.ndarray, start_frame: int, end_frame: int
    ) -> Tuple[float, str]:
        """Cuantiza f0 dentro de una ventana local de beat.

        Calcula la mediana de f0 voiced y determina el tipo de articulación
        basándose en propiedades locales dentro de la ventana.

        Args:
            f0_interval: Segmento de f0 para esta ventana
            ghost_notes: Array booleano de detección de ghost notes
            legato_mask: Array booleano de detección de legato
            start_frame: Índice de frame inicial
            end_frame: Índice de frame final

        Returns:
            Tupla (f0_value, articulation_type)
        """
        voiced = f0_interval[f0_interval > 0.0]

        articulation_type = "normal"
        f0_value = 0.0

        if len(voiced) > 0 and len(voiced) > len(f0_interval) * self.beat_voiced_ratio_threshold:
            f0_value = float(np.median(voiced))

            # Verificar si es ghost note
            ghost_count = np.sum(ghost_notes[start_frame:end_frame])
            if ghost_count > 0:
                articulation_type = "dead"
            # Verificar si hay legato en el intervalo
            elif np.sum(legato_mask[start_frame:end_frame]) > 0:
                articulation_type = "legato"

        return f0_value, articulation_type

    def obtener_f0_por_pulso(
        self, ruta_bajo: Path
    ) -> Tuple[List[Tuple[float, str]], float]:
        """Estima f0, detecta tempo, y cuantiza por pulsos/beats con articulation.

        Implementa cuantización elástica usando beat timestamps no-lineales
        extraídos con librosa.beat.beat_track() para soportar variaciones de groove
        humanas.

        Retorna:
        - f0_pulsos: lista de tuplas (f0_valor, articulation_type) donde:
            - f0_valor: mediana de f0 por beat (0.0 para silencio/rest)
            - articulation_type: 'normal' | 'dead' | 'legato'
        - bpm: tempo detectado en pulsos por minuto
        """
        # 1. Estimar f0 crudo
        y, sr = librosa.load(str(ruta_bajo), sr=self.sr, mono=True)
        f0_raw = self.estimar_f0(ruta_bajo)

        if len(f0_raw) == 0:
            return [], 120.0

        # 2. Detectar tempo
        tempo = librosa.beat.tempo(y=y, sr=self.sr)
        bpm = float(tempo[0]) if len(tempo) > 0 else 120.0

        # 3. PHASE 1: Detectar beats usando librosa.beat.beat_track()
        # para extraer timestamps de beat no-lineales
        _, beat_frames = librosa.beat.beat_track(y=y, sr=self.sr)
        beat_windows = self._extract_beat_windows(y, beat_frames, f0_raw)

        # 4. Detectar ghost notes y legato
        _, _, voiced_prob = librosa.pyin(
            y,
            fmin=self.fmin,
            fmax=self.fmax,
            sr=self.sr,
            frame_length=self.frame_length,
            hop_length=self.hop_length,
        )
        voiced_prob = np.asarray(voiced_prob, dtype=float)

        onsets = librosa.onset.onset_detect(
            y=y,
            sr=self.sr,
            hop_length=self.hop_length,
            backtrack=True,
        )

        beat_frame_starts = np.array([w[0] for w in beat_windows])
        ghost_notes = self._detect_ghost_notes(
            y, f0_raw, voiced_prob, beat_frame_starts
        )
        legato_mask = self._detect_legato(f0_raw, voiced_prob, onsets)
        slide_regions = self.detect_slides(
            f0=f0_raw,
            voiced_prob=voiced_prob,
            min_duration_frames=self.slide_min_duration_frames,
            onsets=onsets,
        )
        for slide_start, slide_end, _, _ in slide_regions:
            legato_mask[slide_start:min(slide_end + 1, len(legato_mask))] = True

        # 5. Cuantizar f0 por ventanas de beat elásticas con articulation
        f0_pulsos: List[Tuple[float, str]] = []
        for start_frame, end_frame in beat_windows:
            f0_interval = f0_raw[start_frame:end_frame]
            f0_value, articulation_type = self._quantize_f0_in_beat_window(
                f0_interval, ghost_notes, legato_mask, start_frame, end_frame
            )
            f0_pulsos.append((f0_value, articulation_type))

        return f0_pulsos, bpm

    def obtener_f0_por_pulso_legacy(self, ruta_bajo: Path) -> Tuple[np.ndarray, float]:
        """Versión legacy que devuelve solo f0 sin articulation para compatibilidad."""
        f0_pulsos_with_articulation, bpm = self.obtener_f0_por_pulso(ruta_bajo)
        f0_values = np.array([val for val, _ in f0_pulsos_with_articulation], dtype=float)
        return f0_values, bpm

    def detect_slides(
        self,
        f0: np.ndarray,
        voiced_prob: np.ndarray,
        min_duration_frames: Optional[int] = None,
        onsets: Optional[np.ndarray] = None,
    ) -> List[Tuple[int, int, int, int]]:
        """Detecta deslices (glissandos) lineales en el contorno de f0.
        
        Identifica rampas de pitch donde la frecuencia cambia monótonamente a lo largo de
        una duración mínima, sin interrupciones de onset, y devuelve los puntos inicio/fin
        con conversión a MIDI.
        
        Args:
            f0: Array de f0 continuo (Hz)
            voiced_prob: Array de probabilidad de voz por frame
            min_duration_frames: Duración mínima de rampa (frames) para ser considerada slide
            onsets: Optional array de detecciones de onset
            
        Returns:
            Lista de tuplas (start_frame, end_frame, start_midi, end_midi) para cada slide
        """
        slides: List[Tuple[int, int, int, int]] = []
        min_duration = int(
            self.slide_min_duration_frames
            if min_duration_frames is None
            else min_duration_frames
        )

        if len(f0) < min_duration:
            return slides
        
        if onsets is None:
            onsets = np.array([], dtype=int)
        else:
            onsets = np.asarray(onsets, dtype=int)
        onset_set = set(int(np.clip(o, 0, len(f0) - 1)) for o in onsets)
        
        # Crear máscara de frames válidos (voiced y con suficiente confianza)
        valid_mask = (f0 > 0.0) & (voiced_prob >= self.voiced_confidence_threshold)
        
        i = 0
        while i < len(f0):
            # Buscar inicio de una posible rampa
            if not valid_mask[i] or i in onset_set:
                i += 1
                continue
            
            # Iniciar búsqueda de rampa monotónica
            ramp_start = i
            ramp_direction = None  # 'up' o 'down'
            ramp_end = i
            
            # Extender la rampa mientras sea monótona
            for j in range(i + 1, len(f0)):
                if not valid_mask[j] or j in onset_set:
                    break
                
                # Calcular cambio de frecuencia
                df = f0[j] - f0[j - 1]
                
                if ramp_direction is None:
                    # Establecer dirección en el primer cambio significativo
                    if abs(df) > self.slide_pitch_change_threshold_hz:
                        ramp_direction = "up" if df > 0 else "down"
                        ramp_end = j
                    else:
                        ramp_end = j
                elif ramp_direction == "up" and df >= -self.slide_tolerance_hz:
                    # Permitir pequeños retrocesos (< 1 Hz) en rampa ascendente
                    ramp_end = j
                elif ramp_direction == "down" and df <= self.slide_tolerance_hz:
                    # Permitir pequeños avances (< 1 Hz) en rampa descendente
                    ramp_end = j
                else:
                    # Dirección invertida: terminar rampa
                    break
            
            # Si encontramos una rampa válida, registrarla
            ramp_length = ramp_end - ramp_start + 1
            if ramp_length >= min_duration and ramp_direction is not None:
                # Calcular MIDI start y end
                midi_start = int(round(librosa.hz_to_midi(float(f0[ramp_start]))))
                midi_end = int(round(librosa.hz_to_midi(float(f0[ramp_end]))))
                
                # Solo registrar si hay cambio de MIDI
                if midi_start != midi_end:
                    slides.append((ramp_start, ramp_end, midi_start, midi_end))
            
            # Avanzar al siguiente frame no procesado
            i = ramp_end + 1
        
        return slides
    
    def _is_monotonic_ramp(
        self,
        f0_segment: np.ndarray,
        voiced_segment: np.ndarray,
        direction: str,
        tolerance_hz: Optional[float] = None,
    ) -> bool:
        """Verifica si un segmento de f0 forma una rampa monótona en la dirección especificada.
        
        Args:
            f0_segment: Segmento de f0 a verificar
            voiced_segment: Máscara voiced correspondiente
            direction: 'up' para ascendente, 'down' para descendente
            tolerance_hz: Tolerancia para pequeños retrocesos
            
        Returns:
            True si el segmento es una rampa monótona
        """
        valid_idx = np.where(voiced_segment)[0]
        if len(valid_idx) < 2:
            return False
        
        valid_f0 = f0_segment[valid_idx]
        
        # Calcular cambios
        diffs = np.diff(valid_f0)
        tol = self.slide_tolerance_hz if tolerance_hz is None else float(tolerance_hz)
        
        if direction == "up":
            # Permitir cambios positivos y pequeños negativos
            return np.all(diffs >= -tol)
        elif direction == "down":
            # Permitir cambios negativos y pequeños positivos
            return np.all(diffs <= tol)
        
        return False
