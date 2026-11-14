#!/usr/bin/env python3
"""Draws every diagram in the project's READMEs, in one drafting-sheet style.

    python3 assets/diagrams/generate.py          # writes assets/diagrams/<name>-{light,dark}.svg
    python3 assets/diagrams/generate.py --sync   # also copies each repo's own sheet into ../<repo>/assets/

Edit a sheet's definition at the bottom of this file, never an SVG.

Boxes are placed by hand on a 10 px grid. Connections are routed automatically:
straight runs with 45 degree corners, never through a box. Standard library only,
and the output is deterministic, so a regenerated file only changes when its
definition below changes.
"""
import heapq
import shutil
import sys
from html import escape
from pathlib import Path

G = 10
CW, CH = 100, 56
W, H = CW * G, CH * G
FLOOR = 47                      # routing stays above the title strip

THEMES = {
    "light": dict(paper="#EFCB86", ink="#35250D", soft="#6B4E1E", fill="#F6DBA4",
                  grid="#C99F52", pulse="#B4370C"),
    "dark":  dict(paper="#16110A", ink="#EDB95F", soft="#B98C42", fill="#211909",
                  grid="#4A3716", pulse="#FFF3CF"),
}

DIRS = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)]
NORMAL = {"L": (-1, 0), "R": (1, 0), "T": (0, -1), "B": (0, 1)}
CHAR = 0.61                     # advance of a monospace glyph, in em


