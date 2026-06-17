#!/usr/bin/env python3
"""
Punkito Tabs Oracle - CLI Orchestrator
Módulo central encargado de la interfaz de línea de comandos, validación del sistema
operativo (ffmpeg), carga dinámica de configuraciones de idioma (i18n) y control del pipeline.
"""

import os
import sys
import argparse
import json
import shutil
from pathlib import Path
from typing import Dict, Any


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


def ejecutar_pipeline(audio_path: Path, locales: Dict[str, str]):
    """Orquesta secuencialmente las etapas de separación U-Net, estimación pYIN y ruteo."""
    print(locales["STATUS_LOAD_MODEL"])
    
    # 1. EJECUCIÓN FASE 2: Separación neuronal offline de fuentes (ML)
    try:
        from punkito_tabs_oracle.ml.separator import BassSeparator
        output_dir = Path("./stems_output")
        separador = BassSeparator(output_dir=output_dir, locales=locales)
        ruta_bajo_aislado = separador.aislar(audio_path)
        print(f"[+] Isolated stem saved at: {ruta_bajo_aislado}")
    except ImportError:
        print("[-] Warning: ml/separator.py is currently empty (stub mode). Skipping ML layer.")
    except Exception as e:
        print(f"[-] Error crítico durante el aislamiento de la pista: {e}", file=sys.stderr)
        sys.exit(1)

    # 2. EJECUCIÓN FASE 3: Estimación espectral de tono (DSP - Siguiente Fase)
    print(locales["STATUS_DSP_START"])
    f0_array = None
    try:
        from punkito_tabs_oracle.dsp.pitch import PitchTracker
        tracker = PitchTracker(sr=22050, frame_length=2048, hop_length=512)
        f0_array = tracker.estimar_f0(ruta_bajo_aislado)
        print(f"[+] Estimated {len(f0_array)} f0 frames from isolated bass stem.")
    except ImportError:
        print("[-] Warning: dsp/pitch.py is missing. Skipping DSP layer.")
    except Exception as e:
        print(f"[-] Error during pitch estimation: {e}", file=sys.stderr)

    # 3. EJECUCIÓN FASE 4: Mapeo y ruteo topológico de trastes (Router)
    print(locales["STATUS_TAB_GEN"])
    try:
        from punkito_tabs_oracle.tab.router import FretboardRouter
        router = FretboardRouter()
        if f0_array is not None:
            states, tab = router.route_from_f0(f0_array)
            print("\n[ASCII TAB OUTPUT]\n")
            print(tab)
        else:
            print("[-] No f0 data available; skipping tab generation.")
    except ImportError:
        print("[-] Warning: tab/router.py is missing. Skipping Router layer.")
    except Exception as e:
        print(f"[-] Error during routing: {e}", file=sys.stderr)

    print(locales["SUCCESS_PIPELINE"])


def main():
    parser = argparse.ArgumentParser(
        description="Punkito Tabs Oracle - Structural CLI & Audio Pipeline Orchestrator"
    )
    parser.add_argument("audio_file", type=str, nargs="?", help="Path absolute or relative to the source audio file")
    parser.add_argument("--lang", type=str, choices=["en", "es"], default="en", help="Interface and log execution language")
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
    ejecutar_pipeline(audio_path_validado, locales)


if __name__ == "__main__":
    main()
