package common

import (
	"net"
	"time"
)

type RegisteredClient struct {
	ClientID     string
	Region       string
	RegisteredTo string       // server the client is registered to
	Addr         *net.UDPAddr // the client's address if registered to main, or edge address
}

type Server struct {
	NodeName    string
	Conn        *net.UDPConn
	ListenAddr  *net.UDPAddr
	DelayMatrix DelayMatrix
	Clients     map[string]*RegisteredClient
}

func NewServer(nodeName string, conn *net.UDPConn, listenAddr *net.UDPAddr, delayMatrix DelayMatrix) Server {
	return Server{
		NodeName:    nodeName,
		Conn:        conn,
		ListenAddr:  listenAddr,
		DelayMatrix: delayMatrix,
		Clients:     make(map[string]*RegisteredClient),
	}
}

func (s *Server) SendAfter(data []byte, addr *net.UDPAddr, delay time.Duration) {
	ScheduleSend(s.Conn, data, addr, delay)
}
