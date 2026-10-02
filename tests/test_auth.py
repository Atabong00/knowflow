import pytest
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from app.core.config import settings
from app.auth.dependencies import serializer, get_session_data, generate_csrf_token, validate_csrf_token
from unittest.mock import MagicMock


class TestSessionCookie:
    def test_serialize_deserialize(self):
        data = {"access_token": "test-token", "refresh_token": "refresh-token"}
        signed = serializer.dumps(data)
        result = serializer.loads(signed, max_age=28800)
        assert result["access_token"] == "test-token"

    def test_invalid_signature(self):
        with pytest.raises(BadSignature):
            serializer.loads("invalid-token")

    def test_expired_session(self):
        data = {"access_token": "test-token"}
        signed = serializer.dumps(data)
        with pytest.raises(SignatureExpired):
            serializer.loads(signed, max_age=-1)


class TestCSRF:
    def test_generate_csrf_token(self):
        token = generate_csrf_token()
        assert token is not None
        assert len(token) > 0

    def test_validate_csrf_token(self):
        token = generate_csrf_token()
        request = MagicMock()
        request.headers = {"X-CSRF-Token": token}
        request.cookies = {"csrf_token": token}
        
        # Should not raise
        validate_csrf_token(request)

    def test_missing_csrf_token(self):
        request = MagicMock()
        request.headers = {}
        request.cookies = {}
        
        with pytest.raises(Exception):
            validate_csrf_token(request)

    def test_invalid_csrf_token(self):
        request = MagicMock()
        request.headers = {}
        request.cookies = {"csrf_token": "invalid"}
        
        with pytest.raises(Exception):
            validate_csrf_token(request)
