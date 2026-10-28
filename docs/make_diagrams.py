#!/usr/bin/env python3
"""Build docs/loss-recovery.svg, the animated README figure.

Run from the repo root:  python docs/make_diagrams.py

Every time below is a CLAIMS.md row (rust-libp2p 0.57.1, 50 ms RTT, the first client
datagram dropped on purpose, pilot grade):
  C-18  handshake medians: hybrid 147.4 ms, classical 1,077.3 ms; classical resend at +1,016 ms
  C-20  quinn's first probe timeout is 999 ms before any RTT sample
  C-21  hybrid: server Initial ACK reaches the client at ~+58-65 ms, client resends part 1 at
        +81-89 ms (RFC 9002 time-threshold loss detection)
  C-04  the hybrid ClientHello (>=1,495 B) is larger than one Initial datagram (1,200 B quinn)
The diagram draws one representative trace. Packet flight times are the 25 ms one-way delay.

The animation is plain CSS inside the SVG, so GitHub plays it in an <img>. With
prefers-reduced-motion, or in a renderer without CSS animation, the finished diagram shows.
"""

from __future__ import annotations

from pathlib import Path

OUT = Path(__file__).resolve().parent / "loss-recovery.svg"

ONE_WAY = 25            # ms, half of the 50 ms RTT
HYB_ACK_SENT = 35       # server ACK leaves at +33-40 ms (C-21)
HYB_RESEND = 85         # +81-89 ms (C-21)
HYB_DONE = 147.4        # C-18 median
CLS_PTO = 999           # C-20
CLS_RESEND = 1016       # C-18
CLS_DONE = 1077.3       # C-18 median

W, H = 960, 520
X0, PX_PER_MS = 110, 0.66
T_MAX = 1150            # ms shown on the axis
CYCLE = 13              # seconds per loop
SWEEP = 0.74            # share of the loop spent sweeping 0..T_MAX

INK, MUTED, GRID, BG = "#1f2933", "#6b7280", "#e5e1d8", "#fbfaf6"
CLS, HYB, LOST = "#b45309", "#0f766e", "#b91c1c"


def x(t: float) -> float:
    return X0 + t * PX_PER_MS


def pct(t: float) -> float:
    return round(100 * SWEEP * t / T_MAX, 2)


class Svg:
    def __init__(self) -> None:
        self.body: list[str] = []
        self.css: list[str] = []
        self.n = 0

    def _anim(self, frames: str) -> str:
        self.n += 1
        name = f"k{self.n}"
        self.css.append(f"#{name}{{animation:{name} {CYCLE}s linear infinite}}"
                        f"@keyframes {name}{{{frames}}}")
        return name

    def appear(self, t: float) -> str:
        """id of an element that fades in at time t and stays until the loop restarts."""
        p = pct(t)
        return self._anim(f"0%,{p}%{{opacity:0}}{p + 0.4}%,97%{{opacity:1}}100%{{opacity:0}}")

    def travel(self, t1: float, t2: float) -> str:
        """id of a path (pathLength=1) that draws itself from t1 to t2."""
        p1, p2 = pct(t1), pct(t2)
        return self._anim(f"0%,{p1}%{{stroke-dashoffset:1;opacity:0}}"
                          f"{p1 + 0.01}%{{opacity:1}}"
                          f"{p2}%,97%{{stroke-dashoffset:0;opacity:1}}100%{{opacity:0}}")

    def add(self, s: str) -> None:
        self.body.append(s)

    def packet(self, t1: float, y1: float, y2: float, color: str, lost: bool = False,
               width: float = 2.0) -> None:
        t2 = t1 + ONE_WAY * (0.5 if lost else 1)
        ya = y1 + (y2 - y1) * (0.5 if lost else 1)
        k = self.travel(t1, t2)
        self.add(f'<path id="{k}" class="draw" pathLength="1" d="M{x(t1):.1f} {y1} L{x(t2):.1f} {ya}" '
                 f'stroke="{color}" stroke-width="{width}" fill="none" stroke-linecap="round"/>')
        if lost:
            k = self.appear(t2)
            cx, cy = x(t2), ya
            self.add(f'<g id="{k}" stroke="{LOST}" stroke-width="2.4" stroke-linecap="round">'
                     f'<path d="M{cx - 6:.1f} {cy - 6} L{cx + 6:.1f} {cy + 6} M{cx + 6:.1f} {cy - 6} '
                     f'L{cx - 6:.1f} {cy + 6}"/></g>')

    def text(self, tx: float, ty: float, s: str, t: float | None = None, **kw: str) -> None:
        attrs = " ".join(f'{k.rstrip("_").replace("_", "-")}="{v}"' for k, v in kw.items())
        ident = f' id="{self.appear(t)}"' if t is not None else ""
        self.add(f'<text{ident} x="{tx:.1f}" y="{ty}" {attrs}>{s}</text>')

    def done(self, t: float, y: float, color: str, label: str) -> None:
        k = self.appear(t)
        self.add(f'<g id="{k}"><circle cx="{x(t):.1f}" cy="{y}" r="6" fill="{color}"/>'
                 f'<text x="{x(t) + 12:.1f}" y="{y + 5}" class="num" fill="{color}" '
                 f'font-weight="700">{label}</text></g>')


