## nim-pair: nim-libp2p QUIC peer for key-exchange interop runs (fits run_pair.sh).
##   nim_pair listen <port> [seconds]   prints "peer <id>", logs "accepted <id>"
##   nim_pair dial <port> <peer-id>     prints "handshake ok"
import std/[os, strutils]
import chronos
import libp2p

proc newQuicSwitch(listenPort: int): Switch =
  var b = SwitchBuilder.new()
    .withQuicTransport()
  if listenPort > 0:
    b = b.withAddress(MultiAddress.init("/ip4/127.0.0.1/udp/" & $listenPort & "/quic-v1").tryGet())
  else:
    b = b.withAddress(MultiAddress.init("/ip4/127.0.0.1/udp/0/quic-v1").tryGet())
  b.build()

proc main() {.async.} =
  let args = commandLineParams()
  case args[0]
  of "listen":
    let sw = newQuicSwitch(parseInt(args[1]))
    sw.addConnEventHandler(proc(peerId: PeerId, event: ConnEvent) {.async: (raises: [CancelledError]).} =
      echo "accepted ", peerId
    , ConnEventKind.Connected)
    await sw.start()
    echo "peer ", sw.peerInfo.peerId
    await sleepAsync(seconds(if args.len > 2: parseInt(args[2]) else: 15))
    await sw.stop()
  of "dial":
    let sw = newQuicSwitch(0)
    await sw.start()
    let peerId = PeerId.init(args[2]).tryGet()
    let ma = MultiAddress.init("/ip4/127.0.0.1/udp/" & args[1] & "/quic-v1").tryGet()
    await sw.connect(peerId, @[ma]).wait(10.seconds)
    echo "handshake ok"
    await sleepAsync(500.milliseconds)
    await sw.stop()
  else:
    quit "usage: listen <port> [seconds] | dial <port> <peer-id>"

waitFor main()
