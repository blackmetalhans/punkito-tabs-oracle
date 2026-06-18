# -*- coding: utf-8 -*-
"""
FastAPI application para Punkito Tabs Oracle.
Proporciona endpoint asincronos para transcripción de audio bass y generación de tabs MusicXML.
"""

import asyncio
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


class TranscribeResponse(BaseModel):
    """Respuesta para el endpoint /api/transcribe"""
    status: str
    message: str
    musicxml_path: Optional[str] = None
    tab: Optional[str] = None
    error: Optional[str] = None


def _decode_subprocess_output(output: Optional[bytes]) -> str:
    """Decode UTF-8 subprocess output, replacing invalid bytes and None."""
    if not output:
        return ""
    return output.decode("utf-8", errors="replace").strip()


def _join_error_sections(*sections: str) -> str:
    """Concatenate non-empty error sections."""
    return "\n\n".join(section for section in sections if section)


def _extract_ascii_tab(stdout_text: str) -> str:
    """Extract the ASCII tab block, or return raw stdout when no marker exists."""
    marker = "[ASCII TAB OUTPUT]"
    if marker not in stdout_text:
        return stdout_text

    _, _, tail = stdout_text.partition(marker)
    tail = tail.strip()
    if "[+]" in tail:
        tail = tail.split("[+]", 1)[0].strip()
    return tail


def create_app() -> FastAPI:
    """Crea y configura la aplicación FastAPI."""
    app = FastAPI(
        title="Punkito Tabs Oracle API",
        description="API para transcripción de bass y generación de tabs",
        version="0.1.0",
    )
    
    # Agregar middleware CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # En producción, especificar orígenes permitidos
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    @app.get("/health")
    async def health_check() -> dict:
        """Health check endpoint."""
        return {"status": "healthy", "service": "punkito-tabs-oracle"}
    
    @app.post("/api/transcribe", response_model=TranscribeResponse)
    async def transcribe_audio(file: UploadFile = File(...)) -> TranscribeResponse:
        """
        Endpoint para transcribir audio de bass y generar MusicXML + ASCII tabs.
        
        - Acepta carga de archivo de audio (MP3, WAV, FLAC, M4A, OGG)
        - Ejecuta el orquestador CLI de forma asincronamente
        - Retorna la ruta al MusicXML generado y la representación ASCII del tab
        
        Args:
            file: Archivo de audio a transcribir
            
        Returns:
            TranscribeResponse con status, paths y tab ASCII
        """
        # Validar que el archivo no esté vacío
        if not file.filename:
            raise HTTPException(status_code=400, detail="Filename is required")
        
        # Validar extensión del archivo
        valid_extensions = {".mp3", ".wav", ".flac", ".m4a", ".ogg"}
        file_ext = Path(file.filename).suffix.lower()
        if file_ext not in valid_extensions:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid audio format. Allowed: {', '.join(valid_extensions)}"
            )
        
        temp_dir = None
        temp_audio_path = None
        output_musicxml_path = None
        stdout = b""
        stderr = b""
        cmd: list[str] = []
        process = None
        
        try:
            # Crear directorio temporal
            temp_dir = tempfile.mkdtemp(prefix="punkito_transcribe_")
            temp_dir_path = Path(temp_dir)
            
            # Guardar archivo de audio en directorio temporal
            temp_audio_path = temp_dir_path / file.filename
            content = await file.read()
            temp_audio_path.write_bytes(content)
            
            # Preparar rutas de salida
            output_musicxml_path = temp_dir_path / "bass_tab.musicxml"
            
            # Ejecutar CLI de forma asincronada usando asyncio.create_subprocess_exec
            cmd = [
                sys.executable,
                "-m",
                "punkito_tabs_oracle.cli",
                str(temp_audio_path),
                "--output-dir",
                str(temp_dir_path),
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            
            # Esperar a que el proceso termine (con timeout)
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=300.0
                )
                return_code = process.returncode
            except asyncio.TimeoutError:
                process.kill()
                # Collect buffered output after termination for error reporting.
                stdout, stderr = await process.communicate()
                raise TimeoutError(
                    "CLI subprocess execution timeout after 5 minutes"
                )

            stdout_text = _decode_subprocess_output(stdout)
            stderr_text = _decode_subprocess_output(stderr)
            
            # Verificar si el CLI se ejecutó exitosamente
            if return_code != 0:
                return TranscribeResponse(
                    status="error",
                    message="CLI execution failed",
                    error=_join_error_sections(
                        f"exit_code: {return_code}",
                        f"stderr:\n{stderr_text}" if stderr_text else "",
                        f"stdout:\n{stdout_text}" if stdout_text else "",
                    ),
                )
            
            # Verificar que el MusicXML se generó
            if not output_musicxml_path.exists():
                return TranscribeResponse(
                    status="error",
                    message="MusicXML generation failed",
                    error=_join_error_sections(
                        "MusicXML output file was not generated",
                        f"stdout:\n{stdout_text}" if stdout_text else "",
                        f"stderr:\n{stderr_text}" if stderr_text else "",
                    ),
                )
            
            tab_content = _extract_ascii_tab(stdout_text)
            
            return TranscribeResponse(
                status="success",
                message="Audio transcribed successfully",
                musicxml_path=str(output_musicxml_path),
                tab=tab_content,
            )
        
        except HTTPException:
            raise
        except Exception:
            stderr_text = _decode_subprocess_output(stderr)
            stdout_text = _decode_subprocess_output(stdout)
            return TranscribeResponse(
                status="error",
                message="Transcription failed",
                error=_join_error_sections(
                    traceback.format_exc().strip(),
                    f"stderr:\n{stderr_text}" if stderr_text else "",
                    f"stdout:\n{stdout_text}" if stdout_text else "",
                    f"command: {' '.join(cmd)}" if cmd else "",
                ),
            )
        finally:
            # Limpiar archivo temporal (opcionalmente, mantenerlo para debugging)
            # if temp_dir and Path(temp_dir).exists():
            #     shutil.rmtree(temp_dir)
            pass
    
    return app


# Instancia global de la aplicación
app = create_app()


if __name__ == "__main__":
    # Para ejecutar localmente: uvicorn app:app --reload --port 8000
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
