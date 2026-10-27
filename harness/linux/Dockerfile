# Linux netem cross-check: the same peers and bench, with kernel netem on lo
# in place of the userspace tap. Build context: harness/.
#   docker build -f linux/Dockerfile -t pqquic-netem .
FROM golang:1.26-bookworm AS go
WORKDIR /src
COPY go-pair/ .
ENV GOFLAGS=-mod=mod CGO_ENABLED=0
RUN go build -o /out/gopair .

FROM rust:1.95-bookworm AS rust
WORKDIR /src
COPY rust-pair/Cargo.toml rust-pair/Cargo.lock ./
COPY rust-pair/vendor/ vendor/
COPY rust-pair/src/ src/
RUN cargo build --release --locked && cp target/release/rust-pair /out-rust-pair

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends iproute2 python3 && rm -rf /var/lib/apt/lists/*
COPY --from=go /out/gopair /usr/local/bin/gopair
COPY --from=rust /out-rust-pair /usr/local/bin/rust-pair
WORKDIR /harness
COPY bench_handshake.py analyse_loss.py linux/run_netem.sh ./
ENV PQQUIC_GO_BIN=/usr/local/bin/gopair PQQUIC_RS_BIN=/usr/local/bin/rust-pair
ENTRYPOINT ["bash", "run_netem.sh"]
