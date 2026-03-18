# Edge/Main Server Integration Notes

## Architecture


The intended message flow is:

```
client → edge → main → edge → client
```
*can to change to main -> all clients

If a client connects directly to the main server:

```
client → main → client/edge
```

Edge servers are designed to behave as **dumb relays**.

---

## How to Run

```
make
```

Start the main server:

```
./main-server A 127.0.0.1:8000 config.json
```

Arguments:

```
<node_name> <listen_addr> <delay_config.json>

```
Start the edge server:
```
./edge-server B 127.0.0.1:8000 9001 config.json A
```

Arguments:

```
<node_name> <upstream_addr> <listen_port> <delay_config.json> <upstream_node_name>
```

## Main Server Behavior

The main server currently handles these message types:

- `PING`
- `DISCOVER`
- `REGISTER`
- `PREDICTION`

It maintains a global table of all clients:

```
clients[clientID] = {
    region
    registeredTo   // "main" or edge node name
    addr
}
```

If a client registers through an edge, the payload should include the registered edge. This allows the main server to determine which edge the client belongs to.

---

## Prediction Routing

When the main server receives a `PREDICTION` message:

1. It processes inbound delay.
2. It broadcasts the message to:
   - all **clients attached directly to the main server**
   - **each other edge server (once)**

The message **is not sent back to the sender’s edge**.

Example:

```
client on edge B sends update

main → clients on main
main → edge C
main → edge D
```

Edge **B does not receive the update back**.

Each edge server is responsible for forwarding the update to its own local clients.

---

## Edge Server Responsibilities

The edge server should act as a **relay and local gateway**.

### Messages from local clients

```
client → edge
edge → main
```

The edge server should:

- track local client addresses
- simulate **client → edge** delay
- simulate **edge → main** delay
- forward messages to the main server

---

### Messages from the main server

```
main → edge
edge → local clients
```

The edge server should:

- receive forwarded predictions from the main server
- simulate **edge → client** delay
- forward the message to all connected local clients

---

## Register Forwarding

When forwarding a `REGISTER` message to the main server, the payload should include:

```json
{
  "region": "A",
  "registered_edge": "B",
  "forwarded_by": "B"
}
```

This allows the main server to correctly associate the client with the edge.

---

## Prediction Forwarding

When forwarding `PREDICTION` messages, the edge server should **not modify**:

- `client_id`
- `seq`
- `timestamp`
- `payload`

The sender must remain the **client ID**

---

## Latency Model

Latency simulation is divided between the edge and main servers.

For clients connected to an edge:

```
client → edge     (simulated by edge)
edge → main       (simulated by edge)
main → edge       (simulated by main)
edge → client     (simulated by edge)
```

For clients connected directly to the main server:

```
client → main     (simulated by main)
main → client     (simulated by main)
```

This avoids double-counting delays and keeps the simulation consistent.