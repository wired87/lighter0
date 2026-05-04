import numpy as np
from PIL import Image, ImageFilter
import plotly.graph_objects as go
import svgwrite
import os
import time
import numpy as np
import svgwrite
import json
import xml.etree.ElementTree as ET
import re
import cv2

HAS_CV = True


def log(stage, t0):
    print(f"[{stage}] done in {time.time()-t0:.3f}s")


def svg_to_energy_map(svg_path):
    tree = ET.parse(svg_path)
    root = tree.getroot()

    energy_map = {}

    def parse_color(color_str, opacity=1.0):
        if color_str is None:
            return 0.0

        color_str = color_str.lower()

        if color_str == "white":
            base = 1.0
        elif color_str == "black":
            base = 0.0
        elif color_str.startswith("#"):
            # hex → grayscale
            r = int(color_str[1:3], 16)
            g = int(color_str[3:5], 16)
            b = int(color_str[5:7], 16)
            base = (r + g + b) / (3 * 255)
        else:
            base = 0.0

        return base * opacity

    # iterate SVG elements
    for elem in root.iter():
        tag = elem.tag.split("}")[-1]

        if tag == "rect":
            x = int(float(elem.attrib.get("x", 0)))
            y = int(float(elem.attrib.get("y", 0)))

            fill = elem.attrib.get("fill", "black")
            opacity = float(elem.attrib.get("opacity", 1.0))

            energy = parse_color(fill, opacity)

            energy_map[(x, y)] = energy

        elif tag == "polyline" or tag == "polygon":
            points_str = elem.attrib.get("points", "")
            fill = elem.attrib.get("fill", "white")
            opacity = float(elem.attrib.get("opacity", 1.0))

            energy = parse_color(fill, opacity)

            pts = re.findall(r"(\d+),(\d+)", points_str)

            for px, py in pts:
                x = int(px)
                y = int(py)
                energy_map[(x, y)] = energy

    return energy_map



