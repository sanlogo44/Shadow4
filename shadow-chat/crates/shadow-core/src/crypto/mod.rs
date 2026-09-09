//! Krypto-Basis: Master-Key (Argon2id/AES-256-GCM), Keystore, SHA-256.

mod hash;
mod keystore;
mod master_key;

pub use hash::{sha256_bytes, sha256_bytes_from_str, sha256_file};
pub use keystore::{initialize as keystore_initialize, is_initialized, unlock as keystore_unlock};
pub use master_key::{KdfParams, MasterKey, NONCE_LEN};
