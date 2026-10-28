"""Render the PQ-QUIC demo video from real handshake traces.

Every handshake number on screen is read from data/demo-*.jsonl through harness/tap/decode_initial.py.
The traces come from harness/run_pair.sh and harness/run_downgrade.sh (commands are shown in the
video, and data/demo-transcript.txt holds the console output of the same runs).
The closing figures are copied from CLAIMS.md (C-05, C-12, C-14, C-18 to C-21).

usage: python docs/make_demo_video.py OUT.mp4   (needs Pillow and ffmpeg on PATH)
"""
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
W, H, FPS = 1920, 1080, 30
FONTS = Path("C:/Windows/Fonts")

BG, PANEL, EDGE = (11, 15, 20), (19, 25, 33), (38, 48, 60)
TEXT, MUTED, DIM = (226, 232, 240), (139, 152, 168), (82, 95, 112)
HYBRID, CLASSIC, ATTACK, OK = (45, 212, 191), (245, 177, 66), (248, 113, 113), (134, 239, 172)


def font(name, size):
    return ImageFont.truetype(str(FONTS / name), size)


MONO, MONO_S = font("CascadiaMono.ttf", 30), font("CascadiaMono.ttf", 24)
H1, H2 = font("segoeuib.ttf", 64), font("segoeuib.ttf", 46)
BODY, SMALL = font("segoeui.ttf", 32), font("segoeui.ttf", 24)


def decode(name):
    trace = ROOT / "data" / f"{name}.jsonl"
    raw = subprocess.run([sys.executable, str(ROOT / "harness/tap/decode_initial.py"), str(trace)],
                         capture_output=True, text=True, check=True).stdout
    d = json.loads(raw)
    ch = next(h["ClientHello"] for h in d["c2s"]["hellos"] if "ClientHello" in h)
    sh = next(h["ServerHello"] for h in d["s2c"]["hellos"] if "ServerHello" in h)
    return ch, sh


SCENES = [
    dict(trace="demo-go-rust", tag="go-libp2p dials rust-libp2p", sub="Default settings on both sides.",
         cmd='./run_pair.sh demo-go-rust "rust-pair listen __LP__ 15" "gopair -mode dial ..."',
         result=[("dialer", "handshake ok", OK)],
         verdict=("Hybrid post-quantum key exchange, no extra round trip", HYBRID)),
    dict(trace="demo-rust-go", tag="rust-libp2p dials go-libp2p", sub="Same result in the other direction.",
         cmd='./run_pair.sh demo-rust-go "gopair -mode listen ..." "rust-pair dial __TP__ __PEER__"',
         result=[("dialer", "handshake ok", OK)],
         verdict=("Two independent TLS stacks agree on X25519MLKEM768", HYBRID)),
    dict(trace="demo-classical", tag="A classical-only dialer", sub="An old peer that has no ML-KEM still connects.",
         cmd='GODEBUG=tlsmlkem=0 ./run_pair.sh demo-classical "rust-pair listen ..." "gopair ..."',
         result=[("dialer", "handshake ok", OK)],
         verdict=("Backward compatible: falls back to X25519, no retry", CLASSIC)),
    dict(trace="demo-strip", tag="On-path downgrade attack", sub="A proxy strips the hybrid group from the ClientHello.",
         cmd='./run_downgrade.sh demo-strip strip "rust-pair listen ..." "gopair ..."',
         result=[("dialer", "failed to dial: context deadline exceeded", ATTACK),
                 ("listener", "Failed to negotiate transport protocol(s)", ATTACK)],
         verdict=("TLS 1.3 transcript binding: the attacker gets no session", ATTACK)),
]


def ease(t):
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def blend(c, a):
    return tuple(int(BG[i] + (c[i] - BG[i]) * a) for i in range(3))


def header(dr, step, title, sub, a):
    dr.text((120, 80), f"{step:02d} / {len(SCENES):02d}", font=SMALL, fill=blend(MUTED, a))
    dr.text((120, 112), title, font=H2, fill=blend(TEXT, a))
    dr.text((120, 178), sub, font=BODY, fill=blend(MUTED, a))


def group_color(g):
    return HYBRID if "MLKEM" in g else CLASSIC


