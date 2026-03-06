import argparse
import os
import signal
import subprocess
import time
from typing import TextIO, cast

def main() -> None:
    parser = argparse.ArgumentParser(description="Launch multiple client instances")
    parser.add_argument("--n", type=int, default=20, help="number of clients to launch")
    parser.add_argument("--main", default="127.0.0.1:8000", help="main server host:port")
    parser.add_argument("--prefix", default="c", help="client id prefix")
    parser.add_argument("--duration", type=int, default=0, help="experiment duration in seconds (0 = run until Ctrl+C)")
    parser.add_argument("--log-dir", default="logs", help="directory for client logs")
    parser.add_argument("--stagger-ms", type=int, default=0, help="delay between launches")
    parser.add_argument( # remove later
        "--use-discovery",
        action="store_true",
        help="use real DISCOVER/EDGE_LIST instead of dummy discovery",
    )
    args = parser.parse_args()

    os.makedirs(args.log_dir, exist_ok=True)

    procs: list[tuple[str, subprocess.Popen, TextIO]] = []

    print(f"Starting {args.n} clients...")

    try:
        for i in range(args.n):
            client_id = f"{args.prefix}{i}"
            log_path = os.path.join(args.log_dir, f"{client_id}.log")
            log_file: TextIO = cast(TextIO, open(log_path, "w"))

            cmd = [
                "python3",
                "client.py",
                "--client-id",
                client_id,
                "--main",
                args.main,
            ]

            if args.use_discovery:
                cmd.append("--use-discovery")

            proc = subprocess.Popen(
                cmd,
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )

            procs.append((client_id, proc, log_file))
            print(f"Started {client_id}")
            time.sleep(args.stagger_ms / 1000.0)

        print("All clients started. Press Ctrl+C to stop.")

        start_time = time.time()
        
        while True:
            time.sleep(1)
            
            if args.duration > 0:
                elapsed = time.time() - start_time
                if elapsed >= args.duration:
                    print(f"\nExperiment duration ({args.duration}s) reached.")
                    break

    except KeyboardInterrupt:
        print("\nStopping clients...")

    finally:
        print("Shutting down clients...")

        for client_id, proc, log_file in procs:
            try:
                if proc.poll() is None:
                    proc.send_signal(signal.SIGINT)
                    proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
            finally:
                log_file.close()

        print("All clients stopped.")


if __name__ == "__main__":
    main()