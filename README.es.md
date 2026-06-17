🎸 Punkito Tabs Oracle para Bajo
Idioma / Language: 🇪🇸 Español | 🇺🇸 Read in English
Sistema de transcripción automática de tablaturas e aislamiento de bajo mediante IA — Convierte cualquier archivo de audio polifónico en tablaturas ejecutables para bajo eléctrico de forma automática.
⚠️ Estado del Proyecto: Desarrollo Activo (Fases del Motor Core 100% Completadas y Funcionales)
🎯 Propósito del Proyecto
Punkito Tabs Oracle es un pipeline inteligente de procesamiento de señales de audio que realiza las siguientes operaciones secuenciales:
Aísla la pista de bajo desde mezclas polifónicas complejas (baterías, guitarras, voces) utilizando redes neuronales convolucionales de separación de fuentes.
Estima la frecuencia fundamental () en el registro grave con alta precisión temporal y frecuencial.
Mapea el diapasón de forma ergonómica calculando la secuencia de digitación (Cuerda, Traste) que minimiza la fatiga de la mano izquierda.
Sincroniza y cuantiza el tempo (BPM) para renderizar una tablatura ASCII compacta, estructurada en compases de  legibles para un músico.
Flujo de Trabajo del Pipeline
Entrada: cancion.mp3 (Mezcla Completa)
   ↓
[Separador de Fuentes U-Net] → Aísla el espectro grave del bajo
   ↓
[Rastreador de Pitch pYIN + YIN Fallback] → Estima la serie temporal f0
   ↓
[Detector de BPM y Onsets] → Segmenta y cuantiza f0 por pulso (Beat)
   ↓
[Ruteador del Diapasón (Viterbi/DP)] → Optimiza la economía de movimientos
   ↓
Salida: Tablatura ASCII cuantizada en compases de 4/4 (Terminal / Archivo)


🏗️ Arquitectura del Sistema
El motor opera como un pipeline desacoplado por contratos de datos definidos en sus capas:
flowchart TD
    A["Audio Polifónico (.mp3/.wav)"] --> B["Separador U-Net<br/>(Spleeter / TensorFlow)"]
    B --> C["Stem de Bajo (.wav)"]
    C --> D["Analizador pYIN/YIN + RMS Gating<br/>(Librosa / NumPy)"]
    D --> E["Vector f0 Cuantizado por Pulso<br/>(Frecuencia Mediana por Beat)"]
    E --> F["Optimizador Topológico de Trastes<br/>(Programación Dinámica / Viterbi)"]
    F --> G["Tablatura ASCII en Compases de 4/4"]
    
    style A fill:#e1f5ff,stroke:#0288d1
    style C fill:#b3e5fc,stroke:#0288d1
    style E fill:#81d4fa,stroke:#0288d1
    style G fill:#4fc3f7,stroke:#0288d1


📐 Fundamentos Matemáticos
1. Separación de Fuentes mediante U-Net Convolucional
Aislamos la energía espectral del bajo eléctrico utilizando una arquitectura de red profunda convolucional de tipo U-Net (entrenada sobre el dataset MusDB18).
El sistema calcula la Transformada de Fourier de Tiempo Corto (STFT) del audio de entrada:
Donde:
 representa la señal temporal de entrada.
 es la ventana de análisis (ventana de Hann).
 corresponde a la representación tiempo-frecuencia (espectrograma complejo).
La red predice máscaras de magnitud suave para el stem del bajo, aplicando un enmascaramiento de Wiener sobre el espectrograma polifónico y reconstruyendo la fase mediante la STFT Inversa (iSTFT).
2. Rastreo Probabilístico de Pitch (pYIN) con Resiliencia Dinámica
La autocorrelación tradicional suele fallar en el registro subgrave de un bajo (E1  a G4 ), induciendo errores de octava. pYIN soluciona esto usando una función de diferencia acumulada normalizada combinada con un Modelo Oculto de Márkov (HMM).
La función de diferencia normalizada se define como:
El decodificador de Viterbi del HMM evalúa las transiciones de múltiples candidatos de pitch a lo largo del tiempo.
Mecanismo de Gating por Energía RMS: Para evitar transcribir transitorios de ataque ruidosos o ruidos de fricción sobre el mástil (fret noise), calculamos la energía RMS normalizada de cada frame. Si cae por debajo del umbral de  (), la frecuencia  se fuerza a  (silencio).
Resiliencia mediante Fallback a YIN: Si la confianza estadística del decodificador probabilístico de pYIN cae por debajo del  global, el sistema conmuta automáticamente al algoritmo determinista clásico YIN (librosa.yin) para mantener la robustez temporal del análisis.
3. Ruteo Ergonómico del Diapasón (Programación Dinámica / Viterbi)
La redundancia del diapasón del bajo implica que una misma nota MIDI puede ejecutarse en múltiples posiciones físicas  (Cuerda, Traste). Encontrar la secuencia que minimice la fatiga muscular se modela como la búsqueda del camino más corto sobre un grafo multifase usando la Ecuación de Bellman.
Dado un estado en el frame anterior  y un candidato actual , el costo de transición  es:
Donde:
 representa la distancia de desplazamiento horizontal de la mano a lo largo del mástil.
 cuantifica el esfuerzo de cruce vertical entre cuerdas.
 es una función indicadora que otorga una recompensa negativa (bonificación de  de costo) por tocar cuerdas al aire, lo que reduce la fatiga estática.
 son los pesos heurísticos configurados en settings.toml.
