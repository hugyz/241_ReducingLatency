import socket
import threading
import sys

def handle_client(conn, addr, name):
    print(f"[{name}] New connection from {addr}")
    try:
        while True:
            data = conn.recv(1024)
            if not data:
                break
            # Print the message received from the Go Edge
            print(f"\n[Received] {data.decode().strip()}")
    except ConnectionResetError:
        pass
    finally:
        conn.close()
        print(f"[{name}] Connection with {addr} closed.")

def start_server(name):
    # Create a TCP/IPv4 socket
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    
    # Bind to an available local IP and port 0 (ephemeral)
    hostname = socket.gethostname()
    local_ip = socket.gethostbyname(hostname)
    server.bind((local_ip, 0))
    ip, port = server.getsockname()
    
    server.listen(5)
    print(f"Server '{name}' listening on {ip}:{port}")

    clients = []

    # Thread to handle keyboard input to broadcast to all clients
    def broadcast_input():
        while True:
            msg = input(f"{name} > ")
            full_msg = f"{name}:{msg}\n".encode()
            for c in clients[:]:
                try:
                    c.sendall(full_msg)
                except:
                    clients.remove(c)

    threading.Thread(target=broadcast_input, daemon=True).start()

    while True:
        conn, addr = server.accept()
        clients.append(conn)
        threading.Thread(target=handle_client, args=(conn, addr, name), daemon=True).start()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python server.py <name>")
    else:
        start_server(sys.argv[1])