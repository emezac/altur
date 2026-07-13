import io
import os
import pytest
from unittest.mock import patch
from app.models.call import Call
from app.models.event import CallEvent
from app.services.storage.factory import get_storage_backend

def test_upload_call_success(client, db):
    # 1. Simulate a valid WAV file upload
    file_content = b"RIFF\x24\x08\x00\x00WAVEfmt " + b"\x00" * 100
    file_name = "test_call_01.wav"
    
    response = client.post(
        "/api/v1/calls",
        files={"file": (file_name, io.BytesIO(file_content), "audio/wav")}
    )
    
    assert response.status_code == 202
    data = response.json()
    assert "call_id" in data
    assert data["status"] == "PENDING"
    assert data["filename"] == file_name
    assert "uploaded_at" in data
    
    # 2. Verify database records
    call_id = data["call_id"]
    db_call = db.query(Call).filter(Call.id == call_id).first()
    assert db_call is not None
    assert db_call.filename == file_name
    assert db_call.status == "PENDING"
    assert db_call.file_size_bytes == len(file_content)
    
    # Check that the status change event was registered
    db_event = db.query(CallEvent).filter(CallEvent.call_id == call_id).first()
    assert db_event is not None
    assert db_event.event_type == "STATUS_CHANGE"
    assert db_event.payload == {"from_status": None, "to_status": "PENDING"}

    # 3. Verify file exists in local storage
    storage = get_storage_backend()
    assert os.path.exists(db_call.storage_path)
    
    # Open and verify file contents
    with storage.open(db_call.storage_path) as f:
        assert f.read() == file_content

def test_upload_call_invalid_extension(client):
    file_content = b"RIFF\x24\x08\x00\x00WAVEfmt "
    response = client.post(
        "/api/v1/calls",
        files={"file": ("test.txt", io.BytesIO(file_content), "text/plain")}
    )
    assert response.status_code == 400
    data = response.json()
    assert "error" in data
    assert data["error"]["code"] == "INVALID_FILE"

def test_upload_call_invalid_signature(client):
    file_content = b"THIS IS NOT A VALID AUDIO HEADER AT ALL"
    response = client.post(
        "/api/v1/calls",
        files={"file": ("test.wav", io.BytesIO(file_content), "audio/wav")}
    )
    assert response.status_code == 400
    data = response.json()
    assert "error" in data
    assert data["error"]["code"] == "INVALID_FILE"

def test_upload_call_file_too_large(client):
    # Set headers to simulate a file exceeding MAX_UPLOAD_MB
    file_content = b"ID3" + b"\x00" * 10
    response = client.post(
        "/api/v1/calls",
        files={"file": ("test.mp3", io.BytesIO(file_content), "audio/mpeg")},
        headers={"Content-Length": str(200 * 1024 * 1024)}  # 200MB (limit is 100MB)
    )
    assert response.status_code == 413
    data = response.json()
    assert "error" in data
    assert data["error"]["code"] == "FILE_TOO_LARGE"

def test_upload_call_atomic_rollback(client, db):
    file_content = b"RIFF\x24\x08\x00\x00WAVEfmt "
    file_name = "test_rollback.wav"
    
    # Mock db.commit to raise an exception, triggering rollback
    with patch("sqlalchemy.orm.Session.commit", side_effect=Exception("Database crash")):
        response = client.post(
            "/api/v1/calls",
            files={"file": (file_name, io.BytesIO(file_content), "audio/wav")}
        )
        assert response.status_code == 500
        
    # Verify no call entry was written to DB
    db_calls = db.query(Call).all()
    assert len(db_calls) == 0
    
    # Verify storage path is clean (no orphaned file in local temp storage)
    storage = get_storage_backend()
    # Check that temporary directory has 0 audio files
    files = os.listdir(storage.base_path)
    # Exclude placeholders like .gitkeep if any
    audio_files = [f for f in files if f != ".gitkeep"]
    assert len(audio_files) == 0
