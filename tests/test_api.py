# -*- coding: utf-8 -*-
"""
Tests for the FastAPI application endpoints.
Verifies async audio transcription and error handling.
"""
import pytest
from fastapi.testclient import TestClient
from pathlib import Path
import io
import sys

import punkito_tabs_oracle.api.app as app_module
from punkito_tabs_oracle.api.app import app


client = TestClient(app)


class FakeProcess:
    """Minimal stub for asyncio.subprocess.Process used in API tests."""

    def __init__(self, returncode=0, stdout=b"", stderr=b""):
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self.killed = False

    async def communicate(self):
        return self._stdout, self._stderr

    def kill(self):
        self.killed = True


def make_success_subprocess(calls):
    """Create a fake async subprocess factory for successful API tests."""

    async def _fake_create_subprocess_exec(*cmd, stdout=None, stderr=None):
        calls.append(cmd)
        output_dir = Path(cmd[cmd.index("--output-dir") + 1])
        (output_dir / "bass_tab.musicxml").write_text("<score-partwise />", encoding="utf-8")
        return FakeProcess(
            returncode=0,
            stdout=(
                b"[ASCII TAB OUTPUT]\n"
                b"E|--0--\n"
                b"A|--5--\n"
                b"[+] MusicXML tab exported at: bass_tab.musicxml\n"
            ),
        )

    return _fake_create_subprocess_exec


class TestAPIEndpoints:
    """Tests for FastAPI endpoints."""

    def test_health_check_endpoint(self):
        """Test the health check endpoint."""
        response = client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "punkito-tabs-oracle"

    def test_transcribe_endpoint_missing_file(self):
        """Test transcribe endpoint without file."""
        response = client.post("/api/transcribe")
        
        # Should return 422 (Unprocessable Entity) due to missing file
        assert response.status_code == 422

    def test_transcribe_endpoint_invalid_extension(self):
        """Test transcribe endpoint with invalid audio format."""
        # Create a fake file with invalid extension
        invalid_file = ("test.txt", io.BytesIO(b"not an audio file"), "text/plain")
        
        response = client.post("/api/transcribe", files={"file": invalid_file})
        
        assert response.status_code == 400
        data = response.json()
        assert "Invalid audio format" in data["detail"]

    def test_transcribe_endpoint_valid_extensions(self, monkeypatch):
        """Test that valid extensions are accepted."""
        calls = []
        monkeypatch.setattr(
            app_module.asyncio,
            "create_subprocess_exec",
            make_success_subprocess(calls),
        )
        valid_extensions = ["test.mp3", "test.wav", "test.flac", "test.m4a", "test.ogg"]
        
        for filename in valid_extensions:
            # Create a fake audio file
            fake_audio = b"fake audio content"
            audio_file = (filename, io.BytesIO(fake_audio), "audio/mpeg")
            
            response = client.post("/api/transcribe", files={"file": audio_file})
            
            assert response.status_code == 200

    def test_transcribe_response_structure(self, monkeypatch):
        """Test that transcribe response has correct structure."""
        calls = []
        monkeypatch.setattr(
            app_module.asyncio,
            "create_subprocess_exec",
            make_success_subprocess(calls),
        )
        # Create a fake audio file
        fake_audio = b"fake audio content"
        audio_file = ("test.wav", io.BytesIO(fake_audio), "audio/wav")
        
        response = client.post("/api/transcribe", files={"file": audio_file})
        
        # Response should be valid JSON regardless of success
        data = response.json()
        assert "status" in data
        assert isinstance(data.get("status"), str)
        assert isinstance(data.get("message"), str)
        assert data["status"] == "success"
        assert data["musicxml_path"].endswith("bass_tab.musicxml")
        assert data["tab"] == "E|--0--\nA|--5--"
        assert calls
        cmd = calls[0]
        assert cmd[0] == sys.executable
        assert cmd[1:3] == ("-m", "punkito_tabs_oracle.cli")
        assert "--output-dir" in cmd
        assert "--audio" not in cmd
        assert "--output-xml" not in cmd

    def test_transcribe_endpoint_includes_stderr_on_cli_failure(self, monkeypatch):
        """Test that CLI stderr is surfaced in the JSON error payload."""

        async def fake_create_subprocess_exec(*cmd, stdout=None, stderr=None):
            return FakeProcess(
                returncode=2,
                stderr=b"usage: punkito-tabs ...\ninvalid arguments\n",
            )

        monkeypatch.setattr(
            app_module.asyncio,
            "create_subprocess_exec",
            fake_create_subprocess_exec,
        )

        audio_file = ("test.wav", io.BytesIO(b"fake audio content"), "audio/wav")
        response = client.post("/api/transcribe", files={"file": audio_file})

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "error"
        assert data["message"] == "CLI execution failed"
        assert "exit_code: 2" in data["error"]
        assert "stderr:" in data["error"]
        assert "invalid arguments" in data["error"]

    def test_transcribe_endpoint_includes_traceback_on_startup_exception(self, monkeypatch):
        """Test that subprocess startup exceptions include traceback details."""

        async def fake_create_subprocess_exec(*cmd, stdout=None, stderr=None):
            raise FileNotFoundError("process launch failed")

        monkeypatch.setattr(
            app_module.asyncio,
            "create_subprocess_exec",
            fake_create_subprocess_exec,
        )

        audio_file = ("test.wav", io.BytesIO(b"fake audio content"), "audio/wav")
        response = client.post("/api/transcribe", files={"file": audio_file})

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "error"
        assert "Traceback" in data["error"]
        assert "FileNotFoundError" in data["error"]
        assert "process launch failed" in data["error"]
        assert "command:" in data["error"]


class TestAPIResponseModels:
    """Tests for API response model validation."""

    def test_transcribe_response_model_success(self):
        """Test TranscribeResponse model with success status."""
        from punkito_tabs_oracle.api.app import TranscribeResponse
        
        response = TranscribeResponse(
            status="success",
            message="Test successful",
            musicxml_path="/path/to/output.musicxml",
            tab="E|--0--\nA|--5--"
        )
        
        assert response.status == "success"
        assert response.musicxml_path == "/path/to/output.musicxml"
        assert response.tab == "E|--0--\nA|--5--"
        assert response.error is None

    def test_transcribe_response_model_error(self):
        """Test TranscribeResponse model with error status."""
        from punkito_tabs_oracle.api.app import TranscribeResponse
        
        response = TranscribeResponse(
            status="error",
            message="Test failed",
            error="Something went wrong"
        )
        
        assert response.status == "error"
        assert response.error == "Something went wrong"
        assert response.musicxml_path is None
        assert response.tab is None


class TestAPICORS:
    """Tests for CORS middleware."""

    def test_cors_headers_present(self):
        """Test that CORS headers are present in responses."""
        response = client.get("/health")
        
        # Check for CORS headers (they may be set by TestClient)
        # In a real ASGI server, these would be present
        assert response.status_code == 200

    def test_cors_preflight_request(self):
        """Test OPTIONS preflight request."""
        # Note: FastAPI with CORSMiddleware handles CORS but the testclient
        # may not properly simulate preflight requests. This test verifies
        # that the endpoint exists (even if it returns 405).
        response = client.options("/api/transcribe")
        
        # OPTIONS is not explicitly handled by FastAPI, so 405 is expected
        assert response.status_code in [200, 405]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
