// browser_wt.mjs: headless Chrome (throwaway profile) opens a WebTransport session
// to a go-libp2p WebTransport listener, via the tap. Only the QUIC/TLS handshake
// matters here; the libp2p Noise step inside WebTransport is not run.
//   node browser_wt.mjs <tap-port> <certhash-multibase> [<certhash-multibase> ...]
import http from 'node:http'
import os from 'node:os'
import path from 'node:path'
import fs from 'node:fs'
import { chromium } from 'playwright-core'

const [tapPort, ...certhashes] = process.argv.slice(2)

// "u" + base64url(multihash); multihash = 0x12 0x20 + 32-byte SHA-256 digest
const digests = certhashes.map((h) => {
  const mh = Buffer.from(h.slice(1), 'base64url')
  if (mh[0] !== 0x12 || mh[1] !== 0x20) throw new Error(`not a sha2-256 multihash: ${h}`)
  return [...mh.subarray(2)]
})

const server = http.createServer((_, res) => { res.end('<!doctype html><title>wt</title>') })
await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
const pagePort = server.address().port

const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'pqquic-chrome-'))
const browser = await chromium.launchPersistentContext(profile, { channel: 'chrome', headless: true })
try {
  const page = browser.pages()[0] ?? await browser.newPage()
  await page.goto(`http://localhost:${pagePort}/`)
  const version = browser.browser()?.version() ?? 'unknown'
  const result = await page.evaluate(async ({ port, digests }) => {
    const wt = new WebTransport(`https://127.0.0.1:${port}/.well-known/libp2p-webtransport?type=noise`, {
      serverCertificateHashes: digests.map((d) => ({ algorithm: 'sha-256', value: new Uint8Array(d) }))
    })
    const timeout = new Promise((_, reject) => setTimeout(() => reject(new Error('timeout')), 10000))
    try {
      await Promise.race([wt.ready, timeout])
      wt.close()
      return 'handshake ok'
    } catch (e) {
      return `failed: ${e.message ?? e}`
    }
  }, { port: Number(tapPort), digests })
  console.log(`chrome ${version}`)
  console.log(result)
} finally {
  await browser.close()
  server.close()
  fs.rmSync(profile, { recursive: true, force: true })
}
