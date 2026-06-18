**Language / Idioma:** [🇺🇸 English](./README.md) | 🇪🇸 Español

> **Sistema de aislamiento de bajo y transcripción de tablaturas impulsado por IA** — Convierte audio polifónico en tablaturas ejecutables para bajo.

⚠️ **Estado del Proyecto:** Desarrollo Activo (Pipeline Base Implementado)

## 🎯 Qué hace este proyecto

Punkito Tabs Oracle es un pipeline de audio que:

1. **Aísla el stem de bajo** desde audio polifónico con Spleeter.
2. **Detecta el tono fundamental (f0)** con `librosa.pyin` y fallback YIN.
3. **Cuantiza tonos por pulso/beat** para mejorar legibilidad musical.
4. **Mapea notas al diapasón** con ruteo por programación dinámica.
5. **Genera tablatura ASCII** para bajo de 4 cuerdas.

## 🏗️ Arquitectura Implementada

```mermaid
flowchart TD
    A[Audio de entrada] --> B[ML: BassSeparator - Spleeter 4 stems]
    B --> C[bass.wav aislado]
    C --> D[DSP: PitchTracker - pYIN/YIN + filtro RMS]
    D --> E[f0 cuantizado por pulsos]
    E --> F[Tab: FretboardRouter - optimización por costo]
    F --> G[Salida ASCII tab]
```

## 📂 Estructura del Proyecto

```
punkito-tabs-oracle/
├── config/
│   ├── locales/
│   │   ├── en.json
│   │   └── es.json
│   └── settings.toml          # Reservado (actualmente vacío)
├── docs/
│   └── ARCHITECTURE.md
├── src/
│   └── punkito_tabs_oracle/
│       ├── cli.py             # CLI que orquesta el pipeline
│       ├── dsp/pitch.py       # pYIN + fallback YIN + cuantización por beat
│       ├── ml/separator.py    # Wrapper de Spleeter para aislar bajo
│       └── tab/router.py      # Ruteo de trastes + render ASCII
└── tests/
    ├── test_dsp.py
    └── test_tab.py
```

## 🚀 Instalación y Configuración

### Requisitos
- **Python 3.10** (requerido para compatibilidad de dependencias)
- `ffmpeg` disponible en el PATH del sistema

### Instalar

```bash
pip install -e .[dev]
```

## 💻 Progreso Funcional Actual

### ✅ Orquestación CLI
- Mensajes localizados en inglés y español.
- Valida existencia y extensión del archivo de audio.
- Valida `ffmpeg` antes de ejecutar.
- Ejecuta el flujo ML → DSP → TAB.

### ✅ Capa ML (`ml/separator.py`)
- Usa modelo `spleeter:4stems`.
- Guarda el bajo aislado en `./stems_output/<audio_name>/bass.wav`.
- Incluye validación de dependencias y salida esperada.

### ✅ Capa DSP (`dsp/pitch.py`)
- Estimación de f0 con pYIN (30–400 Hz).
- Fallback automático a YIN con baja confianza.
- Enmascarado de silencio por RMS.
- Detección de tempo y cuantización por pulso.

### ✅ Capa TAB (`tab/router.py`)
- Conversión Hz → MIDI.
- Selección ergonómica (cuerda/traste) con programación dinámica.
- Manejo de silencios.
- Render de tablatura ASCII de 4 líneas con barras de compás cada 4 pulsos.

## 🔄 Pendiente / En Progreso

- [x] Implementar módulo de estimación de tono.
- [x] Implementar wrapper de separación de bajo.
- [x] Implementar ruteador de trastes y render ASCII.
- [ ] Agregar pruebas de integración end-to-end del pipeline completo por CLI.
- [ ] Integrar parámetros de ejecución desde `config/settings.toml`.
- [ ] Agregar modo batch e interfaz gráfica.

## 📊 Pruebas

Ejecutar:

```bash
pytest -v
```

Cobertura automatizada actual:
- Comportamiento de estimación DSP y cuantización por beat.
- Decisiones de ruteo y render de tablatura ASCII.

## 🎓 Documentación

- **[ARCHITECTURE.md](./docs/ARCHITECTURE.md)** — Arquitectura actual y responsabilidades por módulo.

---

**Última actualización:** Junio de 2026
