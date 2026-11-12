"""棋盘识别：在一张野狐窗口截图里找棋盘、拟合 19 路网格、读出每一点是黑是白是空。

思路（没有任何"必须是木色"的假设，野狐换皮肤也能用）：
1. 以窗口中心的**众数颜色**当棋盘底色种子，找出最大的一块同色矩形 —— 那就是棋盘。
2. 棋盘上有等距的网格线。把"比底色暗"的程度沿 x / y 投影，
   (x0, 格宽) 二维扫描，让 19 条线上的暗度总和最大 —— 得到精确网格。
3. 每个交叉点取一个小方块的平均亮度：明显暗 = 黑子，明显亮 = 白子，接近底色 = 空。
"""

import numpy as np
import cv2


# 结果容器
class BoardReading:
    __slots__ = ("stones", "grid", "rect", "quality", "bg_color", "note")

    def __init__(self, stones, grid, rect, quality, bg_color, note=""):
        self.stones = stones      # n x n，0 空 / 1 黑 / 2 白
        self.grid = grid          # (x0, y0, step) 交叉点坐标，含整窗截图里的像素位置
        self.rect = rect          # 棋盘底色矩形的 (x, y, w, h)
        self.quality = quality    # 0~1，越大越可信
        self.bg_color = bg_color  # 底色 BGR
        self.note = note

    def __repr__(self):
        return f"<BoardReading quality={self.quality:.2f} {self.note}>"


def _to_gray(img):
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)


