"""入口：python run.py

先开野狐，进到对局页，把野狐窗口放到前面，然后点面板上的「开始分析」。
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from foxwq_ai.app import FoxAdvisor
from foxwq_ai.config import Config
from foxwq_ai.panel import ControlPanel


def main():
    cfg = Config()
    if not os.path.exists(cfg.path):
        cfg.save()

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)

    advisor = FoxAdvisor(cfg)
    panel = ControlPanel(advisor, cfg)
    advisor.on_update = lambda _a: None  # 面板自己定时刷新，这里不用推

    # 面板摆在屏幕右上角：野狐的棋盘一般在左边，这样不挡
    scr = QGuiApplication.primaryScreen().availableGeometry()
    panel.show()
    panel.move(scr.right() - panel.width() - 24, scr.top() + 24)
    advisor.set_panel_hwnd(int(panel.winId()))
    advisor.start()

    print("野狐 · AI 标注 已启动。把野狐窗口放到前面，然后点面板上的「开始分析」。", flush=True)
    print(f"引擎: {cfg['katago_exe']}", flush=True)
    print(f"权重: {cfg['katago_model']}", flush=True)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
