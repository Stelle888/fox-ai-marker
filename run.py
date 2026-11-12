"""入口：python run.py

先开野狐，进到对局页，再跑这个。
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from foxwq_ai import winfox
from foxwq_ai.app import FoxAdvisor
from foxwq_ai.config import Config
from foxwq_ai.panel import ControlPanel


def main():
    cfg = Config()
    if not os.path.exists(cfg.path):
        cfg.save()

    # 物理像素坐标：先声明 DPI 感知，再建 Qt 应用
    winfox.enable_dpi_awareness()
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)

    advisor = FoxAdvisor(cfg)
    panel = ControlPanel(advisor, cfg)
    advisor.on_update = lambda _a: None  # 面板自己定时刷新，这里不用推
    panel.show()
    advisor.start()

    print("野狐 · AI 候选点标注已启动。面板上可以暂停/退出。", flush=True)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
