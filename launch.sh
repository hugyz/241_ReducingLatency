#!/usr/bin/env bash
# launch.sh — start main server + edge nodes + game clients
#
# Usage examples:
#
#   Basic (2 players, both through main server):
#     ./launch.sh
#
#   Perth/Sydney experiment (2 Perth clients on edge, 2 Sydney clients on main):
#     ./launch.sh --main-delay 45 --edge perth:5:8001 --players "p1:8001,p2:8001,p3:8000,p4:8000"
#
#   Multiple edge nodes:
#     ./launch.sh --main-delay 45 \
#                 --edge perth:5:8001 \
#                 --edge melbourne:20:8002 \
#                 --players "p1:8001,p2:8001,p3:8002,p4:8000"
#
# Arguments:
#   --main-delay <ms>          one-way delay for main server in ms (default: 0)
#   --main-port <port>         main server port (default: 8000)
#   --edge <name:delay:port>   add an edge node, repeatable
#   --players <id:port,...>    comma-separated playerid:port pairs
#                              defaults to p1:8000,p2:8000 if omitted
#   --terrain <name>           forest|desert|urban|snow|volcano (default: forest)
#   --seed <n>                 map seed shared by all clients (default: 12345)
#   --no-ai                    disable AI enemies

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EDGE_BIN="$SCRIPT_DIR/edge/Edge"

MAIN_DELAY=0
MAIN_PORT=8000
TERRAIN="forest"
SEED=12345
NO_AI=""
EDGES=()
PLAYERS=()

while [[ $# -gt 0 ]]; do
    case $1 in
        --main-delay) MAIN_DELAY="$2"; shift 2 ;;
        --main-port)  MAIN_PORT="$2";  shift 2 ;;
        --edge)       EDGES+=("$2");   shift 2 ;;
        --players)
            IFS=',' read -ra PLAYERS <<< "$2"
            shift 2 ;;
        --terrain)    TERRAIN="$2";    shift 2 ;;
        --seed)       SEED="$2";       shift 2 ;;
        --no-ai)      NO_AI="--no-ai"; shift ;;
        -h|--help)
            head -30 "$0" | grep '^#' | sed 's/^# \{0,1\}//'
            exit 0 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# Default players if none specified
if [[ ${#PLAYERS[@]} -eq 0 ]]; then
    PLAYERS=("p1:$MAIN_PORT" "p2:$MAIN_PORT")
fi

# ── Build edge binary if needed ───────────────────────────────────────────────
if [[ ! -f "$EDGE_BIN" ]]; then
    echo "[launch] Edge binary not found — building..."
    pushd "$SCRIPT_DIR/edge" > /dev/null
    go build -o Edge ./main.go
    popd > /dev/null
    echo "[launch] Build complete."
fi

# ── Cleanup on exit ───────────────────────────────────────────────────────────
PIDS=()
cleanup() {
    echo ""
    echo "[launch] Shutting down servers..."
    for pid in "${PIDS[@]}"; do
        kill "$pid" 2>/dev/null || true
    done
    wait 2>/dev/null || true
    echo "[launch] Done."
}
trap cleanup EXIT INT TERM

# ── Start main server ─────────────────────────────────────────────────────────
echo "[launch] Starting main server (port=$MAIN_PORT delay=${MAIN_DELAY}ms)..."
"$EDGE_BIN" main "$MAIN_DELAY" "$MAIN_PORT" &
PIDS+=($!)
sleep 0.3

# ── Start edge nodes ──────────────────────────────────────────────────────────
for edge_def in "${EDGES[@]}"; do
    IFS=':' read -r ename edelay eport <<< "$edge_def"
    echo "[launch] Starting edge '$ename' (port=$eport delay=${edelay}ms)..."
    "$EDGE_BIN" "$ename" "$edelay" "$eport" &
    PIDS+=($!)
    sleep 0.2
done

sleep 0.3

# ── Launch clients ────────────────────────────────────────────────────────────
COLORS=(0 1 2 3 4 5 6 7 8)
COLOR_IDX=0

echo ""
echo "[launch] Launching ${#PLAYERS[@]} client(s) — terrain=$TERRAIN seed=$SEED"
echo ""

for player_def in "${PLAYERS[@]}"; do
    IFS=':' read -r pid pport <<< "$player_def"
    COL="${COLORS[$COLOR_IDX]}"
    COLOR_IDX=$(( (COLOR_IDX + 1) % ${#COLORS[@]} ))

    CMD="python3 $SCRIPT_DIR/arena_game.py --client-id $pid --edge 127.0.0.1:$pport --color $COL --map-seed $SEED --terrain $TERRAIN $NO_AI"
    echo "[launch] $pid → 127.0.0.1:$pport (color $COL)"

    if command -v gnome-terminal &>/dev/null; then
        gnome-terminal --title="WARZONE $pid" -- bash -c "$CMD; echo; read -p 'Press enter to close'" &
    elif command -v xterm &>/dev/null; then
        xterm -title "WARZONE $pid" -e bash -c "$CMD; echo; read -p 'Press enter to close'" &
    elif wt.exe --version &>/dev/null 2>&1; then
        wt.exe new-tab --title "WARZONE $pid" -- wsl.exe -d Ubuntu --cd "$SCRIPT_DIR" -- bash -c "$CMD; read -p 'Press enter to close'" &
    else
        LOG="$SCRIPT_DIR/${pid}.log"
        echo "[launch]   No GUI terminal — background mode, log: $LOG"
        $CMD > "$LOG" 2>&1 &
    fi

    sleep 0.3
done

echo ""
echo "[launch] All clients launched. Ctrl+C to stop all servers."
echo ""

wait "${PIDS[@]}"