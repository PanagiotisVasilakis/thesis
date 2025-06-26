# tests for security module
from datetime import datetime, timedelta
from types import SimpleNamespace

from jose import jwt
import pytest

from backend.app.app.core import security


def test_create_access_token_expiry(monkeypatch):
    fixed_now = datetime(2023, 1, 1, 0, 0, 0)

    class DummyDatetime(datetime):
        @classmethod
        def utcnow(cls):
            return fixed_now

    monkeypatch.setattr(security, "datetime", DummyDatetime)
    monkeypatch.setattr(security.settings, "SECRET_KEY", "secret", raising=False)

    token = security.create_access_token("u1", expires_delta=timedelta(minutes=5))
    claims = jwt.get_unverified_claims(token)
    assert claims["sub"] == "u1"
    exp = datetime.utcfromtimestamp(claims["exp"])
    assert exp == fixed_now + timedelta(minutes=5)


def test_password_hash_roundtrip():
    plain = "s3cret"
    hashed = security.get_password_hash(plain)
    assert security.verify_password(plain, hashed)
    assert not security.verify_password("wrong", hashed)


def test_extract_public_key(tmp_path, monkeypatch):
    cert_file = tmp_path / "cert.pem"
    cert_file.write_text("dummycert")

    def fake_load_certificate(ftype, data):
        assert ftype == security.crypto.FILETYPE_PEM
        assert data == "dummycert"
        return SimpleNamespace(get_pubkey=lambda: "PUBKEYOBJ")

    def fake_dump_publickey(ftype, obj):
        assert ftype == security.crypto.FILETYPE_PEM
        assert obj == "PUBKEYOBJ"
        return b"PUBLIC"

    monkeypatch.setattr(security.crypto, "load_certificate", fake_load_certificate)
    monkeypatch.setattr(security.crypto, "dump_publickey", fake_dump_publickey)

    result = security.extract_public_key(str(cert_file))
    assert result == b"PUBLIC"

