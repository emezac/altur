import io
import pytest
from app.models.call import Call
from app.models.transcript import Transcript
from app.models.summary import Summary
from app.models.tag import CallTag


def test_list_calls_endpoint(client, db):
    # Register multiple mock calls
    c1 = Call(filename="test_call_A.wav", storage_path="path/A.wav", mime_type="audio/wav", file_size_bytes=100)
    c2 = Call(filename="test_call_B.wav", storage_path="path/B.wav", mime_type="audio/wav", file_size_bytes=200)
    db.add(c1)
    db.add(c2)
    db.commit()

    response = client.get("/api/v1/calls")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert data["total"] >= 2
    filenames = [c["filename"] for c in data["items"]]
    assert "test_call_A.wav" in filenames
    assert "test_call_B.wav" in filenames


def test_get_call_detail_endpoint(client, db):
    # Insert call with transcript, summary, and tags
    c = Call(filename="detailed_call.wav", storage_path="path/detail.wav", mime_type="audio/wav", file_size_bytes=150)
    db.add(c)
    db.commit()

    t = Transcript(
        call_id=c.id,
        language="en",
        raw_text="Hello world.",
        turns=[{"speaker": "Agent", "text": "Hello", "start": 0.0, "end": 1.0}],
        stt_provider="fake",
        stt_model="fake-model"
    )
    s = Summary(
        call_id=c.id,
        summary_text="Client greeted agent.",
        key_points=["Greeting"],
        insights={"sentiment": "neutral", "purchase_intent": "low"},
        llm_provider="fake",
        llm_model="fake-llm",
        prompt_version="v1"
    )
    tag = CallTag(call_id=c.id, tag_category="outcome", tag_value="unknown", confidence=0.8)
    
    db.add(t)
    db.add(s)
    db.add(tag)
    db.commit()

    response = client.get(f"/api/v1/calls/{c.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["filename"] == "detailed_call.wav"
    assert data["transcript"]["language"] == "en"
    assert data["transcript"]["turns"][0]["speaker"] == "Agent"
    assert data["summary"]["summary_text"] == "Client greeted agent."
    assert data["summary"]["insights"]["sentiment"] == "neutral"
    assert len(data["tags"]) == 1
    assert data["tags"][0]["tag_category"] == "outcome"


def test_get_call_detail_not_found(client):
    response = client.get("/api/v1/calls/non-existent-uuid")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_get_call_audio_endpoint(client, db, tmp_path):
    # Create actual dummy file on local disk
    local_file = tmp_path / "audio.wav"
    local_file.write_bytes(b"RIFF dummy audio data")

    c = Call(
        filename="dummy.wav",
        storage_path=str(local_file),
        mime_type="audio/wav",
        file_size_bytes=local_file.stat().st_size
    )
    db.add(c)
    db.commit()

    response = client.get(f"/api/v1/calls/{c.id}/audio")
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert response.content == b"RIFF dummy audio data"


def test_get_call_audio_not_found(client, db):
    # Call exists in DB but file missing from storage path
    c = Call(filename="missing.wav", storage_path="non-existent-path.wav", mime_type="audio/wav", file_size_bytes=10)
    db.add(c)
    db.commit()

    response = client.get(f"/api/v1/calls/{c.id}/audio")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()