def lane(svg: Svg, top: float, name: str, sub: str, color: str) -> tuple[float, float]:
    yc, ys = top + 78, top + 142
    svg.add(f'<rect x="24" y="{top}" width="{W - 48}" height="170" rx="12" fill="#ffffff" '
            f'stroke="{GRID}"/>')
    svg.add(f'<rect x="24" y="{top}" width="6" height="170" rx="3" fill="{color}"/>')
    svg.text(48, top + 28, name, font_weight="700", font_size="15", fill=color)
    svg.text(48, top + 46, sub, font_size="12", fill=MUTED)
    for y, who in ((yc, "client"), (ys, "server")):
        svg.add(f'<line x1="{X0}" y1="{y}" x2="{x(T_MAX)}" y2="{y}" stroke="{GRID}" stroke-width="1.5"/>')
        svg.text(X0 - 12, y + 4, who, text_anchor="end", font_size="12", fill=MUTED)
    return yc, ys


def build() -> str:
    s = Svg()
    s.text(32, 42, "Losing the first datagram: why the hybrid hello recovers faster on rust-libp2p",
           font_size="18", font_weight="700", fill=INK)
    s.text(32, 64, "Targeted loss of the first client Initial, 50 ms RTT, rust-libp2p 0.57.1 (quinn). "
           "Medians from CLAIMS C-18, pilot grade.", font_size="12.5", fill=MUTED)

    # classical lane
    yc, ys = lane(s, 84, "Classical X25519", "ClientHello fits in one datagram", CLS)
    s.packet(0, yc, ys, CLS, lost=True)
    k = s.travel(0, CLS_PTO)
    s.add(f'<path id="{k}" class="draw" pathLength="1" d="M{x(30):.1f} {yc + 14} L{x(CLS_PTO):.1f} {yc + 14}" '
          f'stroke="{CLS}" stroke-width="3" stroke-dasharray="1" stroke-opacity="0.35" fill="none"/>')
    s.text(x(510), yc + 34, "nothing was acknowledged, so the client waits for its probe timeout (999 ms)",
           t=120, text_anchor="middle", font_size="12", fill=CLS)
    s.packet(CLS_RESEND, yc, ys, CLS)
    s.packet(CLS_RESEND + ONE_WAY, ys, yc, MUTED, width=1.4)
    s.text(x(CLS_RESEND) - 6, ys + 22, "resend +1,016 ms", t=CLS_RESEND, text_anchor="end",
           font_size="11.5", fill=CLS, class_="num")
    s.done(CLS_DONE, yc, CLS, "1,077 ms")

    # hybrid lane
    yc, ys = lane(s, 268, "Hybrid X25519MLKEM768",
                  "ClientHello (≥1,495 B) needs two datagrams of 1,200 B", HYB)
    s.packet(0, yc, ys, HYB, lost=True)
    s.packet(1.5, yc, ys, HYB)
    s.packet(HYB_ACK_SENT, ys, yc, HYB, width=1.6)
    s.packet(HYB_RESEND, yc, ys, HYB)
    s.packet(HYB_RESEND + ONE_WAY, ys, yc, MUTED, width=1.4)
    s.done(HYB_DONE, yc, HYB, "147 ms")
    notes = [
        (2, "①  part 1 of the ClientHello is lost"),
        (ONE_WAY, "②  part 2 arrives, and the server acknowledges it (48 B Initial ACK)"),
        (60, "③  a later packet was acked, so RFC 9002's time threshold marks part 1 lost"),
        (HYB_RESEND, "④  the client resends part 1 at +85 ms, no timeout needed"),
    ]
    for i, (t, line) in enumerate(notes):
        s.text(x(300), 268 + 74 + i * 21, line, t=t, font_size="12.5", fill=INK)

    # time axis and sweeping cursor
    ya = 462
    s.add(f'<line x1="{X0}" y1="{ya}" x2="{x(T_MAX)}" y2="{ya}" stroke="{MUTED}"/>')
    for t in range(0, 1101, 100):
        s.add(f'<line x1="{x(t)}" y1="{ya}" x2="{x(t)}" y2="{ya + 5}" stroke="{MUTED}"/>')
        if t % 200 == 0:
            s.text(x(t), ya + 19, f"{t:,}", text_anchor="middle", font_size="11", fill=MUTED,
                   class_="num")
    s.text(x(T_MAX), ya + 19, "ms", text_anchor="end", font_size="11", fill=MUTED)
    span = x(T_MAX) - X0
    s.css.append(f"#cursor{{animation:cursor {CYCLE}s linear infinite}}"
                 f"@keyframes cursor{{0%{{transform:translateX(0)}}{100 * SWEEP}%,100%"
                 f"{{transform:translateX({span:.1f}px)}}}}")
    s.add(f'<line id="cursor" x1="{X0}" y1="88" x2="{X0}" y2="{ya}" stroke="{INK}" '
          f'stroke-opacity="0.25" stroke-width="1.5"/>')

    s.text(32, 504, "go-libp2p (quic-go) waits only 200 ms for its first probe, so there the gap is "
           "268.5 vs 149.7 ms. Under random loss the sign depends on the stack: see C-22, C-25, C-31.",
           font_size="11.5", fill=MUTED)

    css = ("text{font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif}"
           ".num{font-family:ui-monospace,'SF Mono',Menlo,Consolas,monospace}"
           ".draw{stroke-dasharray:1;stroke-dashoffset:0}"
           + "".join(s.css)
           + "@media (prefers-reduced-motion:reduce){*{animation:none!important}}")
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
            f'role="img" aria-labelledby="t d">'
            f'<title id="t">Lost first datagram: classical vs hybrid QUIC handshake recovery</title>'
            f'<desc id="d">Classical: the single ClientHello datagram is lost and the client waits for its '
            f'999 ms probe timeout, finishing at 1,077 ms. Hybrid: part 1 is lost, part 2 is acknowledged, '
            f'the client resends part 1 at 85 ms by time-threshold loss detection and finishes at 147 ms.</desc>'
            f'<style>{css}</style>'
            f'<rect width="{W}" height="{H}" rx="16" fill="{BG}"/>'
            + "".join(s.body) + "</svg>\n")


if __name__ == "__main__":
    OUT.write_text(build(), encoding="utf-8", newline="\n")
    print("wrote", OUT)
