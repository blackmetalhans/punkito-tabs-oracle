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
