"""野狐窗口：定位、几何、截图。

野狐是自绘界面（UIPlus.dll），没有可读的控件树，
所以只能整窗截图，再在像素上找棋盘。
"""

import ctypes
import ctypes.wintypes as wt
import os

import numpy as np

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
gdi32 = ctypes.windll.gdi32

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PW_RENDERFULLCONTENT = 2


# --------------------------------------------------------------------------
# DPI：必须最先调用，否则所有坐标都是被 Windows 缩放过的"逻辑像素"，
# 截图的物理像素和窗口矩形对不上，画出来的点会整体偏移。
# --------------------------------------------------------------------------
def enable_dpi_awareness():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_AWARE
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


def dpi_scale():
    """当前主屏缩放比（125% -> 1.25）。"""
    dc = user32.GetDC(0)
    try:
        return gdi32.GetDeviceCaps(dc, 88) / 96.0  # LOGPIXELSX
    finally:
        user32.ReleaseDC(0, dc)


# --------------------------------------------------------------------------
# 窗口
# --------------------------------------------------------------------------
def _window_title(hwnd):
    n = user32.GetWindowTextLengthW(hwnd)
    if n <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def _process_name(hwnd):
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wt.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value)
    finally:
        kernel32.CloseHandle(h)
    return ""


def get_rect(hwnd):
    r = wt.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(r)):
        return None
    return (r.left, r.top, r.right, r.bottom)


def client_origin(hwnd):
    """客户区左上角在屏幕上的位置。"""
    p = wt.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(p))
    return (p.x, p.y)


def is_minimized(hwnd):
    return bool(user32.IsIconic(hwnd))


def foreground_hwnd():
    """前台窗口的顶层窗口。

    用户点在野狐的某个子控件/浮动窗口上时，GetForegroundWindow 可能返回子窗口，
    所以统一往上取根窗口再比，不然覆盖层会莫名其妙地闪一下没了。
    """
    fg = user32.GetForegroundWindow()
    if not fg:
        return 0
    root = user32.GetAncestor(fg, 2)  # GA_ROOT
    return root or fg


def window_alive(hwnd):
    """窗口还在不在（用户可能把野狐关了）。"""
    if not hwnd:
        return False
    try:
        return bool(user32.IsWindow(int(hwnd)))
    except Exception:
        return False


def find_window(cfg):
    """找野狐主窗口：进程名匹配，取面积最大的可见窗口。"""
    proc_want = cfg["window_process"].lower()
    keywords = [k.lower() for k in cfg["window_title_keywords"]]
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def _cb(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd) or is_minimized(hwnd):
            return True
        title = _window_title(hwnd)
        proc = _process_name(hwnd).lower()
        ok = (proc_want and proc == proc_want) or any(
            k in title.lower() for k in keywords if k
        )
        if not ok:
            return True
        rect = get_rect(hwnd)
        if not rect:
            return True
        w, h = rect[2] - rect[0], rect[3] - rect[1]
        if w < 320 or h < 320:
            return True
        found.append((w * h, hwnd, title, proc))
        return True

    user32.EnumWindows(_cb, 0)
    if not found:
        return None
    found.sort(reverse=True)
    return found[0][1]


# --------------------------------------------------------------------------
# 截图
# --------------------------------------------------------------------------
def _capture_printwindow(hwnd, w, h):
    """PrintWindow：直接从窗口渲染，抓得到被遮住/失焦的窗口，也不会把覆盖层截进去。"""
    import win32gui  # 延迟导入，pywin32 缺失时只是少一条路径
    import win32ui

    hwnd_dc = win32gui.GetWindowDC(hwnd)
    mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
    mem_dc = mfc_dc.CreateCompatibleDC()
    bitmap = win32ui.CreateBitmap()
    bitmap.CreateCompatibleBitmap(mfc_dc, w, h)
    mem_dc.SelectObject(bitmap)
    try:
        ok = user32.PrintWindow(hwnd, mem_dc.GetSafeHdc(), PW_RENDERFULLCONTENT)
        bits = bitmap.GetBitmapBits(True)
        arr = np.frombuffer(bits, dtype=np.uint8).reshape(h, w, 4)
        img = arr[:, :, :3].copy()  # BGRA -> BGR
        return img if ok else None
    finally:
        try:
            mem_dc.DeleteDC()
            mfc_dc.DeleteDC()
            win32gui.ReleaseDC(hwnd, hwnd_dc)
            win32gui.DeleteObject(bitmap.GetHandle())
        except Exception:
            pass


