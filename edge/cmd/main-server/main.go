package main

import (
	"fmt"
	"log"
	"net"
	"os"
	"time"

	"edge/common"
)

type EdgeInfo struct {
	NodeName string
	Addr     *net.UDPAddr
}

type MainServer struct {
	common.Server
	Edges map[string]*EdgeInfo
}

func main() {
	server := mustNewMainServer()
	defer server.Conn.Close()

	fmt.Printf("--- %s (Main Server) ---\n", server.NodeName)
	fmt.Printf("Listening on: %s\n\n", server.Conn.LocalAddr().String())

	server.Run()
}

func mustNewMainServer() *MainServer {
	if len(os.Args) < 3 || len(os.Args) > 4 {
		log.Fatal("Usage: <node_name> <listen_addr> [delay_config.json]")
	}

	nodeName := os.Args[1]
	listenAddrStr := os.Args[2]

	var delayConfigPath string
	if len(os.Args) == 4 {
		delayConfigPath = os.Args[3]
	}

	laddr, err := net.ResolveUDPAddr("udp4", listenAddrStr)
	if err != nil {
		log.Fatal(err)
	}

	conn, err := net.ListenUDP("udp4", laddr)
	if err != nil {
		log.Fatal(err)
	}

	var delayMatrix common.DelayMatrix
	if delayConfigPath != "" {
		delayMatrix = common.MustLoadDelayMatrix(delayConfigPath)
	}

	return &MainServer{
		Server: common.NewServer(nodeName, conn, laddr, delayMatrix),
		Edges:  make(map[string]*EdgeInfo),
	}
}

func (s *MainServer) Run() {
	buf := make([]byte, 4096)

	for {
		n, addr, err := s.Conn.ReadFromUDP(buf)
		if err != nil {
			continue
		}

		data := append([]byte(nil), buf[:n]...)
		msg, err := common.DecodeMessage(data)
		if err != nil || msg == nil {
			continue
		}

		switch msg.Type {
		case common.MsgPing:
			common.HandlePing(s.Conn, s.NodeName, s.DelayMatrix, msg, addr)

		case common.MsgDiscover:
			s.handleDiscover(msg, addr)

		case common.MsgRegister:
			s.handleRegister(msg, addr)

		case common.MsgPrediction:
			s.handlePrediction(msg, data, addr)

		default:
			fmt.Printf("[main] ignoring unsupported msg type=%s from=%s\n", msg.Type, addr.String())
		}
	}
}

func (s *MainServer) handleDiscover(msg *common.Message, addr *net.UDPAddr) {
	servers := []map[string]interface{}{
		{
			"host": s.ListenAddr.IP.String(),
			"port": s.ListenAddr.Port,
			"name": s.NodeName,
			"kind": "main",
		},
	}

	for _, edge := range s.Edges {
		servers = append(servers, map[string]interface{}{
			"host": edge.Addr.IP.String(),
			"port": edge.Addr.Port,
			"name": edge.NodeName,
			"kind": "edge",
		})
	}

	respMsg := &common.Message{
		Type:        common.MsgEdgeList,
		ClientID:    msg.ClientID,
		Seq:         msg.Seq,
		TimestampMs: time.Now().UnixMilli(),
		Payload: map[string]interface{}{
			"edges":  servers,
			"ttl_ms": 10000,
		},
	}

	resp, err := common.EncodeMessage(respMsg)
	if err != nil {
		fmt.Printf("[main] failed to encode edge list: %v\n", err)
		return
	}

	s.SendAfter(resp, addr, 0)
}

func (s *MainServer) handleRegister(msg *common.Message, addr *net.UDPAddr) {
	region, _ := common.GetString(msg.Payload, "region")

	registeredTo := s.NodeName
	if v, ok := common.GetString(msg.Payload, "registered_edge"); ok && v != "" {
		registeredTo = v
	}

	s.Clients[msg.ClientID] = &common.RegisteredClient{
		ClientID:     msg.ClientID,
		Region:       region,
		RegisteredTo: registeredTo,
		Addr:         addr, // either client addr (registered to main) or edge addr
	}

	if registeredTo != s.NodeName {
		s.Edges[registeredTo] = &EdgeInfo{
			NodeName: registeredTo,
			Addr:     addr,
		}
	}

	fmt.Printf("[main] REGISTER client=%s region=%s registered_to=%s from=%s\n",
		msg.ClientID, region, registeredTo, addr.String())
}

func (s *MainServer) handlePrediction(msg *common.Message, raw []byte, addr *net.UDPAddr) {
	sender, ok := s.Clients[msg.ClientID]
	if !ok {
		fmt.Printf("[main] ignoring PREDICTION from unregistered client=%s\n", msg.ClientID)
		return
	}

	// simulate client -> main delay
	var inboundDelay time.Duration

	if sender.RegisteredTo == s.NodeName {
		inboundDelay = common.DelayDuration(s.DelayMatrix, sender.Region, s.NodeName)
	} else {
		inboundDelay = common.DelayDuration(s.DelayMatrix, sender.RegisteredTo, s.NodeName)
	}
	fmt.Printf("[main] PREDICTION client=%s region=%s registered_to=%s from=%s inbound_delay=%v\n",
		msg.ClientID, sender.Region, sender.RegisteredTo, addr.String(), inboundDelay)

	go func(senderClientID string, data []byte, delay time.Duration) {
		if delay > 0 {
			time.Sleep(delay)
		}
		s.broadcastPrediction(data, senderClientID)
	}(msg.ClientID, append([]byte(nil), raw...), inboundDelay)
}

// right now this forwards predictions to all other EDGE NODES as well as the
// main server's registered clients, but can change to all other CLIENTS if makes more sense
func (s *MainServer) broadcastPrediction(data []byte, senderClientID string) {
	sender, ok := s.Clients[senderClientID]
	if !ok {
		return
	}

	originAttachment := sender.RegisteredTo
	sentEdges := map[string]bool{}

	// Send directly to clients attached to main
	for clientID, client := range s.Clients {
		if clientID == senderClientID {
			continue
		}
		if client.RegisteredTo != s.NodeName {
			continue
		}
		if client.Addr == nil {
			continue
		}

		delay := common.DelayDuration(s.DelayMatrix, s.NodeName, client.Region)

		fmt.Printf(
			"[main] BROADCAST source=%s(%s,%s) dest=%s(%s,%s) delay=%v to=%s\n",
			sender.ClientID,
			sender.Region,
			originAttachment,
			client.ClientID,
			client.Region,
			client.RegisteredTo,
			delay,
			client.Addr.String(),
		)

		s.SendAfter(data, client.Addr, delay)
	}

	// Send once to each other edge, but not back to the sender's edge
	for clientID, client := range s.Clients {
		if clientID == senderClientID {
			continue
		}
		if client.RegisteredTo == s.NodeName {
			continue
		}
		if client.RegisteredTo == originAttachment {
			continue
		}
		if sentEdges[client.RegisteredTo] {
			continue
		}

		edge, ok := s.Edges[client.RegisteredTo]
		if !ok || edge.Addr == nil {
			continue
		}

		delay := common.DelayDuration(s.DelayMatrix, s.NodeName, client.RegisteredTo)

		fmt.Printf(
			"[main] BROADCAST source=%s(%s,%s) dest_edge=%s delay=%v to=%s\n",
			sender.ClientID,
			sender.Region,
			originAttachment,
			client.RegisteredTo,
			delay,
			edge.Addr.String(),
		)

		s.SendAfter(data, edge.Addr, delay)
		sentEdges[client.RegisteredTo] = true
	}
}
