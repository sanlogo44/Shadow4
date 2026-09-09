//! Fehler-Typ der HTTP-API. Wird in ein JSON mit Statuscode uebersetzt.

use axum::{http::StatusCode, response::IntoResponse, Json};
use serde_json::json;

#[derive(Debug)]
pub struct ApiError {
    pub status: StatusCode,
    pub message: String,
    pub code: &'static str,
}

impl ApiError {
    pub fn bad_request(msg: impl Into<String>) -> Self {
        Self { status: StatusCode::BAD_REQUEST, message: msg.into(), code: "bad_request" }
    }
    pub fn unauthorized(msg: impl Into<String>) -> Self {
        Self { status: StatusCode::UNAUTHORIZED, message: msg.into(), code: "unauthorized" }
    }
    pub fn forbidden(msg: impl Into<String>) -> Self {
        Self { status: StatusCode::FORBIDDEN, message: msg.into(), code: "forbidden" }
    }
    pub fn not_found(msg: impl Into<String>) -> Self {
        Self { status: StatusCode::NOT_FOUND, message: msg.into(), code: "not_found" }
    }
    pub fn internal(msg: impl Into<String>) -> Self {
        Self { status: StatusCode::INTERNAL_SERVER_ERROR, message: msg.into(), code: "internal" }
    }

    /// Mappt einen shadow-core-Fehler auf einen passenden HTTP-Status.
    pub fn from_core(e: &shadow_core::ShadowError) -> Self {
        use shadow_core::ShadowError;
        match e {
            ShadowError::NotFound(_) => Self::not_found(e.to_string()),
            ShadowError::Forbidden(_) => Self::forbidden(e.to_string()),
            ShadowError::Adapter(ae) => {
                use shadow_core::AdapterError;
                match ae {
                    AdapterError::Auth | AdapterError::Unavailable(_) => {
                        Self { status: StatusCode::SERVICE_UNAVAILABLE, message: ae.to_string(), code: "engine_unavailable" }
                    }
                    AdapterError::ContextOverflow => Self::bad_request(ae.to_string()),
                    _ => Self::internal(ae.to_string()),
                }
            }
            _ => Self::internal(e.to_string()),
        }
    }
}

impl IntoResponse for ApiError {
    fn into_response(self) -> axum::response::Response {
        let body = Json(json!({ "error": self.code, "message": self.message }));
        (self.status, body).into_response()
    }
}