def draw_scene(sc, ch, sh, t, step):
    img = Image.new("RGB", (W, H), BG)
    dr = ImageDraw.Draw(img)
    header(dr, step, sc["tag"], sc["sub"], ease(t / 0.6))

    # terminal panel
    dr.rounded_rectangle((120, 260, 1800, 640), 18, fill=PANEL, outline=EDGE, width=2)
    for i, c in enumerate([(248, 113, 113), (245, 177, 66), (134, 239, 172)]):
        dr.ellipse((150 + i * 30, 284, 166 + i * 30, 300), fill=c)
    typed = sc["cmd"][: int(max(0, t - 0.5) * 70)]
    dr.text((150, 330), "$ ", font=MONO, fill=HYBRID)
    dr.text((190, 330), typed, font=MONO, fill=TEXT)
    t_out = 0.5 + len(sc["cmd"]) / 70 + 0.3
    hrr = "yes" if sh["hello_retry_request"] else "no"
    lines = [(f"{k}: ", v, c) for k, v, c in sc["result"]]
    lines += [("ClientHello  ", f'{ch["length"]} B   groups offered: {len(ch["supported_groups"])}', TEXT),
              ("ServerHello  ", f'selected {sh["selected_group"]}   HelloRetryRequest: {hrr}',
               group_color(sh["selected_group"]))]
    for i, (k, v, c) in enumerate(lines):
        if t < t_out + i * 0.35:
            break
        y = 390 + i * 54
        dr.text((150, y), k, font=MONO, fill=MUTED)
        dr.text((150 + dr.textlength(k, font=MONO), y), v, font=MONO, fill=c)

    # key share bars (bytes on the wire)
    t_bar = t_out + len(lines) * 0.35 + 0.2
    if t >= t_bar:
        a = ease((t - t_bar) / 0.8)
        dr.text((120, 680), "Key shares in the dialer's ClientHello (bytes on the wire)",
                font=SMALL, fill=blend(MUTED, a))
        scale = 1100 / 1216
        for i, (g, n) in enumerate(ch["key_shares"]):
            y = 724 + i * 64
            c = group_color(g)
            dr.text((120, y + 6), g, font=MONO_S, fill=blend(c, a))
            dr.rounded_rectangle((470, y, 470 + max(6, n * scale * a), y + 40), 8, fill=blend(c, a))
            dr.text((490 + n * scale * a, y + 6), f"{n} B", font=MONO_S, fill=blend(TEXT, a))

    t_ver = t_bar + 1.2
    if t >= t_ver:
        a = ease((t - t_ver) / 0.6)
        text, c = sc["verdict"]
        tw = dr.textlength(text, font=BODY)
        dr.rounded_rectangle((120, 900, 120 + tw + 60, 970), 35, fill=blend(tuple(v // 4 for v in c), a),
                             outline=blend(c, a), width=3)
        dr.text((150, 912), text, font=BODY, fill=blend(c, a))
    return img


def card(lines, t):
    img = Image.new("RGB", (W, H), BG)
    dr = ImageDraw.Draw(img)
    y = 270
    for i, (txt, f, c) in enumerate(lines):
        a = ease((t - i * 0.4) / 0.7)
        if a > 0:
            dr.text((160, y), txt, font=f, fill=blend(c, a))
        y += f.size + (48 if i in (0, len(lines) - 2) else 30)
    return img


TITLE = [("PQ-QUIC", H1, HYBRID),
         ("Hybrid post-quantum key exchange in libp2p QUIC", H2, TEXT),
         ("Live handshakes between real libp2p stacks, decoded from the wire.", BODY, MUTED),
         ("github.com/paschal533/pq-quic", MONO, DIM)]
CLOSE = [("What the repository measures", H2, TEXT),
         ("go, rust, js and aioquic PR #634 all select X25519MLKEM768   (C-05, C-12, C-14)", BODY, HYBRID),
         ("First datagram lost, rust-libp2p: classical 1,077 ms vs hybrid 147 ms   (C-18 to C-21, pilot)", BODY, CLASSIC),
         ("Live ClientHello rewrite never yields a session   (C-33)", BODY, ATTACK),
         ("Every number traced to its evidence in CLAIMS.md", BODY, MUTED),
         ("github.com/paschal533/pq-quic", MONO, DIM)]


def frames():
    for f in range(4 * FPS):
        yield card(TITLE, f / FPS)
    for step, sc in enumerate(SCENES, 1):
        ch, sh = decode(sc["trace"])
        for f in range(12 * FPS):
            yield draw_scene(sc, ch, sh, f / FPS, step)
    for f in range(8 * FPS):
        yield card(CLOSE, f / FPS)


def main(out):
    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                           "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264",
                           "-pix_fmt", "yuv420p", "-crf", "20", "-movflags", "+faststart", out],
                          stdin=subprocess.PIPE)
    for img in frames():
        ff.stdin.write(img.tobytes())
    ff.stdin.close()
    if ff.wait() != 0:
        raise SystemExit("ffmpeg failed")
    print("wrote", out)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(sys.argv[1])
