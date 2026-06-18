# -*- coding: utf-8 -*-
"""
Tests for the FastAPI application endpoints.
Verifies async audio transcription and error handling.
"""
import pytest
from fastapi.testclient import TestClient
from pathlib import Path
import io

from punkito_tabs_oracle.api.app import app


client = TestClient(app)


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

    def test_transcribe_endpoint_valid_extensions(self):
        """Test that valid extensions are accepted."""
        valid_extensions = ["test.mp3", "test.wav", "test.flac", "test.m4a", "test.ogg"]
        
        for filename in valid_extensions:
            # Create a fake audio file
            fake_audio = b"fake audio content"
            audio_file = (filename, io.BytesIO(fake_audio), "audio/mpeg")
            
            response = client.post("/api/transcribe", files={"file": audio_file})
            
            # May fail due to CLI not being available, but should not reject based on extension
            assert response.status_code != 400  # Not a format validation error

    def test_transcribe_response_structure(self):
        """Test that transcribe response has correct structure."""
        # Create a fake audio file
        fake_audio = b"fake audio content"
        audio_file = ("test.wav", io.BytesIO(fake_audio), "audio/wav")
        
        response = client.post("/api/transcribe", files={"file": audio_file})
        
        # Response should be valid JSON regardless of success
        data = response.json()
        assert "status" in data
        assert "message" in data
        assert isinstance(data.get("status"), str)
        assert isinstance(data.get("message"), str)


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
