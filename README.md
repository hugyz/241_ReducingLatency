# WARZONE — Multiplayer Top-Down Shooter

A networked multiplayer arena shooter with simulated regional latency, built with a Python game client (pygame) and Go edge/main server infrastructure.

---

## Table of Contents

- [Prerequisites](#prerequisites)
- [Architecture Overview](#architecture-overview)
- [Build](#build)
- [Running the Servers](#running-the-servers)
- [Running the Game Client](#running-the-game-client)
- [Example Scenarios](#example-scenarios)
- [Configuring Latency via config.json](#configuring-latency-via-configjson)
- [Controls](#controls)
- [Weapons Reference](#weapons-reference)
- [Terrains](#terrains)
- [Protocol Reference](#protocol-reference)

---

## Prerequisites

- **Go** 1.23+
- **Python** 3.10+
- Python packages: `pygame`, `pandas`

Install Python dependencies:
```
pip install pygame pandas
```

---

## Architecture Overview

```
client → edge → main → edge → client
```

The **main server** is the authoritative hub. It holds a registry of all connected clients and which edge node each one registered through. **Edge servers** are regional relay nodes — they sit between clients and the main server, simulating realistic one-way propagation delay on every hop. Clients that connect directly to the main server are handled entirely by it.

At connect time, the Python client pings all candidate endpoints (edge + main) and picks the one with the lowest median RTT. The main server is always included as a fallback candidate.

---

## Build

Compile the Go servers:

```bash
cd edge
make
```

This produces two binaries: `main-server` and `edge-server`.

---

## Running the Servers

### Main server

```bash
go run cmd/main-server <region> <listen_addr> <config.json>
```

Example — main server in region `A`, listening on port 8000:

```bash
go run cmd/main-server A 127.0.0.1:8000 config.json
```

Or with the compiled binary:

```bash
./main-server A 127.0.0.1:8000 config.json
```

### Edge server

```bash
go run cmd/edge-server <region> <main_server_port> <config.json>
```

Example — edge node in region `B`, connecting back to main on port 8000, listening on port 9001:

```bash
go run cmd/edge-server B 127.0.0.1:8000 9001 config.json
```

Or with the compiled binary:

```bash
./edge-server B 127.0.0.1:8000 9001 config.json
```

---

## Running the Game Client

```bash
python arena_game.py \
  --edge <ip:port> \
  --client-id <unique_id> \
  --color <0-8> \
  --main <main_host:port> \
  --region <region> \
  --map-seed <integer> \
  --terrain <terrain> \
  [--ai]
```

**All players must use the same `--map-seed` and `--terrain`** — these determine the procedurally generated map layout.

### Client arguments

| Flag | Description | Example |
|---|---|---|
| `--client-id` | Unique player identifier | `p1`, `alice` |
| `--edge` | Edge node or main server address | `127.0.0.1:8000` |
| `--main` | Main server address (for discovery) | `127.0.0.1:8000` |
| `--region` | Client's region (must match a key in config.json) | `A`, `B`, `Perth` |
| `--color` | Player colour index (0–8) | `0` |
| `--map-seed` | Shared map seed — must be the same for all players | `12345` |
| `--terrain` | Map terrain type | `forest` |
| `--ai` | Enable AI enemies | _(flag, no value)_ |

### Colour index reference

| Index | Colour |
|---|---|
| 0 | Green |
| 1 | Blue |
| 2 | Red |
| 3 | Purple |
| 4 | Orange |
| 5 | Cyan |
| 6 | Yellow |
| 7 | Pink |
| 8 | White |

---

## Example Scenarios

All examples below assume you have built the binaries with `make` inside `./edge/`.

### Minimal local 1v1 (no edge node)

Both players connect directly to the main server — no simulated regional latency.

```bash
# Terminal 1 — main server
./main-server A 127.0.0.1:8000 config.json

# Terminal 2 — Player 1
python arena_game.py --client-id p1 --edge 127.0.0.1:8000 --main 127.0.0.1:8000 --region A --color 0

# Terminal 3 — Player 2
python arena_game.py --client-id p2 --edge 127.0.0.1:8000 --main 127.0.0.1:8000 --region A --color 1
```

---

### Two-region local experiment (edge routing)

Simulates players in different regions, routed through an edge node. Adjust `config.json` to set the desired latency between `A` and `B`.

```bash
# Terminal 1 — main server in region A
./main-server A 127.0.0.1:8000 config.json

# Terminal 2 — edge server in region B
./edge-server B 127.0.0.1:8000 9001 config.json

# Terminal 3 — Player 1 (region A, direct to main)
python arena_game.py --client-id p1 --edge 127.0.0.1:8000 --main 127.0.0.1:8000 --region A --color 0

# Terminal 4 — Player 2 (region B, through edge)
python arena_game.py --client-id p2 --edge 127.0.0.1:9001 --main 127.0.0.1:8000 --region B --color 1
```

---

### Perth/Sydney geographic experiment

A realistic intercity scenario. Set `A` = Sydney (main server region) and `B` = Perth (edge region) in `config.json`, with latency values reflecting real cross-country RTT (~70 ms one-way).

```bash
# Terminal 1 — main server (Sydney)
./main-server Sydney 127.0.0.1:8000 config.json

# Terminal 2 — edge node (Perth)
./edge-server Perth 127.0.0.1:8000 9001 config.json

# Sydney players (direct to main)
python arena_game.py --client-id sydney1 --edge 127.0.0.1:8000 --main 127.0.0.1:8000 --region Sydney --color 0
python arena_game.py --client-id sydney2 --edge 127.0.0.1:8000 --main 127.0.0.1:8000 --region Sydney --color 1

# Perth players (through edge)
python arena_game.py --client-id perth1 --edge 127.0.0.1:9001 --main 127.0.0.1:8000 --region Perth --color 2
python arena_game.py --client-id perth2 --edge 127.0.0.1:9001 --main 127.0.0.1:8000 --region Perth --color 3
```

---

### Four-player AI brawl on a volcano map

Single server, AI enemies enabled, unusual seed for a different map layout:

```bash
# Terminal 1
./main-server A 127.0.0.1:8000 config.json

# Terminals 2–5
python arena_game.py --client-id p1 --edge 127.0.0.1:8000 --main 127.0.0.1:8000 --region A --color 0 --map-seed 99999 --terrain volcano --ai
python arena_game.py --client-id p2 --edge 127.0.0.1:8000 --main 127.0.0.1:8000 --region A --color 2 --map-seed 99999 --terrain volcano --ai
python arena_game.py --client-id p3 --edge 127.0.0.1:8000 --main 127.0.0.1:8000 --region A --color 4 --map-seed 99999 --terrain volcano --ai
python arena_game.py --client-id p4 --edge 127.0.0.1:8000 --main 127.0.0.1:8000 --region A --color 6 --map-seed 99999 --terrain volcano --ai
```

---

### High-latency stress test

To observe the effects of bad network conditions, set large delay values in `config.json` (e.g. 200 ms) and run the standard two-region setup. The HUD's `PING` indicator will turn red above 80 ms, and you can observe prediction/rollback behaviour.

---

## Configuring Latency via config.json

`config.json` is a **delay matrix** — a nested JSON object where each key is a region name and its value is a map of destination regions to **one-way delay in milliseconds**.

### Format

```json
{
    "RegionA": {
        "RegionA": <ms>,
        "RegionB": <ms>
    },
    "RegionB": {
        "RegionA": <ms>,
        "RegionB": <ms>
    }
}
```

Every region that will be used — either as a server region or a client `--region` argument — must appear as a top-level key. The value `from[A][B]` is the **one-way simulated delay** when a packet travels from a node in region `A` to a node in region `B`.

### Default (near-zero, same-machine)

```json
{
    "A": {
        "A": 5,
        "B": 5
    },
    "B": {
        "A": 5,
        "B": 5
    }
}
```

### Perth/Sydney example (~70 ms one-way cross-country)

```json
{
    "Sydney": {
        "Sydney": 5,
        "Perth":  70
    },
    "Perth": {
        "Sydney": 70,
        "Perth":  5
    }
}
```

### EU/US/Asia three-region example

```json
{
    "EU": {
        "EU":   10,
        "US":   90,
        "Asia": 150
    },
    "US": {
        "EU":   90,
        "US":   10,
        "Asia": 180
    },
    "Asia": {
        "EU":   150,
        "US":   180,
        "Asia": 10
    }
}
```

### How delays are applied

The delay simulation is split across hops to avoid double-counting:

```
client → edge       simulated by edge server
edge → main         simulated by edge server
main → edge         simulated by main server
edge → client       simulated by edge server

client → main       simulated by main server (direct connections only)
main → client       simulated by main server (direct connections only)
```

The delay looked up is always `matrix[sender_region][receiver_region]`. If a pair is missing from the config, the delay defaults to zero.

> **Tip:** To simulate asymmetric connections (e.g. upload slower than download), set different values for `A→B` vs `B→A`.

---

## Controls

| Key / Input | Action |
|---|---|
| `W A S D` | Move |
| Mouse | Aim |
| Left Mouse Button | Shoot |
| `R` | Reload |
| `1` – `7` | Switch weapon slot |
| `E` | Pick up weapon crate |
| `ESC` | Quit |

---

## Weapons Reference

| Slot | Name | Damage | Fire Rate | Ammo | Special |
|---|---|---|---|---|---|
| 1 | Pistol | 12 | 0.25 s | Unlimited | — |
| 2 | SMG | 10 | 0.07 s | 45 | — |
| 3 | Shotgun | 8 × 7 pellets | 0.55 s | 16 | — |
| 4 | Rifle | 35 | 0.35 s | 20 | Piercing |
| 5 | Flamethrower | 5 | 0.04 s | 100 | Flame |
| 6 | Grenade Launcher | 50 | 0.80 s | 10 | Explosion |
| 7 | Railgun | 100 | 1.20 s | 5 | Rail (instant) |

---

## Terrains

| Value | Description |
|---|---|
| `forest` | Dense woodland — tight corridors |
| `desert` | Open sands — long sightlines |
| `urban` | City ruins — lots of cover |
| `snow` | Frozen tundra — reduced fog |
| `volcano` | Lava fields — narrow paths |

---

## Protocol Reference

All messages are JSON-encoded UDP datagrams.

| Field | Type | Description |
|---|---|---|
| `type` | string | `PING`, `PONG`, `DISCOVER`, `EDGE_LIST`, `REGISTER`, `PREDICTION`, `STATE_UPDATE`, `ROLLBACK` |
| `client_id` | string | Originating client identifier |
| `seq` | int | Monotonically increasing sequence number |
| `timestamp_ms` | int64 | Unix timestamp in milliseconds at send time |
| `payload` | object | Type-specific data (position, action, region, edge list, etc.) |

### PREDICTION payload

```json
{
  "state": {
    "x": 512.0,
    "y": 384.0,
    "angle": 1.57,
    "hp": 85,
    "weapon_idx": 2
  },
  "action": null
}
```

`action` can be `null` or one of:

```json
{ "type": "shoot", "bx": 520, "by": 390, "angle": 1.57, "weapon_idx": 2, "spread_seed": 42314 }
{ "type": "hit",   "target_id": "p2", "damage": 12 }
{ "type": "dead" }
{ "type": "pickup", "crate_idx": 3 }
```
