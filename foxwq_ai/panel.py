"""控制面板：深色、无边框、圆角，一个按钮决定开始/停止。

刻意做小做轻：不挡棋盘，信息一眼扫完。
"""

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from .engine import GTP_COLS

# 深色配色
BG = QColor(24, 26, 30, 247)
BORDER = QColor(255, 255, 255, 22)
TXT = "#E8EAED"
DIM = "#8B9097"
ACCENT = "#25E29A"
RUNNING = "#5FAEFF"


def ij_to_gtp(i, j, n=19):
    if i < 0 or j < 0:
        return "?"
    return f"{GTP_COLS[i]}{n - j}"


class Dot(QWidget):
    """一个小圆点，用来做状态灯和候选色标。"""

    def __init__(self, color="#8B9097", size=8, parent=None):
        super().__init__(parent)
        self._color = QColor(color)
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    def set_color(self, color):
        c = QColor(color)
        if c != self._color:
            self._color = c
            self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        r = self.width() / 2.0
        halo = QColor(self._color)
        halo.setAlpha(55)
        p.setBrush(halo)
        p.drawEllipse(QPoint(int(r), int(r)), int(r), int(r))
        p.setBrush(self._color)
        p.drawEllipse(QPoint(int(r), int(r)), max(1, int(r - 2)), max(1, int(r - 2)))
        p.end()


