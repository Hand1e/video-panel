"""Deterministic stick-figure storyboard renderer.

The model only chooses parameters (camera, size, poses, x positions); drawing is done here so the
output is stable and consistent. Scene is drawn in world coordinates, then the shot size crops a
"camera window" around the primary subject.
"""
from __future__ import annotations

from html import escape

# ---- pose library (adult: feet at origin, y up is negative; facing right) ----
_STAND = dict(head=(0, -155), neck=(0, -140), hip=(0, -85), le=(-14, -112), lh=(-18, -88), re=(14, -112),
              rh=(18, -88), lk=(-7, -45), lf=(-10, 0), rk=(7, -45), rf=(10, 0))


def _p(**over):
    d = dict(_STAND)
    d.update(over)
    return d


ADULT = {
    "stand": _p(),
    "talk": _p(re=(22, -120), rh=(32, -136)),
    "point": _p(re=(26, -132), rh=(52, -138)),
    "wave": _p(re=(20, -150), rh=(26, -172)),
    "walk": _p(le=(-12, -112), lh=(-22, -92), re=(14, -114), rh=(24, -96), lk=(-6, -44), lf=(-18, 0),
               rk=(10, -46), rf=(18, 0)),
    "sit": dict(head=(3, -120), neck=(2, -105), hip=(0, -50), le=(12, -82), lh=(26, -72), re=(10, -80),
                rh=(28, -68), lk=(32, -52), lf=(32, 0), rk=(30, -50), rf=(34, 0)),
    "sit_desk": dict(head=(3, -120), neck=(2, -105), hip=(0, -50), le=(20, -86), lh=(48, -74), re=(22, -84),
                     rh=(54, -74), lk=(32, -52), lf=(32, 0), rk=(30, -50), rf=(34, 0)),
    "sit_floor": dict(head=(0, -82), neck=(0, -67), hip=(0, -12), le=(12, -45), lh=(24, -30), re=(-10, -45),
                      rh=(-14, -20), lk=(28, -28), lf=(48, -2), rk=(26, -24), rf=(44, -2)),
    "hold_baby": _p(le=(-16, -108), lh=(14, -110), re=(16, -100), rh=(-10, -100)),
    "feed_bottle": _p(le=(-16, -108), lh=(14, -110), re=(18, -118), rh=(22, -124)),
    "hold_object": _p(re=(18, -114), rh=(26, -104)),
    "phone": _p(le=(-8, -112), lh=(6, -126), re=(10, -112), rh=(10, -128)),
    "cook": _p(le=(16, -112), lh=(36, -96), re=(18, -110), rh=(40, -98)),
    "squat": dict(head=(12, -116), neck=(8, -102), hip=(0, -48), le=(18, -80), lh=(30, -58), re=(14, -78),
                  rh=(28, -55), lk=(22, -46), lf=(8, 0), rk=(18, -44), rf=(12, 0)),
    "kneel_play": dict(head=(10, -117), neck=(7, -102), hip=(-4, -52), le=(22, -84), lh=(40, -66), re=(20, -82),
                       rh=(42, -62), lk=(18, -3), lf=(-20, -3), rk=(16, -3), rf=(-22, -3)),
    "lie": dict(head=(-70, -14), neck=(-56, -12), hip=(-6, -12), le=(-40, -22), lh=(-24, -28), re=(-40, -6),
                rh=(-20, -4), lk=(26, -14), lf=(60, -8), rk=(26, -10), rf=(60, -4)),
}

BABY = {
    "baby_lie_back": dict(head=(-20, -10), neck=(-12, -9), hip=(8, -9), le=(-6, -18), lh=(-2, -26), re=(-4, -16),
                          rh=(4, -24), lk=(16, -20), lf=(24, -24), rk=(18, -16), rf=(26, -18)),
    "baby_tummy": dict(head=(-20, -22), neck=(-12, -12), hip=(10, -6), le=(-14, -6), lh=(-20, -2), re=(-10, -6),
                       rh=(-16, -2), lk=(18, -4), lf=(26, -4), rk=(18, -6), rf=(26, -8)),
    "baby_bouncer": dict(head=(-14, -36), neck=(-8, -30), hip=(6, -18), le=(0, -26), lh=(8, -30), re=(-2, -24),
                         rh=(6, -22), lk=(16, -24), lf=(24, -20), rk=(16, -20), rf=(24, -16)),
    "baby_bath": dict(head=(0, -34), neck=(0, -26), hip=(0, -12), le=(-8, -22), lh=(-12, -30), re=(8, -22),
                      rh=(12, -30), lk=(-4, -6), lf=(-6, -2), rk=(4, -6), rf=(6, -2)),
    "baby_sleep": dict(head=(-20, -10), neck=(-12, -9), hip=(8, -9), le=(-8, -14), lh=(-16, -18), re=(-6, -6),
                       rh=(0, -4), lk=(16, -12), lf=(26, -10), rk=(16, -8), rf=(26, -6)),
    "baby_held": None,  # drawn in the arms of an adult with hold_baby / feed_bottle
}

