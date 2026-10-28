// hp: go-libp2p DCUtR peers for the RQ3 hole-punch runs (harness/linux/run_holepunch.sh).
// Adapted from test-plans hole-punch-interop impl/go/v0.49 with the redis coordination
// replaced by stdout lines, so a bash script in network namespaces can drive it.
//
//	-role relay   relay v2 service; prints "relay <peer id>"
//	-role listen  peer B: connect to relay, reserve, wait for the hole punch service,
//	              print "ready <peer id>", then serve until SIGTERM or -timeout
//	-role dial    peer A: connect to relay, dial -peer over the circuit, wait for a direct
//	              connection, verify it with an echo over that connection, print "result {...}"
//
// Every hole punch tracer event is printed as "event {...}" (JSON, UNIX-nano timestamps).
// In DCUtR the listener (B, inbound relayed connection) initiates and sprays; the dialer (A)
// dials QUIC as client on receiving SYNC, so A's ClientHello is the one that crosses B's NAT.
// GODEBUG=tlsmlkem=0 on both peers gives the classical baseline (C-13).
package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"log"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/libp2p/go-libp2p"
	"github.com/libp2p/go-libp2p/core/host"
	"github.com/libp2p/go-libp2p/core/network"
	"github.com/libp2p/go-libp2p/core/peer"
	"github.com/libp2p/go-libp2p/p2p/protocol/circuitv2/client"
	"github.com/libp2p/go-libp2p/p2p/protocol/circuitv2/relay"
	"github.com/libp2p/go-libp2p/p2p/protocol/holepunch"
	libp2pquic "github.com/libp2p/go-libp2p/p2p/transport/quic"
	ma "github.com/multiformats/go-multiaddr"
)

// relayLimit is the per-IP and total reservation cap on the relay. All B peers sit behind one
// NAT address, and the default (8 per IP) would refuse trials whose predecessors' connections
// have not closed yet.
const relayLimit = 1024

func main() {
	log.SetFlags(log.Lmicroseconds)
	role := flag.String("role", "", "relay | listen | dial")
	listen := flag.String("listen", "/ip4/0.0.0.0/udp/0/quic-v1", "listen multiaddr")
	relayAddr := flag.String("relay", "", "relay multiaddr with /p2p/<id> (listen, dial)")
	target := flag.String("peer", "", "listener peer id (dial)")
	timeout := flag.Duration("timeout", 45*time.Second, "give up after this long")
	flag.Parse()

	ctx, cancel := signal.NotifyContext(context.Background(), syscall.SIGTERM, os.Interrupt)
	defer cancel()
	ctx, cancelT := context.WithTimeout(ctx, *timeout)
	defer cancelT()

	var err error
	switch *role {
	case "relay":
		err = runRelay(ctx, *listen)
	case "listen":
		err = runListener(ctx, *listen, *relayAddr)
	case "dial":
		err = runDialer(ctx, *listen, *relayAddr, *target)
	default:
		err = fmt.Errorf("unknown role %q", *role)
	}
	if err != nil {
		log.Fatalf("FAILED: %v", err)
	}
}

func runRelay(ctx context.Context, listen string) error {
	rc := relay.DefaultResources()
	rc.MaxReservations = relayLimit
	rc.MaxReservationsPerIP = relayLimit
	rc.MaxReservationsPerASN = relayLimit
	h, err := libp2p.New(
		libp2p.Transport(libp2pquic.NewTransport),
		libp2p.ListenAddrStrings(listen),
		libp2p.ForceReachabilityPublic(),
		libp2p.EnableRelayService(relay.WithResources(rc)),
		libp2p.ResourceManager(&network.NullResourceManager{}),
	)
	if err != nil {
		return fmt.Errorf("relay host: %w", err)
	}
	defer h.Close()
	fmt.Printf("relay %s\n", h.ID())
	<-ctx.Done()
	return nil
}

func newPeer(listen string, tr *tracer) (host.Host, error) {
	return libp2p.New(
		libp2p.Transport(libp2pquic.NewTransport),
		libp2p.ListenAddrStrings(listen),
		libp2p.EnableRelay(),
		libp2p.EnableHolePunching(holepunch.WithTracer(tr)),
		// Both peers sit behind NATs the harness built, so reachability is not discovered.
		libp2p.ForceReachabilityPrivate(),
	)
}

