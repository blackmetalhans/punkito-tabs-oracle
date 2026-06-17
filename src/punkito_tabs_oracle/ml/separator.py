#!/usr/bin/env python3
"""
Punkito Tabs Oracle - Machine Learning Source Separation Module
Encapsula la orquestación del backend de TensorFlow y la API de Spleeter (Deezer)
para aislar de manera offline la banda de frecuencia correspondiente al bajo eléctrico.
"""

import os
import sys
import logging
from pathlib import Path
from typing import Dict

# Silenciar logs verbosos de inicialización de tensores en C++ antes de importar TensorFlow
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
logging.getLogger("tensorflow").setLevel(logging.ERROR)

class BassSeparator:
    """
    Cliente de inferencia para el modelo U-Net Convolucional Profundo (Spleeter 4stems).
    Aísla la pista de bajo del resto del espectro (vocals, drums, other).
    """
    
    def __init__(self, output_dir: Path, locales: Dict[str, str]):
        self.output_dir = Path(output_dir).resolve()
        self.locales = locales
        self.model_name = 'spleeter:4stems'  # Separación en 4 canales de frecuencia
        self._inicializar_backend()

    def _inicializar_backend(self):
        """Prepara las carpetas físicas y valida las dependencias de Python del módulo."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        try:
            # Importación tardía para no penalizar el tiempo de carga del Parser de la CLI
            from spleeter.separator import Separator
            self.SeparatorClass = Separator
        except ImportError as e:
            raise ImportError(
                "[-] Error de entorno: Spleeter o TensorFlow no están correctamente enlazados "
                f"en tu virtualenv. Reinstala con: pip install -e .[dev]. Detalle: {e}"
            )

    def aislar(self, audio_path: Path) -> Path:
        """
        Ejecuta la inferencia de la red convolucional sobre el espectrograma de magnitud.
        Reconstruye el stem del bajo y retorna su ruta absoluta.
        """
        audio_path = Path(audio_path).resolve()
        
        # Instanciamos el separador de Deezer.
        # En su primera ejecución, descargará automáticamente los pesos de la red (~200MB)
        # y los almacenará localmente en el directorio de caché .spleeter-models
        separator = self.SeparatorClass(self.model_name)
        
        # Ejecutar la separación. Esta llamada maneja internamente:
        # 1. Carga del decodificador ffmpeg mediante subproceso.
        # 2. STFT -> Inferencia del grafo U-Net -> iSTFT con reconstrucción de fase.
        # 3. Codificación a PCM de 16 bits en formato WAV.
        separator.separate_to_file(str(audio_path), str(self.output_dir))
        
        # Spleeter escribe la salida estructurada como: {output_dir}/{nombre_archivo}/bass.wav
        nombre_directorio_salida = audio_path.stem
        ruta_esperada_bajo = self.output_dir / nombre_directorio_salida / "bass.wav"
        
        if not ruta_esperada_bajo.exists():
            raise FileNotFoundError(
                self.locales.get(
                    "ERROR_FILE_NOT_FOUND", 
                    "[-] Error: No se pudo generar la pista de bajo aislada."
                ).format(ruta_esperada_bajo)
            )
            
        return ruta_esperada_bajo