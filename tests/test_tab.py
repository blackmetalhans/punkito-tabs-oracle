# tests/test_tab.py
import pytest
from music21 import spanner

from punkito_tabs_oracle.tab.router import FretboardRouter, State
from punkito_tabs_oracle.tab.exporter import MusicXMLExporter


@pytest.fixture(autouse=True)
def _mock_router_settings(monkeypatch):
    monkeypatch.setattr(
        "punkito_tabs_oracle.tab.router.load_settings",
        lambda _settings_path=None: {
            "instrument": {
                "strings": 4,
                "tuning_midi": [28, 33, 38, 43],
                "max_fret": 24,
            },
            "router_weights": {
                "w_fret": 1.0,
                "w_string": 0.5,
                "w_open": -0.2,
            },
        },
    )


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
    f0_pulsos = [
        (82.41, "normal"),
        (110.0, "normal"),
        (220.0, "normal"),
        (164.81, "normal"),
        (82.41, "normal"),
        (110.0, "normal"),
        (220.0, "normal"),
        (164.81, "normal"),
    ]  # Hz
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


def test_router_builds_musicxml_route_with_sustain_grouping():
    router = FretboardRouter()
    midi_seq = [28, 28, None, None, 33]
    states, _ = router.route_from_midi(midi_seq)
    route = router.build_musicxml_route(midi_seq, states)

    assert len(route) == 3
    assert route[0] == {
        "midi_pitch": 28,
        "string_index": 4,
        "fret_number": 0,
        "duration_in_beats": 2.0,
        "articulation_type": "normal",
    }
    assert route[1] == {
        "midi_pitch": None,
        "string_index": None,
        "fret_number": None,
        "duration_in_beats": 2.0,
        "articulation_type": "normal",
    }
    assert route[2]["midi_pitch"] == 33
    assert route[2]["duration_in_beats"] == 1.0


def test_musicxml_exporter_creates_glissando_for_slides(monkeypatch):
    """Test that ascending f0 on same string creates Glissando, not Slur."""
    monkeypatch.setattr(
        "punkito_tabs_oracle.tab.exporter.load_settings",
        lambda _settings_path=None: {
            "instrument": {
                "strings": 4,
                "tuning_midi": [28, 33, 38, 43],
                "max_fret": 24,
            }
        },
    )
    
    # Simulate a slide: E1 (28) to F1 (29) to F#1 (30) on same string (4th string)
    # All marked as "legato" to trigger slide detection
    route_items = [
        {
            "midi_pitch": 28,
            "string_index": 4,
            "fret_number": 0,
            "duration_in_beats": 1.0,
            "articulation_type": "legato",
        },
        {
            "midi_pitch": 29,
            "string_index": 4,
            "fret_number": 1,
            "duration_in_beats": 1.0,
            "articulation_type": "legato",
        },
        {
            "midi_pitch": 30,
            "string_index": 4,
            "fret_number": 2,
            "duration_in_beats": 1.0,
            "articulation_type": "legato",
        },
    ]
    
    exporter = MusicXMLExporter(route_items, tempo_bpm=120)
    part = exporter.build_part()
    
    # Verify that we have Glissando spanners, not Slur
    glissandos = [elem for elem in part if isinstance(elem, spanner.Glissando)]
    slurs = [elem for elem in part if isinstance(elem, spanner.Slur)]
    
    assert len(glissandos) > 0, "Expected at least one Glissando for slide sequence"
    assert len(slurs) == 0, "Expected no Slur for slide sequence"
    
    # Verify glissando connects consecutive notes
    assert len(glissandos) == 2, "Expected 2 Glissandos for 3-note slide"