def _dominant_color(patch, bins=16):
    """量化后取众数颜色（比中位数稳：棋盘中心常常正好压着一颗子）。"""
    q = (patch.reshape(-1, 3) // (256 // bins)).astype(np.int32)
    key = q[:, 0] * bins * bins + q[:, 1] * bins + q[:, 2]
    vals, counts = np.unique(key, return_counts=True)
    k = vals[np.argmax(counts)]
    sel = q[key == k]
    # 用该桶内真实像素的均值，避免量化误差
    mask = key == k
    real = patch.reshape(-1, 3)[mask]
    return real.mean(axis=0)


def _candidate_seeds(small):
    """给几个"像棋盘底色"的候选种子。

    只用中心众数是不够的：残局时棋盘中心常常压着棋子，
    众数就变成了黑/白，整块棋盘反而被漏掉。
    """
    sh, sw = small.shape[:2]
    seeds = []

    # 1) 中心区域众数
    cw0, cw1 = int(sw * 0.30), int(sw * 0.70)
    ch0, ch1 = int(sh * 0.25), int(sh * 0.75)
    seeds.append(_dominant_color(small[ch0:ch1, cw0:cw1]))

    # 2) 四角区域众数（棋盘四角基本不会有子）
    for fx0, fx1, fy0, fy1 in (
        (0.04, 0.20, 0.04, 0.16),
        (0.80, 0.96, 0.04, 0.16),
        (0.04, 0.20, 0.84, 0.96),
        (0.80, 0.96, 0.84, 0.96),
    ):
        patch = small[int(sh * fy0):int(sh * fy1), int(sw * fx0):int(sw * fx1)]
        if patch.size > 64:
            seeds.append(_dominant_color(patch))

    # 3) 整图出现最多的几种量化色（去掉过黑/过白的纯色）
    q = (small.reshape(-1, 3) // 16).astype(np.int32)
    key = q[:, 0] * 256 + q[:, 1] * 16 + q[:, 2]
    vals, counts = np.unique(key, return_counts=True)
    order = np.argsort(-counts)[:12]
    flat = small.reshape(-1, 3)
    for k in order:
        v = vals[k]
        sel = key == v
        mean = flat[sel].mean(axis=0)
        if mean.max() < 45 or mean.min() > 245:
            continue  # 太黑/太白，当棋盘底色的可能性低
        seeds.append(mean)

    # 去重
    uniq = []
    for s in seeds:
        s = np.asarray(s, dtype=np.float32)
        if not any(float(np.abs(s - u).max()) < 12 for u in uniq):
            uniq.append(s)
    return uniq[:8]


def _rects_from_mask(mask, sw, sh, min_frac=0.24):
    # 闭运算要够大，才能把棋子挖的洞填回去（棋子直径约图宽的 3%），
    # 否则残局时木色被棋子切成碎片，整块棋盘反而认不出来
    k = max(9, int(sw * 0.035)) | 1
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    out = []
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if bw < sw * min_frac or bh < sh * min_frac:
            continue
        if not (0.80 < bw / max(bh, 1) < 1.25):
            continue
        fill = area / float(bw * bh)
        if fill < 0.60:
            continue
        out.append((area * fill, x, y, bw, bh))
    out.sort(reverse=True)
    return out


def find_board_rects(img, tol=60, limit=6):
    """找出若干候选棋盘矩形（原图坐标），按面积×填充率排序。"""
    h, w = img.shape[:2]
    scale = 1.0
    if w > 760:
        scale = 760.0 / w
        small = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    else:
        small = img
    sh, sw = small.shape[:2]
    small_i16 = small.astype(np.int16)

    rects = []
    for seed in _candidate_seeds(small):
        diff = np.abs(small_i16 - seed.astype(np.int16)).max(axis=2)
        mask = (diff < tol).astype(np.uint8)
        for _, x, y, bw, bh in _rects_from_mask(mask, sw, sh):
            r = (
                int(round(x / scale)),
                int(round(y / scale)),
                int(round(bw / scale)),
                int(round(bh / scale)),
            )
            # 和已有候选太像就跳过（同一块棋盘会被多个种子命中）
            if any(
                abs(r[0] - q[0]) < 12 and abs(r[1] - q[1]) < 12
                and abs(r[2] - q[2]) < 12
                for q in rects
            ):
                continue
            rects.append(r)
    return rects[:limit]


def _darkness_profile(gray, x0, x1, y0, y1):
    """返回 (每列暗度, 每行暗度)。暗度 = 低于局部底色的量，线会被凸显，棋子不会霸占整列。"""
    roi = gray[y0:y1, x0:x1]
    bg = float(np.median(roi))
    dark = np.clip(bg - roi, 0, None)
    # 用中位数压掉棋子那种大块暗区，让贯穿整列的细线胜出
    col = np.median(dark, axis=0)
    row = np.median(dark, axis=1)
    return col, row, bg


def _scan_grid(profile, n, p_lo, p_hi, p_steps, s_lo, s_hi, s_steps, tol=2):
    L = len(profile)
    if L < n * 2:
        return None
    # 把曲线"加宽"：每个位置取 ±tol 内的最大值。
    # 野狐的网格线只有 1~2px 宽，按单像素采样的话，相位差 1px 就整条丢掉，
    # 搜索会停在"看着也有分"的错误相位上 —— 实测能被拖偏差不多一整格。
    if tol > 0:
        padded = np.pad(profile, (tol, tol), mode="edge")
        wide = np.max(np.stack([padded[i:i + L] for i in range(2 * tol + 1)]), axis=0)
    else:
        wide = profile
    best = None
    for p in np.linspace(p_lo, p_hi, p_steps):
        span = p * (n - 1)
        if span >= L - 1:
            continue
        hi = min(L - 1 - span, s_hi)
        lo = max(0.0, s_lo)
        if hi <= lo:
            continue
        for s in np.linspace(lo, hi, s_steps):
            idx = np.rint(s + np.arange(n) * p).astype(np.int32)
            idx = np.clip(idx, 0, L - 1)
            sc = float(wide[idx].sum())
            if best is None or sc > best[2]:
                best = (float(s), float(p), sc)
    return best


def _board_ground_color(luma, sat, gx0, gy0, sx, sy, n, rect=None):
    """估计棋盘底色（亮度 + 饱和度）。

    用"格子中心"采样：那里离最近的棋子中心有半格，比棋子半径还远，
    所以不管盘上多少子，格子中心都是干净的底色。
    直接拿 361 个交叉点的中位数当底色是不行的 —— 残局时棋子占了大半，会把底色带跑偏。
    """
    cell = (sx + sy) / 2.0
    r = max(2, int(round(cell * 0.10)))
    H, W = luma.shape
    lim = None
    if rect:
        rx, ry, rw, rh = rect
        lim = (rx + 1, ry + 1, rx + rw - 1, ry + rh - 1)

    ls, ss = [], []
    for j in range(n - 1):
        for i in range(n - 1):
            px = int(round(gx0 + (i + 0.5) * sx))
            py = int(round(gy0 + (j + 0.5) * sy))
            y0p, y1p = py - r, py + r + 1
            x0p, x1p = px - r, px + r + 1
            if lim:
                x0p = max(x0p, lim[0])
                y0p = max(y0p, lim[1])
                x1p = min(x1p, lim[2])
                y1p = min(y1p, lim[3])
            y0p, x0p = max(0, y0p), max(0, x0p)
            y1p, x1p = min(H, y1p), min(W, x1p)
            if y1p <= y0p or x1p <= x0p:
                continue
            ls.append(float(np.median(luma[y0p:y1p, x0p:x1p])))
            ss.append(float(np.median(sat[y0p:y1p, x0p:x1p])))
    if not ls:
        return float("nan"), float("nan")
    return float(np.median(ls)), float(np.median(ss))


def _fit_period(profile, n, rough_p, p_tol=0.16, phase_steps=48):
    """一维拟合：找 x0 与 p，使 n 个等距位置的暗度和最大。

    粗搜（格宽 ±16%，容得下各种棋盘留白）→ 再用最优解附近细搜一遍。
    返回 (start, step, score)。
    """
    L = len(profile)
    if L < 10:
        return None
    best = _scan_grid(
        profile, n,
        rough_p * (1 - p_tol), rough_p * (1 + p_tol), 33,
        0.0, L, phase_steps,
    )
    if best is None:
        return None
    s0, p0, _ = best
    fine = _scan_grid(
        profile, n,
        p0 * 0.97, p0 * 1.03, 13,
        s0 - p0 * 0.6, s0 + p0 * 0.6, 25,
    )
    return fine if fine is not None else best


def _read_rect(img, rect, n=19):
    """在给定矩形里拟合网格并判黑白。失败返回 None。"""
    x, y, w, h = rect
    if w < 80 or h < 80:
        return None

    gray = _to_gray(img)
    # 内缩一点，避免把棋盘外框/阴影算进投影
    mx = int(w * 0.02)
    my = int(h * 0.02)
    ix0, iy0 = x + mx, y + my
    ix1, iy1 = x + w - mx, y + h - my
    if ix1 - ix0 < 60 or iy1 - iy0 < 60:
        return None

    col, row, _bg = _darkness_profile(gray, ix0, ix1, iy0, iy1)
    rough_px = w / (n + 0.55)   # 经验估计：外框比网格略宽一点
    rough_py = h / (n + 0.55)

    fx = _fit_period(col, n, rough_px)
    fy = _fit_period(row, n, rough_py)
    if fx is None or fy is None:
        return None
    sx0, spx, sxc = fx
    sy0, spy, syc = fy

    # 棋盘网格横竖格宽必须接近（真野狐的底图是 415x380，拉伸后能差到 9%，
    # 所以给 15% 的富裕；靠这个能挡掉"登录框按钮排成等距"这类假棋盘，那个差 36%）。
    if abs(spx - spy) / max(spx, spy) > 0.15:
        return None

    # 质量分：19 条线上的平均暗度，比"随便挑 19 个位置"高多少倍
    base_x = float(np.median(col))
    base_y = float(np.median(row))
    ratio_x = (sxc / n) / (base_x + 1.0)
    ratio_y = (syc / n) / (base_y + 1.0)
    if ratio_x < 4.0 or ratio_y < 4.0:
        return None  # 没有明显的等距网格线，不是棋盘
    quality = float(np.clip(min(ratio_x, ratio_y) / 8.0, 0, 1))

    gx0 = ix0 + sx0
    gy0 = iy0 + sy0

    stones = np.zeros((n, n), dtype=np.int8)
    cell = max(4.0, (spx + spy) / 2.0)

    # 环形采样：半径 0.18~0.34 格的一圈。
    # 为什么不用实心圆：子中心常有"最后一手"的小三角/圆点标记，
    # 实心采样会被它带偏；而环正好落在子面上、又躲开了网格线和星位。
    r_lo = cell * 0.18
    r_hi = cell * 0.34
    R = int(np.ceil(r_hi))
    rr = np.arange(-R, R + 1)
    YY, XX = np.meshgrid(rr, rr, indexing="ij")
    ring = (np.hypot(YY, XX) >= r_lo) & (np.hypot(YY, XX) <= r_hi)
    offs = np.argwhere(ring) - R          # 相对交叉点的偏移

    # 采样范围夹在"棋盘矩形"和"网格外沿 ±0.35 格"之间。
    # 前者防棋盘外的东西（坐标字/白底），后者防矩形被闭运算外扩后把棋盘外的同色区域算进来。
    pad = int(round(cell * 0.35))
    gx_lo = max(x + 2, int(round(gx0)) - pad)
    gx_hi = min(x + w - 2, int(round(gx0 + (n - 1) * spx)) + pad)
    gy_lo = max(y + 2, int(round(gy0)) - pad)
    gy_hi = min(y + h - 2, int(round(gy0 + (n - 1) * spy)) + pad)
    gx_hi = max(gx_hi, gx_lo + 1)
    gy_hi = max(gy_hi, gy_lo + 1)

    luma = gray
    # 只看亮度不够：野狐的木纹底很亮（灰度 226 左右），白子才 244，差 8%，
    # 纯亮度阈值会把白子当成空点。补上饱和度：木纹有颜色（S≈0.3），白子是中性灰（S≈0）。
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    sat = hsv[:, :, 1].astype(np.float32) / 255.0
    samples = np.zeros((n, n), dtype=np.float32)
    sats = np.zeros((n, n), dtype=np.float32)
    for j in range(n):
        py = int(round(gy0 + j * spy))
        for i in range(n):
            px = int(round(gx0 + i * spx))
            # 越界的采样点夹回来，不往外抓（棋盘外可能是白底/坐标字）
            ys = np.clip(py + offs[:, 0], gy_lo, gy_hi)
            xs = np.clip(px + offs[:, 1], gx_lo, gx_hi)
            samples[j, i] = float(luma[ys, xs].mean())
            sats[j, i] = float(sat[ys, xs].mean())

    bg_level, bg_sat = _board_ground_color(luma, sat, gx0, gy0, spx, spy, n, rect=(x, y, w, h))
    if not np.isfinite(bg_level) or bg_level <= 1:
        return None

    # 判黑白分两路，看棋盘底色本身有没有颜色：
    #  - 彩色底（木纹/黄/绿，S 高）：白子是中性灰，靠饱和度认，亮度完全不可靠
    #    （实测野狐木纹 luma 201，白子 204，差 1.6%，只靠亮度必错）
    #  - 中性底（黑/灰棋盘，S 低）：白子靠"更亮"认
    black_cut = bg_level * 0.62
    stones[samples < black_cut] = 1
    if bg_sat > 0.15:
        neutral_cut = bg_sat * 0.55
        white_mask = (sats < neutral_cut) | (samples > bg_level * 1.12)
    else:
        white_mask = samples > bg_level * 1.12
    stones[white_mask] = 2
    stones[samples < black_cut] = 1   # 黑子优先级最高，别被白判据抢走

    note = f"rect={x},{y},{w}x{h} step=({spx:.1f},{spy:.1f}) line/random=({ratio_x:.1f},{ratio_y:.1f})"
    return BoardReading(
        stones=stones,
        grid=(float(gx0), float(gy0), float(spx), float(spy)),
        rect=(x, y, w, h),
        quality=quality,
        bg_color=None,
        note=note,
    )


def read_board(img, n=19, tol=60, manual_rect=None, hint_rect=None):
    """读一张整窗截图。返回 BoardReading；找不到棋盘返回 None。

    manual_rect: 用户手填的棋盘矩形（最高优先级）
    hint_rect:   上一次成功识别的矩形，棋盘位置通常不变，满盘时靠它兜底
    """
    if img is None or img.size == 0:
        return None

    cands = []
    for r in (manual_rect, hint_rect):
        if r:
            r = tuple(int(v) for v in r)
            if r not in cands:
                cands.append(r)
    for r in find_board_rects(img, tol=tol):
        if r not in cands:
            cands.append(r)

    best = None
    for rect in cands:
        reading = _read_rect(img, rect, n=n)
        if reading is None:
            continue
        if best is None or reading.quality > best.quality:
            best = reading
    return best


def debug_draw(img, reading, path):
    """把识别结果画在截图上，用于肉眼校验（tools/selftest.py 会调用）。"""
    vis = img.copy()
    if reading is None:
        cv2.imwrite(path, vis)
        return
    n = reading.stones.shape[0]
    x0, y0, sx, sy = reading.grid
    for j in range(n):
        for i in range(n):
            px = int(round(x0 + i * sx))
            py = int(round(y0 + j * sy))
            v = reading.stones[j, i]
            if v == 1:
                cv2.circle(vis, (px, py), 3, (0, 0, 255), -1)
            elif v == 2:
                cv2.circle(vis, (px, py), 3, (0, 255, 255), -1)
            else:
                cv2.circle(vis, (px, py), 1, (255, 255, 0), -1)
    cv2.rectangle(
        vis,
        (reading.rect[0], reading.rect[1]),
        (reading.rect[0] + reading.rect[2], reading.rect[1] + reading.rect[3]),
        (0, 255, 0),
        2,
    )
    cv2.imwrite(path, vis)
