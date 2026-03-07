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
| seq | Sequence number used to match request/response messages |
| timestamp_ms | Sender timestamp (ms since epoch) |
| payload | Message-specific data |

---

# Message Types

| Type | Direction | Purpose |
|-----|-----------|--------|
| PING | Client → Main/Edge | Measure latency |
| PONG | Main/Edge → Client | Reply to PING |
| DISCOVER | Client → Main | Request edge servers |
| EDGE_LIST | Main → Client | Return available edges |
| REGISTER | Client → Main/Edge | Register with chosen edge |
| PREDICTION | Client → Main/Edge | Periodic client state update |
| STATE_UPDATE | Main → Client | Authoritative state update |
| ROLLBACK | Main → Client | Correct client state |

---

# Message Payload Definitions

### PING (Client → Main/Edge)

Used to measure latency.

Payload:
```json
{}
```

The server must reply with a `PONG` containing the same `seq`.

---

### PONG (Main/Edge → Client)

Reply to a `PING`.

Payload:
```json
{}
```

The `seq` must match the original `PING`.

---

### DISCOVER (Client → Main)

Client requests available edge servers.

Payload:
```json
{}
```

---

### EDGE_LIST (Main → Client)

Returns a list of available edge servers.

Payload:
```json
{
  "edges": [
    {"host": "127.0.0.1", "port": 9000},
    {"host": "127.0.0.1", "port": 9001}
  ]
}
```

| Field | Type | Description |
|------|------|-------------|
| edges | list | List of available edge servers |
| host | string | Server hostname or IP |
| port | integer | UDP port of the server |

---

### REGISTER (Client → Main/Edge)

Client registers with the selected server.

Payload:
```json
{
  "chosen_edge": "127.0.0.1:9000"
}
```

| Field | Type | Description |
|------|------|-------------|
| chosen_edge | string | Address of the selected server |

---

### PREDICTION (Client → Main/Edge)

Periodic client update containing predicted movement and state.

Payload:
```json
{
  "tick": 123,
  "state": {
    "x": 1.2,
    "y": -3.4
  },
  "input": {
    "dx": 1,
    "dy": 0
  }
}
```

| Field | Type | Description |
|------|------|-------------|
| tick | integer | Client simulation tick |
| state.x | float | Predicted X position |
| state.y | float | Predicted Y position |
| input.dx | integer | X movement input (-1, 0, 1) |
| input.dy | integer | Y movement input (-1, 0, 1) |

---

### STATE_UPDATE (Main/Edge → Client)

Server sends authoritative state update.

Payload:
```json
{
  "server_tick": 540,
  "sent_timestamp_ms": 1710000000500,
  "source_client_id": "c3",
  "origin_timestamp_ms": 1710000000000,
  "authoritative": {
    "x": 1.1,
    "y": -3.2
  }
}
```

| Field | Type | Description |
|------|------|-------------|
| server_tick | integer | Server simulation tick |
| sent_timestamp_ms | integer | Time when server sent the message |
| source_client_id | string | Original sender of the forwarded update |
| origin_timestamp_ms | integer | Original sender timestamp preserved by the server |
| authoritative.x | float | Authoritative X position |
| authoritative.y | float | Authoritative Y position |

---

### ROLLBACK (Main/Edge → Client)

Server instructs the client to correct its predicted state.

Payload:
```json
{
  "server_tick": 540,
  "sent_timestamp_ms": 1710000000500,
  "authoritative": {
    "x": 1.1,
    "y": -3.2
  }
}
```

| Field | Type | Description |
|------|------|-------------|
| server_tick | integer | Server simulation tick |
| sent_timestamp_ms | integer | Time when server sent the message |
| authoritative.x | float | Correct X position |
| authoritative.y | float | Correct Y position |

---

# Client Protocol Flow

1. **Discover edges**

Client sends `DISCOVER` to the main server and receives `EDGE_LIST`.

2. **Select best edge**

Client sends multiple `PING` probes and chooses the edge with the lowest median RTT.

3. **Register**

Client sends `REGISTER` to the selected server.

4. **Run**

Client periodically sends `PREDICTION` updates and listens for server messages (`STATE_UPDATE`, `ROLLBACK`).

---

# Tick Rate

Clients send updates at a fixed tick rate.

Default:

```text
30 ticks/sec
```

This means a prediction update is sent every:

```text
~33 ms
```

---

# Latency Measurement

Latency is measured using **RTT (Round Trip Time)** via `PING/PONG`.

```
RTT = time(PONG received) − time(PING sent)
```

Server messages may include `sent_timestamp_ms`, allowing clients or visualization tools to measure server → client delay:

```
delay = receive_time_ms − sent_timestamp_ms
```

---

# Server Requirements

### Main Server
- Handle `DISCOVER`
- Return `EDGE_LIST`
- May also process client updates directly (same responsibilities as edge server)

### Edge Server
- Reply to `PING` with `PONG`
- Accept `REGISTER`
- Receive `PREDICTION`
- Optionally send `STATE_UPDATE` or `ROLLBACK`


---

# Running Multiple Clients

The `run_clients.py` script launches multiple client instances for experiments.

Example:

python3 run_clients.py --n 20 --main 127.0.0.1:8000 --duration 30

Options:
- --n: number of clients
- --duration: experiment runtime in seconds
- --stagger-ms: delay between launching clients
- --use-discovery: use main server discovery

---

# Logging

Clients log important events to stdout. When running experiments with `run_clients.py`, the output from each client is captured and written to separate log files.

Each client log file is stored in `logs/<client_id>.log`.

Example:
- `logs/c0.log`
- `logs/c1.log`

---

## Endpoint Selection Logging

When a client selects an endpoint, it logs the measured RTT values and the chosen server.

Example:

    [client] ping results:
      ('127.0.0.1', 9000) rtts=[...] median=6.62ms
      ('127.0.0.1', 9001) rtts=[...] median=209.83ms

    [client] selected edge ('127.0.0.1', 9000) (median=6.62ms)

This confirms that clients are selecting the lowest-latency endpoint.

---

## Player-to-Player Latency Logging

When a client receives an update forwarded by the server, it computes the end-to-end latency between the original sender and the receiving client.

Latency is computed as:

    latency_ms = receive_time_ms - origin_timestamp_ms

Example log entry:

    [client] FORWARDED_UPDATE source=c3 dest=c7 latency_ms=46

Fields:
- `source`: original sender
- `dest`: receiving client
- `latency_ms`: measured end-to-end latency

These logs are used to compute **mean worst connection time**.

---

## Multi-Client Experiment Logging

The `run_clients.py` script launches multiple client instances and captures their output into log files.

Example:

    python3 run_clients.py --n 20 --main 127.0.0.1:8000 --duration 30

Each client’s output is written to `logs/<client_id>.log`.

These logs can later be processed to analyze latency across all clients in the session.