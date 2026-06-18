# Punkito Tabs Oracle: Current Architecture (June 2026)

This document reflects the **current functional state** of the repository. Project Status: ✅ Milestone 1 (Advanced Articulations) — ML, DSP, routing, MusicXML export, ghost notes, and legato detection integrated.

The current architecture separates concerns across ML, DSP, routing, and export so each stage can be tuned independently while preserving deterministic end-to-end behavior.

## 1. Implemented System Flow

```text
Input Audio File
   -> CLI validation (language, ffmpeg, path, extension)
   -> ML separation (Spleeter 4 stems)
   -> Isolated bass stem (bass.wav)
   -> DSP pitch tracking (pYIN + cubic interpolation)
   -> Articulation detection (ghost notes, legato) ← NEW Milestone 1
   -> Beat-quantized f0 sequence with articulation types ← UPDATED
   -> Fretboard routing (dynamic programming with articulation metadata) ← UPDATED
   -> ASCII tablature output
   -> MusicXML export with technical string/fret metadata + dead note symbols + legato slurs ← UPDATED
```

## 2. Repository Layout and Responsibilities

```text
punkito-tabs-oracle/
├── config/
│   ├── locales/
│   │   ├── en.json
│   │   └── es.json
│   └── settings.toml
├── src/punkito_tabs_oracle/
│   ├── cli.py
│   ├── ml/separator.py
│   ├── dsp/pitch.py
│   └── tab/
│       ├── router.py
│       └── exporter.py
└── tests/
    ├── test_dsp.py
    └── test_tab.py
```

### `src/punkito_tabs_oracle/cli.py`
- Entry point for `punkito-tabs`.
- Loads i18n messages from `config/locales`.
- Validates input audio and `ffmpeg` availability.
- Orchestrates ML -> DSP -> TAB sequence.
- Exports `stems_output/<audio_name>/bass_tab.musicxml` after routing.

The CLI is intentionally thin: it coordinates stage boundaries, surfaces user-facing status/errors, and writes final artifacts without embedding DSP or routing logic.

### `src/punkito_tabs_oracle/ml/separator.py`
- `BassSeparator` wraps Spleeter (`spleeter:4stems`).
- Runs separation and stores outputs under `stems_output/<input_name>/`.
- Returns the generated `bass.wav` absolute path.

### `src/punkito_tabs_oracle/dsp/pitch.py` — Milestone 1: Articulation Detection
- `PitchTracker.estimar_f0()` computes frame-level f0.
- Uses `librosa.pyin` first, then cubic interpolation for low-confidence or unvoiced frames.
- Applies RMS silence masking (`f0=0.0` in low-energy frames).
- **NEW**: `_detect_ghost_notes()` uses `librosa.onset_detect` + `spectral_flatness` to identify percussive hits without clear pitch.
- **NEW**: `_detect_legato()` uses pitch contour derivatives to identify smooth transitions without sharp onsets.
- `obtener_f0_por_pulso()` detects tempo/beats and returns beat-level tuples: `(f0_median, articulation_type)`.
- Articulation types: `'normal'` | `'dead'` (ghost notes) | `'legato'` (slurs).

### `src/punkito_tabs_oracle/tab/router.py` — Milestone 1: Articulation-Aware Routing
- `FretboardRouter.route_from_f0()` accepts f0 + articulation tuples from DSP.
- **NEW**: `State` dataclass extended to include `articulation_type` field.
- Converts f0/MIDI to ergonomic `(string, fret)` paths using dynamic programming.
- Articulation metadata travels through the Viterbi path unchanged (cost function is pitch/fret/string only).
- Uses transition cost terms loaded from `config/settings.toml`.
- Supports rests and renders 4-string ASCII tablature with bar separators every 4 beats.
- **NEW**: Emits route events with `articulation_type` field: `(midi_pitch, string_index, fret_number, duration_in_beats, articulation_type)`.

### `src/punkito_tabs_oracle/tab/exporter.py` — Milestone 1: Articulation Rendering
- `MusicXMLExporter` builds a `music21` Electric Bass part in Bass Clef.
- Writes rhythmic notes/rests and preserves physical fingering via MusicXML `<technical>` metadata.
- **NEW**: Dead notes (ghost notes) rendered with `notehead='x'` (cross symbol in notation).
- **NEW**: Legato transitions dynamically wrapped in `music21.spanner.Slur()` objects for arc rendering.
- **NEW**: `build_part()` tracks legato sequences and appends slurs after each phrase break.
- Output is compatible with MuseScore, Guitar Pro, AlphaTab, and Songsterr-style rendering engines.

This guarantees interoperability: downstream notation tools receive both the musical event stream and the exact physical fingering selected by the router.

## 3. Test Coverage (Current)

### `tests/test_dsp.py`
- Validates pitch estimation accuracy on synthetic sine waves.
- Validates beat-quantized output behavior.

### `tests/test_tab.py`
- Validates open-string/low-fret decisions.
- Validates bar rendering in ASCII tab output.
- Validates rest handling.

## 4. Current Gaps

- No end-to-end integration tests covering full CLI + ML + DSP + TAB runtime chain.
- `config/settings.toml` contains instrument, router, and DSP parameters used at runtime.
- Heavy runtime dependencies (Spleeter/TensorFlow + Python version constraints) require controlled environment setup.

## 5. Next Milestones

**Milestone 1 (✅ Complete)**: Advanced articulation detection for monophonic bass
- Ghost note detection (onset + spectral flatness)
- Legato detection (pitch contour derivatives)
- Dead note symbols in MusicXML
- Legato slur rendering with music21

**Milestone 2 (Planned)**: Enhanced articulation & technique detection
1. Slide detection and time-quantized rendering
2. Bend detection (pitch excursions) and cent-level annotation
3. Harmonics detection (natural, artificial, pinch)
4. Refined onset clustering to improve ghost/legato disambiguation

**Milestone 3 (Planned)**: Polyphonic transcription
1. Multi-note chord voicing
2. Independent articulation per voice
3. Voice leading optimization

**Milestone 4 (Planned)**: User interface & deployment
1. Integration tests for complete pipeline
2. Batch processing over multiple input files
3. GUI/Web interface on top of CLI
4. Performance optimization for long tracks

---

## 6. Detailed Documentation

- **[ARTICULATION_DETECTION.md](./ARTICULATION_DETECTION.md)**: Deep dive into ghost note and legato detection algorithms, including implementation details, configuration, and music21 integration.
