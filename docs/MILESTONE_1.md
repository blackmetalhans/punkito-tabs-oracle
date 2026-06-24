# Milestone 1 Technical Summary

## Scope

Milestone 1 introduced articulation-aware monophonic bass transcription in the existing audio-to-tab pipeline:

- Ghost note (dead note) detection
- Legato detection
- Articulation metadata propagation through routing
- MusicXML articulation rendering

## Architecture and Design Decisions

1. **Pipeline continuity preserved**  
   Existing ML → DSP → Router → Export structure was kept, and articulation metadata was added without replacing core stages.

2. **Beat-level articulation output**  
   Frame-level DSP detection is aggregated per beat in `PitchTracker.obtener_f0_por_pulso()` and emitted as tuples:
   - `(f0_value, "normal" | "dead" | "legato")`

3. **Routing metadata extension without cost-function rewrite**  
   `State` in `tab/router.py` was extended with `articulation_type`, while Viterbi routing cost behavior remained unchanged.

4. **Notation compatibility through music21 primitives**  
   - Dead notes: `notehead = "x"`
   - Legato: `music21.spanner.Slur(...)` over consecutive legato notes

## Main Code Changes

### `src/punkito_tabs_oracle/dsp/pitch.py`
- Added `_detect_ghost_notes()`
- Added `_detect_legato()`
- Added `detect_slides()` (frame-level slide region detection) and integrated slide regions into beat-level aggregation
- Refactored `obtener_f0_por_pulso()` to return articulation-aware beat tuples `(f0_hz, articulation_type)`
- Kept backward compatibility via `obtener_f0_por_pulso_legacy()`

### `src/punkito_tabs_oracle/tab/router.py`
- Extended `State` dataclass with `articulation_type: str = "normal"`
- Updated routing methods to preserve articulation metadata
- Updated MusicXML route event generation to include `articulation_type`

### `src/punkito_tabs_oracle/tab/exporter.py`
- Extended exported item model with `articulation_type`
- Updated `build_part()` to render dead notes and slurs

### Integration updates
- `src/punkito_tabs_oracle/client.py` updated to handle articulation tuples
- `README.md` and `docs/ARCHITECTURE.md` updated to reflect milestone capabilities

## API and Data Contract Changes

### DSP output contract
- Previous pattern: beat-level f0 values
- Milestone 1 pattern: beat-level tuples with articulation labels

### Router state contract
- `State` now carries articulation metadata from DSP through routing and export preparation

### Export contract
- Route events include articulation type used by `MusicXMLExporter`

## Configuration and Tunables

Milestone documentation identifies DSP thresholds and settings (in `config/settings.toml`) used for articulation behavior. Key parameters:

- `voiced_confidence_threshold` (float) — pYIN voiced-prob threshold used to decide voiced frames (default: `0.05`).
- `ghost_spectral_flatness_threshold` (float) — spectral flatness threshold for ghost/dead-note detection (default: `0.5`).
- `slide_pitch_change_threshold_hz` (float) — minimum pitch change rate (Hz/frame) to consider a slide region.
- `slide_min_duration_frames` (int) — minimum consecutive frames for a slide region to be considered (default: `3`).
- `ghost_onset_voicing_balance` (float) — weighting factor between onset detection and voicedness when classifying ghosts.

These parameters are read from `config/settings.toml` under `[dsp]` and may be tuned without changing code. The pipeline now integrates `detect_slides()` during frame-level analysis; detected slide regions are used when aggregating beat-level articulations to optionally mark beats as `slide` or to annotate transition metadata.

## Verification and Coverage (as reported in milestone documents)

- Python syntax checks reported as passing for modified modules
- Type hints and docstrings were added/extended in changed components
- Backward compatibility paths were documented:
  - Legacy DSP output method remains available
  - Router supports legacy and articulation-aware inputs

Repository tests referenced for ongoing coverage:
- DSP behavior tests (`tests/test_dsp.py`)
- Routing and tablature tests (`tests/test_tab.py`, `tests/test_router_dead_notes.py`)
- Export behavior tests (`tests/test_exporter.py`)
- API tests (`tests/test_api.py`)

## Reported Implementation Metrics

From milestone documentation artifacts:

- Core implementation concentrated in three modules (`pitch.py`, `router.py`, `exporter.py`)
- Documentation deliverables for milestone completion were produced and are now consolidated into this document

## Limitations and Follow-up

- Milestone 1 scope is monophonic transcription
- Later milestones were documented for additional techniques (e.g., advanced articulation and broader voicing support)
