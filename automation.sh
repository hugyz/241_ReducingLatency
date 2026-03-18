#!/bin/bash

# Usage: ./automation.sh <num_edges> <num_clients> [features...]
# Features (any order, all optional): color region seed terrain ai

CLIENT_PIDS=()
EDGE_PIDS=()
EDGE_ADDRS=()
EDGE_ACTUAL_ADDRS=()
MAIN_PID=""
MAIN_LOG=""

CLEANED_UP=false
cleanup() {
  $CLEANED_UP && return
  CLEANED_UP=true
  echo ""
  echo "Shutting down..."

  if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" ]]; then
    # ── Windows (Git Bash) ──
    for pid in "${CLIENT_PIDS[@]}"; do
      taskkill //F //T //PID "$pid" 2>/dev/null
    done
    for pid in "${EDGE_PIDS[@]}" "$MAIN_PID"; do
      [ -n "$pid" ] && taskkill //F //T //PID "$pid" 2>/dev/null
    done
    taskkill //F //IM "go.exe" 2>/dev/null &
    taskkill //F //IM "main-server.exe" 2>/dev/null &
    taskkill //F //IM "edge-server.exe" 2>/dev/null &
    wait
    # Port-based cleanup
    for addr in "${EDGE_ACTUAL_ADDRS[@]}" "${EDGE_ADDRS[@]}" "$MAIN_ADDR"; do
      [ -z "$addr" ] && continue
      p="${addr##*:}"
      netstat -ano 2>/dev/null | grep ":${p}[^0-9]" | awk '{print $5}' | tr -d '\r' | sort -u | while read pid; do
        [ -n "$pid" ] && [ "$pid" != "0" ] && taskkill //F //PID "$pid" 2>/dev/null
      done
    done
  else
    # ── Linux/Mac ──
    for pid in "${CLIENT_PIDS[@]}" "${EDGE_PIDS[@]}" "$MAIN_PID"; do
      [ -n "$pid" ] && kill -9 "$pid" 2>/dev/null
    done
    pkill -9 -f "go run" 2>/dev/null
    pkill -9 -f "main-server" 2>/dev/null
    pkill -9 -f "edge-server" 2>/dev/null
    # Port-based cleanup
    for addr in "${EDGE_ACTUAL_ADDRS[@]}" "${EDGE_ADDRS[@]}" "$MAIN_ADDR"; do
      [ -z "$addr" ] && continue
      p="${addr##*:}"
      lsof -ti ":$p" 2>/dev/null | xargs -r kill -9 2>/dev/null
    done
  fi

  echo "All processes stopped."
  exit 0
}
trap cleanup INT TERM EXIT

NUM_EDGES=${1:-0}
NUM_CLIENTS=${2:-1}
DURATION=300
CONFIG="./edge/config.json"

USE_COLOR=false
USE_REGION=false
USE_SEED=false
USE_TERRAIN=false
USE_AI=false

for arg in "${@:3}"; do
  case "$arg" in
    color)   USE_COLOR=true ;;
    region)  USE_REGION=true ;;
    seed)    USE_SEED=true ;;
    terrain) USE_TERRAIN=true ;;
    ai)      USE_AI=true ;;
    *) echo "Warning: unknown feature '$arg', ignoring." ;;
  esac
done

echo "Features: color=$USE_COLOR region=$USE_REGION seed=$USE_SEED terrain=$USE_TERRAIN ai=$USE_AI"

