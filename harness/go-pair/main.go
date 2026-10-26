// go-pair: go-libp2p QUIC peers for key-exchange interop runs.
//
//	-mode both   listener + dialer in one process; the dialer dials -dial-port (the tap)
//	-mode listen print "peer <id>", accept connections for -seconds
//	-mode listen-wt  WebTransport listener; prints "wt <multiaddr>" lines
//	-mode dial   dial -peer at 127.0.0.1:-dial-port and report the handshake
//
// GODEBUG=tlsmlkem=0 turns off Go's default X25519MLKEM768 for classical baselines.
// SSLKEYLOGFILE=<path> appends TLS secrets (NSS key log format) so the tap decoder
// can decrypt Handshake packets. Test harness only: it breaks the security of the logged connections.
package main

import (
	"context"
	"flag"
	"fmt"
	"log"
	"os"
	"time"

	"github.com/libp2p/go-libp2p"
	"github.com/libp2p/go-libp2p/core/host"
	"github.com/libp2p/go-libp2p/core/network"
	"github.com/libp2p/go-libp2p/core/peer"
	p2ptls "github.com/libp2p/go-libp2p/p2p/security/tls"
	quic "github.com/libp2p/go-libp2p/p2p/transport/quic"
	webtransport "github.com/libp2p/go-libp2p/p2p/transport/webtransport"
	ma "github.com/multiformats/go-multiaddr"
)

// listenWebTransport prints "wt <multiaddr with certhashes>" so a browser can dial it.
func listenWebTransport(port, seconds int) {
	h, err := libp2p.New(
		libp2p.Transport(webtransport.New),
		libp2p.ListenAddrStrings(fmt.Sprintf("/ip4/127.0.0.1/udp/%d/quic-v1/webtransport", port)),
	)
	if err != nil {
		log.Fatalf("webtransport listener: %v", err)
	}
	defer h.Close()
	for _, a := range h.Addrs() {
		fmt.Printf("wt %s\n", a)
	}
	fmt.Printf("peer %s\n", h.ID())
	time.Sleep(time.Duration(seconds) * time.Second)
}

// quicTransport is the QUIC transport, with a TLS key log when SSLKEYLOGFILE is set
// (the same variable rustls reads, so both harnesses are switched the same way).
func quicTransport() libp2p.Option {
	path := os.Getenv("SSLKEYLOGFILE")
	if path == "" {
		return libp2p.Transport(quic.NewTransport)
	}
	f, err := os.OpenFile(path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o600)
	if err != nil {
		log.Fatalf("SSLKEYLOGFILE: %v", err)
	}
	return libp2p.Transport(quic.NewTransport, quic.WithTLSIdentityOption(p2ptls.WithKeyLogWriter(f)))
}

func newListener(port int) host.Host {
	h, err := libp2p.New(
		quicTransport(),
		libp2p.ListenAddrStrings(fmt.Sprintf("/ip4/127.0.0.1/udp/%d/quic-v1", port)),
	)
	if err != nil {
		log.Fatalf("listener: %v", err)
	}
	return h
}

func dial(id peer.ID, port int) {
	dialer, err := libp2p.New(quicTransport(), libp2p.NoListenAddrs)
	if err != nil {
		log.Fatalf("dialer: %v", err)
	}
	defer dialer.Close()
	target := ma.StringCast(fmt.Sprintf("/ip4/127.0.0.1/udp/%d/quic-v1", port))
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	start := time.Now()
	if err := dialer.Connect(ctx, peer.AddrInfo{ID: id, Addrs: []ma.Multiaddr{target}}); err != nil {
		log.Fatalf("connect: %v", err)
	}
	fmt.Printf("elapsed_ms %.3f\n", float64(time.Since(start).Microseconds())/1000)
	fmt.Println("handshake ok")
	time.Sleep(500 * time.Millisecond)
}

func main() {
	mode := flag.String("mode", "both", "both | listen | dial")
	listenPort := flag.Int("listen-port", 0, "port the listener binds")
	dialPort := flag.Int("dial-port", 0, "port the dialer dials (the tap)")
	peerID := flag.String("peer", "", "peer ID to dial (dial mode)")
	seconds := flag.Int("seconds", 15, "how long a listener stays up (listen mode)")
	flag.Parse()

	switch *mode {
	case "both":
		l := newListener(*listenPort)
		defer l.Close()
		dial(l.ID(), *dialPort)
	case "listen":
		l := newListener(*listenPort)
		defer l.Close()
		l.Network().Notify(&network.NotifyBundle{ConnectedF: func(_ network.Network, c network.Conn) {
			fmt.Printf("accepted %s\n", c.RemotePeer())
		}})
		fmt.Printf("peer %s\n", l.ID())
		time.Sleep(time.Duration(*seconds) * time.Second)
	case "listen-wt":
		listenWebTransport(*listenPort, *seconds)
	case "dial":
		id, err := peer.Decode(*peerID)
		if err != nil {
			log.Fatalf("peer id: %v", err)
		}
		dial(id, *dialPort)
	default:
		log.Fatalf("unknown mode %q", *mode)
	}
}