class Sheet:
    def __init__(self, repo, name, title, number, legend):
        self.repo, self.name, self.title, self.number, self.legend = repo, name, title, number, legend
        self.nodes, self.groups, self.edges, self.extra = {}, [], [], []

    def group(self, x, y, w, h, label):
        self.groups.append((x, y, w, h, label))

    def node(self, key, x, y, w, h, title, sub=(), style="part", shape="box"):
        self.nodes[key] = dict(x=x, y=y, w=w, h=h, title=title,
                               sub=[sub] if isinstance(sub, str) else list(sub), style=style, shape=shape)

    def edge(self, a, b, label="", dashed=False, both=False, lp=None, via=(), plain=False, n=None):
        """a and b are "node.SIDE" or "node.SIDE+2" (offset in cells from the middle of that side).
        n puts a step number in front of the label, for sheets that show a sequence."""
        self.edges.append(dict(a=a, b=b, label=label, dashed=dashed, both=both, lp=lp, via=list(via), plain=plain, n=n))

    def raw(self, svg):
        self.extra.append(svg)

    # ---- routing -------------------------------------------------------------------------------

    def port(self, spec):
        key, rest = spec.split(".")
        side, off = rest[0], int(rest[1:] or 0)
        n = self.nodes[key]
        if side in "LR":
            p = (n["x"] if side == "L" else n["x"] + n["w"], n["y"] + n["h"] // 2 + off)
        else:
            p = (n["x"] + n["w"] // 2 + off, n["y"] if side == "T" else n["y"] + n["h"])
        return p, NORMAL[side]

    def blocked(self):
        cells = set()
        for n in self.nodes.values():
            for x in range(n["x"] - 1, n["x"] + n["w"] + 2):
                for y in range(n["y"] - 1, n["y"] + n["h"] + 2):
                    cells.add((x, y))
        return cells

    def astar(self, start, sdir, goal, gdir, blocked, occ, diag):
        def h(x, y):
            return abs(x - goal[0]) + abs(y - goal[1])

        s = (start[0], start[1], sdir)
        best, prev, heap = {s: 0.0}, {}, [(h(*start), 0.0, s)]
        while heap:
            _, g, cur = heapq.heappop(heap)
            if g > best.get(cur, 1e9):
                continue
            x, y, d = cur
            if (x, y) == goal and (gdir is None or min((d - gdir) % 8, (gdir - d) % 8) <= 1):
                path = [(x, y)]
                while cur in prev:
                    cur = prev[cur]
                    path.append((cur[0], cur[1]))
                return path[::-1], d
            crossing = (x, y) in occ and (x, y) != start
            for turn in ((0,) if crossing else (0, 1, -1)):
                nd = (d + turn) % 8
                dx, dy = DIRS[nd]
                nx, ny = x + dx, y + dy
                if not (2 <= nx <= CW - 2 and 2 <= ny <= FLOOR):
                    continue
                if (nx, ny) in blocked and (nx, ny) != goal:
                    continue
                step = 2.3 if dx and dy else 1.0
                if (nx, ny) in occ:
                    if nd % 4 in occ[(nx, ny)] or nd % 2:      # no overlap, and cross at right angles only
                        continue
                    step += 6
                if dx and dy and ((min(x, nx), min(y, ny)), dx * dy < 0) in diag:
                    continue
                ng = g + step + (0.4 if turn else 0.0)
                ns = (nx, ny, nd)
                if ng < best.get(ns, 1e9):
                    best[ns] = ng
                    prev[ns] = cur
                    heapq.heappush(heap, (ng + h(nx, ny), ng, ns))
        return None, None

    def route(self):
        blocked, occ, diag = self.blocked(), {}, set()
        for e in self.edges:
            (pa, na), (pb, nb) = self.port(e["a"]), self.port(e["b"])
            stops = [(pa[0] + na[0], pa[1] + na[1])] + e["via"] + [(pb[0] + nb[0], pb[1] + nb[1])]
            d, cells = DIRS.index(na), []
            for i, (s, t) in enumerate(zip(stops, stops[1:])):
                last = i == len(stops) - 2
                leg, d = self.astar(s, d, t, DIRS.index((-nb[0], -nb[1])) if last else None, blocked, occ, diag)
                if leg is None:
                    raise SystemExit(f"{self.repo}: no route for {e['a']} -> {e['b']}")
                cells += leg if not cells else leg[1:]
            cells = [pa] + cells + [pb]
            for (ax, ay), (bx, by) in zip(cells, cells[1:]):
                axis = DIRS.index((bx - ax, by - ay)) % 4
                occ.setdefault((ax, ay), set()).add(axis)
                occ.setdefault((bx, by), set()).add(axis)
                if ax != bx and ay != by:
                    diag.add(((min(ax, bx), min(ay, by)), (bx - ax) * (by - ay) > 0))
            pts = [cells[0]]
            for p, q, r in zip(cells, cells[1:], cells[2:]):
                if (q[0] - p[0], q[1] - p[1]) != (r[0] - q[0], r[1] - q[1]):
                    pts.append(q)
            pts.append(cells[-1])
            e["pts"] = pts

    # ---- drawing -------------------------------------------------------------------------------

    def draw_node(self, n):
        x, y, w, h = n["x"] * G, n["y"] * G, n["w"] * G, n["h"] * G
        cx, style, sub = x + w / 2, n["style"], n["sub"]
        o = []
        if style == "anchor":
            return ""
        if n["shape"] == "db":
            o.append(f'<path class="box {style}" d="M{x} {y + 7} a{w / 2} 7 0 0 1 {w} 0 v{h - 14} '
                     f'a{w / 2} 7 0 0 1 {-w} 0 z"/><path class="line" d="M{x} {y + 7} a{w / 2} 7 0 0 0 {w} 0"/>')
        else:
            o.append(f'<rect class="box {style}" x="{x}" y="{y}" width="{w}" height="{h}" rx="3"/>')
        if style == "pane":
            o.append(f'<text class="cap" x="{x + 8}" y="{y + 14}">{escape(n["title"].upper())}</text>'
                     f'<path class="hair" d="M{x} {y + 20} h{w}"/>')
            return "".join(o)
        if style == "own" and sub:
            o.append(f'<path class="bar" d="M{x + 3} {y} h{w - 6} a3 3 0 0 1 3 3 v19 h{-w} v-19 a3 3 0 0 1 3 -3z"/>'
                     f'<text class="t inv" x="{cx}" y="{y + 15.5}">{escape(n["title"])}</text>')
            top = y + 22 + (h - 22 - 13 * len(sub)) / 2 + 9.5
        elif style == "own":
            o.append(f'<rect class="bar" x="{x}" y="{y}" width="{w}" height="{h}" rx="3"/>'
                     f'<text class="t inv" x="{cx}" y="{y + h / 2 + 4.5}">{escape(n["title"])}</text>')
            top = 0
        else:
            block = 14 + 13 * len(sub)
            ty = y + (h - block) / 2 + 11 + (4 if n["shape"] == "db" else 0)
            o.append(f'<text class="t" x="{cx}" y="{ty:.1f}">{escape(n["title"])}</text>')
            top = ty + 14
        for i, line in enumerate(sub):
            o.append(f'<text class="s" x="{cx}" y="{top + 13 * i:.1f}">{escape(line)}</text>')
        return "".join(o)

    def label_at(self, e):
        width = len(e["label"]) * 10.5 * CHAR + (10 if e["label"] else 0) + (20 if e["n"] else 0)
        if e["lp"]:
            return e["lp"][0] * G, e["lp"][1] * G, width
        best, score = None, -1
        for (ax, ay), (bx, by) in zip(e["pts"], e["pts"][1:]):
            length = (abs(bx - ax) + abs(by - ay)) * G
            s = length + (1000 if ay == by and length >= width + 14 else 0)
            if s > score:
                best, score = ((ax + bx) / 2 * G, (ay + by) / 2 * G), s
        return best[0], best[1], width

    def svg(self, theme):
        c = THEMES[theme]
        self.route()
        o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
             f'class="sheet" role="img" aria-labelledby="st sd">',
             f'<title id="st">{escape(self.title)}</title>',
             f'<desc id="sd">{escape(self.describe())}</desc>', "<style>",
             ".sheet{" + "".join(f"--{k}:{v};" for k, v in c.items()) + "}",
             STYLE, "</style>",
             '<defs><pattern id="dots" width="20" height="20" patternUnits="userSpaceOnUse">'
             '<circle class="dot" cx="10" cy="10" r=".9"/></pattern>'
             '<marker id="arrow" viewBox="0 0 8 8" refX="7.2" refY="4" markerWidth="8" markerHeight="8" '
             'orient="auto-start-reverse" markerUnits="userSpaceOnUse"><path class="head" d="M0 .8 L7.6 4 L0 7.2z"/></marker></defs>',
             f'<rect class="paper" x="1.5" y="1.5" width="{W - 3}" height="{H - 3}" rx="16"/>',
             f'<rect fill="url(#dots)" x="10" y="10" width="{W - 20}" height="{H - 20}" rx="10"/>',
             f'<rect class="inner" x="9.5" y="9.5" width="{W - 19}" height="{H - 19}" rx="10"/>']
        for x, y, w, h, label in self.groups:
            lw = len(label) * 9.5 * (CHAR + .13) + 12
            o.append(f'<rect class="group" x="{x * G}" y="{y * G}" width="{w * G}" height="{h * G}" rx="8"/>'
                     f'<rect class="mask" x="{x * G + 12}" y="{y * G - 7}" width="{lw:.0f}" height="14"/>'
                     f'<text class="cap" x="{x * G + 19}" y="{y * G + 3.5}">{escape(label)}</text>')
        for e in self.edges:
            pts = " ".join(f"{x * G},{y * G}" for x, y in e["pts"])
            ends = "" if e["plain"] else ' marker-end="url(#arrow)"' + (' marker-start="url(#arrow)"' if e["both"] else "")
            o.append(f'<polyline class="wire{" dash" if e["dashed"] else ""}" points="{pts}"{ends}/>')
        for i, e in enumerate(self.edges):
            if not e["plain"]:
                pts = " ".join(f"{x * G},{y * G}" for x, y in e["pts"])
                o.append(f'<polyline class="pulse" pathLength="100" style="animation-delay:-{(i * 1.37) % 6:.2f}s" points="{pts}"/>')
        for n in self.nodes.values():
            o.append(self.draw_node(n))
        for e in self.edges:
            if e["label"] or e["n"]:
                lx, ly, lw = self.label_at(e)
                o.append(f'<rect class="mask" x="{lx - lw / 2:.1f}" y="{ly - 9}" width="{lw:.1f}" height="18" rx="2"/>')
                if e["n"]:
                    o.append(f'<circle class="bar" cx="{lx - lw / 2 + 10:.1f}" cy="{ly}" r="8.5"/>'
                             f'<text class="num" x="{lx - lw / 2 + 10:.1f}" y="{ly + 3.6}">{e["n"]}</text>')
                o.append(f'<text class="l" x="{lx + (10 if e["n"] else 0):.1f}" y="{ly + 3.6}">{escape(e["label"])}</text>')
        o += self.extra

        # legend and title block
        lx, ly = 28, 505
        for style, text in self.legend:
            if style == "dash":
                o.append(f'<path class="wire dash" d="M{lx} {ly + 7} h26"/>')
            elif style == "wire":
                o.append(f'<path class="wire" d="M{lx} {ly + 7} h26" marker-end="url(#arrow)"/>')
            elif style == "own":
                o.append(f'<rect class="bar" x="{lx}" y="{ly}" width="26" height="14" rx="2"/>')
            else:
                o.append(f'<rect class="box {style}" x="{lx}" y="{ly}" width="26" height="14" rx="2"/>')
            o.append(f'<text class="s left" x="{lx + 34}" y="{ly + 11}">{escape(text)}</text>')
            lx += 34 + len(text) * 10.5 * CHAR + 22
        if lx - 22 > W - 24 - (max(len(self.repo) + 31, len(self.title) * 1.75) * 5.6 + 100):
            raise SystemExit(f"{self.name}: the legend runs into the title block, shorten it")
        cap = f"KUBERNETES-LEARNING-PLATFORM / {self.repo.upper()}"
        left = max(len(cap) * 9.5 * (CHAR + .13), len(self.title) * 16 * CHAR) + 22
        bw, bh, by = left + 78, 46, 490
        bx = W - 24 - bw
        o.append(f'<rect class="tb" x="{bx:.0f}" y="{by}" width="{bw:.0f}" height="{bh}"/>'
                 f'<path class="line" d="M{bx + left:.0f} {by} v{bh}"/>'
                 f'<text class="cap" x="{bx + 10:.0f}" y="{by + 15}">{cap}</text>'
                 f'<text class="big" x="{bx + 10:.0f}" y="{by + 36}">{escape(self.title)}</text>'
                 f'<text class="cap" x="{bx + left + 10:.0f}" y="{by + 15}">SHEET</text>'
                 f'<text class="big" x="{bx + left + 10:.0f}" y="{by + 36}">{self.number}/{len(SHEETS)}</text>')
        o.append("</svg>")
        return "\n".join(o) + "\n"

    def describe(self):
        names = {k: n["title"] for k, n in self.nodes.items()}
        links = []
        for e in self.edges:
            a, b = names[e["a"].split(".")[0]], names[e["b"].split(".")[0]]
            links.append(f"{a} to {b}" + (f" ({e['label']})" if e["label"] else ""))
        return f"{self.title}. Connections: " + "; ".join(links) + "."


STYLE = """.sheet{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,"Liberation Mono",monospace}
.paper{fill:var(--paper);stroke:var(--ink);stroke-width:3}
.inner{fill:none;stroke:var(--ink);stroke-width:.8}
.dot{fill:var(--grid)}
.group{fill:none;stroke:var(--soft);stroke-width:1.2;stroke-dasharray:7 5}
.mask{fill:var(--paper)}
.box{fill:var(--fill);stroke:var(--ink);stroke-width:1.5}
.box.ext{fill:var(--paper);stroke:var(--soft);stroke-dasharray:4 3}
.box.pane{fill:var(--paper)}
.bar{fill:var(--ink)}
.line,.hair{fill:none;stroke:var(--ink);stroke-width:1.2}
.hair{stroke:var(--soft);stroke-width:.8}
.wire{fill:none;stroke:var(--ink);stroke-width:1.6;stroke-linejoin:round}
.wire.dash{stroke-dasharray:5 4}
.head{fill:var(--ink)}
.t{fill:var(--ink);font-size:13px;font-weight:700;text-anchor:middle;letter-spacing:.02em}
.t.inv{fill:var(--paper)}
.s{fill:var(--soft);font-size:10.5px;text-anchor:middle}
.s.left,.s.code{text-anchor:start}
.s.code{fill:var(--ink)}
.l{fill:var(--ink);font-size:10.5px;text-anchor:middle}
.num{fill:var(--paper);font-size:10.5px;font-weight:700;text-anchor:middle}
.note{fill:var(--ink);font-size:12px;text-anchor:middle;letter-spacing:.02em}
.cap{fill:var(--soft);font-size:9.5px;letter-spacing:.13em}
.big{fill:var(--ink);font-size:16px;font-weight:700}
.tb{fill:var(--paper);stroke:var(--ink);stroke-width:1.4}
.chip{fill:var(--fill);stroke:var(--ink);stroke-width:1.1}
.chip.on{fill:var(--ink)}
.thin{fill:none;stroke:var(--soft);stroke-width:1}
.pulse{fill:none;stroke:var(--pulse);stroke-width:3.2;stroke-linecap:round;stroke-dasharray:1.2 98.8;animation:flow 6s linear infinite}
@keyframes flow{from{stroke-dashoffset:100}to{stroke-dashoffset:0}}
@media (prefers-reduced-motion:reduce){.pulse{display:none}}"""


# ---- the six sheets --------------------------------------------------------------------------------

def docs():
    d = Sheet("docs", "system-map", "System map", 1, [("own", "a service we write"), ("part", "off the shelf"),
                                         ("ext", "outside the stack"), ("dash", "work queue")])
    d.group(19, 5, 40, 41, "COURSE VM · THE STACK")
    d.group(64, 5, 33, 41, "COURSE VM · ON THE HOST")
    d.group(80, 9, 15, 34, "SANDBOX")
    d.node("browser", 3, 19, 11, 8, "Browser", "in the tailnet", "ext")
    d.node("llm", 3, 35, 11, 6, "LLM API", style="ext")
    d.node("caddy", 22, 19, 10, 8, "Caddy", "proxy")
    d.node("web", 38, 8, 13, 7, "web", "Next.js", "own")
    d.node("api", 39, 19, 15, 9, "api", ["ASP.NET Core", "scenarios + helper"], "own")
    d.node("pg", 25, 35, 12, 8, "Postgres", "event log", shape="db")
    d.node("mq", 44, 36, 12, 7, "RabbitMQ", "start + teardown")
    d.node("envmgr", 66, 19, 11, 9, "envmgr", ["systemd", "on the host"], "own")
    d.node("harness", 82, 13, 11, 7, "harness", "Native AOT", "own")
    d.node("k3d", 82, 28, 11, 11, "k3d cluster", "cp · w1 · w2")
    d.edge("browser.R", "caddy.L", "HTTPS")
    d.edge("caddy.T", "web.L")
    d.edge("caddy.R", "api.L", "REST + WS")
    d.edge("api.L+3", "llm.R", "HTTPS", lp=(26, 29))
    d.edge("api.B-4", "pg.T+3")
    d.edge("api.B+2", "mq.T", dashed=True)
    d.edge("mq.R", "envmgr.B", "AMQP", dashed=True)
    d.edge("api.R", "envmgr.L", "gRPC")
    d.edge("harness.L", "envmgr.T", "WebSocket", lp=(77, 16))
    d.edge("harness.B", "k3d.T", "kubectl")
    return d


def contracts():
    d = Sheet("contracts", "contracts", "One schema, every boundary", 6,
              [("own", "this repo"), ("part", "consumer"), ("wire", "a boundary and its .proto"), ("dash", "package")])
    d.node("proto", 27, 5, 46, 9, "proto/kubernetes_learning/v1",
           "common · envmgr · harness · topology · view · session · rest · jobs", "own")
    d.node("web", 4, 26, 13, 8, "web", "browser")
    d.node("api", 31, 26, 13, 8, "api", "the stack")
    d.node("envmgr", 58, 26, 13, 8, "envmgr", "on the host")
    d.node("harness", 84, 26, 12, 8, "harness", "sandbox")
    d.node("mq", 45, 40, 12, 6, "RabbitMQ")
    d.edge("proto.L", "web.T", "npm", dashed=True, lp=(10.5, 18))
    d.edge("proto.B-10", "api.T", "NuGet", dashed=True, lp=(37.5, 20))
    d.edge("proto.B+10", "envmgr.T", "NuGet", dashed=True, lp=(64.5, 20))
    d.edge("proto.R", "harness.T", "NuGet", dashed=True, lp=(90, 18))
    d.edge("web.R-2", "api.L-2", "session · WS", both=True)
    d.edge("web.R+2", "api.L+2", "rest · HTTP")
    d.edge("api.R", "envmgr.L", "envmgr · gRPC", both=True)
    d.edge("envmgr.R", "harness.L", "harness · WS", both=True)
    d.edge("api.B", "mq.L", "jobs", lp=(37.5, 39))
    d.edge("mq.R", "envmgr.B", "AMQP", lp=(64.5, 39))
    return d


def sandbox():
    d = Sheet("sandbox", "sandbox", "One sandbox, end to end", 7,
              [("own", "built in this repo"), ("part", "runs in the sandbox"), ("ext", "outside"), ("dash", "work queue")])
    d.group(19, 5, 38, 41, "ENVMGR · SYSTEMD ON THE COURSE VM")
    d.group(63, 5, 34, 41, "SANDBOX · ISOLATED NETWORK")
    d.node("api", 3, 9, 11, 8, "api", "SandboxClient", "ext")
    d.node("mq", 3, 34, 11, 6, "RabbitMQ", style="ext")
    d.node("grpc", 22, 9, 14, 8, "gRPC service", ["Create · Watch", "Connect"], "own")
    d.node("relay", 41, 9, 13, 8, "Relay", ["pairs api", "with harness"], "own")
    d.node("queue", 22, 33, 14, 8, "Consumers", ["provision", "teardown"], "own")
    d.node("recon", 22, 21, 14, 8, "Reconciler", ["warm pool · cap", "max lifetime"], "own")
    d.node("prov", 41, 30, 13, 9, "Providers", ["QEMU/libvirt", "Docker"], "own")
    d.node("harness", 65, 9, 13, 11, "harness", ["exec · pty · file", "fault · check"], "own")
    d.node("watch", 65, 29, 13, 9, "Watchers", ["kube · docker", "to topology"], "own")
    d.node("vm", 62, 42, 0, 0, "the sandbox", style="anchor")
    d.node("cp", 87, 10, 8, 5, "cp")
    d.node("w1", 87, 22, 8, 5, "w1")
    d.node("w2", 87, 34, 8, 5, "w2")
    d.raw(f'<rect class="group" x="855" y="70" width="105" height="350" rx="8"/>'
          f'<rect class="mask" x="864" y="413" width="86" height="14"/><text class="cap" x="869" y="423.5">K3D CLUSTER</text>')
    d.edge("api.R", "grpc.L", "gRPC")
    d.edge("grpc.R", "relay.L")
    d.edge("relay.R", "harness.L-2", "WS :7071", both=True)
    d.edge("mq.R", "queue.L", "AMQP", dashed=True)
    d.edge("queue.T", "recon.B")
    d.edge("recon.R", "prov.L")
    d.edge("prov.B", "vm.L", "clone · cloud-init")
    d.edge("harness.R-2", "cp.L", "kubectl")
    d.edge("harness.R+2", "w1.L")
    d.edge("w2.L", "watch.R+3", "events")
    d.edge("watch.T", "harness.B", "diffs")
    return d


def api():
    d = Sheet("api", "api", "Inside api", 8, [("own", "KubernetesLearning.Api"), ("part", "library"),
                                       ("ext", "outside"), ("dash", "work queue")])
    d.group(19, 5, 55, 41, "API · ASP.NET CORE · ONE PROCESS")
    d.node("browser", 3, 8, 11, 18, "Browser", style="ext")
    d.node("pg", 3, 34, 11, 8, "Postgres", shape="db", style="ext")
    d.node("ctl", 22, 8, 14, 8, "Controllers", ["Auth · Sessions", "Scenarios · Events"], "own")
    d.node("ws", 22, 21, 14, 7, "Socket", "/ws/sessions/{id}", "own")
    d.node("fan", 22, 34, 14, 8, "EventFanout", ["persist,", "then broadcast"], "own")
    d.node("scn", 41, 8, 13, 8, "Scenarios", ["runner · checks", "no LLM"])
    d.node("live", 41, 21, 13, 8, "LiveSession", ["one per", "session"], "own")
    d.node("prov", 41, 35, 13, 7, "Provisioner", "queue + fake", "own")
    d.node("agent", 58, 8, 13, 8, "Agent", ["helper loop", "typed tools"])
    d.node("sbx", 58, 21, 13, 8, "SandboxClient", "ISandboxSession")
    d.node("llm", 81, 9, 13, 6, "LLM API", style="ext")
    d.node("envmgr", 81, 21, 13, 8, "envmgr", "on the host", "ext")
    d.node("mq", 81, 35, 13, 7, "RabbitMQ", style="ext")
    d.edge("browser.R-5", "ctl.L", "REST")
    d.edge("browser.R+7", "ws.L", "WS", both=True)
    d.edge("ws.R", "live.L")
    d.edge("live.T", "scn.B")
    d.edge("live.R-2", "agent.L", lp=(56, 19))
    d.edge("live.R+1", "sbx.L+1")
    d.edge("live.B-3", "fan.R", "events", lp=(38.5, 35))
    d.edge("fan.T", "ws.B", "seq")
    d.edge("fan.L", "pg.R", "append")
    d.edge("live.B+2", "prov.T+2")
    d.edge("agent.R", "llm.L", "HTTPS")
    d.edge("sbx.R", "envmgr.L", "gRPC", both=True)
    d.edge("prov.R", "mq.L", "start · teardown", dashed=True)
    return d


def web():
    d = Sheet("web", "web", "The lab screen", 9, [("own", "state"), ("pane", "what you see"), ("ext", "api")])
    d.group(33, 5, 64, 41, "/SESSION/[ID]")
    d.node("api", 3, 21, 9, 8, "api", "/ws", "ext")
    d.node("sock", 15, 8, 14, 7, "socket.ts", "protobuf-es", "own")
    d.node("topo", 15, 20, 14, 8, "topology", ["what exists", "snapshot + diffs"], "own")
    d.node("view", 15, 34, 14, 8, "view", ["where you look", "ViewIntent"], "own")
    d.node("canvas", 36, 8, 34, 23, "Topology canvas", style="pane")
    d.node("term", 36, 34, 34, 10, "Terminal", style="pane")
    d.node("scen", 73, 8, 22, 12, "Scenario", style="pane")
    d.node("chat", 73, 22, 22, 10, "Helper chat", style="pane")
    d.node("insp", 73, 34, 22, 10, "Config inspector", style="pane")
    d.edge("api.T", "sock.L", both=True)
    d.edge("sock.B", "topo.T")
    d.edge("topo.R", "canvas.L+5")
    d.edge("view.R", "canvas.L+9")
    d.edge("topo.B", "view.T", plain=True)
    # canvas: three nodes with pod chips, one service
    o = []
    for i, name in enumerate(["cp", "w1", "w2"]):
        x = 385 + i * 105
        o.append(f'<rect class="chip" x="{x}" y="190" width="88" height="94" rx="4"/>'
                 f'<text class="s code" x="{x + 8}" y="205">{name}</text>')
        for j in range([1, 3, 2][i]):
            on = " on" if (i, j) == (2, 1) else ""
            o.append(f'<rect class="chip{on}" x="{x + 10 + (j % 2) * 36}" y="{216 + (j // 2) * 30}" width="30" height="22" rx="3"/>')
    o.append('<rect class="chip" x="480" y="122" width="110" height="24" rx="12"/>'
             '<text class="s" x="535" y="138">svc/web</text>'
             '<path class="thin" d="M510 146 L510 216 M535 146 L535 170 L616 170 L616 216 M560 146 L560 160 L656 160 L656 216"/>'
             '<text class="s left" x="385" y="301">one pod on w2 is crash-looping</text>')
    # terminal, scenario, chat, inspector
    o.append('<text class="s code" x="372" y="382">$ kubectl get pods -n shop</text>'
             '<text class="s left" x="372" y="398">web-7c9f-abc   0/1   CrashLoopBackOff</text>'
             '<text class="s code" x="372" y="414">agent$ kubectl describe ingress web</text>')
    o.append('<text class="s code" x="742" y="118">Fix a broken ingress</text>'
             '<rect class="chip on" x="742" y="130" width="11" height="11" rx="2"/><text class="s left" x="760" y="140">Service web exists</text>'
             '<rect class="chip" x="742" y="149" width="11" height="11" rx="2"/><text class="s left" x="760" y="159">GET / returns 200</text>'
             '<rect class="chip" x="742" y="172" width="54" height="18" rx="3"/><text class="s" x="769" y="185">Hint</text>'
             '<rect class="chip" x="804" y="172" width="54" height="18" rx="3"/><text class="s" x="831" y="185">Reset</text>'
             '<rect class="chip on" x="866" y="172" width="54" height="18" rx="3"/><text class="s" x="893" y="185" style="fill:var(--paper)">Next</text>')
    o.append('<rect class="chip" x="800" y="250" width="140" height="20" rx="8"/><text class="s" x="870" y="264">why is it stuck?</text>'
             '<rect class="chip" x="740" y="278" width="170" height="34" rx="8"/><text class="s left" x="750" y="292">The Ingress points at a</text>'
             '<text class="s left" x="750" y="305">Service that is missing.</text>')
    o.append('<text class="s code" x="742" y="378">kind: Ingress</text><text class="s left" x="742" y="392">spec:</text>'
             '<text class="s left" x="742" y="406">  rules:</text><text class="s left" x="742" y="420">  - host: shop.localhost</text>'
             '<rect class="chip on" x="884" y="366" width="56" height="18" rx="3"/><text class="s" x="912" y="379" style="fill:var(--paper)">Apply</text>')
    d.raw("".join(o))
    return d


def platform():
    d = Sheet("platform", "platform", "From a commit to the VM", 10,
              [("own", "reusable workflow"), ("part", "what it ships"), ("ext", "caller or target"), ("dash", "Tailscale")])
    d.group(18, 5, 20, 41, "PLATFORM WORKFLOWS")
    d.group(69, 15, 28, 31, "COURSE VM")
    d.node("contracts", 3, 8, 11, 7, "contracts", style="ext")
    d.node("sandbox", 3, 21, 11, 7, "sandbox", style="ext")
    d.node("apiweb", 3, 36, 11, 7, "api", "web", "ext")
    d.node("proto", 20, 8, 16, 7, "proto-ci", "buf · codegen", "own")
    d.node("bin", 20, 17, 16, 7, "release-binary", "linux x64 + arm64", "own")
    d.node("vm", 20, 26, 16, 7, "sandbox-template", "self-hosted runner", "own")
    d.node("img", 20, 36, 16, 7, "container-publish", "multi-arch", "own")
    d.node("pkg", 43, 8, 16, 7, "GitHub Packages", "NuGet · npm")
    d.node("rel", 43, 17, 16, 7, "GitHub Releases", "envmgr · harness")
    d.node("tpl", 43, 26, 16, 7, "Sandbox template", "Packer · qcow2")
    d.node("ghcr", 43, 36, 16, 7, "GHCR", "api · web images")
    d.node("lap", 72, 5, 22, 5, "Demo laptop", style="ext")
    d.node("px", 72, 18, 22, 12, "On the host", ["envmgr · sandboxes", "CI runner"], "ext")
    d.node("hz", 72, 35, 22, 9, "The stack", ["Caddy · web · api", "Postgres · RabbitMQ"], "ext")
    d.edge("contracts.R", "proto.L")
    d.edge("sandbox.R-1", "bin.L")
    d.edge("sandbox.R+1", "vm.L")
    d.edge("apiweb.R", "img.L")
    d.edge("proto.R", "pkg.L")
    d.edge("bin.R", "rel.L")
    d.edge("vm.R", "tpl.L")
    d.edge("img.R", "ghcr.L")
    d.edge("rel.R", "px.L-3", "deploy/vm")
    d.edge("tpl.R", "px.L+6", "linked clones")
    d.edge("ghcr.R", "hz.L", "manual deploy")
    d.edge("lap.B", "px.T", dashed=True, plain=True)
    return d


def repos():
    d = Sheet("docs", "repos", "Repos and packages", 2,
              [("own", "product code"), ("ext", "shared tooling"), ("wire", "installs from"), ("dash", "calls its CI")])
    d.node("contracts", 4, 18, 15, 9, "contracts", ["the .proto schema", "NuGet + npm"], "own")
    d.node("sandbox", 30, 18, 15, 9, "sandbox", ["envmgr · harness", "SandboxClient"], "own")
    d.node("api", 56, 18, 15, 9, "api", ["backend", "scenarios + helper"], "own")
    d.node("web", 81, 18, 15, 9, "web", ["Next.js", "frontend"], "own")
    d.node("platform", 4, 37, 92, 7, "platform", "reusable CI workflows · lint configs · VM install script · deploy files", "ext")
    d.edge("contracts.R", "sandbox.L", "NuGet")
    d.edge("sandbox.R", "api.L", "SandboxClient")
    d.edge("contracts.T+2", "api.T", "NuGet", via=[(37, 12)], lp=(37, 12))
    d.edge("contracts.T-2", "web.T", "npm", via=[(50, 7)], lp=(50, 7))
    d.edge("platform.T-39", "contracts.B", dashed=True)
    d.edge("platform.T-13", "sandbox.B", dashed=True)
    d.edge("platform.T+13", "api.B", dashed=True)
    d.edge("platform.T+38", "web.B", dashed=True)
    return d


def session_start():
    d = Sheet("docs", "session-start", "Starting a session", 3,
              [("own", "we write it"), ("part", "off the shelf"), ("ext", "outside"), ("dash", "work queue")])
    d.group(21, 5, 20, 41, "COURSE VM · STACK")
    d.group(47, 5, 50, 41, "COURSE VM · ON THE HOST")
    d.node("browser", 3, 14, 10, 12, "Browser", style="ext")
    d.node("api", 24, 14, 14, 12, "api", ["creates the", "session"], "own")
    d.node("mq", 24, 35, 14, 7, "RabbitMQ", "work queue")
    d.node("envmgr", 51, 14, 14, 12, "envmgr", ["capacity cap", "warm pool"], "own")
    d.node("vm", 80, 14, 14, 12, "Sandbox", ["harness", "cp · w1 · w2"], "own")
    d.edge("browser.R-3", "api.L-3", "Start", n=1)
    d.edge("api.B-3", "mq.T-3", "request", dashed=True, n=2)
    d.edge("mq.R-1", "envmgr.B-3", "when there is room", dashed=True, n=3)
    d.edge("envmgr.R-3", "vm.L-3", "warm one or clone", n=4)
    d.edge("envmgr.B+3", "mq.R+2", "result", dashed=True, n=5)
    d.edge("mq.T+3", "api.B+3", dashed=True, n=5)
    d.edge("api.R-3", "envmgr.L-3", "Connect", n=6)
    d.edge("vm.L+3", "envmgr.R+3", "first snapshot", n=7)
    d.edge("envmgr.L+3", "api.R+3", "snapshot", n=7)
    d.edge("api.L+3", "browser.R+3", "live", n=8)
    return d


def two_streams():
    d = Sheet("docs", "two-streams", "How a change reaches the screen", 4,
              [("own", "we write it"), ("wire", "state stream"), ("dash", "intent stream")])
    d.group(3, 5, 16, 41, "BROWSER")
    d.group(63, 5, 34, 41, "SANDBOX")
    d.node("term", 5, 9, 12, 7, "Terminal", "you type")
    d.node("canvas", 5, 27, 12, 9, "Canvas", ["draws only", "real state"])
    d.node("api", 27, 8, 13, 28, "api", ["gives each", "message a", "number,", "saves it,", "then sends it"], "own")
    d.node("envmgr", 47, 8, 11, 28, "envmgr", ["relays", "both ways"], "own")
    d.node("run", 66, 9, 13, 7, "harness", "runs it", "own")
    d.node("k3d", 84, 17, 11, 10, "k3d cluster", "really changes")
    d.node("watch", 66, 28, 13, 7, "harness", "watches", "own")
    d.node("helper", 27, 39, 13, 6, "helper", "optional")
    d.edge("term.R", "api.L-10", "command", n=1)
    d.edge("api.R-10", "envmgr.L-10")
    d.edge("envmgr.R-10", "run.L", "exec", n=2)
    d.edge("run.R", "k3d.T", "change", n=3)
    d.edge("k3d.B", "watch.R", "watch", n=4)
    d.edge("watch.L", "envmgr.R+9", "diff", n=5)
    d.edge("envmgr.L+9", "api.R+9")
    d.edge("api.L+9", "canvas.R", "redraw", n=6)
    d.edge("helper.L", "canvas.B", "camera only", dashed=True)
    return d


def helper_turn():
    d = Sheet("docs", "helper-turn", "A helper turn", 5,
              [("part", "you drive"), ("own", "the helper drives"), ("ext", "the helper is off")])
    d.node("idle", 6, 17, 18, 12, "Idle", ["terminal: yours", "helper: silent"])
    d.node("acting", 41, 17, 18, 12, "Acting", ["terminal: read-only", "commands show as agent$", "Stop is available"], "own")
    d.node("waiting", 76, 17, 18, 12, "Waiting", ["terminal: yours", "a question card is open"])
    d.node("off", 41, 37, 18, 7, "Helper off", "the scenario carries on", "ext")
    d.edge("idle.R-3", "acting.L-3", "you send a message")
    d.edge("acting.L+3", "idle.R+3", "turn ends, or Stop")
    d.edge("acting.R-3", "waiting.L-3", "it asks a question")
    d.edge("waiting.L+3", "acting.R+3", "you answer")
    d.edge("acting.B", "off.T", "token budget spent")
    d.raw('<text class="note" x="500" y="105">A turn only ever starts from your message or your answer.</text>')
    return d


SHEETS = [docs, repos, session_start, two_streams, helper_turn, contracts, sandbox, api, web, platform]


def main():
    out = Path(__file__).parent
    for make in SHEETS:
        for theme in THEMES:
            sheet = make()
            path = out / f"{sheet.name}-{theme}.svg"
            path.write_text(sheet.svg(theme), encoding="utf-8", newline="\n")
            target = out.parents[2] / sheet.repo / "assets"
            if "--sync" in sys.argv and sheet.repo != "docs" and target.parent.is_dir():
                target.mkdir(exist_ok=True)
                shutil.copyfile(path, target / path.name)
    print(f"wrote {len(SHEETS) * len(THEMES)} files to {out}")


if __name__ == "__main__":
    main()
