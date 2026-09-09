"""Shadow Node Protocol v1 - Nachrichtenformate.

Richtung Client -> Server (Rust Core -> AI Layer):
    hello    {"v":1,"type":"hello"}
    load     {"v":1,"type":"load","config":{model_id,adapter_config,expected_sha256}}
    stream   {"v":1,"type":"stream","request":GenerateRequest}
    cancel   {"v":1,"type":"cancel"}          # nur waehrend eines laufenden Streams
    shutdown {"v":1,"type":"shutdown"}

Richtung Server -> Client:
    hello_ack {"v":1,"type":"hello_ack","protocol":1,"adapter":"echo"}
    ok        {"v":1,"type":"ok"}
    token     {"v":1,"type":"token","text":str,"index":int}
    usage     {"v":1,"type":"usage","tokens_in":int,"tokens_out":int}
    finish    {"v":1,"type":"finish","reason":"stop|length|cancelled|error"}
    error     {"v":1,"type":"error","code":str,"message":str}

Fehlercodes (normiert, spiegeln AdapterError):
    auth | rate_limited | context_overflow | unavailable | cancelled | internal
"""

PROTOCOL_VERSION = 1
# Harte Zeilenlimit: Schutz gegen kaputte Peers (DoS-Begrenzung).
PROTOCOL_LINE_MAX = 1_048_576  # 1 MiB
