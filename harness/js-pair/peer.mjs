// js-pair: js-libp2p (Node) QUIC peer via @chainsafe/libp2p-quic, fits run_pair.sh.
//   node peer.mjs listen <port> [seconds]   prints "peer <id>", logs "accepted <id>"
//   node peer.mjs dial <port> <peer-id>     prints "handshake ok"
import { createLibp2p } from 'libp2p'
import { quic } from '@chainsafe/libp2p-quic'
import { multiaddr } from '@multiformats/multiaddr'

const [mode, port, extra] = process.argv.slice(2)

if (mode === 'listen') {
  const node = await createLibp2p({
    addresses: { listen: [`/ip4/127.0.0.1/udp/${port}/quic-v1`] },
    transports: [quic()]
  })
  node.addEventListener('peer:connect', (e) => console.log(`accepted ${e.detail.toString()}`))
  console.log(`peer ${node.peerId.toString()}`)
  setTimeout(async () => { await node.stop(); process.exit(0) }, Number(extra ?? 15) * 1000)
} else if (mode === 'dial') {
  const node = await createLibp2p({ transports: [quic()] })
  await node.dial(multiaddr(`/ip4/127.0.0.1/udp/${port}/quic-v1/p2p/${extra}`), { signal: AbortSignal.timeout(10000) })
  console.log('handshake ok')
  setTimeout(async () => { await node.stop(); process.exit(0) }, 500)
} else {
  console.error('usage: listen <port> [seconds] | dial <port> <peer-id>')
  process.exit(2)
}
