mod adapter;
mod capabilities;
mod python;
mod registry;
mod stub;

pub use adapter::{
    EventSink, GenerateRequest, GenerateResult, GenConstraints, GenParams,
    HealthStatus, MessageInput, ModelAdapter, ModelConfig, StreamEvent,
};
pub use capabilities::ModelCapabilities;
pub use python::PythonAdapter;
pub use registry::{ModelEntry, ModelRegistry};
pub use stub::StubAdapter;
