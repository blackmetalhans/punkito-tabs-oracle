# -*- coding: utf-8 -*-
"""
FastAPI application para Punkito Tabs Oracle.
Proporciona endpoint asincronos para transcripción de audio bass y generación de tabs MusicXML.
"""

import asyncio
import tempfile
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
        
        try:
            # Crear directorio temporal
            temp_dir = tempfile.mkdtemp(prefix="punkito_transcribe_")
            temp_dir_path = Path(temp_dir)
            
            # Guardar archivo de audio en directorio temporal
            temp_audio_path = temp_dir_path / file.filename
            content = await file.read()
            temp_audio_path.write_bytes(content)
            
            # Preparar rutas de salida
            output_musicxml_path = temp_dir_path / "output.musicxml"
            output_tab_path = temp_dir_path / "output.txt"
            
            # Ejecutar CLI de forma asincronada usando asyncio.create_subprocess_exec
            cmd = [
                "punkito-tabs",
                "--audio", str(temp_audio_path),
                "--output-xml", str(output_musicxml_path),
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
                raise HTTPException(
                    status_code=504,
                    detail="Transcription timeout after 5 minutes"
                )
            
            # Verificar si el CLI se ejecutó exitosamente
            if return_code != 0:
                error_msg = stderr.decode("utf-8", errors="replace") if stderr else "Unknown error"
                raise HTTPException(
                    status_code=500,
                    detail=f"CLI execution failed: {error_msg}"
                )
            
            # Verificar que el MusicXML se generó
            if not output_musicxml_path.exists():
                raise HTTPException(
                    status_code=500,
                    detail="MusicXML output file was not generated"
                )
            
            # Intentar leer el tab ASCII (puede no existir)
            tab_content = ""
            if output_tab_path.exists():
                tab_content = output_tab_path.read_text(encoding="utf-8")
            
            return TranscribeResponse(
                status="success",
                message="Audio transcribed successfully",
                musicxml_path=str(output_musicxml_path),
                tab=tab_content,
            )
        
        except HTTPException:
            raise
        except Exception as e:
            return TranscribeResponse(
                status="error",
                message="Transcription failed",
                error=str(e),
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
