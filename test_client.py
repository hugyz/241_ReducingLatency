import socket
import threading
import sys

def receive_messages(sock):
    while True:
        try:
            data = sock.recv(1024)
            if not data:
                break
            print(f"\n{data.decode().strip()}")
            print("> ", end="", flush=True)
        except:
            break

def start_client(name, server_addr):
    ip, port = server_addr.split(":")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    
    try:
        sock.connect((ip, int(port)))
        print(f"Client '{name}' connected to {server_addr}")
    except Exception as e:
        print(f"Connection failed: {e}")
        return

    # Start thread to listen for incoming broadcasts/server messages
    threading.Thread(target=receive_messages, args=(sock,), daemon=True).start()

    while True:
        msg = input("> ")
        if msg.lower() == "exit":
            break
        # Format: Name:Message
        full_msg = f"{name}:{msg}\n"
        sock.sendall(full_msg.encode())

    sock.close()

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python client.py <name> <ip:port>")
    else:
        start_client(sys.argv[1], sys.argv[2])