# Articulation Detection — Milestone 1 Technical Documentation

**Punkito Tabs Oracle** now includes advanced articulation detection for monophonic bass transcription. This document explains the DSP algorithms, data flow, and integration points.

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [Ghost Note Detection](#ghost-note-detection)
3. [Legato/Slur Detection](#legatoslur-detection)
4. [Data Flow Through the Pipeline](#data-flow-through-the-pipeline)
5. [API Reference](#api-reference)
6. [Configuration](#configuration)
7. [Music21 Integration](#music21-integration)
8. [Examples](#examples)

---

## Overview

The articulation detection pipeline extends the baseline monophonic bass transcription with three key enhancements:

| Articulation | Detection Method | MusicXML Rendering | Use Case |
|---|---|---|---|
| **Normal** | No special onset or legato cues | Standard note | Regular played notes |
| **Dead (Ghost)** | Onset + low voicedness OR high spectral flatness | `notehead='x'` | Percussive muting (slap bass, muted pick) |
| **Legato** | Continuous pitch without sharp onset | `music21.spanner.Slur()` | Hammer-ons, pull-offs, slides within a fret position |

### Key Design Decisions

1. **Monophonic Only**: Detection is optimized for single-note bass lines. Polyphonic voicing is future work.
2. **Beat Quantization**: Articulation types are assigned per beat, not per frame, for cleaner transcription.
3. **Viterbi Integration**: The articulation type travels through the dynamic-programming path, ensuring consistency.
4. **Music21 Rendering**: Dead notes use standard `notehead='x'` (cross). Legato notes are spanned by `Slur` objects.

---

## Ghost Note Detection

### Concept

A **ghost note (dead note)** is a percussive impact on the strings without clear pitch definition. Common in slap bass, muted pick technique, or accidental finger-muting.

Detection heuristic:
- Strong onset (transient spike in energy) **AND**
- Low voiced confidence (pYIN reports weak or absent pitch) **OR**
- High spectral flatness (energy spread across frequencies, not a tonal peak)

### Algorithm

```
For each beat interval [start_frame, end_frame]:
  1. Run librosa.onset_detect(y, hop_length=hop_length)
     → yields frame indices of percussive onsets
  
  2. For each onset frame:
     a. Check voiced_prob[onset_frame] < voiced_confidence_threshold
        (default: 0.05)
     b. Check spectral_flatness[onset_frame] > 0.5
        (normalized entropy; >0.5 = noise-like)
     
     If (a) OR (b) → mark as ghost note
  
  3. Aggregate ghost_notes mask per beat interval
     If count(ghost_notes in interval) > 0:
       articulation_type = 'dead'
```

### Implementation in `pitch.py`

```python
def _detect_ghost_notes(
    self,
    y: np.ndarray,
    f0: np.ndarray,
    voiced_prob: np.ndarray,
    beat_frames: np.ndarray,
) -> np.ndarray:
    """Detect ghost notes using onset_detect + spectral_flatness."""
    onsets = librosa.onset.onset_detect(
        y=y,
        sr=self.sr,
        hop_length=self.hop_length,
        backtrack=True,
    )
    
    spectral_flatness = librosa.feature.spectral_flatness(
        y=y, hop_length=self.hop_length
    )[0]
    
    ghost_notes = np.zeros(len(f0), dtype=bool)
    
    for onset_frame in onsets:
        onset_idx = int(np.clip(onset_frame, 0, len(f0) - 1))
        is_weak_voiced = (
            voiced_prob[onset_idx] < self.voiced_confidence_threshold
        )
        is_percussive = spectral_flatness[onset_idx] > 0.5
        
        if is_weak_voiced or is_percussive:
            ghost_notes[onset_idx] = True
    
    return ghost_notes
```

### Output

- **Array shape**: `(n_frames,)` boolean mask
- **Usage**: Aggregated per beat in `obtener_f0_por_pulso()` to assign `articulation_type='dead'`

---

## Legato/Slur Detection

### Concept

A **legato** (slur) transition occurs when a bassist moves between fretted positions via hammer-on, pull-off, or slide *without rearticulation*. The pitch changes smoothly without a sharp onset.

Detection heuristic:
- Both frames are voiced (pYIN confidence > threshold) **AND**
- No sharp onset at the transition frame **AND**
- Continuous pitch contour (derivative not discontinuous)

### Algorithm

```
For each frame i in [1, n_frames]:
  1. Check if f0[i-1] > 0 AND f0[i] > 0 (both voiced)
  2. Check if i is NOT in onset_set (no sharp attack)
  3. Compute pitch derivative: df/dt[i] = gradient(f0)[i]
  4. If all conditions true: mark frame i as legato
  
Result: legato_mask[i] = True for legato transition points
```

### Implementation in `pitch.py`

```python
def _detect_legato(
    self,
    f0: np.ndarray,
    voiced_prob: np.ndarray,
    onsets: np.ndarray,
) -> np.ndarray:
    """Detect legato using pitch contour derivatives."""
    legato_mask = np.zeros(len(f0), dtype=bool)
    
    f0_valid = f0.copy()
    f0_valid[f0_valid <= 0.0] = np.nan
    pitch_derivative = np.gradient(f0_valid)
    
    onset_set = set(
        int(np.clip(o, 0, len(f0) - 1)) for o in onsets
    )
    
    for i in range(1, len(f0)):
        prev_voiced = (
            f0[i - 1] > 0.0 and 
            voiced_prob[i - 1] >= self.voiced_confidence_threshold
        )
        curr_voiced = (
            f0[i] > 0.0 and 
            voiced_prob[i] >= self.voiced_confidence_threshold
        )
        
        if prev_voiced and curr_voiced and i not in onset_set:
            if not np.isnan(pitch_derivative[i]):
                legato_mask[i] = True
    
    return legato_mask
```

### Output

- **Array shape**: `(n_frames,)` boolean mask
- **Usage**: Aggregated per beat to assign `articulation_type='legato'`

---

## Data Flow Through the Pipeline

### 1. **PitchTracker.obtener_f0_por_pulso()** → Articulation-Aware Output

```
Input:  ruta_bajo (Path to isolated bass stem)
           ↓
      Estimate f0 raw array, BPM, beat frames
           ↓
      Detect ghost notes → ghost_notes[n_frames]
           ↓
      Detect legato → legato_mask[n_frames]
           ↓
      For each beat interval:
        - Compute median f0 in interval
        - Count ghost notes & legato frames
        - Assign articulation_type:
            'dead' if ghost_count > 0
            'legato' if legato_count > 0 (and not dead)
            'normal' otherwise
           ↓
Output: List[Tuple[float, str]]
        E.g., [(440.0, 'normal'), (0.0, 'normal'), (392.5, 'legato'), ...]
```

### 2. **FretboardRouter.route_from_f0()** → Articulation-Aware Routing

```
Input:  f0_with_articulation: List[Tuple[float, str]]
           ↓
      For each (f0, articulation) pair:
        - Convert f0 → MIDI
        - Generate State candidates with articulation_type
        - Run Viterbi DP (transition costs unchanged)
           ↓
Output: List[State(string, fret, articulation_type)]
        E.g., [
          State(4, 0, 'normal'),
          State(4, 2, 'dead'),
          State(3, 5, 'legato'),
        ]
```

### 3. **FretboardRouter.build_musicxml_route()** → Articulation Metadata in Events

```
Input:  midi_sequence, states (both length-aligned)
           ↓
      Group consecutive states with same (midi, string, fret, articulation)
           ↓
Output: List[Dict] with keys:
        {
          'midi_pitch': int,
          'string_index': int,
          'fret_number': int,
          'duration_in_beats': float,
          'articulation_type': str  ← NEW
        }
```

### 4. **MusicXMLExporter.build_part()** → Music21 Rendering

```
Input:  route_events with 'articulation_type' field
           ↓
      For each event:
        - Create music21.note.Note
        - If articulation_type == 'dead':
            n.notehead = 'x'
        - If articulation_type == 'legato':
            accumulate in legato_sequence[]
        - Append to part
           ↓
      After each non-legato note or rest:
        - If legato_sequence.length > 1:
            slur = spanner.Slur(legato_sequence)
            part.append(slur)
           ↓
Output: music21.stream.Part with dead notes and slurs rendered
```

---

## API Reference

### PitchTracker

#### `obtener_f0_por_pulso(ruta_bajo: Path) -> Tuple[List[Tuple[float, str]], float]`

Returns beat-quantized f0 with articulation metadata.

**Returns:**
- `f0_pulsos`: `List[(f0_value: float, articulation_type: str)]`
  - `f0_value`: 0.0 for rests, Hz for voiced notes
  - `articulation_type`: `'normal'` | `'dead'` | `'legato'`
- `bpm`: Detected tempo in BPM

**Example:**
```python
tracker = PitchTracker()
f0_with_art, bpm = tracker.obtener_f0_por_pulso(Path("bass.wav"))
# [(523.25, 'normal'), (0.0, 'normal'), (587.33, 'legato'), ...]
```

#### `obtener_f0_por_pulso_legacy(ruta_bajo: Path) -> Tuple[np.ndarray, float]`

Legacy method returning only f0 values (for backward compatibility).

---

### FretboardRouter

#### `route_from_f0(f0_with_articulation: List[Tuple[float, str]]) -> Tuple[List[State], str]`

Routes f0 with articulation to fretboard positions.

**Parameters:**
- `f0_with_articulation`: From `PitchTracker.obtener_f0_por_pulso()`

**Returns:**
- `states`: `List[State(string, fret, articulation_type)]`
- `tab`: ASCII tab string

#### `build_musicxml_route(midi_sequence, states) -> List[Dict]`

Builds route events with articulation metadata for export.

---

### MusicXMLExporter

#### `build_part() -> music21.stream.Part`

Constructs a Part with:
- Dead notes: `notehead='x'`
- Legato: `music21.spanner.Slur()` wrapping consecutive legato notes
- String/fret metadata: `articulations.StringIndication`, `articulations.FretIndication`

---

## Configuration

### DSP Thresholds (config/settings.toml)

The DSP stage reads thresholds and behaviour flags from `config/settings.toml` under `[dsp]`. Key tunables:

```toml
[dsp]
voiced_confidence_threshold = 0.05            # pYIN voiced-prob threshold
ghost_spectral_flatness_threshold = 0.5       # spectral flatness for ghost notes
slide_pitch_change_threshold_hz = 5.0         # Hz/frame pitch-change threshold for slides
slide_min_duration_frames = 3                 # minimum consecutive frames to declare a slide
ghost_onset_voicing_balance = 0.5             # balance between onset energy and voicedness for ghost detection
```

Notes:
- `detect_slides()` is implemented in `PitchTracker` and is integrated into the frame→beat aggregation performed by `obtener_f0_por_pulso()`. Slide regions are reported and may annotate beats as `slide` or be used to avoid marking a transition as `legato` when a slide is present.

- NaN / gradient interaction (implementation note): the DSP replaces non-voiced or zero f0 frames with `np.nan` before computing pitch derivatives. Computing `np.gradient()` over arrays containing NaNs propagates NaNs and can suppress legitimate derivative values. The implemented mitigation is:
  1. Fill short internal NaN gaps by cubic interpolation (scipy.interpolate.interp1d or pandas.Series.interpolate(method='cubic')) to obtain a continuous pitch contour for derivative estimation.
  2. Cap or fall back to linear interpolation for long, edge, or ill-conditioned gaps to avoid producing NaNs.
  3. Compute `np.gradient()` on the interpolated contour and then consult original voiced masks to decide whether derivatives are valid for articulation detection.

This approach avoids false-negative legato detection caused by NaN propagation while preserving explicit non-voiced frames for downstream routing and export.

### Ghost Note Detection Tuning

To **increase** ghost note sensitivity:
- Reduce `voiced_confidence_threshold` (e.g., 0.02)
- Reduce spectral flatness threshold in `_detect_ghost_notes()` (e.g., 0.4)

To **decrease** ghost note sensitivity:
- Increase `voiced_confidence_threshold` (e.g., 0.1)
- Increase spectral flatness threshold (e.g., 0.6)

---

## Music21 Integration

### Dead Notes

MusicXML representation:
```xml
<note>
  <pitch>
    <step>E</step>
    <octave>1</octave>
  </pitch>
  <duration>4</duration>
  <notehead>x</notehead>
  <articulations>
    <string-indication>4</string-indication>
    <fret-indication>0</fret-indication>
  </articulations>
</note>
```

**Rendering**: MuseScore, Dorico, Guitar Pro render `notehead='x'` as a cross or 'x' symbol.

### Legato Slurs

MusicXML representation (auto-generated by music21):
```xml
<spanner type="slur" number="1">
  <starting-note-index>0</starting-note-index>
  <ending-note-index>2</ending-note-index>
</spanner>
```

**Rendering**: Notation software renders an arc connecting the slurred notes.

---

## Examples

### Example 1: Simple Slap Bass with Ghost Notes

**Audio Analysis:**
- Measure 1, Beat 1–2: Ghost notes (percussive slaps, low voicing)
- Measure 1, Beat 3–4: Legato transition (hammer-on from fret 2 to 5)

**Pipeline Output:**
```python
# From PitchTracker:
f0_with_art = [
    (0.0, 'normal'),    # Rest
    (0.0, 'dead'),      # Ghost note (slap)
    (0.0, 'dead'),      # Ghost note (slap)
    (110.0, 'legato'),  # Hammer-on (fret 0 → 2)
]

# From Router:
states = [
    State(4, -1, 'normal'),     # Rest
    State(4, 0, 'dead'),        # Slap on open string
    State(4, 0, 'dead'),        # Slap on open string
    State(4, 2, 'legato'),      # Hammered fret
]

# MusicXML render:
# Beat 1: [Rest]
# Beat 2: [X on string 4, fret 0]
# Beat 3: [X on string 4, fret 0]
# Beat 4: [Note E2 on string 4, fret 2] ← connected to beat 3 with slur
```

### Example 2: Smooth Legato Line

**Audio Analysis:**
- All notes voiced with no percussive attacks
- Continuous pitch contour (no pitch jumps)

**Pipeline Output:**
```python
f0_with_art = [
    (110.0, 'normal'),   # Fret 0
    (123.5, 'legato'),   # Pulled to fret 3
    (146.8, 'legato'),   # Pulled to fret 5
    (164.8, 'normal'),   # Rearticulated (new onset)
]

# MusicXML: First 3 notes spanned by Slur, 4th note not slurred.
```

---

## Testing Recommendations

1. **Ghost Note Detection**:
   - Record or find audio with slap bass, muted pick, or accidental mutes
   - Verify that `articulation_type='dead'` is assigned
   - Check MusicXML for `notehead='x'`

2. **Legato Detection**:
   - Record or find audio with smooth hammer-ons/pull-offs
   - Verify that consecutive frames report `articulation_type='legato'`
   - Check MusicXML for slur arcs

3. **Edge Cases**:
   - Rest followed by note: Should not slur
   - Rearticulated note: Onset should break legato
   - Very slow pitch transitions: May be classified as legato or normal; tune thresholds as needed

---

## Future Enhancements (Milestone 2+)

- **Slide Detection**: (Implemented) frame-level slide region detection (`detect_slides()`) is now part of the PitchTracker and integrated into beat aggregation; further improvements will focus on velocity-based slide classification and duration quantization.
- **Bend Detection**: Pitch excursions beyond quantized fret
- **Harmonics**: High-frequency components without fundamental
- **Polyphonic Voicing**: Multi-note chords with independent articulation per note
- **Slide Time Quantization**: Snap slide durations to beats/sub-beats

---

## References

- **librosa.onset_detect**: https://librosa.org/doc/main/generated/librosa.onset.onset_detect.html
- **librosa.feature.spectral_flatness**: https://librosa.org/doc/main/generated/librosa.feature.spectral_flatness.html
- **music21 Slur**: https://music21-cuthbert.github.io/music21/reference/classes/spanner.html#music21.spanner.Slur
- **music21 Notehead**: https://music21-cuthbert.github.io/music21/reference/classes/note.html#music21.note.Note.notehead

---

**Last Updated:** June 2026
