package common

import (
	"net"
	"time"
)

type RegisteredClient struct {
	ClientID         string
	Region           string
	RegisteredRegion string       // server the client is registered to
	Addr             *net.UDPAddr // the client's address if registered to main, or edge address
}

type Server struct {
	NodeRegion  string
	Conn        *net.UDPConn
	ListenAddr  *net.UDPAddr
	DelayMatrix DelayMatrix
	Clients     map[string]*RegisteredClient
}

func NewServer(nodeRegion string, conn *net.UDPConn, listenAddr *net.UDPAddr, delayMatrix DelayMatrix) Server {
	return Server{
		NodeRegion:  nodeRegion,
		Conn:        conn,
		ListenAddr:  listenAddr,
		DelayMatrix: delayMatrix,
		Clients:     make(map[string]*RegisteredClient),
	}
}

func (s *Server) SendAfter(data []byte, addr *net.UDPAddr, delay time.Duration) {
	ScheduleSend(s.Conn, data, addr, delay)
}

func (s *Server) DelayToClient(client *RegisteredClient) time.Duration {
	if client.RegisteredRegion == s.NodeRegion {
		return DelayDuration(s.DelayMatrix, s.NodeRegion, client.Region)
	}
	return DelayDuration(s.DelayMatrix, s.NodeRegion, client.RegisteredRegion)
}

func (s *Server) DelayFromClient(client *RegisteredClient) time.Duration {
	if client.RegisteredRegion == s.NodeRegion {
		return DelayDuration(s.DelayMatrix, client.Region, s.NodeRegion)
	}
	return DelayDuration(s.DelayMatrix, client.RegisteredRegion, s.NodeRegion)
}

func (s *Server) DelayToClientMs(client *RegisteredClient) int64 {
	return s.DelayToClient(client).Milliseconds()
}

func (s *Server) DelayFromClientMs(client *RegisteredClient) int64 {
	return s.DelayFromClient(client).Milliseconds()
}

func (s *Server) BroadcastLocal(data []byte, excludeClientID string) {
	for clientID, client := range s.Clients {
		if clientID == excludeClientID {
			continue
		}
		// Only broadcast to clients attached directly to this specific server region
		if client.RegisteredRegion != s.NodeRegion {
			continue
		}
		if client.Addr == nil {
			continue
		}
		delay := s.DelayToClient(client)
		s.SendAfter(data, client.Addr, delay)
	}
}