ADULT_POSES = list(ADULT)
BABY_POSES = list(BABY)
SIZES = ["wide", "medium", "close", "extreme_close"]
SIZE_CN = {"wide": "全景", "medium": "中景", "close": "近景", "extreme_close": "特写"}
CAM_CN = {"pov": "第一人称 POV", "tripod": "第三人称·三脚架", "handheld": "第三人称·手持(爱人)"}
WHO_CN = {"me": "我", "partner": "爱人", "baby": "宝宝"}
COLORS = {"me": "#1f6feb", "partner": "#d6336c", "baby": "#e8590c"}
HOLDING = ("hold_baby", "feed_bottle")


def _frame_dims(aspect: str) -> tuple[int, int]:
    return (225, 400) if aspect == "9:16" else (400, 225)


def _transform(pts: dict, ox: float, oy: float, scale: float, mirror: bool) -> dict:
    m = -1 if mirror else 1
    return {k: (ox + m * x * scale, oy + y * scale) for k, (x, y) in pts.items()}


def _skeleton(p: dict, color: str, head_r: float, closed_eyes: bool = False, facing: int = 1) -> list[str]:
    seg = lambda a, b: f'<line x1="{p[a][0]:.1f}" y1="{p[a][1]:.1f}" x2="{p[b][0]:.1f}" y2="{p[b][1]:.1f}"/>'
    s = [f'<g stroke="{color}" stroke-width="3" stroke-linecap="round" fill="none" '
         f'vector-effect="non-scaling-stroke">']
    for a, b in (("neck", "hip"), ("neck", "le"), ("le", "lh"), ("neck", "re"), ("re", "rh"),
                 ("hip", "lk"), ("lk", "lf"), ("hip", "rk"), ("rk", "rf")):
        s.append(seg(a, b).replace("/>", ' vector-effect="non-scaling-stroke"/>'))
    hx, hy = p["head"]
    s.append(f'<circle cx="{hx:.1f}" cy="{hy:.1f}" r="{head_r:.1f}" fill="#fff" '
             f'vector-effect="non-scaling-stroke"/>')
    ex = hx + facing * head_r * 0.35
    if closed_eyes:
        s.append(f'<path d="M{ex - 3:.1f},{hy - 1:.1f} q3,3 6,0" stroke-width="1.5" '
                 f'vector-effect="non-scaling-stroke"/>')
    else:
        s.append(f'<circle cx="{ex - 2.5:.1f}" cy="{hy - 1.5:.1f}" r="1.3" fill="{color}" stroke="none"/>')
        s.append(f'<circle cx="{ex + 2.5:.1f}" cy="{hy - 1.5:.1f}" r="1.3" fill="{color}" stroke="none"/>')
        s.append(f'<path d="M{ex - 3:.1f},{hy + 4:.1f} q3,3 6,0" stroke-width="1.5" '
                 f'vector-effect="non-scaling-stroke"/>')
    s.append("</g>")
    return s


def _held_baby(cx: float, cy: float, scale: float, mirror: bool) -> list[str]:
    m = -1 if mirror else 1
    pts = {"head": (cx + m * 14 * scale, cy - 6 * scale), "neck": (cx + m * 8 * scale, cy - 3 * scale),
           "hip": (cx - m * 8 * scale, cy), "le": (cx + m * 4 * scale, cy - 6 * scale),
           "lh": (cx + m * 2 * scale, cy - 12 * scale), "re": (cx + m * 4 * scale, cy),
           "rh": (cx, cy + 4 * scale), "lk": (cx - m * 14 * scale, cy - 6 * scale),
           "lf": (cx - m * 20 * scale, cy - 2 * scale), "rk": (cx - m * 14 * scale, cy + 2 * scale),
           "rf": (cx - m * 20 * scale, cy + 6 * scale)}
    return _skeleton(pts, COLORS["baby"], 7 * scale, facing=m)


