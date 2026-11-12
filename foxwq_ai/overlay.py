"""棋盘上的透明标注层。

一个"贴"在野狐窗口上的透明窗：无边框、置顶、点击穿透（点不到它，鼠标照常穿过），
只在棋盘交叉点上画几个圆点。
"""

import ctypes

from PySide6.QtCore import Qt, QPointF, QRectF, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QBrush
from PySide6.QtWidgets import QWidget

user32 = ctypes.windll.user32

GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TRANSPARENT = 0x00000020
HWND_TOPMOST = -1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010


class BoardOverlay(QWidget):
    def __init__(self, cfg):
        super().__init__(None)
        self.cfg = cfg
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowTransparentForInput
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        self.phys_rect = None       # 野狐窗口的物理矩形 (l, t, r, b)
        self.grid = None            # (x0, y0, sx, sy) 物理像素，整窗截图坐标系
        self.candidates = []        # [(i, j, color, label)]
        self.status_text = ""
        self.show_status = bool(cfg["show_winrate_text"])
        self._applied_style = False

        # 位置/尺寸由 win32 直接摆，避免 Qt 的 DPI 换算来回折损
        self._follow = QTimer(self)
        self._follow.setInterval(500)
        self._follow.timeout.connect(self._keep_on_top)
        self._follow.start()

    # ---------------- 窗口几何 ----------------
    def _dpr(self):
        """屏幕缩放比。单屏用主屏值；多屏时以窗口所在屏幕为准。"""
        from PySide6.QtGui import QGuiApplication

        win = self.windowHandle()
        if win is not None and win.screen() is not None:
            d = win.screen().devicePixelRatio()
            if d:
                return float(d)
        scr = QGuiApplication.primaryScreen()
        return float(scr.devicePixelRatio()) if scr else 1.0

    def place(self, phys_rect):
        """把覆盖层摆到野狐窗口上（物理像素）。

        注意：用 SetWindowPos 会被 Qt 的窗口几何同步立刻"改回去"，
        必须走 Qt 自己的 setGeometry（逻辑坐标 = 物理 / 缩放比）。
        """
        if not phys_rect:
            self.hide()
            return
        self.phys_rect = tuple(int(v) for v in phys_rect)
        l, t, r, b = self.phys_rect
        w, h = r - l, b - t
        if w <= 0 or h <= 0:
            return

        if not self.isVisible():
            self.show()
        dpr = self._dpr()
        target = (
            int(round(l / dpr)),
            int(round(t / dpr)),
            int(round(w / dpr)),
            int(round(h / dpr)),
        )
        if self.geometry().getRect() != target:
            self.setGeometry(*target)
            self.update()
        self.raise_()
        # 鼠标穿透 + 不进 Alt-Tab（Qt 的 flag 之外再钉一遍，某些系统上才稳）
        hwnd = int(self.winId())
        ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        want = ex | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_TRANSPARENT
        if ex != want:
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, want)

    def _keep_on_top(self):
        if not self.isVisible() or not self.phys_rect:
            return
        self.place(self.phys_rect)

    def set_state(self, grid, candidates, status_text=""):
        self.grid = grid
        self.candidates = candidates or []
        self.status_text = status_text
        self.update()

    def clear_points(self):
        self.candidates = []
        self.update()

    # ---------------- 绘制 ----------------
    def _scale(self):
        """物理像素 -> 本窗口绘图坐标的换算系数。"""
        if not self.phys_rect:
            return 1.0
        pw = max(1, self.phys_rect[2] - self.phys_rect[0])
        return self.width() / float(pw)

    def paintEvent(self, _ev):
        if not self.grid or not self.phys_rect:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        s = self._scale()
        dpr = self.devicePixelRatioF() or 1.0
        _ = dpr
        x0, y0, sx, sy = self.grid

        # 点：不同颜色 + 细白圈，保证深色皮肤上也看得清
        for (i, j, color, label) in self.candidates:
            cx = (x0 + i * sx) * s
            cy = (y0 + j * sy) * s
            rad = (min(sx, sy) * float(self.cfg["dot_radius_ratio"])) * s
            c = QColor(color)
            c.setAlpha(int(self.cfg["dot_alpha"]))
            p.setBrush(QBrush(c))
            p.setPen(QPen(QColor(255, 255, 255, 200), max(1.0, 1.2 * s)))
            p.drawEllipse(QPointF(cx, cy), rad, rad)

            if self.show_status and label:
                f = QFont("Microsoft YaHei", max(7, int(rad * 0.42 / s / 1.3)))
                f.setBold(True)
                p.setFont(f)
                p.setPen(QPen(QColor(0, 0, 0, 190)))
                p.setBrush(QBrush(Qt.NoBrush))
                # 轻微描边：先黑后白，压在任意底色上都读得出来
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    p.drawText(
                        QRectF(cx - rad + dx, cy - rad + dy, rad * 2, rad * 2),
                        Qt.AlignCenter, label,
                    )
                p.setPen(QPen(QColor(255, 255, 255, 240)))
                p.drawText(QRectF(cx - rad, cy - rad, rad * 2, rad * 2), Qt.AlignCenter, label)

        # 左上角状态（很小，不碍事）
        if self.status_text:
            f = QFont("Microsoft YaHei", max(7, int(13 * s)))
            p.setFont(f)
            p.setBrush(QBrush(Qt.NoBrush))
            txt_rect = QRectF(8 * s, 4 * s, self.width() - 16 * s, 22 * s)
            p.setPen(QPen(QColor(0, 0, 0, 120)))
            p.drawText(txt_rect.translated(1, 1), Qt.AlignLeft | Qt.AlignVCenter, self.status_text)
            p.setPen(QPen(QColor(255, 255, 255, 205)))
            p.drawText(txt_rect, Qt.AlignLeft | Qt.AlignVCenter, self.status_text)
        p.end()
