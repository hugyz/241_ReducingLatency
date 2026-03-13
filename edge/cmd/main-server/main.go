package main

import (
	"fmt"
	"log"
	"net"
	"os"
	"time"

	"edge/common"
)

// all clients in the system
type registeredClient struct {
	ClientID   string
	Region     string
	registeredTo string // server the client is registered to
	Addr       *net.UDPAddr // the client's address if registered to main, 
	// otherwise the client's edge address
}

type edgeInfo struct {
	NodeName string
	Addr     *net.UDPAddr
}

type MainServer struct {
	nodeName    string
	conn        *net.UDPConn
	listenAddr  *net.UDPAddr
	delayMatrix common.DelayMatrix
	clients     map[string]*registeredClient
	edges       map[string]*edgeInfo
}

func main() {
	server := mustNewMainServer()
	defer server.conn.Close()

	fmt.Printf("--- %s (Main Server) ---\n", server.nodeName)
	fmt.Printf("Listening on: %s\n\n", server.conn.LocalAddr().String())

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
		nodeName:    nodeName,
		conn:        conn,
		listenAddr:  laddr,
		delayMatrix: delayMatrix,
		clients:     map[string]*registeredClient{},
		edges:       map[string]*edgeInfo{},
	}
}

func (s *MainServer) Run() {
	buf := make([]byte, 4096)

	for {
		n, addr, err := s.conn.ReadFromUDP(buf)
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
			common.HandlePing(s.conn, s.nodeName, s.delayMatrix, msg, addr)

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
			"host": s.listenAddr.IP.String(),
			"port": s.listenAddr.Port,
			"name": s.nodeName,
			"kind": "main",
		},
	}

	for _, edge := range s.edges {
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

	s.sendAfter(resp, addr, 0)
}

func (s *MainServer) handleRegister(msg *common.Message, addr *net.UDPAddr) {
	region, _ := common.GetString(msg.Payload, "region")

	registeredTo := "main"
	if v, ok := common.GetString(msg.Payload, "attached_edge"); ok && v != "" {
		registeredTo = v
	}

	s.clients[msg.ClientID] = &registeredClient{
		ClientID:   msg.ClientID,
		Region:     region,
		registeredTo: registeredTo,
		Addr:       addr,
	}

	if registeredTo != "main" {
		s.edges[registeredTo] = &edgeInfo{
			NodeName: registeredTo,
			Addr:     addr,
		}
	}

	fmt.Printf("[main] REGISTER client=%s region=%s registered_to=%s from=%s\n",
		msg.ClientID, region, registeredTo, addr.String())
}

func (s *MainServer) handlePrediction(msg *common.Message, raw []byte, addr *net.UDPAddr) {
	sender, ok := s.clients[msg.ClientID]
	if !ok {
		fmt.Printf("[main] ignoring PREDICTION from unregistered client=%s\n", msg.ClientID)
		return
	}

	// simulate client -> main delay
	var inboundDelay time.Duration

	if sender.registeredTo == "main" {
		inboundDelay = common.DelayDuration(s.delayMatrix, sender.Region, s.nodeName)
	} else {
		inboundDelay = 0
	}
	fmt.Printf("[main] PREDICTION client=%s region=%s registered_to=%s from=%s inbound_delay=%v\n",
		msg.ClientID, sender.Region, sender.registeredTo, addr.String(), inboundDelay)

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
	sender, ok := s.clients[senderClientID]
	if !ok {
		return
	}

	originAttachment := sender.registeredTo
	sentEdges := map[string]bool{}

	// Send directly to clients attached to main
	for clientID, client := range s.clients {
		if clientID == senderClientID {
			continue
		}
		if client.registeredTo != "main" {
			continue
		}
		if client.Addr == nil {
			continue
		}

		delay := common.DelayDuration(s.delayMatrix, s.nodeName, client.Region)

		fmt.Printf(
			"[main] BROADCAST source=%s(%s,%s) dest=%s(%s,%s) delay=%v to=%s\n",
			sender.ClientID,
			sender.Region,
			originAttachment,
			client.ClientID,
			client.Region,
			client.registeredTo,
			delay,
			client.Addr.String(),
		)

		s.sendAfter(data, client.Addr, delay)
	}

	// Send once to each other edge, but not back to the sender's edge
	for clientID, client := range s.clients {
		if clientID == senderClientID {
			continue
		}
		if client.registeredTo == "main" {
			continue
		}
		if client.registeredTo == originAttachment {
			continue
		}
		if sentEdges[client.registeredTo] {
			continue
		}

		edge, ok := s.edges[client.registeredTo]
		if !ok || edge.Addr == nil {
			continue
		}

		delay := common.DelayDuration(s.delayMatrix, s.nodeName, client.registeredTo)

		fmt.Printf(
			"[main] BROADCAST source=%s(%s,%s) dest_edge=%s delay=%v to=%s\n",
			sender.ClientID,
			sender.Region,
			originAttachment,
			client.registeredTo,
			delay,
			edge.Addr.String(),
		)

		s.sendAfter(data, edge.Addr, delay)
		sentEdges[client.registeredTo] = true
	}
}

func (s *MainServer) sendAfter(data []byte, addr *net.UDPAddr, delay time.Duration) {
	common.ScheduleSend(s.conn, data, addr, delay)
}