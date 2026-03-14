package common

import (
	"net"
	"strings"
)

// GetLocalIP returns the first valid private LAN IPv4 address,
// ignoring common virtual adapters (WSL, Hyper-V, VMware, etc).
func GetLocalIP() string {
	interfaces, err := net.Interfaces()
	if err != nil {
		return "127.0.0.1"
	}
	for _, iface := range interfaces {
		if iface.Flags&net.FlagUp == 0 || iface.Flags&net.FlagLoopback != 0 {
			continue
		}

		name := strings.ToLower(iface.Name)
		if strings.Contains(name, "wsl") || strings.Contains(name, "virtual") || strings.Contains(name, "veth") || strings.Contains(name, "vmware") {
			continue
		}

		addrs, _ := iface.Addrs()
		for _, address := range addrs {
			if ipnet, ok := address.(*net.IPNet); ok && ipnet.IP.To4() != nil {
				ip := ipnet.IP
				if !ip.IsLinkLocalUnicast() && ip.IsPrivate() {
					return ip.String()
				}
			}
		}
	}
	return "127.0.0.1"
}

/*
func GetLocalIP() string {
	interfaces, err := net.Interfaces()
	if err != nil {
		return "127.0.0.1"
	}

	var fallback string

	for _, iface := range interfaces {
		if iface.Flags&net.FlagUp == 0 || iface.Flags&net.FlagLoopback != 0 {
			continue
		}
		name := strings.ToLower(iface.Name)
		if strings.Contains(name, "wsl") || strings.Contains(name, "virtual") ||
			strings.Contains(name, "veth") || strings.Contains(name, "vmware") {
			continue
		}
		addrs, _ := iface.Addrs()
		for _, address := range addrs {
			if ipnet, ok := address.(*net.IPNet); ok && ipnet.IP.To4() != nil {
				ip := ipnet.IP
				if !ip.IsLinkLocalUnicast() && ip.IsPrivate() {
					if strings.HasPrefix(ip.String(), "172.19.") {
						return ip.String()
					}
					fallback = ip.String()
				}
			}
		}
	}

	if fallback != "" {
		return fallback
	}
	return "127.0.0.1"
}
*/
