from pathlib import Path
from typing import Any, Dict, Optional, Union


def _resolve_path(value: Union[str, Path]) -> Path:
    return Path(value).expanduser().resolve()


def run_pipeline(
    audio_file: Union[str, Path],
    lang: str = "en",
    settings_path: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """Run the full pipeline programmatically and return artifact paths and metadata.

    This is a lightweight programmatic client that mirrors the CLI orchestration
    but returns structured results for use in other Python code or tests.

    Returns a dict with keys:
      - 'bass_stem': Path to isolated bass stem (if generated)
      - 'musicxml': Path to exported MusicXML (if generated)
      - 'ascii_tab': ASCII tab string
      - 'bpm': detected tempo (float)
      - 'route_events': list of routing event dicts used for export

    Note: Errors raise exceptions — callers should catch and handle them.
    """
    # Local imports to keep top-level import cheap and allow optional deps
    from punkito_tabs_oracle.cli import cargar_locales
    from punkito_tabs_oracle.ml.separator import BassSeparator
    from punkito_tabs_oracle.dsp.pitch import PitchTracker
    from punkito_tabs_oracle.tab.router import FretboardRouter
    from punkito_tabs_oracle.tab.exporter import MusicXMLExporter

    locales = cargar_locales(lang)
    audio_path = _resolve_path(audio_file)

    # 1. ML separation (may be a stub in some dev environments)
    output_dir = Path("./stems_output")
    separator = BassSeparator(output_dir=output_dir, locales=locales)
    bass_stem = separator.aislar(audio_path)

    # 2. DSP pitch tracking (now returns tuples with articulation)
    tracker = PitchTracker(settings_path=Path(settings_path) if settings_path else None)
    f0_pulsos_with_articulation, bpm = tracker.obtener_f0_por_pulso(bass_stem)

    # 3. Routing (now passes articulation through the Viterbi path)
    router = FretboardRouter(settings_path=Path(settings_path) if settings_path else None)
    states, ascii_tab = router.route_from_f0(f0_pulsos_with_articulation)

    # Extract MIDI sequence from f0 values for route building
    midi_seq = []
    for f0_val, _ in f0_pulsos_with_articulation:
        if f0_val is None or f0_val == 0.0:
            midi_seq.append(None)
        else:
            import librosa
            midi_seq.append(int(round(librosa.hz_to_midi(float(f0_val)))))

    route_events = router.build_musicxml_route(midi_sequence=midi_seq, states=states)

    # 4. Export (now handles articulation metadata in notes)
    musicxml_path = Path(bass_stem).parent / "bass_tab.musicxml"
    exporter = MusicXMLExporter(route_events, tempo_bpm=bpm, settings_path=Path(settings_path) if settings_path else None)
    exported = exporter.write(musicxml_path)

    return {
        "bass_stem": Path(bass_stem),
        "musicxml": Path(exported),
        "ascii_tab": ascii_tab,
        "bpm": float(bpm),
        "route_events": route_events,
    }