def _props_for(pose: str, p: dict, scale: float, mirror: bool) -> list[str]:
    m = -1 if mirror else 1
    g = 'stroke="#555" stroke-width="2" fill="none" vector-effect="non-scaling-stroke"'
    hip_x, foot_y = p["hip"][0], max(p["lf"][1], p["rf"][1])
    out = []
    if pose in ("sit", "sit_desk"):
        x0 = hip_x - m * 12 * scale
        seat_y = p["hip"][1] + 2 * scale
        out.append(f'<path d="M{x0:.1f},{seat_y - 50 * scale:.1f} L{x0:.1f},{foot_y:.1f} M{x0:.1f},{seat_y:.1f} '
                   f'L{hip_x + m * 22 * scale:.1f},{seat_y:.1f} L{hip_x + m * 22 * scale:.1f},{foot_y:.1f}" {g}/>')
    if pose == "sit_desk":
        tx = hip_x + m * 40 * scale
        ty = p["hip"][1] - 22 * scale
        out.append(f'<path d="M{tx:.1f},{ty:.1f} L{tx + m * 80 * scale:.1f},{ty:.1f} M{tx + m * 70 * scale:.1f},'
                   f'{ty:.1f} L{tx + m * 70 * scale:.1f},{foot_y:.1f}" {g}/>')
    if pose == "cook":
        cx = hip_x + m * 34 * scale
        top = foot_y - 90 * scale
        w = 86 * scale
        x = min(cx, cx + m * w)
        out.append(f'<rect x="{x:.1f}" y="{top:.1f}" width="{w:.1f}" height="{90 * scale:.1f}" {g}/>')
    if pose == "hold_object":
        hx, hy = p["rh"]
        out.append(f'<rect x="{hx - 6 * scale:.1f}" y="{hy - 10 * scale:.1f}" width="{12 * scale:.1f}" '
                   f'height="{14 * scale:.1f}" {g}/>')
    if pose == "phone":
        hx, hy = p["rh"]
        out.append(f'<rect x="{hx - 4 * scale:.1f}" y="{hy - 9 * scale:.1f}" width="{8 * scale:.1f}" '
                   f'height="{14 * scale:.1f}" {g}/>')
    if pose == "feed_bottle":
        hx, hy = p["rh"]
        out.append(f'<line x1="{hx:.1f}" y1="{hy:.1f}" x2="{hx - m * 14 * scale:.1f}" y2="{hy + 10 * scale:.1f}" '
                   f'stroke="#555" stroke-width="4" vector-effect="non-scaling-stroke"/>')
    return out


def _baby_props(pose: str, p: dict, scale: float) -> list[str]:
    g = 'stroke="#999" stroke-width="2" fill="none" vector-effect="non-scaling-stroke"'
    xs = [x for x, _ in p.values()]
    y0 = max(y for _, y in p.values())
    if pose in ("baby_lie_back", "baby_tummy", "baby_sleep"):
        return [f'<rect x="{min(xs) - 8:.1f}" y="{y0 + 1:.1f}" width="{max(xs) - min(xs) + 16:.1f}" '
                f'height="{4 * scale:.1f}" {g}/>']
    if pose == "baby_bouncer":
        return [f'<path d="M{min(xs) - 6:.1f},{p["head"][1] - 4:.1f} Q{p["hip"][0]:.1f},{y0 + 14 * scale:.1f} '
                f'{max(xs) + 6:.1f},{p["lf"][1] - 2:.1f}" {g}/>']
    if pose == "baby_bath":
        return [f'<path d="M{min(xs) - 14:.1f},{p["neck"][1] + 4:.1f} L{min(xs) - 10:.1f},{y0 + 4:.1f} '
                f'L{max(xs) + 10:.1f},{y0 + 4:.1f} L{max(xs) + 14:.1f},{p["neck"][1] + 4:.1f} Z" '
                f'fill="#dbeafe" stroke="#60a5fa" stroke-width="2" vector-effect="non-scaling-stroke"/>']
    return []


def _wrap(text: str, n: int) -> list[str]:
    text = text or ""
    return [text[i:i + n] for i in range(0, len(text), n)] or [""]


