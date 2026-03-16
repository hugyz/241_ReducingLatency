#!/bin/bash

MAIN=192.168.1.74:52101
DURATION=30

# Number of clients (default = 8)
NUM_CLIENTS=${1:-8}

echo "Starting $NUM_CLIENTS clients..."

for ((i=1;i<=NUM_CLIENTS;i++)); do
  if [ $i -le $((NUM_CLIENTS/2)) ]; then
    REGION=A
  else
    REGION=B
  fi

  COLOR=$(( (i-1) % 9 ))

  python3 arena_game.py \
    --client-id p$i \
    --main $MAIN \
    --region $REGION \
    --color $COLOR &
done

PIDS=$(jobs -p)

echo "Clients running for $DURATION seconds..."
sleep $DURATION

echo "Stopping clients..."
kill $PIDS
wait

echo "Test finished."