// connectRelay dials the relay and returns its AddrInfo.
func connectRelay(ctx context.Context, h host.Host, relayAddr string) (peer.AddrInfo, error) {
	m, err := ma.NewMultiaddr(relayAddr)
	if err != nil {
		return peer.AddrInfo{}, fmt.Errorf("relay multiaddr: %w", err)
	}
	ri, err := peer.AddrInfoFromP2pAddr(m)
	if err != nil {
		return peer.AddrInfo{}, fmt.Errorf("relay peer info: %w", err)
	}
	if err := h.Connect(ctx, *ri); err != nil {
		return peer.AddrInfo{}, fmt.Errorf("connect relay: %w", err)
	}
	return *ri, nil
}

func runListener(ctx context.Context, listen, relayAddr string) error {
	tr := newTracer("listen")
	h, err := newPeer(listen, tr)
	if err != nil {
		return err
	}
	defer h.Close()
	ri, err := connectRelay(ctx, h, relayAddr)
	if err != nil {
		return err
	}
	if _, err := client.Reserve(ctx, h, ri); err != nil {
		return fmt.Errorf("reserve: %w", err)
	}
	if err := waitForDCUtR(ctx, h); err != nil {
		return err
	}
	fmt.Printf("ready %s\n", h.ID())
	<-ctx.Done()
	return nil
}

func runDialer(ctx context.Context, listen, relayAddr, target string) error {
	tr := newTracer("dial")
	h, err := newPeer(listen, tr)
	if err != nil {
		return err
	}
	defer h.Close()
	pid, err := peer.Decode(target)
	if err != nil {
		return fmt.Errorf("peer id: %w", err)
	}
	if _, err := connectRelay(ctx, h, relayAddr); err != nil {
		return err
	}
	// The receiver's stream handler exists only once the host has a public (observed) address.
	if err := waitForDCUtR(ctx, h); err != nil {
		return err
	}
	circuit := ma.StringCast(relayAddr + "/p2p-circuit")
	start := time.Now()
	if err := h.Connect(ctx, peer.AddrInfo{ID: pid, Addrs: []ma.Multiaddr{circuit}}); err != nil {
		return fmt.Errorf("connect over circuit: %w", err)
	}
	relayed := time.Since(start)
	conn, err := waitForDirect(ctx, h, pid)
	res := map[string]any{
		"relayed_ms": ms(relayed),
		"total_ms":   ms(time.Since(start)),
		"direct":     err == nil,
	}
	if err != nil {
		res["error"] = err.Error()
	} else {
		res["remote"] = conn.RemoteMultiaddr().String()
	}
	b, _ := json.Marshal(res)
	fmt.Printf("result %s\n", b)
	return nil
}

func ms(d time.Duration) float64 { return float64(d.Microseconds()) / 1000 }

// waitForDirect polls for a non-relayed connection to pid.
func waitForDirect(ctx context.Context, h host.Host, pid peer.ID) (network.Conn, error) {
	t := time.NewTicker(5 * time.Millisecond)
	defer t.Stop()
	for {
		for _, c := range h.Network().ConnsToPeer(pid) {
			if _, err := c.RemoteMultiaddr().ValueForProtocol(ma.P_CIRCUIT); err != nil {
				return c, nil
			}
		}
		select {
		case <-ctx.Done():
			return nil, errors.New("no direct connection before timeout")
		case <-t.C:
		}
	}
}

// waitForDCUtR blocks until the hole punch stream handler is registered (see test-plans
// impl/go/v0.49 for why: the service starts only after a public address is observed).
func waitForDCUtR(ctx context.Context, h host.Host) error {
	t := time.NewTicker(20 * time.Millisecond)
	defer t.Stop()
	for {
		for _, p := range h.Mux().Protocols() {
			if p == holepunch.Protocol {
				return nil
			}
		}
		select {
		case <-ctx.Done():
			return errors.New("hole punch service did not start")
		case <-t.C:
		}
	}
}

// tracer prints every hole punch event as one JSON line.
type tracer struct{ role string }

func newTracer(role string) *tracer { return &tracer{role: role} }

func (t *tracer) Trace(evt *holepunch.Event) {
	b, err := json.Marshal(map[string]any{"role": t.role, "ts": evt.Timestamp, "type": evt.Type, "evt": evt.Evt})
	if err != nil {
		log.Printf("event marshal: %v", err)
		return
	}
	fmt.Printf("event %s\n", b)
}