El algoritmo realiza un paso hacia adelante (Forward pass) acumulando los costos y luego un Backtracking para extraer la trayectoria óptima global de digitación.
📂 Estructura del Proyecto
punkito-tabs-oracle/
├── .github/
│   └── workflows/
│       └── ci.yml             # Integración Continua (Automated Testing en GitHub)
├── config/
│   ├── locales/
│   │   ├── en.json            # Claves de traducción en Inglés
│   │   └── es.json            # Claves de traducción en Español
│   └── settings.toml          # Parámetros físicos del bajo y pesos de costos
├── docs/
│   └── backlog_issues.md      # Planificación ágil del ciclo de desarrollo
├── src/
│   └── punkito_tabs_oracle/
│       ├── __init__.py
│       ├── cli.py             # Orquestador y CLI multilingüe
│       ├── dsp/
│       │   └── pitch.py       # Rastreo de tono por pYIN/YIN y cuantización rítmica
│       ├── ml/
│       │   └── separator.py   # Separación de fuentes mediante TensorFlow
│       └── tab/
│           └── router.py      # Optimizador ergonómico y renderizador ASCII de 4/4
├── tests/                     # Suite de pruebas unitarias y de integración
│   ├── test_dsp.py            # Validación matemática del análisis de señal (pYIN)
│   └── test_tab.py            # Validación de restricciones del algoritmo de ruteo
├── pyproject.toml             # Configuración del paquete y dependencias (PEP 518)
└── .gitignore


🚀 Instalación y Configuración
Requisitos Previos
Python 3.10 (entorno de pruebas nativo validado)
FFmpeg instalado y disponible en las variables de entorno (PATH) de tu sistema operativo.
Paso 1: Clonar el Repositorio
git clone [https://github.com/blackmetalhans/punkito-tabs-oracle.git](https://github.com/blackmetalhans/punkito-tabs-oracle.git)
cd punkito-tabs-oracle


Paso 2: Crear y Activar el Entorno Virtual
# Crear entorno virtual (venv)
python -m venv env

# Activar en Windows (Git Bash)
source env/Scripts/activate

# Activar en macOS/Linux
source env/bin/activate


Paso 3: Instalar dependencias en modo editable
# Actualizar el gestor de paquetes
python -m pip install --upgrade pip

# Instalar el paquete en modo desarrollo con extras de testeo
pip install -e .[dev]


Esto instalará automáticamente:
Core: numpy, scipy, librosa, soundfile, tensorflow o tensorflowspleeter (según plataforma).
Desarrollo y Testing: pytest, pytest-cov, black, flake8.
💻 Ejecución y Uso de la CLI
El orquestador cuenta con soporte bilingüe nativo. Para procesar un audio, simplemente ejecuta:
# Ejecutar análisis en español
punkito-tabs ruta_a_tu_cancion.mp3 --lang es

# Ejecutar análisis en inglés
punkito-tabs ruta_a_tu_cancion.mp3 --lang en


Verificación de Ayuda y Flags:
punkito-tabs --help


📊 Suite de Pruebas Automatizadas
Hemos diseñado pruebas rigurosas utilizando señales sintéticas para blindar la regresión de algoritmos clave:
test_pitchtracker_on_sine: Valida la precisión frecuencial de pYIN con una onda senoidal pura de  (La2, MIDI 45), garantizando una tolerancia de error inferior al .
test_pitchtracker_beat_quantization: Asegura que la cuantización temporal agrupe correctamente los frames de frecuencia dentro de la grilla de pulsos detectada.
test_router_prefers_open_and_low_frets: Evalúa que el motor de programación dinámica resuelva con ergonomía real, prefiriendo cuerdas al aire y trastes cómodos ante saltos extremos.
Para ejecutar los tests, corre en la raíz:
pytest -v


🤝 Contribuciones
Para proponer cambios en el motor matemático de ruteo o en la arquitectura de ML:
Crea una rama de desarrollo siguiendo la nomenclatura del backlog: feature/issue-X-nombre-descriptivo.
Asegura que la suite de pruebas pase en su totalidad antes de abrir un Pull Request: pytest -v.
Sigue los estándares estilísticos descritos en PEP 8.
📝 Licencia
Este proyecto se encuentra liberado bajo la Licencia MIT. Consulta el archivo LICENSE para mayores detalles.
