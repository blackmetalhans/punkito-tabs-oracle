# -*- coding: utf-8 -*-
"""
Ruteador de trastes para bajo de N cuerdas.
Modela el mapeo de una secuencia temporal de f0 (Hz) -> MIDI -> (String, Fret)
como un problema de camino mínimo (programación dinámica / Viterbi-like).

Implementa un topología Viterbi consciente de escala con reglas ergonómicas:
- Estimación de tono usando librosa.feature.chroma_cqt
- Penalización por notas fuera de escala (error correction contra artefactos)
- Regla del octavo: transposciones de 12 semitonos descuentan fret distance
- Regla del box shape: transiciones dentro de 4 trastes favorecen string changes

Comentarios en español.
"""
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass

import numpy as np
import librosa

from music21 import pitch as pitch_module

from punkito_tabs_oracle.settings import load_settings


def estimate_key_from_chroma(
    y: np.ndarray,
    sr: int = 22050,
    hop_length: int = 256,
) -> Tuple[str, np.ndarray]:
    """Estima la tonalidad global usando chroma_cqt.

    Calcula chroma features (12 notas de la escala cromática) y detecta
    la tonalidad dominante usando correlación con templates de escala mayor/menor.

    Args:
        y: Señal de audio
        sr: Sample rate
        hop_length: Número de muestras entre frames

    Returns:
        (key_name: str, chroma_normalized: np.ndarray)
        - key_name: Nombre de la tonalidad (e.g., "E minor", "C major")
        - chroma_normalized: Vector de 12 dimensiones (notas C a B)
    """
    # Extraer características cromáticas usando constant-Q transform
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=hop_length)
    # Promediar sobre el tiempo
    chroma_mean = np.mean(chroma, axis=1)
    chroma_normalized = chroma_mean / (np.sum(np.abs(chroma_mean)) + 1e-9)

    # Templates de escala mayor y menor (normalizados)
    major_template = np.array(
        [1, 0, 1, 0, 1, 1, 0, 1, 0, 1, 0, 1],
        dtype=float
    )
    minor_template = np.array(
        [1, 0, 1, 1, 0, 1, 0, 1, 1, 0, 1, 0],
        dtype=float
    )
    major_template = major_template / np.sum(major_template)
    minor_template = minor_template / np.sum(minor_template)

    # Probar rotaciones para cada tono
    note_names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    best_score = -np.inf
    best_key = "C major"

    for shift in range(12):
        rotated = np.roll(chroma_normalized, shift)
        major_score = np.dot(rotated, major_template)
        minor_score = np.dot(rotated, minor_template)

        if major_score > best_score:
            best_score = major_score
            best_key = f"{note_names[shift]} major"

        if minor_score > best_score:
            best_score = minor_score
            best_key = f"{note_names[shift]} minor"

    return best_key, chroma_normalized


def get_scale_degrees(key_name: str) -> np.ndarray:
    """Devuelve un array booleano de 12 notas en la escala detectada.

    Args:
        key_name: Tonalidad detectada (e.g., "E minor")

    Returns:
        Array booleano de 12 elementos (C a B) indicando qué notas están en la escala
    """
    note_to_idx = {
        "C": 0,
        "C#": 1,
        "D": 2,
        "D#": 3,
        "E": 4,
        "F": 5,
        "F#": 6,
        "G": 7,
        "G#": 8,
        "A": 9,
        "A#": 10,
        "B": 11,
    }

    # Parsear tonalidad
    parts = key_name.split()
    root_note = parts[0]
    scale_type = parts[1] if len(parts) > 1 else "major"

    root_idx = note_to_idx.get(root_note, 0)

    # Templates de escala
    if scale_type.lower() == "major":
        intervals = [0, 2, 4, 5, 7, 9, 11]  # Pasos en semitonos
    else:  # minor
        intervals = [0, 2, 3, 5, 7, 8, 10]  # Natural minor

    scale_degrees = np.zeros(12, dtype=bool)
    for interval in intervals:
        scale_degrees[(root_idx + interval) % 12] = True

    return scale_degrees


def midi_to_scale_degree(midi: int) -> int:
    """Convierte MIDI a índice de nota cromática (0-11).

    Args:
        midi: Número MIDI (0-127)

    Returns:
        Índice cromático 0-11 (C a B)
    """
    return midi % 12


