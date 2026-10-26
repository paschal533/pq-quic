//! rust-pair: rust-libp2p QUIC peers for key-exchange interop runs.
//!
//!   rust-pair both <listen-port> <dial-port>   listener + dialer in one process
//!   rust-pair listen <port> [seconds]           print "peer <id>", accept connections
//!   rust-pair dial <port> <peer-id>             dial and report the handshake
use futures::StreamExt;
use libp2p::{
    multiaddr::Protocol, swarm::dummy, swarm::SwarmEvent, Multiaddr, PeerId, Swarm, SwarmBuilder,
};
use std::{env, error::Error, net::Ipv4Addr, time::Duration};

type Res<T> = Result<T, Box<dyn Error>>;

fn swarm() -> Res<Swarm<dummy::Behaviour>> {
    Ok(SwarmBuilder::with_new_identity()
        .with_tokio()
        .with_quic()
        .with_behaviour(|_| dummy::Behaviour)?
        .with_swarm_config(|c| c.with_idle_connection_timeout(Duration::from_secs(5)))
        .build())
}

fn quic_addr(port: u16) -> Multiaddr {
    Multiaddr::empty()
        .with(Protocol::Ip4(Ipv4Addr::LOCALHOST))
        .with(Protocol::Udp(port))
        .with(Protocol::QuicV1)
}

async fn listen(port: u16) -> Res<Swarm<dummy::Behaviour>> {
    let mut s = swarm()?;
    s.listen_on(quic_addr(port))?;
    loop {
        if let SwarmEvent::NewListenAddr { .. } = s.select_next_some().await {
            return Ok(s);
        }
    }
}

async fn dial(port: u16, peer: Option<PeerId>) -> Res<()> {
    let mut d = swarm()?;
    let mut addr = quic_addr(port);
    if let Some(p) = peer {
        addr = addr.with(Protocol::P2p(p));
    }
    let start = std::time::Instant::now();
    d.dial(addr)?;
    let outcome = tokio::time::timeout(Duration::from_secs(10), async {
        loop {
            match d.select_next_some().await {
                SwarmEvent::ConnectionEstablished { .. } => return Ok(()),
                SwarmEvent::OutgoingConnectionError { error, .. } => return Err(error.to_string()),
                _ => {}
            }
        }
    })
    .await?;
    outcome?;
    println!("elapsed_ms {:.3}", start.elapsed().as_secs_f64() * 1000.0);
    println!("handshake ok");
    tokio::time::sleep(Duration::from_millis(500)).await;
    Ok(())
}

fn drive(mut s: Swarm<dummy::Behaviour>) {
    tokio::spawn(async move {
        loop {
            match s.select_next_some().await {
                SwarmEvent::IncomingConnectionError { error, .. } => println!("incoming error: {error}"),
                SwarmEvent::ConnectionEstablished { peer_id, .. } => println!("accepted {peer_id}"),
                _ => {}
            }
        }
    });
}

#[tokio::main]
async fn main() -> Res<()> {
    let args: Vec<String> = env::args().skip(1).collect();
    let port = |i: usize| -> u16 { args[i].parse().expect("port") };
    match args.first().map(String::as_str) {
        Some("both") => {
            drive(listen(port(1)).await?);
            dial(port(2), None).await
        }
        Some("listen") => {
            let s = listen(port(1)).await?;
            println!("peer {}", s.local_peer_id());
            let secs = args.get(2).map(|v| v.parse().expect("seconds")).unwrap_or(15);
            drive(s);
            tokio::time::sleep(Duration::from_secs(secs)).await;
            Ok(())
        }
        Some("dial") => dial(port(1), Some(args[2].parse()?)).await,
        _ => Err("usage: both <lp> <dp> | listen <port> [secs] | dial <port> <peer>".into()),
    }
}
