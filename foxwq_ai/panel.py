"""小小的控制面板：看状态、暂停、退出。

刻意做小：不挡棋盘，界面上只有一行状态和几个按钮。
"""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from .engine import GTP_COLS


def ij_to_gtp(i, j, n=19):
    if i < 0 or j < 0:
        return "?"
    return f"{GTP_COLS[i]}{n - j}"


class ControlPanel(QWidget):
    def __init__(self, advisor, cfg):
        super().__init__(None)
        self.advisor = advisor
        self.cfg = cfg
        self.setWindowTitle("野狐 · AI 标注")
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setMinimumWidth(300)

        font = QFont("Microsoft YaHei", 9)
        self.setFont(font)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(6)

        self.title = QLabel("野狐 · AI 候选点")
        f = QFont("Microsoft YaHei", 11)
        f.setBold(True)
        self.title.setFont(f)
        lay.addWidget(self.title)

        self.status_lbl = QLabel("启动中")
        self.status_lbl.setWordWrap(True)
        lay.addWidget(self.status_lbl)

        self.info_lbl = QLabel("")
        self.info_lbl.setWordWrap(True)
        self.info_lbl.setTextFormat(Qt.RichText)
        lay.addWidget(self.info_lbl)

        self.engine_lbl = QLabel("")
        self.engine_lbl.setWordWrap(True)
        self.engine_lbl.setStyleSheet("color:#777;")
        lay.addWidget(self.engine_lbl)

        row = QHBoxLayout()
        self.btn_pause = QPushButton("暂停")
        self.btn_pause.clicked.connect(self._toggle_pause)
        self.btn_cal = QPushButton("重新找棋盘")
        self.btn_cal.clicked.connect(self._recalibrate)
        self.btn_quit = QPushButton("退出")
        self.btn_quit.clicked.connect(self._quit)
        row.addWidget(self.btn_pause)
        row.addWidget(self.btn_cal)
        row.addWidget(self.btn_quit)
        lay.addLayout(row)

        hint = QLabel("标注只画在棋盘上；鼠标可以正常穿透点它。")
        hint.setStyleSheet("color:#888;font-size:11px;")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        self.move(40, 40)
        self._tick = QTimer(self)
        self._tick.setInterval(400)
        self._tick.timeout.connect(self.refresh_from_advisor)
        self._tick.start()

    # ------------------------------------------------------------------
    def _toggle_pause(self):
        self.advisor.set_paused(not self.advisor.paused)
        self.btn_pause.setText("继续" if self.advisor.paused else "暂停")
        self.refresh_from_advisor()

    def _recalibrate(self):
        self.advisor.recalibrate()

    def _quit(self):
        self.advisor.stop()
        self.close()
        from PySide6.QtWidgets import QApplication

        QApplication.instance().quit()

    # ------------------------------------------------------------------
    def refresh_from_advisor(self):
        snap = self.advisor.snapshot()
        self.status_lbl.setText(snap["status"])

        eng_txt = []
        if not snap["engine_alive"]:
            eng_txt.append("引擎：已停止")
        elif not snap["engine_ready"]:
            eng_txt.append("引擎：加载中…")
        else:
            eng_txt.append("引擎：就绪")
        eng_txt.append(f"帧率 {snap['fps']:.1f}/s")
        eng_txt.append(f"盘上 {snap['stones']} 子")
        self.info_lbl.setText(
            f"<span style='color:#888'>{' · '.join(eng_txt)}</span>"
        )

        cands = snap["cands"]
        if cands:
            n = self.cfg["board_size"]
            parts = []
            for k, (i, j, color, label) in enumerate(cands):
                parts.append(
                    f"<span style='background:{color};color:#111;padding:0 3px'>"
                    f"&nbsp;{ij_to_gtp(i, j, n)}&nbsp;</span>"
                    f"<span style='color:#555'>{label}%</span>"
                )
            self.engine_lbl.setText("&nbsp; ".join(parts))
            self.engine_lbl.setTextFormat(Qt.RichText)
        else:
            self.engine_lbl.setText(snap["engine_msg"][:120] or "")
