# A simple UDP server used for local testing before integrating with go server

import argparse
import socket
import time
from typing import Tuple

from protocol import MessageType, decode_message, encode_message, now_ms

Addr = Tuple[str, int]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--delay-ms", type=int, default=0, help="simulate latency")
    args = ap.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", args.port))

    print(f"[dummy_server] listening UDP :{args.port} (delay={args.delay_ms}ms)")

    try:
        while True:
            data, addr = sock.recvfrom(65535)
            msg = decode_message(data)
            mtype = msg.get("type")

            if args.delay_ms > 0:
                time.sleep(args.delay_ms / 1000.0)

            if mtype == MessageType.PING.value:
                pong = {
                    "type": MessageType.PONG.value,
                    "client_id": msg.get("client_id", ""),
                    "seq": msg.get("seq", 0),
                    "timestamp_ms": now_ms(),
                    "payload": {},
                }
                sock.sendto(encode_message(pong), addr)

            elif mtype == MessageType.REGISTER.value:
                print(f"[dummy_server] REGISTER from {addr}: {msg}")

            elif mtype == MessageType.PREDICTION.value:
                tick = msg.get("payload", {}).get("tick")
                if isinstance(tick, int) and tick % 30 == 0: # prints once every 30 ticks
                    print(f"[dummy_server] PREDICTION tick={tick} from {addr}")

            else:
                pass

    except KeyboardInterrupt:
        print("\n[dummy_server] stopped (Ctrl+C)")
    finally:
        sock.close()


if __name__ == "__main__":
    main()