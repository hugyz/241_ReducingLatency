# Client–Server Protocol

This document describes the UDP protocol used between the Python clients and the main/edge servers.

---

# Transport

- Transport: **UDP**
- Encoding: **JSON (UTF-8)**
- Messages are **best-effort** (UDP packets may be lost or reordered).
- Each message contains a **sequence number (`seq`)** used to match request/response messages.

---

# Message Format

All messages follow the same structure.

```json
{
  "type": "STRING",
  "client_id": "STRING",
  "seq": 123,
  "timestamp_ms": 1710000000000,
  "payload": {}
}
```

| Field | Description |
|------|-------------|
| type | Message type |
| client_id | Client identifier |
| seq | Sequence number |
| timestamp_ms | Sender timestamp |
| payload | Message-specific data |

---

# Message Types

| Type | Direction | Purpose |
|-----|-----------|--------|
| PING | Client → Edge | Measure latency |
| PONG | Edge → Client | Reply to PING |
| DISCOVER | Client → Main | Request edge servers |
| EDGE_LIST | Main → Client | Return available edges |
| REGISTER | Client → Edge | Register with chosen edge |
| PREDICTION | Client → Edge | Periodic client state update |
| STATE_UPDATE | Edge → Client | Authoritative state update |
| ROLLBACK | Edge → Client | Correct client state |

---

# Example Messages

### PING
```json
{}
```

### EDGE_LIST
```json
{
  "edges": [
    {"host": "127.0.0.1", "port": 9000},
    {"host": "127.0.0.1", "port": 9001}
  ]
}
```

### PREDICTION
```json
{
  "tick": 123,
  "state": {"x": 1.2, "y": -3.4},
  "input": {"dx": 1, "dy": 0}
}
```

---

# Client Protocol Flow

1. **Discover edges**

Client sends `DISCOVER` to the main server and receives `EDGE_LIST`.

2. **Select best edge**

Client sends multiple `PING` probes and chooses the edge with the lowest median RTT.

3. **Register**

Client sends `REGISTER` to the selected edge server.

4. **Run**

Client periodically sends `PREDICTION` updates and listens for server messages (`STATE_UPDATE`, `ROLLBACK`).

---

# Tick Rate

Clients send updates at a fixed tick rate.

Default:

```
30 ticks/sec
```

This means a prediction update is sent every:

```
~33 ms
```

---

# Latency Measurement

Latency is measured using **RTT (Round Trip Time)** via `PING/PONG`.

```
RTT = time(PONG received) − time(PING sent)
```

---

# Server Requirements

### Main Server
- Handle `DISCOVER`
- Return `EDGE_LIST`

### Edge Server
- Reply to `PING` with `PONG`
- Accept `REGISTER`
- Receive `PREDICTION`
- Optionally send `STATE_UPDATE` or `ROLLBACK`