def _capture_screen(rect):
    """退路：直接抓屏幕对应区域（要求野狐在最前面）。"""
    from PIL import ImageGrab

    l, t, r, b = rect
    img = ImageGrab.grab(bbox=(l, t, r, b), all_screens=True)
    return np.array(img.convert("RGB"))[:, :, ::-1].copy()  # RGB -> BGR


class _BMIH(ctypes.Structure):
    _fields_ = [
        ("biSize", wt.DWORD),
        ("biWidth", wt.LONG),
        ("biHeight", wt.LONG),
        ("biPlanes", wt.WORD),
        ("biBitCount", wt.WORD),
        ("biCompression", wt.DWORD),
        ("biSizeImage", wt.DWORD),
        ("biXPelsPerMeter", wt.LONG),
        ("biYPelsPerMeter", wt.LONG),
        ("biClrUsed", wt.DWORD),
        ("biClrImportant", wt.DWORD),
    ]


def capture_region(hwnd, x, y, w, h):
    """只抓窗口里的一块（BitBlt 从窗口 DC，坐标就是整窗截图坐标系）。

    为什么值得单独写一条：PrintWindow 抓整个 1920x1083 要 130+ ms，
    BitBlt 抓棋盘那一块（约 960x950）只要 13 ms，快一个数量级。
    代价是只对 GDI 自绘的窗口有效 —— 野狐正好是。
    抓出来是黑的就返回 None，让调用方退回 PrintWindow。
    """
    if w <= 0 or h <= 0:
        return None
    gdi32 = ctypes.windll.gdi32
    hdc = user32.GetWindowDC(hwnd)
    if not hdc:
        return None
    mem = None
    bmp = None
    old = None
    try:
        mem = gdi32.CreateCompatibleDC(hdc)
        bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
        if not mem or not bmp:
            return None
        old = gdi32.SelectObject(mem, bmp)
        if not gdi32.BitBlt(mem, 0, 0, w, h, hdc, x, y, 0x00CC0020):
            return None
        bi = _BMIH()
        bi.biSize = ctypes.sizeof(_BMIH)
        bi.biWidth = w
        bi.biHeight = -h          # 负数 = 自上而下，正好是 BGR 的顺序
        bi.biPlanes = 1
        bi.biBitCount = 32
        buf = np.zeros((h, w, 4), dtype=np.uint8)
        rows = gdi32.GetDIBits(
            mem, bmp, 0, h, ctypes.c_void_p(buf.ctypes.data), ctypes.byref(bi), 0
        )
        if not rows:
            return None
        return buf[:, :, :3].copy()
    finally:
        try:
            if mem and old:
                gdi32.SelectObject(mem, old)
            if bmp:
                gdi32.DeleteObject(bmp)
            if mem:
                gdi32.DeleteDC(mem)
            user32.ReleaseDC(hwnd, hdc)
        except Exception:
            pass


def _looks_blank(img):
    """判断这张图是不是"没抓到"。

    野狐是自绘界面，PrintWindow 偶尔会返回一整块黑（实测过：整列都是 (0,35,34)），
    这时宁可不识别，也别拿它去误导棋盘拟合。

    注意要抽样：对一整张 1920x1083 的图直接算 std 要 80~100ms，
    而这一步只是"判定"，抽 1/36 的像素完全够用（实测 0.5ms）。
    """
    if img is None or img.size == 0:
        return True
    sample = img[::6, ::6]
    if float(sample.std()) < 3.0:
        return True
    gray_mean = sample.mean(axis=2)
    if float((gray_mean < 20).mean()) > 0.35:
        return True   # 正常对局页近黑像素 < 5%
    return False


def capture_window(hwnd, allow_screen_fallback=True):
    """返回整窗 BGR 图 + 窗口矩形。失败返回 (None, rect)。"""
    rect = get_rect(hwnd)
    if not rect:
        return None, None
    l, t, r, b = rect
    w, h = r - l, b - t
    if w <= 0 or h <= 0:
        return None, rect

    img = None
    try:
        img = _capture_printwindow(hwnd, w, h)
    except Exception:
        img = None

    if img is not None and _looks_blank(img):
        img = None

    if img is None and allow_screen_fallback:
        if foreground_hwnd() != hwnd:
            # 屏幕抓图会抓到别的窗口，而且会把我们自己的标注也抓进去
            return None, rect
        try:
            img = _capture_screen(rect)
            if _looks_blank(img):
                return None, rect
        except Exception:
            return None, rect

    return img, rect
