Punkito Tabs Oracle: System Architecture Specification

This document details the software engineering design, directory layout, and structural flow of the Punkito Tabs Oracle engine.

1. Current State of the Repository (The Skeleton)

At this moment, the repository is structured as a professional, installable Python package adhering to PEP 518. Here is the responsibility mapping of each component you just established in your machine:

Oraculo de Tabs/
├── config/
│   ├── locales/
│   │   ├── en.json            # Dynamic string mapping for English UI
│   │   └── es.json            # Dynamic string mapping for Spanish UI
│   └── settings.toml          # Physics constraints (Tuning, weights, frets)
├── src/
│   └── punkito_tabs_oracle/
│       ├── __init__.py        # Packages exposure
│       ├── cli.py             # Orchestrator & CLI argument parser (Entry point)
│       ├── dsp/
│       │   └── pitch.py       # STUB: Empty interface for pYIN algorithms
│       ├── ml/
│       │   └── separator.py   # STUB: Empty interface for Spleeter/TensorFlow
│       └── tab/
│           └── router.py      # STUB: Empty interface for fretboard physical optimization
├── pyproject.toml             # Package metadata, executable registration & dependency locks
└── .gitignore                 # Binary and heavy data isolation rules


2. Functional Components of the Skeleton

A. The Setup Metadata (pyproject.toml)

Instead of a simple execution script, your project is now registered in your Windows registry as an editable package.

Whenever you run the command punkito-tabs in your terminal (with the virtualenv activated), Windows knows it must invoke punkito_tabs_oracle.cli:main thanks to the [project.scripts] registration.

It locks down compatibility boundaries to prevent Python 3.11+ compilers from attempting to install incompatible TensorFlow binaries on Windows.

B. Decoupled Internationalization (i18n via JSON)

The UI strings are entirely isolated from the executable code.

The orchestration engine in cli.py loads config/locales/{lang}.json dynamically based on the execution flags (--lang en or --lang es).

This pattern guarantees that adding support for a new language (e.g., Latin) only requires dropping a new {lang}.json file in config/locales/ without modifying a single line of Python code.

3. The Signal & Algorithmic Pipeline (The Core to Populate)

Once we start writing code within the modules inside src/, the data will flow through three heavily decoupled processing layers:

[ Input Audio: Polyphonic Mix (.mp3/.wav) ]
                    │
                    ▼
┌───────────────────────────────────────┐
│           ml/separator.py             │
│  - Load Isolated Spleeter Model       │   (Runs U-Net Conv2D network via TensorFlow)
│  - Compute Masking Spectrogram        │
└───────────────────────────────────────┘
                    │
                    ▼
         [ Bass Stem (.wav) ]
                    │
                    ▼
┌───────────────────────────────────────┐
│            dsp/pitch.py               │
│  - Downsample signal to 22050Hz       │   (Uses Librosa pYIN tracking to estimate f0)
│  - Compute autocorrelation & HMM      │
└───────────────────────────────────────┘
                    │
                    ▼
        [ f0/Pitch Time Series ]
                    │
                    ▼
┌───────────────────────────────────────┐
│            tab/router.py              │
│  - Parse frequency to MIDI notes      │   (Heuristic / Dynamic Programming path-finder)
│  - Map notes to 4-string fretboard    │
│  - Apply transition-cost algorithms   │
└───────────────────────────────────────┘
                    │
                    ▼
    [ Print Optimized ASCII Tablature ]


Module Responsibilities:

ml/separator.py (The Heavy Lifter):
This module will host the neural network client. It imports TensorFlow and wraps Spleeter. Its only job is to intake an arbitrary polyphonic audio file, pass it through Spleeter's pre-trained 4-stems convolutional neural network, and write a clean, isolated bass.wav to the stems_output/ folder (which Git will ignore to keep your repo clean).

dsp/pitch.py (The Precision Ear):
This module imports Librosa. It takes the bass.wav generated in the previous step, reads the raw samples, downsamples them to a manageable sample rate ($22.05 \text{ kHz}$), and applies the Probabilistic YIN (pYIN) algorithm. It outputs a simple NumPy array representing the fundamental frequencies ($f_0$) over time, filtering out non-voiced frames (rests/silences).

tab/router.py (The Ergonomic Guitarist):
This is the pure algorithmic engine. It converts the $f_0$ frequencies to MIDI values. Because a bass guitar has overlapping note positions (e.g., the fifth fret on the E string is the same pitch as the open A string), this module runs a pathfinding optimizer. It calculates the physical distance between consecutive notes on the fretboard to choose a finger pattern that minimizes hand movement. It then formats this decision matrix into standard string layouts:

G|--------------------------------|
D|--------------------------------|
A|--------5---7---5---------------|
E|----5---------------7---5-------|
