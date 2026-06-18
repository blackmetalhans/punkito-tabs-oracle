# tests/test_tab.py
from punkito_tabs_oracle.tab.router import FretboardRouter, State


def test_router_prefers_open_and_low_frets():
    """Secuencia determinista de MIDI: 28 (E open), 33 (A open), 45 (A2 preferir traste bajo), 28 (E open)
    Verificar que el ruteador elige cuerdas abiertas cuando es posible y posiciones de traste bajas.
    """
    midi_seq = [28, 33, 45, 28]
    router = FretboardRouter()
    states, tab = router.route_from_midi(midi_seq)

    # Estado para 28 debe ser cuerda E (4), traste 0
    assert states[0].string == 4 and states[0].fret == 0
    # Estado para 33 debe ser cuerda A (3), traste 0
    assert states[1].string == 3 and states[1].fret == 0
    # Estado para 45 debe preferir cuerda G (1) traste 2 (la opción de menor traste)
    assert states[2].string == 1 and states[2].fret == 2
    # Estado final 28 de nuevo cuerda E abierta
    assert states[3].string == 4 and states[3].fret == 0

    # El ASCII tab debe contener al menos los caracteres '0' para las cuerdas abiertas
    assert '0' in tab


def test_router_beat_quantized_with_bars():
    """Verificar que el ruteador renderiza compases con barras cada 4 beats en formato 4/4."""
    # Secuencia de 8 beats (2 compases): 28 (E), 33 (A), 45 (A), 40 (E), 28 (E), 33 (A), 45 (A), 40 (E)
    f0_pulsos = [82.41, 110.0, 220.0, 164.81, 82.41, 110.0, 220.0, 164.81]  # Hz
    router = FretboardRouter()
    states, tab = router.route_from_f0(f0_pulsos)

    # Verificar que tenemos 8 estados
    assert len(states) == 8, f"Se esperaban 8 estados, pero se obtuvieron {len(states)}"
    # Todos los estados deben ser válidos (no rest)
    for s in states:
        assert s.string is not None, "No se esperaban descansos en esta secuencia"

    # El tab debe contener barras '|' para los compases
    # En la primera línea esperamos: G|xxxx|xxxx (barra en posición ~4)
    lines = tab.split('\n')
    assert len(lines) == 4, "El tab debe tener 4 líneas"
    # Contar las barras en la primera línea (después del prefijo "G|")
    first_line = lines[0]
    bar_count = first_line.count('|') - 1  # Restar el prefijo inicial
    assert bar_count > 0, "Se espera al menos una barra de compás interior"


def test_router_handles_rests():
    """Verificar que el ruteador maneja correctamente los silencios/descansos."""
    # Secuencia: 28 (nota), 0 (rest), 28 (nota), 0 (rest)
    midi_seq = [28, None, 28, None]
    router = FretboardRouter()
    states, tab = router.route_from_midi(midi_seq)

    # Los estados con None deben ser rest (None, -1)
    assert states[0].string == 4 and states[0].fret == 0  # E open
    assert states[1].string is None and states[1].fret == -1  # Rest
    assert states[2].string == 4 and states[2].fret == 0  # E open
    assert states[3].string is None and states[3].fret == -1  # Rest

    # El tab debe ser válido
    assert '\n' in tab, "El tab debe contener múltiples líneas"


def test_router_renders_sustain_without_retrigger():
    """Si el pitch se repite en beats consecutivos, debe mostrarse sustain sin retrigger."""
    midi_seq = [28, 28, 28, 28]
    router = FretboardRouter()
    _, tab = router.route_from_midi(midi_seq)

    lines = tab.split("\n")
    assert len(lines) == 4
    e_line = lines[3]
    assert e_line.startswith("E|")
    assert e_line == "E|0---"
