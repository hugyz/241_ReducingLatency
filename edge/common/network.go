package common

import (
	"log"
	"net"
	"strings"
	"time"
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
		return []string{"127.0.0.1"}
	}
	return ips
}

func PickBindIP(targetAddrStr string) string {
	localIPs := GetExternalIPv4()
	displayIP := localIPs[0]

	hostPrefix := ""
	parts := strings.Split(targetAddrStr, ".")
	if len(parts) >= 3 {
		hostPrefix = strings.Join(parts[:3], ".")
	}

	for _, ip := range localIPs {
		if strings.HasPrefix(ip, hostPrefix) {
			displayIP = ip
			break
		}
	}
	return displayIP
}

func OriginFromMessage(msg *Message, fallback string) string {
	if msg == nil || msg.Payload == nil {
		return fallback
	}
	if v, ok := msg.Payload["origin"]; ok {
		if s, ok := v.(string); ok && s != "" {
			return s
		}
	}
	return fallback
}

func ScheduleSend(conn *net.UDPConn, data []byte, addr *net.UDPAddr, delay time.Duration) {
	out := append([]byte(nil), data...)
	time.AfterFunc(delay, func() { _, _ = conn.WriteToUDP(out, addr) })
}

func ScheduleWrite(conn *net.UDPConn, data []byte, delay time.Duration) {
	out := append([]byte(nil), data...)
	time.AfterFunc(delay, func() { _, _ = conn.Write(out) })
}
