use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ModelCapabilities {
    pub streaming: bool,
    pub tool_calling: bool,
    pub vision: bool,
    pub context_window: u32,
    pub max_output_tokens: u32,
}

impl Default for ModelCapabilities {
    fn default() -> Self {
        Self {
            streaming: true,
            tool_calling: false,
            vision: false,
            context_window: 8192,
            max_output_tokens: 2048,
        }
    }
}
