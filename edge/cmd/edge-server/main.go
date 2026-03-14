package main

import (
	"fmt"
	"log"
	"net"
	"os"
	"time"

	"edge/common"
)

type EdgeServer struct {
	common.Server
	upstreamAddr    *net.UDPAddr
	upstreamAddrStr string
	serverConns     map[string]*net.UDPConn
}

func main() {
	server := mustNewEdgeServer()
	defer server.Conn.Close()

	fmt.Printf("--- %s (Edge) ---\n", server.NodeRegion)
	fmt.Printf("Listening on: %s\n", server.ListenAddr.String())
	fmt.Printf("Target: %s\n", server.upstreamAddrStr)
	fmt.Printf("\n")

	server.Run()
}

func mustNewEdgeServer() *EdgeServer {
	if len(os.Args) != 4 {
		log.Fatal("Usage: <node_region> <upstream_addr> <delay_config.json>")
	}

	nodeRegion := os.Args[1]
	upstreamAddrStr := os.Args[2]
	delayConfigPath := os.Args[3]

	delayMatrix := common.MustLoadDelayMatrix(delayConfigPath)

	upstreamAddr, err := net.ResolveUDPAddr("udp4", upstreamAddrStr)
	if err != nil {
		log.Fatal(err)
	}

	laddr, err := net.ResolveUDPAddr("udp4", "0.0.0.0:")
	if err != nil {
		log.Fatal(err)
	}

	conn, err := net.ListenUDP("udp4", laddr)
	if err != nil {
		log.Fatal(err)
	}

	// Combine the detected LAN IP with the OS-assigned port for discovery
	actualPort := conn.LocalAddr().(*net.UDPAddr).Port
	displayAddr, err := net.ResolveUDPAddr("udp4", fmt.Sprintf("%s:%d", common.GetLocalIP(), actualPort))
	if err != nil {
		log.Fatal(err)
	}

	return &EdgeServer{
		Server:          common.NewServer(nodeRegion, conn, displayAddr, delayMatrix),
		upstreamAddr:    upstreamAddr,
		upstreamAddrStr: upstreamAddrStr,
		serverConns:     make(map[string]*net.UDPConn),
	}
}

func (s *EdgeServer) Run() {
	// Send register packet to main server to announce this edge's listening port
	regMsg := &common.Message{
		Type:        common.MsgRegister,
		ClientID:    s.NodeRegion,
		Seq:         0,
		TimestampMs: time.Now().UnixMilli(),
		Payload: map[string]interface{}{
			"region":          s.NodeRegion,
			"registered_edge": "self",
		},
	}
	regData, err := common.EncodeMessage(regMsg)
	if err != nil {
		fmt.Printf("[edge] Failed to encode register packet: %v\n", err)
	} else {
		_, err = s.Conn.WriteToUDP(regData, s.upstreamAddr)
		if err != nil {
			fmt.Printf("[edge] Failed to send register packet: %v\n", err)
		} else {
			fmt.Printf("[edge] Sent register packet to main server at %s\n", s.upstreamAddr.String())
		}
	}

	buf := make([]byte, 4096)

	for {
		n, addr, err := s.Conn.ReadFromUDP(buf)
		if err != nil {
			continue
		}

		data := append([]byte(nil), buf[:n]...)
		msg, _ := common.DecodeMessage(data)

		// fmt.Printf("[RECV][EDGE %s] %d bytes from %s\n", s.NodeRegion, n, addr)

		inboundDelay := s.InboundDelayFromMessage(msg)

		// Shadow variables to safely capture them in the delayed goroutine closure
		cMsg := msg
		cAddr := addr
		cData := data

		exec := func() {
			switch {
			case cMsg != nil && cMsg.Type == common.MsgPing:
				s.HandlePing(cMsg, cAddr)
			case cMsg != nil && cMsg.Type == common.MsgRegister:
				s.handleRegister(cMsg, cAddr)
			case cMsg != nil && cMsg.Type == common.MsgEdgeList:
				// Route EDGE_LIST back down to client
				if client, ok := s.Clients[cMsg.ClientID]; ok {
					outDelay := s.DelayToClient(client)
					s.SendAfter(cData, client.Addr, outDelay)
				}
			default:
				s.handleClientMessage(cData, cMsg, cAddr)
			}
		}

		time.AfterFunc(inboundDelay, exec)
	}
}

func (s *EdgeServer) handleRegister(msg *common.Message, clientAddr *net.UDPAddr) {
	region, _ := common.GetString(msg.Payload, "region")
	client := &common.RegisteredClient{
		ClientID: msg.ClientID,
		Region:   region,
		Addr:     clientAddr,
	}

	serverConn, err := net.DialUDP("udp4", nil, s.upstreamAddr)
	if err != nil {
		fmt.Printf("[edge] failed to bind new port for client %s: %v\n", msg.ClientID, err)
		return
	}
	s.serverConns[msg.ClientID] = serverConn

	s.Clients[msg.ClientID] = client
	fmt.Printf("[NEW CLIENT] %s registered, bound upstream port %v\n", msg.ClientID, serverConn.LocalAddr())

	// Swap the region with the Edge's own region
	if msg.Payload == nil {
		msg.Payload = make(map[string]interface{})
	}
	msg.Payload["region"] = s.NodeRegion

	forwardData, err := common.EncodeMessage(msg)
	if err != nil {
		fmt.Printf("[edge] failed to encode register: %v\n", err)
		return
	}

	_, _ = serverConn.Write(forwardData)

	go s.runUpstreamReader(msg.ClientID, serverConn)
}

func (s *EdgeServer) handleClientMessage(data []byte, msg *common.Message, clientAddr *net.UDPAddr) {
	if msg == nil {
		return
	}

	client, ok := s.Clients[msg.ClientID]
	if !ok {
		region, _ := common.GetString(msg.Payload, "region")
		client = &common.RegisteredClient{
			ClientID: msg.ClientID,
			Region:   region,
			Addr:     clientAddr,
		}
		s.Clients[msg.ClientID] = client
		fmt.Printf("[NEW CLIENT] %s\n", msg.ClientID)
	} else {
		client.Addr = clientAddr
	}

	// Forward to main server using the dedicated connection if available
	if conn, ok := s.serverConns[msg.ClientID]; ok {
		_, _ = conn.Write(data)
	} else {
		_, _ = s.Conn.WriteToUDP(data, s.upstreamAddr)
	}

	// Forward incoming client packets to every other local client on this edge
	s.BroadcastLocal(data, msg.ClientID)
}

func (s *EdgeServer) runUpstreamReader(clientID string, conn *net.UDPConn) {
	buf := make([]byte, 4096)
	for {
		n, err := conn.Read(buf)
		if err != nil {
			break
		}
		data := append([]byte(nil), buf[:n]...)

		client, ok := s.Clients[clientID]
		if !ok {
			continue
		}

		outDelay := s.DelayToClient(client)
		s.SendAfter(data, client.Addr, outDelay)
	}
}
