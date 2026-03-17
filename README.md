# WARZONE — Multiplayer Top-Down Shooter

A networked multiplayer arena shooter with simulated regional latency, built with a Python game client (pygame) and Go edge/main server infrastructure.

---

## Table of Contents

- [Prerequisites](#prerequisites)
- [Architecture Overview](#architecture-overview)
- [Build](#build)
- [Running the Servers](#running-the-servers)
- [Running the Game Client](#running-the-game-client)
- [Running Multiple Clients](#running-multiple-clients)
- [Example Scenarios](#example-scenarios)
- [Configuring Latency](#configuring-latency-via-configjson)
- [Controls](#controls)
- [Weapons Reference](#weapons-reference)
- [Terrains](#terrains)
- [Protocol Reference](#protocol-reference)
- [Plotting Latency Logs](#plotting-latency-logs)

---

## Prerequisites

- Go 1.23+
- Python 3.10+
- Python packages: `pygame`, `pandas`
- A graphical display (pygame renders a game window)
  - **Windows**: Works out of the box (used Git Bash)
  - **Linux/Mac (local desktop)**: Works with a display server running

```bash
pip install pygame pandas
```

---

## Architecture Overview

```
client -> edge -> main -> client
```

The main server is the authoritative hub. It holds a registry of all connected clients and which edge node each one registered through. Edge servers are regional relay nodes — they sit between clients and the main server, simulating realistic one-way propagation delay on every hop. Clients that connect directly to the main server are handled entirely by it.

**Discovery:** At connect time, the Python client pings all candidate endpoints (edge + main) and picks the one with the lowest median RTT. The main server is always included as a fallback candidate.

---

## Build

```bash
cd edge
make
```

This produces two binaries: `main-server` and `edge-server`.

---

## Running the Servers

Servers must be started in this order:

```
1. Main server
2. Edge servers (if any)
3. Game clients
```

### Main Server

```bash
# With go run
go run cmd/main-server <region> <config.json>

# Or with compiled binary
./main-server <region> <config.json>
```

Example:

```bash
./main-server A config.json
```

The main server binds to an available UDP port and prints its address:

```
--- A (Main Server) ---
Listening on: 192.168.1.5:8000
```

Use this printed address when starting edge servers.

---

### Edge Server

```bash
# With go run
go run cmd/edge-server <region> <main_host:port> <config.json>

# Or with compiled binary
./edge-server <region> <main_host:port> <config.json>
```

Example:

```bash
./edge-server B 192.168.1.5:8000 config.json
```

The edge server binds to an available UDP port, registers with main, and begins relaying:

```
--- B (Edge) ---
Listening on: 192.168.1.5:9001
Target: 192.168.1.5:8000
```

---

## Running the Game Client

```bash
python arena_game.py \
  --client-id <unique_id> \
  --edge <host:port> \
  --color <0-8> \
  --region <region> \
  [--ai]
```

### Client Arguments

| Argument | Required | Description |
|---|---|---|
| `--client-id` | Yes | Unique player identifier. Example: `p1`, `alice` |
| `--edge` | Yes | Server address to connect to (main or edge). Example: `192.168.1.5:8000` |
| `--region` | Yes | Client region — match a key in `config.json`. For latency testing purposes. Example: `A`, `Perth` |
| `--color` | No | Player colour index `0–8` (default: `0`) |
| `--ai` | No | Flag. Enables AI enemies |

### Colour Index Reference

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

## Running Multiple Clients

For load testing and repeatable experiments, use `run_clients.sh` to launch multiple clients and servers automatically.

### Usage

```bash
bash run_clients.sh <num_edges> <num_clients> [features...]
```

### Arguments

| Argument | Description |
|---|---|
| `num_edges` | Number of edge servers to start |
| `num_clients` | Number of game clients to spawn |
| `features` | Optional flags (see table below) |

### Feature Flags

| Flag | Description |
|---|---|
| `color` | Assign each client a random colour instead of cycling sequentially |
| `region` | Assign each client a random region instead of matching their server |
| `seed` | Generate a shared random map seed so all clients share the same map layout |
| `terrain` | Pick a random terrain type shared across all clients |
| `ai` | Enable AI enemies for all clients |

### Examples

```bash
# 2 edge servers, 4 clients, AI enabled, random colours
bash run_clients.sh 2 4 ai color

# 1 edge server, 8 clients, shared map seed and terrain
bash run_clients.sh 1 8 seed terrain

# No edge servers, 2 clients (both connect to main directly)
bash run_clients.sh 0 2
```

### What the script does

1. Starts the main server and waits until it is listening
2. Starts each edge server in order, waiting for each to come up before starting the next
3. Waits until all edge servers have registered with main
4. Spawns clients staggered 1 second apart, randomly distributed across available servers
5. Runs for 300 seconds then shuts everything down cleanly

---

## Example Scenarios

All examples assume binaries have been built with `make` inside `./edge/`.

### Minimal local 1v1 (no edge node)

Both players connect directly to the main server. No simulated latency.

```bash
# Terminal 1
./main-server A config.json

# Terminal 2
python arena_game.py --client-id p1 --edge 127.0.0.1:8000 --region A --color 0

# Terminal 3
python arena_game.py --client-id p2 --edge 127.0.0.1:8000 --region A --color 1
```

---

### Two-region local experiment (edge routing)

Simulates players in different regions routed through an edge node. Adjust `config.json` to set the desired latency between A and B.

```bash
# Terminal 1 — main server (region A)
./main-server A config.json

# Terminal 2 — edge server (region B)
./edge-server B 127.0.0.1:8000 config.json

# Terminal 3 — Player 1 (region A, direct to main)
python arena_game.py --client-id p1 --edge 127.0.0.1:8000 --region A --color 0

# Terminal 4 — Player 2 (region B, through edge)
python arena_game.py --client-id p2 --edge 127.0.0.1:<edge_port> --region B --color 1
```

---

### Perth/Sydney geographic experiment

Simulates intercity latency (~45 ms one-way). Update `config.json` with regions `Sydney` and `Perth` and set delay values accordingly.

```bash
# Terminal 1 — main server (Sydney)
./main-server Sydney config.json

# Terminal 2 — edge node (Perth)
./edge-server Perth 127.0.0.1:8000 config.json

# Sydney players
python arena_game.py --client-id sydney1 --edge 127.0.0.1:8000 --region Sydney --color 0
python arena_game.py --client-id sydney2 --edge 127.0.0.1:8000 --region Sydney --color 1

# Perth players
python arena_game.py --client-id perth1 --edge 127.0.0.1:<edge_port> --region Perth --color 2
python arena_game.py --client-id perth2 --edge 127.0.0.1:<edge_port> --region Perth --color 3
```

---

### Four-player AI brawl (automated)

```bash
bash run_clients.sh 0 4 ai color
```

---

### High-latency stress test

Set large delay values in `config.json` (e.g. `200` ms) and run the two-region setup. The HUD PING indicator turns yellow above 30 ms and red above 80 ms.

---

## Configuring Latency via config.json

`config.json` is a delay matrix — a nested JSON object where each key is a region name and its value maps destination region names to one-way delay in milliseconds.

### Format

```json
{
    "RegionA": {
        "RegionA": 5,
        "RegionB": 50
    },
    "RegionB": {
        "RegionA": 50,
        "RegionB": 5
    }
}
```

Every region used as a `--region` argument must appear as a top-level key. `matrix[A][B]` is the one-way simulated delay for a packet travelling from a node in region A to a node in region B. Missing pairs default to zero.

### Default (same machine, near-zero latency)

```json
{
    "A": { "A": 5, "B": 5 },
    "B": { "A": 5, "B": 5 }
}
```

### Perth/Sydney (~45 ms one-way)

```json
{
    "Sydney": { "Sydney": 5,  "Perth": 45 },
    "Perth":  { "Sydney": 45, "Perth": 5  }
}
```

### Three-region EU/US/Asia

```json
{
    "EU":   { "EU": 10,  "US": 90,  "Asia": 150 },
    "US":   { "EU": 90,  "US": 10,  "Asia": 180 },
    "Asia": { "EU": 150, "US": 180, "Asia": 10  }
}
```

### How delays are applied

| Hop | Simulated by |
|---|---|
| client → edge | edge server |
| edge → main | edge server |
| main → edge | main server |
| edge → client | edge server |
| client → main (direct) | main server |
| main → client (direct) | main server |

To simulate asymmetric links (upload slower than download), set different values for A→B vs B→A.

---

## Controls

| Key | Action |
|---|---|
| `W A S D` | Move |
| Mouse | Aim |
| Left click | Shoot |
| `R` | Reload |
| `1` – `7` | Switch weapon slot |
| `E` | Pick up weapon crate |
| `ESC` | Quit |

---

## Weapons Reference

| Slot | Name | Damage | Fire Rate | Ammo | Special |
|---|---|---|---|---|---|
| 1 | PISTOL | 12 | 0.25s | Unlimited | — |
| 2 | SMG | 10 | 0.07s | 45 | — |
| 3 | SHOTGUN | 8 × 7 | 0.55s | 16 | — |
| 4 | RIFLE | 35 | 0.35s | 20 | Piercing |
| 5 | FLAMETHROWER | 5 | 0.04s | 100 | Flame |
| 6 | GRENADE LAUNCHER | 50 | 0.80s | 10 | Explosion |
| 7 | RAILGUN | 100 | 1.20s | 5 | Instant |

---

## Terrains

| Terrain | Description |
|---|---|
| `forest` | Dense woodland — tight corridors |
| `desert` | Open sands — long sightlines |
| `urban` | City ruins — lots of cover |
| `snow` | Frozen tundra — reduced fog radius |
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
| `payload` | object | Type-specific data |

### PREDICTION payload

```json
{
  "state": {
    "x": 512.0,
    "y": 384.0,
    "angle": 1.57,
    "hp": 85
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

---

## Plotting Latency Logs

Latency logs are recorded automatically by each client to `logs/<client_id>.csv`. Visualize them with `plot_latency.py`.

```bash
python plot_latency.py
```

### Available metric functions

| Function | Description |
|---|---|
| `max_latency_nan` | Maximum latency per frame, ignoring missing values |
| `mean_latency_nan` | Mean latency per frame, ignoring missing values |
| `mean_latency_strict` | Mean latency per frame, requiring all clients present |
| `max_latency_strict` | Maximum latency per frame, requiring all clients present |

Pass any of these into `plot_metric_across_folder()` to control how aggregate latency is computed across the full `logs/` folder.