# Build against the nim-libp2p master clone in ../../deps (dependencies resolved there by nimble setup -l).
include "../../deps/nim-libp2p/nimble.paths"
switch("path", "../../deps/nim-libp2p")
--mm:refc
--threads:on
if defined(windows):
  --define:nimRawSetjmp