def is_midi_in_scale(midi: int, scale_degrees: np.ndarray) -> bool:
    """Verifica si un MIDI está en la escala detectada.

    Args:
        midi: Número MIDI
        scale_degrees: Array booleano de notas en escala

    Returns:
        True si MIDI está en la escala
    """
    scale_idx = midi_to_scale_degree(midi)
    return bool(scale_degrees[scale_idx])


@dataclass(frozen=True)
class State:
    string: Optional[int]
    fret: int
    articulation_type: str = "normal"  # 'normal' | 'dead' | 'legato'


class FretboardRouter:
    """Router que calcula la secuencia de (string, fret) de coste mínimo.

    Implementa topología Viterbi consciente de escala:
    - route_from_f0: acepta array de f0 (Hz) y devuelve (states, tab_ascii)
    - route_from_midi: acepta array con valores MIDI (int) y devuelve
      (states, tab_ascii)

    Parámetros opcionales:
    - scale_degrees: Array booleano (12 elementos) para penalizar notas
      fuera de escala
    - w_scale_penalty: Penalización por notas fuera de escala (default 5.0)
    - w_octave_discount: Descuento para transiciones de octava (default 0.5)

    Carga hiperparámetros desde config/settings.toml.
    """

    def __init__(
        self,
        settings_path: Optional[Path] = None,
        w_fret: Optional[float] = None,
        w_string: Optional[float] = None,
        w_open: Optional[float] = None,
        scale_degrees: Optional[np.ndarray] = None,
        w_scale_penalty: Optional[float] = None,
        w_octave_discount: Optional[float] = None,
        w_fourth_fifth_discount: Optional[float] = 0.4,
    ):
        settings = load_settings(settings_path)
        instrument = settings.get("instrument", {})
        weights = settings.get("router_weights", {})

        required_instrument = ("strings", "tuning_midi", "max_fret")
        missing_instrument = [
            k for k in required_instrument if k not in instrument
        ]
        if missing_instrument:
            raise KeyError(f"Missing instrument settings: {missing_instrument}")

        required_weights = ("w_fret", "w_string", "w_open")
        missing_weights = [k for k in required_weights if k not in weights]
        if missing_weights:
            raise KeyError(f"Missing router_weights settings: {missing_weights}")

        strings = int(instrument["strings"])

        tuning_low_to_high = [int(v) for v in instrument["tuning_midi"]]
        if len(tuning_low_to_high) != strings:
            raise ValueError(
                "instrument.tuning_midi length must match instrument.strings"
            )

        # Internamente usamos 1=aguda ... 4=grave.
        tuning_high_to_low = list(reversed(tuning_low_to_high))
        self.tuning = {idx + 1: tuning_high_to_low[idx] for idx in range(strings)}
        self.max_fret = int(instrument["max_fret"])
        self.strings = strings

        self.w1 = float(w_fret if w_fret is not None else weights["w_fret"])
        self.w2 = float(
            w_string if w_string is not None else weights["w_string"]
        )
        self.w3 = float(w_open if w_open is not None else weights["w_open"])
        self.quantization_grid = (0.25, 1.0 / 3.0)

        # Phase 2: Scale-aware parameters
        self.scale_degrees = (
            scale_degrees
            if scale_degrees is not None
            else np.ones(12, dtype=bool)
        )  # Default: all notes allowed
        self.w_scale_penalty = (
            float(w_scale_penalty) if w_scale_penalty is not None else 5.0
        )
        self.w_octave_discount = (
            float(w_octave_discount) if w_octave_discount is not None else 0.5
        )
        self.w_fourth_fifth_discount = (
            float(w_fourth_fifth_discount)
            if w_fourth_fifth_discount is not None
            else 0.4
        )

    def _quantize_duration(self, duration_in_beats: float) -> float:
        """Snap durations to the strict micro-beat grid used by the exporter."""
        if duration_in_beats <= 0:
            return 0.25

        candidates = sorted(
            {
                0.25,
                1.0 / 3.0,
                0.5,
                2.0 / 3.0,
                0.75,
                1.0,
                1.25,
                4.0 / 3.0,
                1.5,
                5.0 / 3.0,
                1.75,
                2.0,
            }
        )
        return min(candidates, key=lambda value: abs(value - duration_in_beats))

    def _string_label(self, string_index: int) -> str:
        """Return a human-readable string label from the configured tuning."""
        if string_index < 1 or string_index > self.strings:
            raise ValueError("string_index out of range for configured tuning")
        return pitch_module.Pitch(midi=int(self.tuning[string_index])).step

    def _emission_cost(self, midi: Optional[int]) -> float:
        """Calcula el coste de emisión para un MIDI (penalización por fuera de escala).

        Penaliza notas que caen completamente fuera del contexto diatónico detectado.
        Actúa como capa de corrección de errores contra artefactos de pYIN.

        Args:
            midi: Número MIDI o None para silencio

        Returns:
            Coste de emisión (0.0 si en escala, w_scale_penalty si fuera)
        """
        if midi is None:
            return 0.0

        if not is_midi_in_scale(midi, self.scale_degrees):
            return self.w_scale_penalty

        return 0.0

    def _midi_candidates(
        self, midi: Optional[int], articulation_type: str = "normal"
    ) -> List[State]:
        """Devuelve todos los (string,fret) válidos para un MIDI dado.
        Si midi es None o articulation_type es 'dead', devuelve fallback states.

        Para dead notes, devuelve un estado unvoiced (None, -1) con articulation='dead'
        para evitar colapso de trellis durante el traceback de Viterbi.
        """
        if midi is None or articulation_type == "dead":
            # Devolver estado fallback: unvoiced con la articulation especificada
            return [State(None, -1, articulation_type)]

        candidates: List[State] = []
        for s in range(1, self.strings + 1):
            fret = midi - self.tuning[s]
            if 0 <= fret <= self.max_fret:
                candidates.append(State(s, int(fret), articulation_type))

        if not candidates:
            # No hay representación física -> fallback rest state
            return [State(None, -1, articulation_type)]
        return candidates

    def _transition_cost(
        self,
        u: State,
        v: State,
        midi_u: Optional[int] = None,
        midi_v: Optional[int] = None,
    ) -> float:
        """Calcula el coste de transición entre dos estados.

        Implementa:
        - Coste base: distancia de fret y cuerda
        - Regla del octavo: si abs(delta_midi) == 12, descuenta fret distance
        - Regla del box shape: si ambas notas están en escala, favorece cambios de
          cuerda sobre movimiento horizontal, descuento si dentro de 4-fret block
        - Coste neutro para descansos/dead notes

        Args:
            u: Estado previo
            v: Estado actual
            midi_u: MIDI anterior (opcional, para octave/box rules)
            midi_v: MIDI actual (opcional, para octave/box rules)

        Returns:
            Coste de transición
        """
        # Si alguno es descanso o dead note, coste neutro para evitar penalización
        if u.string is None or v.string is None:
            return 0.0

        # Si la nota destino es dead, transición neutral
        if v.articulation_type == "dead":
            return 0.0

        # Coste base: movimiento horizontal y vertical
        fret_distance = abs(v.fret - u.fret)
        string_distance = abs(v.string - u.string)

        cost = self.w1 * fret_distance + self.w2 * string_distance
        # Recompensa por cuerda al aire: indicador devuelve -2.0 si fret==0
        indicator = -2.0 if v.fret == 0 else 0.0
        cost += self.w3 * indicator

        # Phase 2: Octave Rule
        # Si abs(delta_midi) == 12 (un octavo), es un slap/pop ergonómico
        # Descuenta fuertemente la distancia de fret
        if midi_u is not None and midi_v is not None:
            delta_midi = midi_v - midi_u

            # Perfect 4th / Perfect 5th Ergonomic Rule
            # Saltos de 5 o 7 semitonos favorecen cruce vertical de cuerda.
            # Se descuenta el componente horizontal (fret distance).
            if abs(delta_midi) in (5, 7):
                cost -= self.w1 * fret_distance * self.w_fourth_fifth_discount

            if abs(delta_midi) == 12:
                # Descuenta fret distance por factor w_octave_discount
                cost -= self.w1 * fret_distance * (1.0 - self.w_octave_discount)

        # Phase 2: Box Shape Rule
        # Si ambas notas están en la escala detectada:
        # - Favorece cambios de cuerda sobre movimiento horizontal (4-fret limit)
        # - Descuento si nueva nota cae dentro de 4-fret block relativo a anterior
        if (
            midi_u is not None
            and midi_v is not None
            and is_midi_in_scale(midi_u, self.scale_degrees)
            and is_midi_in_scale(midi_v, self.scale_degrees)
        ):
            # Si el movimiento de fret es pequeño (≤4), favorece string crossing
            if fret_distance <= 4:
                # Descuenta el coste del movimiento horizontal
                cost -= self.w1 * fret_distance * 0.3  # Descuento del 30%
                # Penaliza ligeramente cruce de cuerda pero menos que horizontal
                # (ya aplicado en w2, así que no se aplica penalización extra)

        return cost

    def route_from_midi(
        self,
        midi_sequence: List[Optional[int]],
        articulation_sequence: Optional[List[str]] = None,
    ) -> Tuple[List[State], str]:
        """Calcula la ruta óptima sobre una secuencia de valores MIDI.

        Para silencio, pase None. Implementa Viterbi con:
        - Costes de emisión basados en escala (penaliza notas fuera)
        - Costes de transición con regla del octavo y box shape

        Args:
            midi_sequence: List of MIDI pitches or None for rests
            articulation_sequence: Optional list of articulation types
                ('normal'|'dead'|'legato')

        Retorna (states, tab_ascii).
        """
        if articulation_sequence is None:
            articulation_sequence = ["normal"] * len(midi_sequence)

        if len(articulation_sequence) != len(midi_sequence):
            raise ValueError(
                "articulation_sequence must match midi_sequence length"
            )

        T = len(midi_sequence)
        prev_costs = {}
        prev_ptrs = []

        for t in range(T):
            midi = midi_sequence[t]
            articulation = articulation_sequence[t]

            if midi is None or midi == 0:
                candidates = [State(None, -1, articulation)]
            else:
                candidates = self._midi_candidates(midi, articulation)

            curr_costs = {}
            curr_ptr = {}

            if t == 0:
                for v in candidates:
                    # Coste de emisión para la nota inicial
                    emission_cost = self._emission_cost(midi)
                    curr_costs[v] = emission_cost
                    curr_ptr[v] = None
            else:
                for v in candidates:
                    best_cost = float("inf")
                    best_prev = None
                    midi_prev = midi_sequence[t - 1]

                    for u, u_cost in prev_costs.items():
                        # Transición cost con MIDI info para octave/box rules
                        trans_cost = self._transition_cost(
                            u, v, midi_u=midi_prev, midi_v=midi
                        )
                        # Coste de emisión para nota actual
                        emission_cost = self._emission_cost(midi)
                        c = u_cost + trans_cost + emission_cost

                        if c < best_cost:
                            best_cost = c
                            best_prev = u
                        elif c == best_cost:
                            if (
                                best_prev is not None
                                and v.fret >= 0
                                and best_prev.fret >= 0
                            ):
                                if v.fret < best_prev.fret:
                                    best_prev = u

                    curr_costs[v] = best_cost
                    curr_ptr[v] = best_prev

            prev_costs = curr_costs
            prev_ptrs.append(curr_ptr)

        if not prev_costs:
            return ([], "")
        end_state = min(prev_costs.items(), key=lambda kv: kv[1])[0]
        states = [None] * T
        for t in range(T - 1, -1, -1):
            states[t] = end_state
            end_state = prev_ptrs[t][end_state]
            if end_state is None:
                pass

        tab = self._render_tab(states, midi_sequence)
        return (states, tab)

    def estimate_key_and_set_scale(self, y: np.ndarray, sr: int = 22050) -> str:
        """Estima tonalidad desde audio y configura scale_degrees.

        Args:
            y: Señal de audio
            sr: Sample rate

        Returns:
            Nombre de la tonalidad detectada
        """
        key_name, _ = estimate_key_from_chroma(y, sr=sr, hop_length=256)
        self.scale_degrees = get_scale_degrees(key_name)
        return key_name

    def route_from_f0(
        self, f0_with_articulation: List[Tuple[float, str]]
    ) -> Tuple[List[State], str]:
        """Convierte f0 con articulation a MIDI y ejecuta el ruteo.

        Args:
            f0_with_articulation: List of tuples (f0_hz, articulation_type)

        f0==0.0 se considera silencio/rest (None)
        """
        midi_seq = []
        articulation_seq = []
        for f0_val, articulation in f0_with_articulation:
            if f0_val is None or f0_val == 0.0 or np.isnan(f0_val):
                midi_seq.append(None)
            else:
                midi_seq.append(int(round(librosa.hz_to_midi(float(f0_val)))))
            articulation_seq.append(articulation)

        return self.route_from_midi(midi_seq, articulation_seq)

    def f0_to_midi_sequence(
        self, f0_input: list
    ) -> list:
        """Convierte una secuencia de f0 a MIDI entero o None para silencios.

        Maneja tanto el formato legacy (floats) como el nuevo (tuples con articulation).
        """
        midi_seq = []
        for item in f0_input:
            # Handle both legacy (float) and new (tuple) formats
            if isinstance(item, tuple):
                f0_val = item[0]
            else:
                f0_val = item

            if f0_val is None or f0_val == 0.0 or np.isnan(f0_val):
                midi_seq.append(None)
            else:
                midi_seq.append(int(round(librosa.hz_to_midi(float(f0_val)))))
        return midi_seq

    def build_musicxml_route(
        self,
        midi_sequence: List[Optional[int]],
        states: List[State],
    ) -> List[Dict[str, object]]:
        """Construye eventos para exportación MusicXML.

        Agrupa beats consecutivos con mismo (midi, cuerda, traste,
        articulation) en un único evento para representar sustain.
        """
        if len(midi_sequence) != len(states):
            raise ValueError(
                "midi_sequence and states must have the same length."
            )
        if not states:
            return []

        events: List[Dict[str, object]] = []

        def append_event(
            midi_pitch: Optional[int],
            state: State,
            duration_in_beats: float,
        ) -> None:
            events.append(
                {
                    "midi_pitch": (
                        None if midi_pitch is None else int(midi_pitch)
                    ),
                    "string_index": (
                        None if state.string is None else int(state.string)
                    ),
                    "fret_number": (
                        None if state.string is None else int(state.fret)
                    ),
                    "duration_in_beats": float(duration_in_beats),
                    "articulation_type": state.articulation_type,
                }
            )

        current_midi = midi_sequence[0]
        current_state = states[0]
        current_duration = 1.0

        for idx in range(1, len(states)):
            midi_pitch = midi_sequence[idx]
            state = states[idx]
            if midi_pitch == current_midi and state == current_state:
                current_duration += 1.0
                continue
            append_event(
                current_midi,
                current_state,
                self._quantize_duration(current_duration),
            )
            current_midi = midi_pitch
            current_state = state
            current_duration = 1.0

        append_event(
            current_midi,
            current_state,
            self._quantize_duration(current_duration),
        )
        return events

    def _render_tab(
        self,
        states: List[State],
        midi_sequence: Optional[List[Optional[int]]] = None,
    ) -> str:
        """Crea representación ASCII con 4 líneas y barras cada 4 beats.

        - Cada carácter representa un pulso/beat (cuantizado).
        - Inserta barras '|' cada 4 beats para agrupar en compases 4/4.
        """
        if not states:
            return ""

        # Anchura de celda según dígitos de traste
        max_fret = max((s.fret for s in states if s.fret >= 0), default=0)
        cell_w = max(1, len(str(max_fret)))

        lines = {string_index: [] for string_index in range(1, self.strings + 1)}
        previous_midi = None

        for beat_idx, state in enumerate(states):
            # Cada beat_idx=0,1,2,3 forma un compás; cada beat_idx%4==0 = nueva barra
            if beat_idx > 0 and beat_idx % 4 == 0:
                # Insertar barra de compás
                for s_idx in range(1, 5):
                    lines[s_idx].append("|")

            current_midi = None
            if midi_sequence is not None and beat_idx < len(midi_sequence):
                current_midi = midi_sequence[beat_idx]
            is_sustain = (
                beat_idx > 0
                and state.string is not None
                and previous_midi is not None
                and current_midi is not None
                and current_midi == previous_midi
            )

            # Renderizar la nota de este beat en cada cuerda
            for s_idx in range(1, self.strings + 1):
                if state.string == s_idx:
                    if state.fret >= 0 and not is_sustain:
                        # Número de traste, centrado en la celda
                        cell = str(state.fret).rjust(cell_w, " ")
                    else:
                        # Sustain o descanso en cuerda al aire (oculto)
                        cell = "-" * cell_w
                else:
                    # Silencio en esta cuerda
                    cell = "-" * cell_w
                lines[s_idx].append(cell)
            previous_midi = current_midi

        # Combinar en texto con nombres de cuerda al inicio
        text_lines = []
        for s_idx in range(1, self.strings + 1):
            prefix = self._string_label(s_idx) + "|"
            text_lines.append(prefix + "".join(lines[s_idx]))
        return "\n".join(text_lines)
