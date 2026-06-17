# -*- coding: utf-8 -*-
"""
Ruteador de trastes para bajo de 4 cuerdas.
Modela el mapeo de una secuencia temporal de f0 (Hz) -> MIDI -> (String, Fret)
como un problema de camino mínimo (programación dinámica / Viterbi-like).

Comentarios en español.
"""
from typing import List, Tuple, Optional
from dataclasses import dataclass

import numpy as np
import librosa


# Definiciones y constantes
STRING_ORDER = {1: "G", 2: "D", 3: "A", 4: "E"}  # 1 = G (más aguda), 4 = E (más grave)
TUNING = {1: 43, 2: 38, 3: 33, 4: 28}  # MIDI base notes por cuerda
MAX_FRET = 21


@dataclass(frozen=True)
class State:
    string: Optional[int]
    fret: int


class FretboardRouter:
    """Router que calcula la secuencia de (string, fret) de coste mínimo.

    - route_from_f0: acepta array de f0 (Hz) y devuelve (states, tab_ascii)
    - route_from_midi: acepta array con valores MIDI (int) y devuelve (states, tab_ascii)

    Los pesos por defecto siguen la especificación.
    """

    def __init__(self, w1: float = 1.0, w2: float = 0.5, w3: float = 1.0):
        self.w1 = float(w1)
        self.w2 = float(w2)
        self.w3 = float(w3)

    def _midi_candidates(self, midi: Optional[int]) -> List[State]:
        """Devuelve todos los (string,fret) válidos para un MIDI dado.
        Si midi es None, devuelve sólo el estado de descanso.
        """
        if midi is None:
            return [State(None, -1)]
        candidates: List[State] = []
        for s in range(1, 5):
            fret = midi - TUNING[s]
            if 0 <= fret <= MAX_FRET:
                candidates.append(State(s, int(fret)))
        if not candidates:
            # No hay representación física -> rest
            return [State(None, -1)]
        return candidates

    def _transition_cost(self, u: State, v: State) -> float:
        # Si alguno es descanso, coste 0
        if u.string is None or v.string is None:
            return 0.0
        # Coste de movimiento horizontal y vertical
        cost = self.w1 * abs(v.fret - u.fret) + self.w2 * abs(v.string - u.string)
        # Recompensa por cuerda al aire: indicador devuelve -2.0 si fret==0
        indicator = -2.0 if v.fret == 0 else 0.0
        cost += self.w3 * indicator
        return cost

    def route_from_midi(self, midi_sequence: List[Optional[int]]) -> Tuple[List[State], str]:
        """Calcula la ruta óptima sobre una secuencia de valores MIDI (o None para silencio).

        Retorna (states, tab_ascii).
        """
        T = len(midi_sequence)
        # Estado inicial: en t=-1 no hay estado; para t=0 inicializamos costos a 0
        prev_costs = {}
        prev_ptrs = []  # lista de dicts para backpointers

        # Para t=0..T-1
        for t in range(T):
            midi = midi_sequence[t]
            if midi is None or midi == 0:
                # Treat zero or None as rest
                candidates = [State(None, -1)]
            else:
                candidates = self._midi_candidates(midi)

            curr_costs = {}
            curr_ptr = {}

            if t == 0:
                # Inicializar: coste 0 para cada candidato
                for v in candidates:
                    curr_costs[v] = 0.0
                    curr_ptr[v] = None
            else:
                # Para cada candidato v buscar mejor previo u
                for v in candidates:
                    best_cost = float("inf")
                    best_prev = None
                    for u, u_cost in prev_costs.items():
                        c = u_cost + self._transition_cost(u, v)
                        if c < best_cost:
                            best_cost = c
                            best_prev = u
                        elif c == best_cost:
                            # Romper empates favoreciendo menor traste (más cercano al nut)
                            if best_prev is not None and v.fret >= 0 and best_prev.fret >= 0:
                                if v.fret < best_prev.fret:
                                    best_prev = u
                    curr_costs[v] = best_cost
                    curr_ptr[v] = best_prev

            prev_costs = curr_costs
            prev_ptrs.append(curr_ptr)

        # Backtrack: elegir estado final de menor coste
        if not prev_costs:
            return ([], "")
        end_state = min(prev_costs.items(), key=lambda kv: kv[1])[0]
        states = [None] * T
        # Reconstruct en reversa
        for t in range(T - 1, -1, -1):
            states[t] = end_state
            end_state = prev_ptrs[t][end_state]
            if end_state is None:
                # reached start
                pass

        # Render ASCII tab
        tab = self._render_tab(states)
        return (states, tab)

    def route_from_f0(self, f0_array: List[float]) -> Tuple[List[State], str]:
        """Convierte f0 (Hz) a MIDI y ejecuta el ruteo.

        - f0==0.0 se considera silencio/rest (None)
        """
        midi_seq = []
        for f in f0_array:
            if f is None or f == 0.0 or np.isnan(f):
                midi_seq.append(None)
            else:
                midi_seq.append(int(round(librosa.hz_to_midi(float(f)))))
        return self.route_from_midi(midi_seq)

    def _render_tab(self, states: List[State]) -> str:
        """Crea una representación ASCII clásica de 4 líneas.

        - Colapsa secuencias idénticas en una sola columna por grupo para limpieza.
        """
        # Agrupar tramos consecutivos idénticos
        groups = []  # list of (state, length)
        if not states:
            return ""
        prev = states[0]
        count = 1
        for s in states[1:]:
            if s == prev:
                count += 1
            else:
                groups.append((prev, count))
                prev = s
                count = 1
        groups.append((prev, count))

        # Anchura de celda según dígitos de traste
        max_fret = max((g[0].fret for g in groups if g[0].fret >= 0), default=0)
        cell_w = max(2, len(str(max_fret)))

        # Construir líneas, orden G, D, A, E (1..4)
        lines = {1: [], 2: [], 3: [], 4: []}
        sep = "-" * cell_w
        for (state, length) in groups:
            # Por simplicidad, representar cada grupo con una columna que contiene el número de traste (si existe)
            for s_idx in range(1, 5):
                if state.string == s_idx:
                    if state.fret >= 0:
                        cell = str(state.fret).rjust(cell_w, " ")
                    else:
                        cell = " " * cell_w
                else:
                    cell = sep
                lines[s_idx].append(cell)
            # Añadir un separador corto entre grupos para legibilidad
            for s_idx in range(1, 5):
                lines[s_idx].append(sep)

        # Combinar en texto con nombres de cuerda al inicio
        text_lines = []
        for s_idx in [1, 2, 3, 4]:
            prefix = STRING_ORDER[s_idx] + "|"
            text_lines.append(prefix + "".join(lines[s_idx]))
        return "\n".join(text_lines)