LOCATIONS=($(python3 -c "
import json
with open('$CONFIG') as f:
    data = json.load(f)
for key in data.keys():
    print(key)
" | tr -d '\r'))

if [ ${#LOCATIONS[@]} -eq 0 ]; then
  echo "Error: could not read locations from $CONFIG"
  exit 1
fi

# ── Main Server ───────────────────────────────────────────────────────────────
MAIN_LOCATION=${LOCATIONS[0]}

echo "Starting main server (location: $MAIN_LOCATION)..."
MAIN_LOG=$(mktemp)
(cd edge && go run ./cmd/main-server/ "$MAIN_LOCATION" config.json) > "$MAIN_LOG" 2>&1 &
MAIN_PID=$!

# Wait until main server is actually listening
MAIN_ADDR=""
for i in $(seq 1 60); do
  MAIN_ADDR=$(grep -o 'Listening on: [^ ]*' "$MAIN_LOG" 2>/dev/null | head -1 | sed 's/Listening on: //' | tr -d '\r')
  [ -n "$MAIN_ADDR" ] && break
  sleep 0.5
done
cat "$MAIN_LOG"

if [ -z "$MAIN_ADDR" ]; then
  echo "Error: could not detect main server address"
  cleanup
fi
echo "Main server ready at: $MAIN_ADDR"

# ── Edge Servers ──────────────────────────────────────────────────────────────
# Edge server args: <node_region> <upstream_main_addr> <delay_config.json>
# The edge picks its own random port — we read it back from the log
EDGE_LOCS=()
NUM_REMAINING=$(( ${#LOCATIONS[@]} - 1 ))

for ((e=0; e<NUM_EDGES; e++)); do
  if [ $NUM_REMAINING -gt 0 ]; then
    LOC_IDX=$(( (e % NUM_REMAINING) + 1 ))
  else
    LOC_IDX=0
  fi
  EDGE_LOC=${LOCATIONS[$LOC_IDX]}
  EDGE_LOCS+=("$EDGE_LOC")
  EDGE_LOG=$(mktemp)

  echo "Starting edge server $((e+1)) (location: $EDGE_LOC, upstream: $MAIN_ADDR)..."
  (cd edge && go run ./cmd/edge-server/ "$EDGE_LOC" "$MAIN_ADDR" config.json) > "$EDGE_LOG" 2>&1 &
  EDGE_PIDS+=($!)

  # Wait until this edge is actually listening
  echo "  Waiting for edge $((e+1)) to be ready..."
  EDGE_READY=false
  for i in $(seq 1 60); do
    grep -q 'Listening on' "$EDGE_LOG" 2>/dev/null && EDGE_READY=true && break
    sleep 0.5
  done
  cat "$EDGE_LOG"

  if ! $EDGE_READY; then
    echo "Error: edge server $((e+1)) failed to start in time"
    cleanup
  fi

  # Read the actual address the edge bound to (random OS-assigned port)
  ACTUAL_ADDR=$(grep -o 'Listening on: [^ ]*' "$EDGE_LOG" | head -1 | sed 's/Listening on: //' | tr -d '\r')
  EDGE_ACTUAL_ADDRS+=("$ACTUAL_ADDR")
  echo "  Edge $((e+1)) ready at $ACTUAL_ADDR"
done

# ── Wait for all edges to register with main ─────────────────────────────────
if [ $NUM_EDGES -gt 0 ]; then
  echo "Waiting for all $NUM_EDGES edge(s) to register with main server..."
  for i in $(seq 1 60); do
    REGISTERED=$(grep -c 'Registered edge server' "$MAIN_LOG" 2>/dev/null | tr -d '\r' || echo 0)
    [ "$REGISTERED" -ge "$NUM_EDGES" ] && break
    sleep 0.5
  done
  REGISTERED=$(grep -c 'Registered edge server' "$MAIN_LOG" 2>/dev/null | tr -d '\r' || echo 0)
  if [ "$REGISTERED" -lt "$NUM_EDGES" ]; then
    echo "Error: only $REGISTERED/$NUM_EDGES edge(s) registered with main in time"
    echo "Main server log:"
    cat "$MAIN_LOG"
    cleanup
  fi
  echo "All $NUM_EDGES edge(s) confirmed registered with main."
fi

# ── Build Server Pool ─────────────────────────────────────────────────────────
# Use actual edge addresses (random ports), not fixed ones
SERVER_POOL=("$MAIN_ADDR")
SERVER_LOCS=("$MAIN_LOCATION")
for ((e=0; e<NUM_EDGES; e++)); do
  SERVER_POOL+=("${EDGE_ACTUAL_ADDRS[$e]}")
  SERVER_LOCS+=("${EDGE_LOCS[$e]}")
done

POOL_SIZE=${#SERVER_POOL[@]}
TERRAIN_TYPES=("forest" "desert" "urban" "snow" "volcano")
NUM_TERRAINS=${#TERRAIN_TYPES[@]}

# Generate ONE shared seed and terrain for the whole lobby
if $USE_SEED;    then SHARED_SEED=$(( RANDOM * RANDOM )); fi
if $USE_TERRAIN; then SHARED_TERRAIN="${TERRAIN_TYPES[$((RANDOM % NUM_TERRAINS))]}"; fi

# ── Clients ───────────────────────────────────────────────────────────────────
echo "Starting $NUM_CLIENTS client(s) across $POOL_SIZE server(s)..."

for ((i=1; i<=NUM_CLIENTS; i++)); do
  SERVER_IDX=$(( RANDOM % POOL_SIZE ))
  SERVER=${SERVER_POOL[$SERVER_IDX]}
  LOC=${SERVER_LOCS[$SERVER_IDX]}

  ARGS=(--client-id "p$i" --edge "$SERVER")

  if $USE_COLOR; then
    ARGS+=(--color $(( RANDOM % 9 )))
  else
    ARGS+=(--color $(( (i-1) % 9 )))
  fi

  if $USE_REGION; then
    RAND_LOC=${LOCATIONS[$((RANDOM % ${#LOCATIONS[@]}))]}
    ARGS+=(--region "$RAND_LOC")
  else
    ARGS+=(--region "$LOC")
  fi

  if $USE_SEED;    then ARGS+=(--map-seed "$SHARED_SEED"); fi
  if $USE_TERRAIN; then ARGS+=(--terrain "$SHARED_TERRAIN"); fi
  if $USE_AI;      then ARGS+=(--ai); fi

  echo "  Client p$i -> $SERVER (region: $LOC)"
  python3 arena_game.py "${ARGS[@]}" &
  CLIENT_PIDS+=($!)   # capture Python PID immediately, before sleep
  sleep 1.0           # stagger clients so they don't all hit the server at once
done

echo "All $NUM_CLIENTS client(s) running. Session ends in $DURATION seconds (Ctrl+C to stop)..."
sleep $DURATION