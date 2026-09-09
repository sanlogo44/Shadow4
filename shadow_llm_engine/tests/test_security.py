"""Tests für die Metadaten-Verschlüsselung (System 7): Ver-/Entschlüsselung,
Schlüsselrotation, Backup, Zugriffskontrolle, Audit-Logs, Manipulationsschutz."""

from __future__ import annotations

import pytest

from shadow_engine.security import (
    AccessDeniedError,
    AuditLog,
    EncryptionLayer,
    KeyStore,
    SENSITIVE_FIELDS,
)


@pytest.fixture()
def setup(tmp_path):
    audit = AuditLog(path=str(tmp_path / "audit.log"))
    ks = KeyStore(path=str(tmp_path / "keystore.json"), audit=audit)
    ks.init_key(actor="admin")
    ks.grant("app")
    layer = EncryptionLayer(ks, audit=audit)
    return layer, ks, audit


# ---------------------------------------------------------------------- #
# Feld-Verschlüsselung
# ---------------------------------------------------------------------- #


def test_sensitive_fields_set_contains_expected():
    assert "username" in SENSITIVE_FIELDS
    assert "email" in SENSITIVE_FIELDS
    assert "roles" in SENSITIVE_FIELDS
    assert "node_data" in SENSITIVE_FIELDS
    assert "logs" in SENSITIVE_FIELDS


def test_encrypt_decrypt_value_roundtrip(setup):
    layer, _, _ = setup
    token = layer.encrypt_value({"secret": "data", "n": 42}, actor="app")
    assert layer.is_encrypted(token)
    decrypted = layer.decrypt_value(token, actor="app")
    assert decrypted == {"secret": "data", "n": 42}


def test_encrypt_fields_only_sensitive(setup):
    layer, _, _ = setup
    record = {"username": "alice", "email": "a@x.com", "public": "hello", "roles": ["admin"]}
    enc = layer.encrypt_fields(record, actor="app")
    assert layer.is_encrypted(enc["username"])
    assert layer.is_encrypted(enc["email"])
    assert layer.is_encrypted(enc["roles"])
    assert enc["public"] == "hello"  # nicht sensibel -> Klartext
    dec = layer.decrypt_fields(enc, actor="app")
    assert dec == record


def test_decrypt_plaintext_returns_plaintext(setup):
    layer, _, _ = setup
    assert layer.decrypt_value("not-encrypted", actor="app") == "not-encrypted"


def test_tampered_ciphertext_fails(setup):
    layer, _, _ = setup
    token = layer.encrypt_value("geheim", actor="app")
    # Token manipulieren
    tampered = token[:-2] + "00"
    with pytest.raises(ValueError):
        layer.decrypt_value(tampered, actor="app")


# ---------------------------------------------------------------------- #
# Schlüsselrotation
# ---------------------------------------------------------------------- #


def test_key_rotation_keeps_old_data_decryptable(setup):
    layer, ks, _ = setup
    old_token = layer.encrypt_value("alte daten", actor="app")
    new_version = ks.rotate(actor="admin")
    assert new_version > 1
    # alte Daten noch entschlüsselbar
    assert layer.decrypt_value(old_token, actor="app") == "alte daten"
    # neue Daten nutzen neue Version
    new_token = layer.encrypt_value("neue daten", actor="app")
    assert "v2" in new_token or f"v{new_version}" in new_token


def test_key_store_persists_across_instances(tmp_path):
    audit = AuditLog(path=str(tmp_path / "audit.log"))
    ks = KeyStore(path=str(tmp_path / "keystore.json"), audit=audit)
    ks.init_key(actor="admin")
    ks.grant("app")
    v1 = ks.current_version
    # neu laden
    ks2 = KeyStore(path=str(tmp_path / "keystore.json"), audit=audit)
    assert ks2.current_version == v1
    assert "app" in ks2._actors


# ---------------------------------------------------------------------- #
# Zugriffskontrolle
# ---------------------------------------------------------------------- #


def test_access_denied_for_unauthorized_actor(tmp_path):
    audit = AuditLog(path=str(tmp_path / "audit.log"))
    ks = KeyStore(path=str(tmp_path / "keystore.json"), audit=audit)
    ks.init_key(actor="admin")
    # "intruder" wurde nicht berechtigt
    with pytest.raises(AccessDeniedError):
        ks.current_key(actor="intruder")
    # Audit zeigt verweigerten Zugriff
    denied = audit.filter(action="access_denied")
    assert len(denied) >= 1


def test_encryption_requires_authorized_actor(tmp_path):
    audit = AuditLog(path=str(tmp_path / "audit.log"))
    ks = KeyStore(path=str(tmp_path / "keystore.json"), audit=audit)
    ks.init_key(actor="admin")
    layer = EncryptionLayer(ks, audit=audit)
    with pytest.raises(AccessDeniedError):
        layer.encrypt_value("x", actor="intruder")


# ---------------------------------------------------------------------- #
# Backup / Restore
# ---------------------------------------------------------------------- #


def test_backup_and_restore_keys(tmp_path):
    audit = AuditLog(path=str(tmp_path / "audit.log"))
    ks = KeyStore(path=str(tmp_path / "keystore.json"), audit=audit)
    ks.init_key(actor="admin")
    ks.grant("admin")
    original_version = ks.current_version
    blob = ks.backup(password="backup-pass", actor="admin")
    # neuer Keystore, restore
    ks2 = KeyStore(path=str(tmp_path / "keystore2.json"), audit=audit)
    ks2.restore(blob, password="backup-pass", actor="admin")
    assert ks2.current_version == original_version


def test_backup_with_wrong_password_fails(tmp_path):
    audit = AuditLog(path=str(tmp_path / "audit.log"))
    ks = KeyStore(path=str(tmp_path / "keystore.json"), audit=audit)
    ks.init_key(actor="admin")
    ks.grant("admin")
    blob = ks.backup(password="right", actor="admin")
    ks2 = KeyStore(path=str(tmp_path / "keystore2.json"), audit=audit)
    with pytest.raises(Exception):
        ks2.restore(blob, password="wrong", actor="admin")


# ---------------------------------------------------------------------- #
# Audit-Logs
# ---------------------------------------------------------------------- #


def test_audit_log_records_operations(setup):
    layer, ks, audit = setup
    layer.encrypt_value("x", actor="app")
    layer.decrypt_value(layer.encrypt_value("y", actor="app"), actor="app")
    ks.rotate(actor="admin")
    actions = {e["action"] for e in audit.entries()}
    assert "encrypt" in actions
    assert "decrypt" in actions
    assert "key_rotate" in actions


def test_audit_log_filter_by_outcome(tmp_path):
    audit = AuditLog(path=str(tmp_path / "audit.log"))
    ks = KeyStore(path=str(tmp_path / "keystore.json"), audit=audit)
    ks.init_key(actor="admin")
    with pytest.raises(AccessDeniedError):
        ks.current_key(actor="intruder")
    denied = audit.filter(outcome="denied")
    assert len(denied) >= 1
