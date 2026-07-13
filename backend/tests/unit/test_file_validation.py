import pytest
from app.core.exceptions import AppError
from app.services.file_validator import validate_file_size, validate_file_format

def test_validate_file_size_valid():
    # 50MB is below the 100MB limit, should pass without raising
    validate_file_size(50 * 1024 * 1024)

def test_validate_file_size_invalid():
    # 101MB exceeds the 100MB limit, should raise 413
    with pytest.raises(AppError) as exc_info:
        validate_file_size(101 * 1024 * 1024)
    assert exc_info.value.status_code == 413
    assert exc_info.value.code == "FILE_TOO_LARGE"

def test_validate_file_format_valid_wav():
    # Valid WAV file header has RIFF and WAVE
    header = b"RIFF\x24\x08\x00\x00WAVEfmt "
    validate_file_format("call.wav", header)

def test_validate_file_format_valid_mp3():
    # Valid MP3 with ID3 header
    header = b"ID3\x03\x00\x00\x00\x00"
    validate_file_format("call.mp3", header)

    # Valid MP3 with raw sync frame header
    header = b"\xff\xfb\x90\x00"
    validate_file_format("call.mp3", header)

def test_validate_file_format_invalid_extension():
    header = b"RIFF\x24\x08\x00\x00WAVEfmt "
    with pytest.raises(AppError) as exc_info:
        validate_file_format("call.exe", header)
    assert exc_info.value.status_code == 400
    assert exc_info.value.code == "INVALID_FILE"

def test_validate_file_format_invalid_signature():
    header = b"PLAIN TEXT OR CORRUPT HEADER DATA"
    with pytest.raises(AppError) as exc_info:
        validate_file_format("call.wav", header)
    assert exc_info.value.status_code == 400
    assert exc_info.value.code == "INVALID_FILE"