def generate_animated_svg(arr, black_threshold=40, out="animated.svg"):
    t0 = time.time()

    h, w = arr.shape
    cx, cy = w // 2, h // 2

    xs = np.arange(w)
    ys = np.arange(h)
    X, Y = np.meshgrid(xs, ys)

    # distance layers
    dist = np.maximum(np.abs(X - cx), np.abs(Y - cy))
    max_d = int(dist.max())

    dwg = svgwrite.Drawing(out, size=(f"{w}px", f"{h}px"))
    dwg.attribs['shape-rendering'] = 'crispEdges'

    # optional: reduce frames (huge speedup)
    step = max(1, max_d // 120)   # ~120 frames max

    total_shapes = 0

    for t in range(0, max_d + 1, step):
        group = dwg.g(id=f"layer_{t}", visibility="hidden")

        # mask for this layer
        mask = (dist == t)

        ys_t, xs_t = np.where(mask)

        if len(xs_t) == 0:
            continue

        # 🔥 convert once (fix crash)
        xs_t = xs_t.astype(int)
        ys_t = ys_t.astype(int)

        # filter visible pixels only
        vals = arr[ys_t, xs_t]
        valid = vals > black_threshold

        xs_t = xs_t[valid]
        ys_t = ys_t[valid]
        vals = vals[valid].astype(float)

        if len(xs_t) == 0:
            continue

        # -------------------------
        # FAST DRAW (reduced density)
        # -------------------------
        # skip pixels for speed (important!)
        skip = max(1, len(xs_t) // 5000)

        for i in range(0, len(xs_t), skip):
            x = int(xs_t[i])
            y = int(ys_t[i])
            v = vals[i]

            group.add(dwg.rect(
                insert=(x, y),
                size=(1, 1),
                fill="white",
                opacity=v / 255.0
            ))

        total_shapes += len(xs_t) // skip

        # animation
        group.add(dwg.animate(
            attributeName="visibility",
            values="hidden;visible",
            dur="0.08s",
            begin=f"{t * 0.02}s",
            fill="freeze"
        ))

        dwg.add(group)

    dwg.save()

    print(f"[ANIM_SVG] done in {time.time()-t0:.2f}s")
    print(f"[ANIM_SVG] shapes ~ {total_shapes}")






def generate_animated_svg_with_energy(
    arr,
    black_threshold=40,
    out_animation="animated.svg",
    out_brain="brainmaster.json"
):
    t0 = time.time()

    h, w = arr.shape
    cx, cy = w // 2, h // 2

    xs = np.arange(w)
    ys = np.arange(h)
    X, Y = np.meshgrid(xs, ys)

    # distance field
    dist = np.maximum(np.abs(X - cx), np.abs(Y - cy))
    max_d = int(dist.max())

    dwg = svgwrite.Drawing(out_animation, size=(f"{w}px", f"{h}px"))
    dwg.attribs['shape-rendering'] = 'crispEdges'

    # -------------------------
    # ENERGY MAP INIT
    # -------------------------
    energy_dict = {}

    # normalize energy (0-1)
    arr_norm = arr.astype(float) / 255.0

    step = max(1, max_d // 120)

    for t in range(0, max_d + 1, step):
        group = dwg.g(id=f"layer_{t}", visibility="hidden")

        mask = (dist == t)
        ys_t, xs_t = np.where(mask)

        if len(xs_t) == 0:
            continue

        xs_t = xs_t.astype(int)
        ys_t = ys_t.astype(int)

        vals = arr_norm[ys_t, xs_t]
        valid = vals > (black_threshold / 255.0)

        xs_t = xs_t[valid]
        ys_t = ys_t[valid]
        vals = vals[valid]

        if len(xs_t) == 0:
            continue

        # reduce density
        skip = max(1, len(xs_t) // 5000)

        for i in range(0, len(xs_t), skip):
            x = int(xs_t[i])
            y = int(ys_t[i])
            e = float(vals[i])

            # -------------------------
            # SVG DRAW
            # -------------------------
            group.add(dwg.rect(
                insert=(x, y),
                size=(1, 1),
                fill="white",
                opacity=e
            ))

            # -------------------------
            # ENERGY TRACKING
            # -------------------------
            key = (x, y)

            if key not in energy_dict:
                energy_dict[key] = [[], []]

            energy_dict[key][0].append(int(t))   # time
            energy_dict[key][1].append(e)        # energy

        group.add(dwg.animate(
            attributeName="visibility",
            values="hidden;visible",
            dur="0.08s",
            begin=f"{t * 0.02}s",
            fill="freeze"
        ))

        dwg.add(group)

    dwg.save()

    # -------------------------
    # JSON EXPORT
    # -------------------------
    brainmaster = []

    for (x, y), (times, energies) in energy_dict.items():
        brainmaster.append((
            (int(x), int(y)),
            [times, energies]
        ))

    with open(out_brain, "w") as f:
        json.dump(brainmaster, f)

    print(f"[ANIM] done in {time.time()-t0:.2f}s")
    print(f"[ANIM] nodes={len(brainmaster)}")

def process_image(
    out_dir,
    path,
    out_html="out.html",
    out_svg="out.svg",
    out_stl="out.stl",
    out_animation="animated.svg",
    out_brain="brainmaster.json",
    target_res=4096,
    mesh_res=512,
    height_scale=20.0,
    white_threshold=220,
    black_threshold=40
):
    t_total = time.time()

    out_html = os.path.join(out_dir, out_html)
    out_svg = os.path.join(out_dir, out_svg)
    out_stl = os.path.join(out_dir, out_stl)
    out_brain = os.path.join(out_dir, out_brain)
    out_animation = os.path.join(out_dir, out_animation)

    # -------------------------
    # 1. LOAD
    # -------------------------
    t0 = time.time()

    if path and os.path.exists(path):
        img = Image.open(path).convert("L")
        print("[LOAD] using input image")
    else:
        print("[LOAD] using fallback")
        x = np.linspace(-1, 1, mesh_res)
        y = np.linspace(-1, 1, mesh_res)
        xx, yy = np.meshgrid(x, y)
        img_arr = np.exp(-(xx**2 + yy**2) * 5) * 255
        img = Image.fromarray(img_arr.astype(np.uint8))

    img_hr = img.resize((target_res, target_res), Image.LANCZOS)
    img = img.resize((mesh_res, mesh_res), Image.LANCZOS)
    img = img.filter(ImageFilter.GaussianBlur(1.0))

    arr = np.array(img)
    arr_hr = np.array(img_hr)

    log("LOAD", t0)

    # -------------------------
    # 2. EDGE DETECTION
    # -------------------------
    t0 = time.time()

    if HAS_CV:
        edges = cv2.Canny(arr, 80, 160)
        mask = edges > 0
        print("[EDGE] OpenCV used")
    else:
        mask = arr > black_threshold
        print("[EDGE] fallback threshold")

    log("EDGE", t0)

    # -------------------------
    # 3. HEIGHTMAP
    # -------------------------
    t0 = time.time()

    h = arr.astype(np.float32) / 255.0
    h[arr > white_threshold] = 1.0
    h = h * mask
    h = h * height_scale

    h = (h +
         np.roll(h, 1, 0) + np.roll(h, -1, 0) +
         np.roll(h, 1, 1) + np.roll(h, -1, 1)) / 5.0

    log("HEIGHTMAP", t0)

    # -------------------------
    # 4. MESH
    # -------------------------
    t0 = time.time()

    size = mesh_res
    X, Y = np.meshgrid(np.arange(size), np.arange(size))
    Z = h

    vertices = np.column_stack((X.flatten(), Y.flatten(), Z.flatten()))

    faces = []
    for i in range(size - 1):
        for j in range(size - 1):
            if Z[i, j] == 0:
                continue

            v0 = i * size + j
            v1 = (i + 1) * size + j
            v2 = i * size + (j + 1)
            v3 = (i + 1) * size + (j + 1)

            faces.append([v0, v1, v2])
            faces.append([v1, v3, v2])

    faces = np.array(faces)

    log("MESH", t0)
    print(f"[MESH] vertices={len(vertices)} faces={len(faces)}")

    # -------------------------
    # 5. INTERACTIVE 3D
    # -------------------------
    t0 = time.time()

    fig = go.Figure(data=[
        go.Mesh3d(
            x=vertices[:, 0],
            y=vertices[:, 1],
            z=vertices[:, 2],
            i=faces[:, 0],
            j=faces[:, 1],
            k=faces[:, 2],
            intensity=vertices[:, 2],
            colorscale="Gray",
            opacity=1.0
        )
    ])

    fig.update_layout(scene=dict(
        xaxis_visible=False,
        yaxis_visible=False,
        zaxis_visible=False
    ))

    fig.write_html(out_html)

    log("HTML", t0)

    # -------------------------
    # 6. FAST SVG (FIXED)
    # -------------------------
    t0 = time.time()

    if HAS_CV:
        step = max(1, target_res // 2048)
        img_svg = arr_hr[::step, ::step].astype(np.uint8)

        # EDGE BASED (nicht threshold!)
        edges = cv2.Canny(img_svg, 80, 160)

        # ALLE Konturen holen
        contours, _ = cv2.findContours(
            edges,
            cv2.RETR_LIST,  # ← wichtig!
            cv2.CHAIN_APPROX_SIMPLE
        )

        h_svg, w_svg = img_svg.shape
        dwg = svgwrite.Drawing(out_svg, size=(f"{w_svg}px", f"{h_svg}px"))
        dwg.attribs['shape-rendering'] = 'crispEdges'

        kept = 0

        for cnt in contours:
            if len(cnt) < 10:  # filter noise
                continue

            pts = [(int(p[0][0]), int(p[0][1])) for p in cnt]

            # LINES statt filled polygons → sichtbar!
            dwg.add(dwg.polyline(
                points=pts,
                stroke="white",
                fill="none",
                stroke_width=1
            ))

            kept += 1

        print(f"[SVG] contours_kept={kept}")

    else:
        print("[SVG] fallback skipped (no cv2)")

    dwg.save()
    log("SVG", t0)

    # scale etry over time
    generate_animated_svg_with_energy(
        arr,
        out_animation=out_animation,
        out_brain=out_brain,
    )


    # -------------------------
    # 7. STL
    # -------------------------
    t0 = time.time()

    try:
        import trimesh

        mesh = trimesh.Trimesh(vertices=vertices, faces=faces)
        mesh.remove_degenerate_faces()
        mesh.remove_unreferenced_vertices()
        mesh.fill_holes()

        mesh.export(out_stl)
        stl_status = "ok"
    except Exception as e:
        stl_status = str(e)

    log("STL", t0)

    print(f"[TOTAL] {time.time()-t_total:.3f}s")

    return {
        "html": out_html,
        "svg": out_svg,
        "stl": out_stl,
        "stl_status": stl_status,
        "vertices": len(vertices),
        "faces": len(faces)
    }


if __name__ == "__main__":
    res = process_image(
        out_dir=os.path.join("output", "test"),
        path="output/ce5c9acd-55bb-4d65-9f0f-7a58eee033d5/img.jpg")
    print(res)




"""


def generate_animated_svg(arr, black_threshold=40, out="animated.svg"):


    t0 = time.time()

    h, w = arr.shape
    cx, cy = w // 2, h // 2

    xs = np.arange(w)
    ys = np.arange(h)
    X, Y = np.meshgrid(xs, ys)

    # distance layers
    dist = np.maximum(np.abs(X - cx), np.abs(Y - cy))
    max_d = int(dist.max())

    dwg = svgwrite.Drawing(out, size=(f"{w}px", f"{h}px"))
    dwg.attribs['shape-rendering'] = 'crispEdges'

    # optional: reduce frames (huge speedup)
    step = max(1, max_d // 120)   # ~120 frames max

    total_shapes = 0

    for t in range(0, max_d + 1, step):
        group = dwg.g(id=f"layer_{t}", visibility="hidden")

        # mask for this layer
        mask = (dist == t)

        ys_t, xs_t = np.where(mask)

        if len(xs_t) == 0:
            continue

        # 🔥 convert once (fix crash)
        xs_t = xs_t.astype(int)
        ys_t = ys_t.astype(int)

        # filter visible pixels only
        vals = arr[ys_t, xs_t]
        valid = vals > black_threshold

        xs_t = xs_t[valid]
        ys_t = ys_t[valid]
        vals = vals[valid].astype(float)

        if len(xs_t) == 0:
            continue

        # -------------------------
        # FAST DRAW (reduced density)
        # -------------------------
        # skip pixels for speed (important!)
        skip = max(1, len(xs_t) // 5000)

        for i in range(0, len(xs_t), skip):
            x = int(xs_t[i])
            y = int(ys_t[i])
            v = vals[i]

            group.add(dwg.rect(
                insert=(x, y),
                size=(1, 1),
                fill="white",
                opacity=v / 255.0
            ))

        total_shapes += len(xs_t) // skip

        # animation
        group.add(dwg.animate(
            attributeName="visibility",
            values="hidden;visible",
            dur="0.08s",
            begin=f"{t * 0.02}s",
            fill="freeze"
        ))

        dwg.add(group)

    dwg.save()

    print(f"[ANIM_SVG] done in {time.time()-t0:.2f}s")
    print(f"[ANIM_SVG] shapes ~ {total_shapes}")



"""

