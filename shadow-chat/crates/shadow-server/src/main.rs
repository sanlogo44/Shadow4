//! Shadow Server Binary – eigenständiger Einstieg in den HTTP-API-Server.

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    shadow_server::run(args)
}
