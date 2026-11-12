"""手动校准：点两下，告诉程序棋盘在哪。

自动检测一般够用；换皮肤、换分辨率、或者识别总是不对的时候跑这个。
跑法：python tools\\calibrate.py

点了之后会立刻用你框的位置试读一遍，能读到棋子才算校准成功。
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import numpy as np
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from foxwq_ai import winfox
from foxwq_ai.boardreader import read_board
from foxwq_ai.config import Config


def bgr_to_pixmap(img):
    rgb = np.ascontiguousarray(img[:, :, ::-1])
    h, w = rgb.shape[:2]
    qimg = QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy()
    return QPixmap.fromImage(qimg)


class CalibWindow(QWidget):
    def __init__(self, img, cfg):
        super().__init__(None)
        self.cfg = cfg
        self.orig = img
        self.pix = bgr_to_pixmap(img)
        self.scale = 1.0
        self.pts = []
        self.rect = None
        self.setWindowTitle("校准：先点左上角那个交叉点，再点右下角那个")
        self.setAttribute(Qt.WA_DeleteOnClose, True)

        self._fit_to_screen()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.canvas = QLabel()
        self.canvas.setPixmap(self.pix)
        self.canvas.setMouseTracking(False)
        lay.addWidget(self.canvas)

        bar = QWidget()
        from PySide6.QtWidgets import QHBoxLayout

        bl = QHBoxLayout(bar)
        bl.setContentsMargins(6, 4, 6, 4)
        self.hint = QLabel("先点左上角交叉点，再点右下角交叉点")
        bl.addWidget(self.hint, 1)
        b1 = QPushButton("重来")
        b1.clicked.connect(self._reset)
        b2 = QPushButton("保存")
        b2.clicked.connect(self._save)
        b3 = QPushButton("关闭")
        b3.clicked.connect(self.close)
        bl.addWidget(b1)
        bl.addWidget(b2)
        bl.addWidget(b3)
        lay.addWidget(bar)

    def _fit_to_screen(self):
        scr = QApplication.primaryScreen().availableGeometry()
        max_w = int(scr.width() * 0.92)
        max_h = int(scr.height() * 0.86)
        w, h = self.pix.width(), self.pix.height()
        s = min(max_w / w, max_h / h, 1.0)
        self.scale = s
        if s < 1.0:
            self.pix = self.pix.scaled(int(w * s), int(h * s), Qt.KeepAspectRatio,
                                       Qt.SmoothTransformation)

    def mousePressEvent(self, ev):
        if self.canvas.geometry().contains(ev.position().toPoint()):
            self._reset()
            return
        # 点的是整窗，要减去画布的偏移
        pos = ev.position().toPoint() - self.canvas.geometry().topLeft()
        if not (0 <= pos.x() < self.pix.width() and 0 <= pos.y() < self.pix.height()):
            return
        ox = int(pos.x() / self.scale)
        oy = int(pos.y() / self.scale)
        self.pts.append((ox, oy))
        if len(self.pts) == 1:
            self.hint.setText("再点右下角那个交叉点（T1）")
        elif len(self.pts) == 2:
            self._compute()
        self.update()

    def _reset(self):
        self.pts = []
        self.rect = None
        self.hint.setText("先点左上角交叉点，再点右下角交叉点")
        self.update()

    def _compute(self):
        (x0, y0), (x1, y1) = self.pts
        if x1 <= x0 or y1 <= y0:
            self.hint.setText("两点位置不对，重来")
            self.pts = []
            return
        n = self.cfg["board_size"]
        sx = (x1 - x0) / (n - 1)
        sy = (y1 - y0) / (n - 1)
        # 用格子外沿再留半格，当"棋盘底色矩形"用
        pad = 0.55
        rx = int(round(x0 - pad * sx))
        ry = int(round(y0 - pad * sy))
        rw = int(round(2 * pad * sx + (n - 1) * sx))
        rh = int(round(2 * pad * sy + (n - 1) * sy))
        self.rect = [rx, ry, rw, rh]

        rd = read_board(self.orig, n=n, manual_rect=self.rect)
        if rd is None:
            self.hint.setText("这个位置读不出棋盘，再点一次")
            self.rect = None
            return
        cnt = int((rd.stones > 0).sum())
        self.hint.setText(
            f"读到 {cnt} 个棋子（{int((rd.stones==1).sum())} 黑 "
            f"{int((rd.stones==2).sum())} 白），满意就点保存"
        )
        self.rd = rd
        self.update()

    def paintEvent(self, _ev):
        if not self.pts and not getattr(self, "rd", None):
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        # 画布坐标 = 窗口坐标（画布在布局里从 0,0 开始，底部还有一条按钮栏）
        off = self.canvas.geometry().topLeft()
        s = self.scale
        pen = QPen(QColor(0, 220, 120), 2)
        p.setPen(pen)
        for (x, y) in self.pts:
            cx = off.x() + x * s
            cy = off.y() + y * s
            p.drawLine(QPoint(int(cx - 8), int(cy)), QPoint(int(cx + 8), int(cy)))
            p.drawLine(QPoint(int(cx), int(cy - 8)), QPoint(int(cx), int(cy + 8)))

        rd = getattr(self, "rd", None)
        if rd is not None:
            n = rd.stones.shape[0]
            gx0, gy0, sx, sy = rd.grid
            for j in range(n):
                for i in range(n):
                    v = rd.stones[j, i]
                    if not v:
                        continue
                    cx = off.x() + (gx0 + i * sx) * s
                    cy = off.y() + (gy0 + j * sy) * s
                    p.setPen(QPen(QColor(0, 0, 255) if v == 1 else QColor(255, 0, 0), 2))
                    p.drawEllipse(QPoint(int(cx), int(cy)), 4, 4)
        p.end()

    def _save(self):
        rd = getattr(self, "rd", None)
        if rd is None or not self.rect:
            QMessageBox.warning(self, "还没校准好", "先点两个交叉点，读到棋子再保存。")
            return
        self.cfg["manual_board"] = self.rect
        self.cfg.save()
        QMessageBox.information(
            self, "已保存",
            f"写入 {self.cfg.path}\nmanual_board = {self.rect}\n\n"
            "以后窗口大小变了要重新校准一次。",
        )
        self.close()


def main():
    winfox.enable_dpi_awareness()
    app = QApplication(sys.argv)
    cfg = Config()
    hwnd = winfox.find_window(cfg)
    if not hwnd:
        print("没找到野狐窗口，先打开野狐并进入对局页。")
        return 1
    img, rect = winfox.capture_window(hwnd)
    if img is None:
        print("截图失败。野狐要在前台。")
        return 1
    print(f"窗口 {rect}，截图 {img.shape}")
    w = CalibWindow(img, cfg)
    w.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
