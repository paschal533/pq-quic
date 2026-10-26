"""Loss-recovery state per connection from quic-go client qlogs (QLOGDIR), joined to bench rows.

The qlog file name is the original destination connection ID; the tap trace gives
each client's first Initial DCID, and client i + 1 is CSV row i (client 0 = warm-up).

  python qlog_recovery.py <run.csv> <run.jsonl> <qlog dir>
"""

import csv
import json
import statistics
import sys
from pathlib import Path

from decode_initial import split_datagram


def odcid_by_client(trace: str) -> dict[int, str]:
    out: dict[int, str] = {}
    for line in open(trace, encoding="utf-8"):
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r["dir"] != "c2s" or r["client"] in out:
            continue
        for p in split_datagram(bytes.fromhex(r["hex"])):
            if p.ptype == 0:
                out[r["client"]] = p.dcid.hex()
                break
    return out


def recovery_summary(path: Path) -> dict:
    s = {"first_rtt": None, "srtt_at_confirm": None, "rttvar_at_confirm": None, "t_confirm": None,
         "pto_expired": {}, "lost": 0, "max_app_pto": 0.0, "t_closed": None}
    srtt = rttvar = None
    for line in open(path, encoding="utf-8"):
        line = line.lstrip("\x1e").strip()
        if not line.startswith('{"time"'):
            continue
        e = json.loads(line)
        name, d, t = e["name"], e.get("data", {}), e["time"]
        if name == "recovery:metrics_updated" and "smoothed_rtt" in d:
            srtt, rttvar = d["smoothed_rtt"], d.get("rtt_variance", rttvar)
            if s["first_rtt"] is None:
                s["first_rtt"] = d.get("latest_rtt")
        elif name == "security:key_discarded" and d.get("key_type") == "client_handshake_secret" and s["t_confirm"] is None:
            s.update(t_confirm=t, srtt_at_confirm=srtt, rttvar_at_confirm=rttvar)
        elif name == "recovery:loss_timer_updated" and d.get("timer_type") == "pto":
            space = d.get("packet_number_space")
            if d.get("event_type") == "expired":
                s["pto_expired"][space] = s["pto_expired"].get(space, 0) + 1
            elif d.get("event_type") == "set" and space == "application_data":
                s["max_app_pto"] = max(s["max_app_pto"], d.get("delta", 0.0))
        elif name == "recovery:packet_lost":
            s["lost"] += 1
        elif name == "transport:connection_closed":
            s["t_closed"] = t
    return s


def main(csv_path: str, trace: str, qdir: str) -> int:
    odcid = odcid_by_client(trace)
    rows = list(csv.DictReader(open(csv_path, encoding="utf-8")))
    by_variant: dict[str, list[dict]] = {"hybrid": [], "classical": []}
    for i, r in enumerate(rows):
        q = Path(qdir) / f"{odcid.get(i + 1, '')}_client.sqlog"
        if not q.exists():
            continue
        s = recovery_summary(q)
        s["elapsed_ms"] = float(r["elapsed_ms"])
        by_variant[r["variant"]].append(s)

    def m(xs):
        xs = [x for x in xs if x is not None]
        return f"{statistics.fmean(xs):.1f}" if xs else "-"

    for v, ss in by_variant.items():
        app_pto = sum(1 for s in ss if s["pto_expired"].get("application_data"))
        hs_pto = sum(1 for s in ss if s["pto_expired"].get("handshake"))
        init_pto = sum(1 for s in ss if s["pto_expired"].get("initial"))
        print(f"{v:9s} n={len(ss)} first_rtt={m([s['first_rtt'] for s in ss])} "
              f"srtt@confirm={m([s['srtt_at_confirm'] for s in ss])} rttvar@confirm={m([s['rttvar_at_confirm'] for s in ss])} "
              f"t_confirm={m([s['t_confirm'] for s in ss])} max_app_pto={m([s['max_app_pto'] for s in ss])} "
              f"lost/conn={m([s['lost'] for s in ss])} conns with PTO expiry: initial={init_pto} handshake={hs_pto} app={app_pto}")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:4]))
