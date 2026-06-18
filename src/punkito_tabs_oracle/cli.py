#!/usr/bin/env python3
"""
Punkito Tabs Oracle - CLI Orchestrator
Módulo central encargado de la interfaz de línea de comandos, validación del sistema
operativo (ffmpeg), carga dinámica de configuraciones de idioma (i18n) y control del pipeline.
"""

import sys
import argparse
import json
import shutil
from pathlib import Path
from typing import Dict, Optional


def resolver_ruta_config(lang: str) -> Path:
    """
    Resuelve dinámicamente la ruta física del archivo JSON de traducción.
    Soporta ejecución en modo editable (pip install -e .) y estructura empaquetada.
    """
    directorio_actual = Path(__file__).resolve()
    ruta_desarrollo = directorio_actual.parents[2] / "config" / "locales" / f"{lang}.json"
    if ruta_desarrollo.exists():
        return ruta_desarrollo
        
    ruta_paquete = directorio_actual.parent / "config" / "locales" / f"{lang}.json"
    if ruta_paquete.exists():
        return ruta_paquete
        
    raise FileNotFoundError(
        f"[-] Error crítico de arquitectura: No se encontró el diccionario locales para '{lang}'."
    )


def cargar_locales(lang: str) -> Dict[str, str]:
    """Carga y decodifica el diccionario JSON correspondiente al idioma de ejecución."""
    try:
        ruta_archivo = resolver_ruta_config(lang)
        with open(ruta_archivo, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[-] Critical i18n loading failure for language '{lang}': {e}", file=sys.stderr)
        sys.exit(1)


def verificar_ffmpeg() -> bool:
    """Verifica si ffmpeg está instalado y accesible en el PATH del sistema."""
    return shutil.which("ffmpeg") is not None


def validar_audio_entrada(ruta_archivo: str, locales: Dict[str, str]) -> Path:
    """Valida la existencia del archivo de audio y su formato."""
    path_obj = Path(ruta_archivo).resolve()
    if not path_obj.exists():
        print(locales["ERROR_FILE_NOT_FOUND"].format(ruta_archivo), file=sys.stderr)
        sys.exit(1)
        
    extensiones_validas = {".mp3", ".wav", ".flac", ".m4a", ".ogg"}
    if path_obj.suffix.lower() not in extensiones_validas:
        print(locales["ERROR_INVALID_EXTENSION"].format(path_obj.suffix, ", ".join(extensiones_validas)), file=sys.stderr)
        sys.exit(1)
        
    return path_obj


def _localize(locales: Dict[str, str], key: str, default: str) -> str:
    """Devuelve un mensaje localizado con fallback seguro."""
    return locales.get(key, default)


def ejecutar_pipeline(
    audio_path: Path,
    locales: Dict[str, str],
    output_dir: Optional[Path] = None,
) -> None:
    """Orquesta secuencialmente las etapas de separación U-Net, estimación pYIN y ruteo."""
    print(locales["STATUS_LOAD_MODEL"])

    destino_stems = output_dir if output_dir is not None else audio_path.parent / "stems_output"
    destino_stems.mkdir(parents=True, exist_ok=True)

    # 1. EJECUCIÓN FASE 2: Separación neuronal offline de fuentes (ML)
    try:
        from punkito_tabs_oracle.ml.separator import BassSeparator
        separador = BassSeparator(output_dir=destino_stems, locales=locales)
        ruta_bajo_aislado = separador.aislar(audio_path)
        print(
            _localize(
                locales,
                "INFO_ISOLATED_STEM_SAVED",
                "[+] Isolated stem saved at: {}",
            ).format(ruta_bajo_aislado)
        )
    except ImportError:
        print(
            _localize(
                locales,
                "ERROR_ML_UNAVAILABLE",
                "[-] Critical error: ML separator is unavailable. Pipeline cannot continue.",
            ),
            file=sys.stderr,
        )
        sys.exit(1)
    except Exception as e:
        print(
            _localize(
                locales,
                "ERROR_ISOLATION_FAILED",
                "[-] Error crítico durante el aislamiento de la pista: {}",
            ).format(e),
            file=sys.stderr,
        )
        sys.exit(1)

    # 2. EJECUCIÓN FASE 3: Estimación espectral de tono con beat quantization (DSP)
    print(locales["STATUS_DSP_START"])
    try:
        from punkito_tabs_oracle.dsp.pitch import PitchTracker
        tracker = PitchTracker()
        f0_pulsos, bpm = tracker.obtener_f0_por_pulso(ruta_bajo_aislado)
        print(
            _localize(
                locales,
                "INFO_DETECTED_TEMPO",
                "[+] Detected tempo: {:.1f} BPM",
            ).format(bpm)
        )
        print(
            _localize(
                locales,
                "INFO_ESTIMATED_F0",
                "[+] Estimated {} beat-quantized f0 pulses from isolated bass stem.",
            ).format(len(f0_pulsos))
        )
    except ImportError:
        print(
            _localize(
                locales,
                "ERROR_DSP_UNAVAILABLE",
                "[-] Critical error: DSP pitch tracker is unavailable. Pipeline cannot continue.",
            ),
            file=sys.stderr,
        )
        sys.exit(1)
    except Exception as e:
        print(
            _localize(
                locales,
                "ERROR_PITCH_ESTIMATION",
                "[-] Error during pitch estimation: {}",
            ).format(e),
            file=sys.stderr,
        )
        sys.exit(1)

    if len(f0_pulsos) == 0:
        print(
            _localize(
                locales,
                "ERROR_EMPTY_F0",
                "[-] Error: No valid f0 pulses were detected. Pipeline cannot continue.",
            ),
            file=sys.stderr,
        )
        sys.exit(1)

    # 3. EJECUCIÓN FASE 4: Mapeo y ruteo topológico de trastes (Router)
    print(locales["STATUS_TAB_GEN"])
    try:
        from punkito_tabs_oracle.tab import router
        from punkito_tabs_oracle.tab.exporter import MusicXMLExporter
    except ImportError:
        print(
            _localize(
                locales,
                "ERROR_ROUTER_UNAVAILABLE",
                "[-] Critical error: Router module is unavailable. Pipeline cannot continue.",
            ),
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        router_instance = router.FretboardRouter()
        midi_seq = router_instance.f0_to_midi_sequence(list(f0_pulsos))
        states, tab = router_instance.route_from_f0(list(f0_pulsos))
        print(_localize(locales, "INFO_ASCII_TAB", "\n[ASCII TAB OUTPUT]\n"))
        print(tab)
        musicxml_route = router_instance.build_musicxml_route(
            midi_sequence=midi_seq,
            states=states,
        )
        musicxml_path = destino_stems / "bass_tab.musicxml"
        exported_path = MusicXMLExporter(
            musicxml_route,
            tempo_bpm=bpm,
        ).write(musicxml_path)
        if not Path(exported_path).exists():
            raise FileNotFoundError(
                _localize(
                    locales,
                    "ERROR_MUSICXML_NOT_WRITTEN",
                    "[-] Critical error: MusicXML output was not written.",
                )
            )
        print(
            _localize(
                locales,
                "INFO_MUSICXML_EXPORTED",
                "[+] MusicXML tab exported at: {}",
            ).format(exported_path)
        )
    except Exception as e:
        print(
            _localize(locales, "ERROR_ROUTING", "[-] Error during routing: {}").format(e),
            file=sys.stderr,
        )
        sys.exit(1)

    print(locales["SUCCESS_PIPELINE"])


def main():
    parser = argparse.ArgumentParser(
        description="Punkito Tabs Oracle - Structural CLI & Audio Pipeline Orchestrator"
    )
    parser.add_argument(
        "audio_file",
        type=str,
        nargs="?",
        help="Path absolute or relative to the source audio file",
    )
    parser.add_argument(
        "--lang",
        type=str,
        choices=["en", "es"],
        default="en",
        help="Interface and log execution language",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="./stems_output",
        help="Directory for stems and MusicXML output.",
    )
    args = parser.parse_args()

    locales = cargar_locales(args.lang)

    if not args.audio_file:
        print(locales["ERROR_NO_AUDIO_PROVIDED"], file=sys.stderr)
        parser.print_help()
        sys.exit(1)

    print(locales["STATUS_VERIFYING_DEPS"])

    if not verificar_ffmpeg():
        print(locales["ERROR_FFMPEG_MISSING"], file=sys.stderr)
        sys.exit(1)

    audio_path_validado = validar_audio_entrada(args.audio_file, locales)
    output_dir = Path(args.output_dir).expanduser().resolve()
    ejecutar_pipeline(audio_path_validado, locales, output_dir=output_dir)


if __name__ == "__main__":
    main()
