//! Master-Key-Verwaltung: Argon2id + AES-256-GCM.
//!
//! Der Master-Key wird NIE im Klartext persistiert. Persistiert werden
//! KDF-Salt, KDF-Parameter und der wrapped Key. Wrap und Open sind
//! symmetrisch: beide nutzen denselben Salt (Passwort-Change = Re-Wrap
//! mit neuem Salt moeglich, ohne Daten neu zu verschluesseln).
//!
//! MVP-Einschraenkung: KDF-Parameter sind fest (19 MiB, t=2, p=1).
//! Die Tabelle speichert sie bereits fuer spaetere Aenderungen.

use aes_gcm::{
    aead::{Aead, KeyInit, OsRng},
    Aes256Gcm, Nonce,
};
use argon2::{Algorithm, Argon2, Params, Version};
use rand::RngCore;
use zeroize::Zeroize;
use zeroize::Zeroizing;

use crate::error::ShadowError;

pub const NONCE_LEN: usize = 12;

#[derive(Clone)]
pub struct MasterKey(Zeroizing<[u8; 32]>);

impl MasterKey {
    /// Leitet einen Master-Key aus einem Passwort ab (frische Salt).
    pub fn derive(password: &str) -> Result<(Self, [u8; 16], KdfParams), ShadowError> {
        let mut salt = [0u8; 16];
        OsRng.fill_bytes(&mut salt);
        let params = KdfParams::default();
        Self::derive_with(password, &salt, &params).map(|k| (k, salt, params))
    }

    fn derive_with(password: &str, salt: &[u8; 16], params: &KdfParams) -> Result<Self, ShadowError> {
        let argon2 = Argon2::new(Algorithm::Argon2id, Version::V0x13, params.to_argon2()?);
        let mut key = Zeroizing::new([0u8; 32]);
        argon2
            .hash_password_into(password.as_bytes(), salt, key.as_mut())
            .map_err(|e| ShadowError::Crypto(format!("argon2: {e}")))?;
        Ok(Self(key))
    }

    /// Oeffnet einen bestehenden wrapped Key (siehe Keystore).
    pub fn open(password: &str, salt: &[u8; 16], wrapped: &[u8]) -> Result<Self, ShadowError> {
        // MVP: feste KDF-Params. TODO: aus key_material.kdf_params lesen.
        let key = Self::derive_with(password, salt, &KdfParams::default())?;
        let cipher = Aes256Gcm::new_from_slice(key.0.as_ref())
            .map_err(|e| ShadowError::Crypto(e.to_string()))?;
        let (nonce, ct) = wrapped
            .split_first_chunk::<NONCE_LEN>()
            .ok_or_else(|| ShadowError::Crypto("wrapped key too short".into()))?;
        cipher
            .decrypt(Nonce::from_slice(nonce), ct)
            .map_err(|_| ShadowError::Crypto("wrong password or corrupted key".into()))?;
        Ok(key)
    }

    /// Wrappt den Master-Key mit dem Passwort. MUSS denselben Salt
    /// verwenden wie das spaetere `open` — Caller persistiert beides.
    pub fn wrap_with_password(
        &self,
        password: &str,
        salt: &[u8; 16],
    ) -> Result<Vec<u8>, ShadowError> {
        let kek = Self::derive_with(password, salt, &KdfParams::default())?;
        let cipher = Aes256Gcm::new_from_slice(kek.0.as_ref())
            .map_err(|e| ShadowError::Crypto(e.to_string()))?;
        let mut nonce = [0u8; NONCE_LEN];
        OsRng.fill_bytes(&mut nonce);
        let ct = cipher
            .encrypt(Nonce::from_slice(&nonce), self.0.as_ref())
            .map_err(|e| ShadowError::Crypto(e.to_string()))?;
        let mut out = nonce.to_vec();
        out.extend_from_slice(&ct);
        Ok(out)
    }

    /// Verschluesselt einen Payload (nonce-Prefix + Ciphertext).
    pub fn seal(&self, plaintext: &[u8]) -> Result<Vec<u8>, ShadowError> {
        let cipher = Aes256Gcm::new_from_slice(self.0.as_ref())
            .map_err(|e| ShadowError::Crypto(e.to_string()))?;
        let mut nonce = [0u8; NONCE_LEN];
        OsRng.fill_bytes(&mut nonce);
        let ct = cipher
            .encrypt(Nonce::from_slice(&nonce), plaintext)
            .map_err(|e| ShadowError::Crypto(e.to_string()))?;
        let mut out = nonce.to_vec();
        out.extend_from_slice(&ct);
        Ok(out)
    }

    pub fn open_sealed(&self, sealed: &[u8]) -> Result<Vec<u8>, ShadowError> {
        let cipher = Aes256Gcm::new_from_slice(self.0.as_ref())
            .map_err(|e| ShadowError::Crypto(e.to_string()))?;
        let (nonce, ct) = sealed
            .split_first_chunk::<NONCE_LEN>()
            .ok_or_else(|| ShadowError::Crypto("sealed payload too short".into()))?;
        cipher
            .decrypt(Nonce::from_slice(nonce), ct)
            .map_err(|_| ShadowError::Crypto("decryption failed".into()))
    }
}

impl Drop for MasterKey {
    fn drop(&mut self) {
        self.0.zeroize();
    }
}

/// Persistierbare KDF-Parameter (Tabelle key_material.kdf_params).
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct KdfParams {
    pub m: u32,
    pub t: u32,
    pub p: u32,
    pub version: String,
}

impl Default for KdfParams {
    fn default() -> Self {
        Self { m: 19_456, t: 2, p: 1, version: "0x13".into() }
    }
}

impl KdfParams {
    fn to_argon2(&self) -> Result<Params, ShadowError> {
        Params::new(self.m, self.t, self.p, Some(32))
            .map_err(|e| ShadowError::Crypto(format!("argon2 params: {e}")))
    }
}