class CandRow(QWidget):
    """一行候选：色点 + 坐标 + 胜率。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(8)
        self.dot = Dot("#8B9097", 9)
        self.name = QLabel("—")
        self.name.setStyleSheet(f"color:{TXT};")
        f = QFont("Consolas", 11)
        f.setBold(True)
        self.name.setFont(f)
        self.win = QLabel("")
        self.win.setStyleSheet(f"color:{DIM};")
        self.win.setFont(QFont("Consolas", 9))
        self.win.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.addWidget(self.dot)
        lay.addWidget(self.name)
        lay.addStretch(1)
        lay.addWidget(self.win)

    def set_data(self, color=None, move="—", winrate=""):
        if color:
            self.dot.set_color(color)
        self.dot.setVisible(bool(move))
        self.name.setText(move)
        self.win.setText(winrate)

    def clear(self):
        """空位：什么都不显示，但高度照占，面板就不会跳。"""
        self.dot.setVisible(False)
        self.name.setText("")
        self.win.setText("")


class ControlPanel(QWidget):
    def __init__(self, advisor, cfg):
        super().__init__(None)
        self.advisor = advisor
        self.cfg = cfg
        self._drag = None
        self._btn_running = None

        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedWidth(272)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 13, 16, 14)
        root.setSpacing(0)

        # ---- 标题行 ----
        head = QHBoxLayout()
        head.setSpacing(7)
        self.light = Dot(DIM, 8)
        title = QLabel("野狐 · AI 标注")
        f = QFont("Microsoft YaHei", 10)
        f.setBold(True)
        title.setFont(f)
        title.setStyleSheet(f"color:{TXT};")
        close = QPushButton("✕")
        close.setFixedSize(20, 20)
        close.setCursor(Qt.PointingHandCursor)
        close.setStyleSheet(
            "QPushButton{color:#6B7078;border:none;background:transparent;font-size:12px;}"
            "QPushButton:hover{color:#E8EAED;}"
        )
        close.clicked.connect(self._close)
        head.addWidget(self.light)
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(close)
        root.addLayout(head)

        root.addSpacing(12)

        # ---- 主按钮 ----
        self.btn = QPushButton("开始分析")
        self.btn.setCursor(Qt.PointingHandCursor)
        self.btn.setFixedHeight(40)
        self.btn.clicked.connect(self._toggle)
        self.btn.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
        root.addWidget(self.btn)

        root.addSpacing(11)

        # ---- 状态 ----
        st = QHBoxLayout()
        st.setSpacing(6)
        self.state_dot = Dot("#6B7078", 6)
        self.status = QLabel("准备好了，点「开始分析」")
        self.status.setStyleSheet(f"color:{DIM};font-size:11px;")
        self.status.setWordWrap(True)
        # 状态文字换行会让面板忽高忽低，这里先留两行的位置
        self.status.setMinimumHeight(30)
        self.status.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        st.addWidget(self.state_dot, 0, Qt.AlignTop)
        st.addWidget(self.status, 1)
        root.addLayout(st)

        root.addSpacing(10)

        # ---- 推荐 ----
        self.cap = QLabel("推荐")
        self.cap.setStyleSheet("color:#5A5F66;font-size:10px;")
        root.addWidget(self.cap)
        root.addSpacing(2)
        self.rows = [CandRow() for _ in range(3)]
        for r in self.rows:
            r.setFixedHeight(21)
            root.addWidget(r)

        root.addSpacing(9)

        # ---- 页脚 ----
        self.foot = QLabel("引擎加载中…")
        self.foot.setStyleSheet("color:#4E535A;font-size:10px;")
        root.addWidget(self.foot)

        self._apply_button_style(False)
        self._tick = QTimer(self)
        self._tick.setInterval(350)
        self._tick.timeout.connect(self.refresh)
        self._tick.start()
        self.adjustSize()

    # ---------------- 外观 ----------------
    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        rect = self.rect().adjusted(1, 1, -1, -1)
        p.setBrush(BG)
        p.setPen(QPen(BORDER, 1))
        p.drawRoundedRect(rect, 14, 14)
        p.end()

    def _apply_button_style(self, running):
        if running:
            css = (
                "QPushButton{color:#FFE2DF;border:1px solid rgba(255,130,120,120);"
                "border-radius:9px;background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
                "stop:0 rgba(198,72,62,190), stop:1 rgba(166,54,46,190));font-weight:600;}"
                "QPushButton:hover{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
                "stop:0 rgba(220,88,76,215), stop:1 rgba(186,62,52,215));}"
                "QPushButton:pressed{background:rgba(150,46,40,220);}"
            )
        else:
            css = (
                "QPushButton{color:#06231A;border:none;border-radius:9px;"
                "background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
                "stop:0 #35EBA6, stop:1 #17B87C);font-weight:600;}"
                "QPushButton:hover{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
                "stop:0 #4AF0B2, stop:1 #1CC789);}"
                "QPushButton:pressed{background:#14A46D;}"
            )
        self.btn.setStyleSheet(css)

    # ---------------- 交互 ----------------
    def _toggle(self):
        if self.advisor.running:
            self.advisor.stop_analysis("已停止")
        else:
            self.advisor.start_analysis()
        self.refresh()

    def _close(self):
        self.advisor.shutdown()
        self.close()
        app = QApplication.instance()
        if app:
            app.quit()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._drag = ev.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, ev):
        if self._drag is not None and ev.buttons() & Qt.LeftButton:
            self.move(ev.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, _ev):
        self._drag = None

    # ---------------- 刷新 ----------------
    def refresh(self):
        s = self.advisor.snapshot()
        running = s["running"]
        if running != self._btn_running:
            self._btn_running = running
            self.btn.setText("停止分析" if running else "开始分析")
            self._apply_button_style(running)

        if not s["ready"]:
            self.light.set_color("#6B7078")
            self.state_dot.set_color("#6B7078")
        elif running:
            self.light.set_color(RUNNING)
            self.state_dot.set_color(RUNNING)
        else:
            self.light.set_color(ACCENT)
            self.state_dot.set_color("#6B7078")
        self.status.setText(s["status"])

        n = self.cfg["board_size"]
        cands = s["cands"]
        # 三行始终占位，面板高度就不会在"出结果"那一瞬间跳一下
        for k, row in enumerate(self.rows):
            if k < len(cands):
                i, j, color, label = cands[k]
                row.set_data(color, ij_to_gtp(i, j, n), f"{label}%")
            else:
                row.clear()

        bits = []
        if s["ready"]:
            bits.append("引擎就绪")
        elif s["engine_alive"]:
            bits.append("引擎加载中")
        else:
            bits.append("引擎未运行")
        if s["stones"]:
            bits.append(f"盘上 {s['stones']} 子")
        if s["visits"]:
            bits.append(f"{s['visits']} visits")
        self.foot.setText(" · ".join(bits))
        self.adjustSize()
