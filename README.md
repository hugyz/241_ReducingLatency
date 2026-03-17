# WARZONE - Multiplayer Top-Down Shooter

A networked multiplayer arena shooter with simulated regional latency,
built with a Python game client (pygame) and Go edge/main server infrastructure.

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
- [Plotting Latency Logs](#plotting-latency-logs)

---

## Prerequisites

- Go 1.23+
- Python 3.10+
- Python packages: pygame, pandas

Install Python dependencies:

    pip install pygame pandas

---

## Architecture Overview

    client -> edge -> main -> edge -> client

The main server is the authoritative hub. It holds a registry of all connected
clients and which edge node each one registered through. Edge servers are
regional relay nodes -- they sit between clients and the main server,
simulating realistic one-way propagation delay on every hop. Clients that
connect directly to the main server are handled entirely by it.

Discovery: At connect time, the Python client pings all candidate endpoints (edge + main)
and picks the one with the lowest median RTT. The main server is always
included as a fallback candidate.

---

## Build

Compile the Go servers:

    cd edge
    make

This produces two binaries: main-server and edge-server.

---

## Running the Servers

You can either run the servers directly using `go run`, or build the binaries first and run them.

---

### Main Server

Run with Go:

```
go run cmd/main-server <region> <config.json>
```

Example:

```
go run cmd/main-server A config.json
```

Or run the compiled binary:

```
./main-server <region> <config.json>
```

Example:

```
./main-server A config.json
```

The main server automatically binds to an available UDP port and prints the address it is listening on.

Example output:

```
--- A (Main Server) ---
Listening on: 192.168.1.5:8000
```

The printed address should be used by edge servers and clients when connecting.

---

### Edge Server

Run with Go:

```
go run cmd/edge-server <region> <main_host:port> <config.json>
```

Example:

```
go run cmd/edge-server B 127.0.0.1:8000 config.json
```

Or run the compiled binary:

```
./edge-server <region> <main_host:port> <config.json>
```

Example:

```
./edge-server B 127.0.0.1:8000 config.json
```

The edge server automatically binds to an available UDP port, registers itself with the main server, and begins relaying client traffic.

Example output:

```
--- B (Edge) ---
Listening on: 192.168.1.5:9001
Target: 127.0.0.1:8000
```

Edge servers act as regional relay nodes between clients and the main server.

---

### Startup Order

Servers should be started in the following order:

```
1. Main server
2. Edge servers
3. Game clients
```

---

## Running the Game Client

    python arena_game.py \
      --client-id <unique_id> \
      --main <main_host:port> \
      --color <0-8> \
      --region <region> \
      --map-seed <integer> \
      --terrain <terrain> \
      [--ai]

All players must use the same --map-seed and --terrain. These determine
the procedurally generated map layout.

### Client arguments

|               |                                                                 |
|---------------|-----------------------------------------------------------------|
| --client-id   | Unique player identifier (e.g., p1, alice)                     |
| --main        | Main server address for discovery (e.g., 127.0.0.1:8000)       |
| --region      | Client region (must match a key in config.json, e.g., A, B, Perth) |
| --color       | Player colour index 0–8 (see table below)                      |
| --map-seed    | Shared map seed (must be the same for all players)             |
| --terrain     | Map terrain type (forest, desert, urban, snow, volcano)        |
| --ai          | Flag to enable AI enemies                                      |

### Colour index reference

  0 = Green
  1 = Blue
  2 = Red
  3 = Purple
  4 = Orange
  5 = Cyan
  6 = Yellow
  7 = Pink
  8 = White

## Running Multiple Clients

For load testing and repeatable experiments, the project includes a helper script that launches multiple game clients automatically.

### Usage

Run with the default of 8 clients:

```bash
./run_clients.sh
```

Run with a custom number of clients:

```bash
./run_clients.sh 16
```

Set the `MAIN` variable in the file to the main server address. Ex: `MAIN=192.168.1.74:52101`

The script automatically:

- assigns the first half of clients to region `A`
- assigns the second half to region `B`
- cycles colour indices as needed
- runs the simulation for 30 seconds
- terminates all spawned clients at the end of the test

This is useful for scalability experiments, repeatable latency tests, and collecting larger log sets without manually launching each client.


---

## Example Scenarios

All examples below assume you have built the binaries with `make` inside ./edge/.

### Minimal local 1v1 (no edge node)

Both players connect directly to the main server. No simulated regional latency.

    # Terminal 1 - main server
    ./main-server A config.json

    # Terminal 2 - Player 1
    python arena_game.py --client-id p1 --main 127.0.0.1:8000 --region A --color 0

    # Terminal 3 - Player 2
    python arena_game.py --client-id p2 --main 127.0.0.1:8000 --region A --color 1

---

### Two-region local experiment (edge routing)

Simulates players in different regions, routed through an edge node.
Adjust config.json to set the desired latency between A and B.

    # Terminal 1 - main server in region A
    ./main-server A config.json

    # Terminal 2 - edge server in region B
    ./edge-server B 127.0.0.1:8000 9001 config.json

    # Terminal 3 - Player 1 (region A, direct to main)
    python arena_game.py --client-id p1 --main 127.0.0.1:8000 --region A --color 0

    # Terminal 4 - Player 2 (region B, through edge)
    python arena_game.py --client-id p2 --main 127.0.0.1:8000 --region B --color 1

---

### Perth/Sydney geographic experiment

Simulates intercity latency (~46 ms one-way). The main server represents
Sydney; the edge node represents Perth. Update config.json with region names
"Sydney" and "Perth" and set the delay values accordingly (see the
config.json section below). The main server routes Perth clients to the
Perth edge and retains Sydney clients directly.

    # Terminal 1 - main server (Sydney)
    ./main-server Sydney config.json

    # Terminal 2 - edge node (Perth)
    ./edge-server Perth 127.0.0.1:8000 config.json

    # Sydney players (direct to main)
    python arena_game.py --client-id sydney1 --main 127.0.0.1:8000 --region Sydney --color 0
    python arena_game.py --client-id sydney2 --main 127.0.0.1:8000 --region Sydney --color 1

    # Perth players (through edge)
    python arena_game.py --client-id perth1 --main 127.0.0.1:8000 --region Perth --color 2
    python arena_game.py --client-id perth2 --main 127.0.0.1:8000 --region Perth --color 3

---

### Four-player AI brawl on volcano terrain

Single server, AI enemies enabled, custom seed for a different layout.

    # Terminal 1
    ./main-server A config.json

    # Terminals 2-5
    python arena_game.py --client-id p1 --main 127.0.0.1:8000 --region A --color 0 --map-seed 99999 --terrain volcano --ai
    python arena_game.py --client-id p2 --main 127.0.0.1:8000 --region A --color 2 --map-seed 99999 --terrain volcano --ai
    python arena_game.py --client-id p3 --main 127.0.0.1:8000 --region A --color 4 --map-seed 99999 --terrain volcano --ai
    python arena_game.py --client-id p4 --main 127.0.0.1:8000 --region A --color 6 --map-seed 99999 --terrain volcano --ai

---

### High-latency stress test

Set large delay values in config.json (e.g. 200 ms) and run the two-region
setup. The HUD PING indicator turns yellow above 30 ms and red above 80 ms.
Use this to observe the effects of bad network conditions on prediction and
rollback behaviour.

---

## Configuring Latency via config.json

config.json is a delay matrix -- a nested JSON object where each key is a
region name and its value maps destination region names to one-way delay
in milliseconds.

### Format

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

Every region used as a server region or as a client --region argument must
appear as a top-level key. The value matrix[A][B] is the one-way simulated
delay when a packet travels from a node in region A to a node in region B.
If a pair is missing, the delay defaults to zero.

### Default (near-zero, same machine)

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

### Perth/Sydney example (~46 ms one-way cross-country)

    {   
        "Sydney": {
            "Sydney": 5,
            "Perth":  46
        },
        "Perth": {
            "Sydney": 46,
            "Perth":  5
        }
    }


### Three-region EU/US/Asia example

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

### How delays are applied

Delays are split across hops to avoid double-counting:

    client -> edge      simulated by edge server
    edge -> main        simulated by edge server
    main -> edge        simulated by main server
    edge -> client      simulated by edge server

    client -> main      simulated by main server (direct connections only)
    main -> client      simulated by main server (direct connections only)

To simulate asymmetric links (e.g. upload slower than download), set
different values for A->B vs B->A.

---

## Controls

| Control      | Action              |
|-------------|---------------------|
| W / A / S / D | Move               |
| Mouse        | Aim                |
| Left Click   | Shoot              |
| R            | Reload             |
| 1 – 7        | Switch weapon slot |
| E            | Pick up weapon crate |
| ESC          | Quit               |

---

## Weapons Reference

  | Slot | Weapon            | Damage | Fire Rate | Ammo       | Special      |
|------|------------------|--------|-----------|------------|--------------|
| 1    | Pistol           | 12     | 0.25s     | Unlimited  | —            |
| 2    | SMG              | 10     | 0.07s     | 45         | —            |
| 3    | Shotgun          | 8×7    | 0.55s     | 16         | —            |
| 4    | Rifle            | 35     | 0.35s     | 20         | Piercing     |
| 5    | Flamethrower     | 5      | 0.04s     | 100        | Flame        |
| 6    | Grenade Launcher | 50     | 0.80s     | 10         | Explosion    |
| 7    | Railgun          | 100    | 1.20s     | 5          | Instant      |
---

## Terrains

forest    Dense woodland — tight corridors  
desert    Open sands — long sightlines  
urban     City ruins — lots of cover  
snow      Frozen tundra — reduced fog  
volcano   Lava fields — narrow paths  

---

## Protocol Reference

All messages are JSON-encoded UDP datagrams.

 | Field         | Type   | Description |
|--------------|--------|------------|
| type         | string | PING, PONG, DISCOVER, EDGE_LIST, REGISTER, PREDICTION, STATE_UPDATE, ROLLBACK |
| client_id    | string | Originating client identifier |
| seq          | int    | Monotonically increasing sequence number |
| timestamp_ms | int64  | Unix timestamp in milliseconds at send time |
| payload      | object | Type-specific data |

### PREDICTION payload

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

action can be null or one of:

    { "type": "shoot", "bx": 520, "by": 390, "angle": 1.57,
      "weapon_idx": 2, "spread_seed": 42314 }
    { "type": "hit",    "target_id": "p2", "damage": 12 }
    { "type": "dead" }
    { "type": "pickup", "crate_idx": 3 }

## Plotting Latency Logs

Latency logs recorded by the clients can be visualized using `plot_latency.py`. This script supports both per-client latency plots and aggregate latency plots across all client CSV files in a folder.


The script reads client CSV logs, aligns them onto a common timeline, computes latency metrics, and plots the results using `matplotlib`.

### Features

- plot all connection latencies for a single client log
- align multiple client logs to a common framerate
- compute aggregate latency metrics across all clients
- visualize maximum or average latency over time

### Example usage

Inside `plot_latency.py`, the default main block plots four individual client logs and then computes an aggregate metric across the full `logs/` folder:

Run it with:

```bash
python plot_latency.py
```

### Available metric helpers

The script includes several metric functions:

- `max_latency_nan` — maximum latency per frame, ignoring missing values
- `mean_latency_nan` — mean latency per frame, ignoring missing values
- `mean_latency_strict` — mean latency per frame, requiring all values
- `max_latency_strict` — maximum latency per frame, requiring all values

These can be passed into `plot_metric_across_folder()` depending on the analysis being performed.

