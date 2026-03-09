package main

import (
	"fmt"
	"log"
	"net"
	"os"
	"strconv"
	"strings"
	"sync"
	"time"
)

type ClientSession struct {
	clientAddr *net.UDPAddr
	hostConn   *net.UDPConn
}

var (
	sessions sync.Map
	edgeConn *net.UDPConn
)

// GetExternalIPv4 returns all valid private LAN addresses.
func GetExternalIPv4() []string {
	var ips []string
	addrs, err := net.InterfaceAddrs()
	if err != nil {
		log.Panicf("Failed to access network interfaces: %v", err)
	}

	for _, address := range addrs {
		if ipnet, ok := address.(*net.IPNet); ok && ipnet.IP.To4() != nil {
			ip := ipnet.IP
			if !ip.IsLoopback() && !ip.IsLinkLocalUnicast() && ip.IsPrivate() {
				ips = append(ips, ip.String())
			}
		}
	}

	if len(ips) == 0 {
		log.Panic("FATAL: No valid LAN IPv4 address found.")
	}
	return ips
}

func main() {
	if len(os.Args) != 4 {
		log.Fatal("Usage: <name> <host_addr> <delay_ms>")
	}

	name := os.Args[1]
	hostAddrStr := os.Args[2]
	delayMs, _ := strconv.Atoi(os.Args[3])
	delay := time.Duration(delayMs) * time.Millisecond

	// 1. Find the best Local IP based on the Host Address provided
	localIPs := GetExternalIPv4()
	displayIP := localIPs[0] // Default to first found

	// Heuristic: If our host is 192.168.0.x, try to find a local 192.168.0.x
	hostPrefix := ""
	parts := strings.Split(hostAddrStr, ".")
	if len(parts) >= 3 {
		hostPrefix = strings.Join(parts[:3], ".")
	}

	for _, ip := range localIPs {
		if strings.HasPrefix(ip, hostPrefix) {
			displayIP = ip
			break
		}
	}

	// 2. Bind to wildcard
	hostAddr, _ := net.ResolveUDPAddr("udp4", hostAddrStr)
	laddr, _ := net.ResolveUDPAddr("udp4", displayIP+":0")
	edgeConn, _ = net.ListenUDP("udp4", laddr)

	_, assignedPort, _ := net.SplitHostPort(edgeConn.LocalAddr().String())

	fmt.Printf("--- %s (Edge) Active ---\n", name)
	fmt.Printf("Detected LAN IP: %s (Selected to match Host subnet)\n", displayIP)
	fmt.Printf("Listening on: %s:%s\n", displayIP, assignedPort)
	fmt.Printf("Target: %s\n\n", hostAddrStr)

	buf := make([]byte, 4096)
	for {
		n, clientAddr, err := edgeConn.ReadFromUDP(buf)
		if err != nil {
			continue
		}

		fmt.Printf("[RECV] %d bytes from client %s\n", n, clientAddr)

		data := make([]byte, n)
		copy(data, buf[:n])

		session := getOrCreateSession(clientAddr, hostAddr, delay)
		broadcast(clientAddr.String(), data)

		time.AfterFunc(delay, func() {
			if session != nil {
				session.hostConn.Write(data)
			}
		})
	}
}

func getOrCreateSession(clientAddr *net.UDPAddr, hostAddr *net.UDPAddr, delay time.Duration) *ClientSession {
	key := clientAddr.String()
	if val, ok := sessions.Load(key); ok {
		return val.(*ClientSession)
	}

	hConn, err := net.DialUDP("udp4", nil, hostAddr)
	if err != nil {
		return nil
	}

	session := &ClientSession{clientAddr, hConn}

	go func() {
		defer hConn.Close()
		buf := make([]byte, 4096)
		for {
			n, _, err := hConn.ReadFromUDP(buf)
			if err != nil {
				sessions.Delete(key)
				return
			}
			respData := make([]byte, n)
			copy(respData, buf[:n])

			time.AfterFunc(delay, func() {
				edgeConn.WriteToUDP(respData, clientAddr)
			})
		}
	}()

	sessions.Store(key, session)
	fmt.Printf("[NEW SESSION] %s\n", key)
	return session
}

func broadcast(senderKey string, data []byte) {
	sessions.Range(func(key, value interface{}) bool {
		if key.(string) != senderKey {
			edgeConn.WriteToUDP(data, value.(*ClientSession).clientAddr)
		}
		return true
	})
}
