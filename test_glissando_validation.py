"""Script de validación rápida para verificar glissando vs slur."""
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from music21 import spanner
from punkito_tabs_oracle.tab.exporter import MusicXMLExporter


def test_glissando_detection():
    """Test que una secuencia de slides genera Glissando."""
    # Simular configuración
    import punkito_tabs_oracle.tab.exporter as exp_module
    original_load = exp_module.load_settings
    
    def mock_settings(path=None):
        return {
            "instrument": {
                "strings": 4,
                "tuning_midi": [28, 33, 38, 43],
                "max_fret": 24,
            }
        }
    
    exp_module.load_settings = mock_settings
    
    try:
        # Slide: E1 (28) -> F1 (29) -> F#1 (30) en la misma cuerda 4
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
        
        # Contar spanners
        glissandos = [elem for elem in part if isinstance(elem, spanner.Glissando)]
        slurs = [elem for elem in part if isinstance(elem, spanner.Slur)]
        
        print(f"✓ Glissandos encontrados: {len(glissandos)}")
        print(f"✓ Slurs encontrados: {len(slurs)}")
        
        assert len(glissandos) == 2, f"Esperaba 2 Glissandos, obtuve {len(glissandos)}"
        assert len(slurs) == 0, f"Esperaba 0 Slurs, obtuve {len(slurs)}"
        
        print("\n✅ TEST PASADO: Slides correctamente convertidos a Glissando")
        return True
        
    finally:
        exp_module.load_settings = original_load


def test_slur_for_different_strings():
    """Test que legato en diferentes cuerdas genera Slur."""
    import punkito_tabs_oracle.tab.exporter as exp_module
    original_load = exp_module.load_settings
    
    def mock_settings(path=None):
        return {
            "instrument": {
                "strings": 4,
                "tuning_midi": [28, 33, 38, 43],
                "max_fret": 24,
            }
        }
    
    exp_module.load_settings = mock_settings
    
    try:
        # Legato en cuerdas diferentes
        route_items = [
            {
                "midi_pitch": 28,
                "string_index": 4,
                "fret_number": 0,
                "duration_in_beats": 1.0,
                "articulation_type": "legato",
            },
            {
                "midi_pitch": 33,
                "string_index": 3,
                "fret_number": 0,
                "duration_in_beats": 1.0,
                "articulation_type": "legato",
            },
        ]
        
        exporter = MusicXMLExporter(route_items, tempo_bpm=120)
        part = exporter.build_part()
        
        glissandos = [elem for elem in part if isinstance(elem, spanner.Glissando)]
        slurs = [elem for elem in part if isinstance(elem, spanner.Slur)]
        
        print(f"\n✓ Glissandos encontrados: {len(glissandos)}")
        print(f"✓ Slurs encontrados: {len(slurs)}")
        
        assert len(glissandos) == 0, f"Esperaba 0 Glissandos, obtuve {len(glissandos)}"
        assert len(slurs) == 1, f"Esperaba 1 Slur, obtuve {len(slurs)}"
        
        print("✅ TEST PASADO: Legato en diferentes cuerdas genera Slur")
        return True
        
    finally:
        exp_module.load_settings = original_load


if __name__ == "__main__":
    print("=== Validando detección de Glissando vs Slur ===\n")
    
    try:
        test_glissando_detection()
        test_slur_for_different_strings()
        print("\n🎉 TODOS LOS TESTS PASARON")
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