def render_shot(shot: dict, aspect: str = "16:9", width: int | None = None) -> str:
    W, H = _frame_dims(aspect)
    width = width or (360 if W > H else 240)
    ground = H - 18
    cam = shot.get("camera", "tripod")
    size = shot.get("size", "medium")
    figures = shot.get("figures", []) or []
    adult_scale = 0.9 if aspect == "16:9" else 1.1
    baby_scale = 1.6 if aspect == "16:9" else 1.9

    world: list[str] = [f'<rect x="0" y="0" width="{W}" height="{H}" fill="#fafaf7"/>',
                        f'<line x1="0" y1="{ground}" x2="{W}" y2="{ground}" stroke="#ccc" stroke-width="1.5" '
                        f'vector-effect="non-scaling-stroke"/>']
    bboxes: list[tuple[float, float, float, float, tuple[float, float]]] = []
    holder_exists = any(f.get("pose") in HOLDING for f in figures if f.get("who") != "baby")

    for f in figures:
        who, pose = f.get("who", "me"), f.get("pose", "stand")
        ox = f.get("x", 0.5) * W
        mirror = f.get("facing") == "left" or (f.get("facing") is None and f.get("x", 0.5) > 0.6)
        color = COLORS.get(who, "#333")
        if who == "baby":
            if pose == "baby_held" and holder_exists:
                continue
            base = BABY.get(pose) or BABY["baby_lie_back"]
            if cam == "pov" and pose == "baby_held":
                base = BABY["baby_lie_back"]
            sc = baby_scale * (1.5 if cam == "pov" else 1.0)
            oy = ground - (40 if cam == "pov" else 2)
            p = _transform(base, ox, oy, sc, mirror)
            world += _baby_props(pose, p, sc)
            world += _skeleton(p, color, 8 * sc, closed_eyes=(pose == "baby_sleep"), facing=-1 if mirror else 1)
        else:
            base = ADULT.get(pose, ADULT["stand"])
            p = _transform(base, ox, ground, adult_scale, mirror)
            world += _props_for(pose, p, adult_scale, mirror)
            world += _skeleton(p, color, 13 * adult_scale, facing=-1 if mirror else 1)
            if pose in HOLDING:
                cx = (p["lh"][0] + p["rh"][0]) / 2
                cy = (p["lh"][1] + p["rh"][1]) / 2 - 4
                world += _held_baby(cx, cy, adult_scale * 1.2, mirror)
        xs = [x for x, _ in p.values()]
        ys = [y for _, y in p.values()]
        hr = (8 * (baby_scale if who == "baby" else 1)) if who == "baby" else 13 * adult_scale
        bboxes.append((min(xs) - hr, min(ys) - hr, max(xs) + hr, max(ys) + 2, p["head"]))
        if size in ("wide", "medium"):
            world.append(f'<text x="{ox:.1f}" y="{ground + 13}" font-size="10" text-anchor="middle" '
                         f'fill="{color}">{escape(WHO_CN.get(who, who))}</text>')

    if cam == "pov":
        hands = shot.get("pov_hands") or "双手"
        for sx, ex in ((0.18, 0.38), (0.82, 0.62)):
            world.append(f'<line x1="{W * sx:.1f}" y1="{H + 5}" x2="{W * ex:.1f}" y2="{H * 0.74:.1f}" '
                         f'stroke="#1f6feb" stroke-width="10" stroke-linecap="round" opacity="0.55"/>')
            world.append(f'<circle cx="{W * ex:.1f}" cy="{H * 0.72:.1f}" r="9" fill="#fff" stroke="#1f6feb" '
                         f'stroke-width="3" opacity="0.8"/>')
        world.append(f'<text x="{W / 2:.1f}" y="{H - 6}" font-size="9" text-anchor="middle" fill="#1f6feb">'
                     f'我的手：{escape(hands[:20])}</text>')

    # ---- camera window (shot size crop) ----
    vx, vy, vw, vh = 0.0, 0.0, float(W), float(H)
    if bboxes and size != "wide" and cam != "pov":
        primary_is_baby = (figures[0].get("who") == "baby") if figures else False
        if size == "medium":
            # medium keeps everyone in frame (union), framed waist-up for adults
            x0 = min(b[0] for b in bboxes); y0 = min(b[1] for b in bboxes)
            x1 = max(b[2] for b in bboxes); y1 = max(b[3] for b in bboxes)
            hx, hy = bboxes[0][4]
        else:
            x0, y0, x1, y1, (hx, hy) = bboxes[0]
        ext = max(y1 - y0, (x1 - x0) * H / W)
        if primary_is_baby:
            frac = {"medium": 2.0, "close": 1.15, "extreme_close": 0.6}[size]
        else:
            frac = {"medium": 0.85, "close": 0.45, "extreme_close": 0.22}[size]
        if size == "medium" and len(bboxes) > 1:
            frac = max(frac, 1.05)
        if H > W:  # portrait frame is narrow: open close-ups up so shoulders/arms stay in
            frac *= 1.6 if size in ("close", "extreme_close") else (1.0 if len(bboxes) > 1 else 0.85)
        vh = min(max(ext * frac, 28.0), float(H))
        vw = vh * W / H
        if vw < (x1 - x0) * 1.08 and size == "medium" and (len(bboxes) > 1 or W > H):
            vw = min((x1 - x0) * 1.08, float(W)); vh = vw * H / W
        holding = figures and figures[0].get("pose") in HOLDING
        if size == "medium" or primary_is_baby:
            cx, cy = (x0 + x1) / 2, (y0 + vh / 2 - 4) if not primary_is_baby else (y0 + y1) / 2
        elif holding:  # keep both faces: between adult head and the baby in arms
            cx, cy = hx, hy + vh * 0.3
        else:
            cx, cy = hx, hy + vh * 0.12
        vx = min(max(cx - vw / 2, 0), W - vw)
        vy = min(max(cy - vh / 2, 0), H - vh)

    loc = shot.get("location", "")
    if loc:
        world.append(f'<text x="{vx + 6:.1f}" y="{vy + 12 * vh / H:.1f}" font-size="{10 * vh / H:.1f}" '
                     f'fill="#999">📍{escape(loc)}</text>')

    fh = width * H / W
    cap_lines: list[tuple[str, str, str]] = []
    cpl = max(int(width / 13), 12)
    for t in _wrap(f"动作：{shot.get('action', '')}", cpl):
        cap_lines.append((t, "#222", "normal"))
    if shot.get("line"):
        for t in _wrap(f"台词：「{shot['line']}」", cpl):
            cap_lines.append((t, "#1f6feb", "normal"))
    if shot.get("capture"):
        cap_lines.append(("🎯 捕捉镜头：长录，等宝宝自然反应", "#e8590c", "normal"))
    if shot.get("notes"):
        for t in _wrap(f"备注：{shot['notes']}", cpl):
            cap_lines.append((t, "#666", "normal"))
    h1 = f'{escape(shot.get("shot_id", ""))} · {CAM_CN.get(cam, cam)}'
    h2 = f'{SIZE_CN.get(size, size)} · {shot.get("duration_s", "?")}s · 转场:{escape(str(shot.get("transition", "cut")))}'
    heads = [h1 + " · " + h2] if width >= 330 else [h1, h2]
    hh = 17 * (len(heads) - 1)
    cap_h = 30 + hh + 17 * len(cap_lines)
    total_h = fh + cap_h
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{total_h:.0f}" '
           f'viewBox="0 0 {width} {total_h:.0f}" font-family="PingFang SC, Microsoft YaHei, sans-serif">',
           f'<svg x="0" y="0" width="{width}" height="{fh:.1f}" viewBox="{vx:.1f} {vy:.1f} {vw:.1f} {vh:.1f}" '
           f'preserveAspectRatio="xMidYMid slice">', *world, "</svg>",
           f'<rect x="0.5" y="0.5" width="{width - 1}" height="{fh - 1:.1f}" fill="none" stroke="#222" '
           f'stroke-width="2"/>',
           *[f'<text x="6" y="{fh + 19 + k * 17:.1f}" font-size="13" font-weight="bold" fill="#111">{h}</text>'
             for k, h in enumerate(heads)]]
    for i, (t, color, _) in enumerate(cap_lines):
        svg.append(f'<text x="6" y="{fh + 38 + hh + i * 17:.1f}" font-size="12.5" fill="{color}">'
                   f'{escape(t)}</text>')
    svg.append("</svg>")
    return "\n".join(svg)


def render_board(shots: list[dict], aspect: str = "16:9") -> list[dict]:
    return [{"shot_id": s.get("shot_id"), "svg": render_shot(s, aspect)} for s in shots]
