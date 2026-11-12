"""配置：默认值 + config.json 读写。

设计原则：开箱即用。引擎和权重优先用**项目目录里自带的**（katago/ 和 weights/），
只有没找到时才回落到 From github\艾姆西；换皮肤 / 换权重才需要改 config.json。
"""

import json
import os
import sys

# 没有自带引擎时的回落位置（From github\艾姆西 里现成的）
DEFAULT_EMXI_ROOT = r"D:\OneDrive\桌面\From github\艾姆西"
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _pick_exe():
    """优先用项目自带的 katago，找不到再用艾姆西那份。"""
    local = os.path.join(_ROOT, "katago", "katago.exe")
    if os.path.exists(local):
        return local
    return os.path.join(DEFAULT_EMXI_ROOT, "katago-v1.16.4-opencl-windows-x64", "katago.exe")


def _pick_model():
    """优先用项目自带的 weights/*.bin.gz（b20 优先：够强又快），找不到才回落。"""
    wdir = os.path.join(_ROOT, "weights")
    if os.path.isdir(wdir):
        bins = sorted(
            os.path.join(wdir, f)
            for f in os.listdir(wdir)
            if f.lower().endswith(".bin.gz")
        )
        for b in bins:
            if "b20" in os.path.basename(b).lower():
                return b
        if bins:
            return bins[0]
    return os.path.join(
        DEFAULT_EMXI_ROOT,
        "WEIGHTS",
        "kata1-b20c256x2-s5303129600-d1228401921.bin.gz",
    )


DEFAULTS = {
    # ---------- 引擎 ----------
    "katago_exe": _pick_exe(),
    # b20 比 b28 轻三倍，实时标注优先选它；想更强就换成 weights/ 里的 b28
    "katago_model": _pick_model(),
    "katago_config": os.path.join(_ROOT, "analysis.cfg"),
    "max_visits": 400,          # 每个局面分析的 visits，越小越快（400 在这台机上约 0.3s）
    "analysis_threads": 2,      # 不改 cfg 时的兜底线程数提示（真值在 analysis.cfg）
    "komi": 7.5,
    "rules": "chinese",
    "use_override_visits": True,  # 是否在 query 里覆盖 maxVisits

    # ---------- 野狐窗口 ----------
    "window_title_keywords": ["野狐", "foxwq", "FoxGo", "围棋", "Fox"],
    "window_process": "foxwq.exe",
    "capture_interval_ms": 300,   # 多久看一次棋盘
    "auto_calibrate": True,       # 自动找棋盘；失败时用手动 calibrate 值

    # ---------- 棋盘识别 ----------
    "board_size": 19,
    "color_tolerance": 60,        # 与棋盘底色差多少算"不是底色"（0-255）
    "stone_black_thresh": 0.34,   # 亮度 < 底亮度-该值*底亮度 → 黑子
    "stone_white_thresh": 0.20,   # 亮度 > 底亮度+该值*底亮度 → 白子
    "manual_board": None,         # [x0, y0, bw, bh] 相对窗口客户区左上角的物理像素

    # ---------- 标注 ----------
    "show_candidates": 3,         # 最多标几个点
    "winrate_gap_1stone": 1.5,    # 一选与二选胜率差(百分点) ≥ 此值 → 只标一选
    "winrate_gap_2stone": 3.0,    # 二选与三选胜率差 ≥ 此值 → 不标三选
    "dot_radius_ratio": 0.38,     # 点半径 = 0.38 格
    "colors": ["#25E29A", "#FFC24A", "#5FAEFF"],  # 一选/二选/三选
    "show_winrate_text": True,    # 点上是否写胜率
    "show_status": False,         # 左上角那行状态小字（默认关，面板里已经能看到）
    "dot_alpha": 215,
    "overlay_hide_when_other": True,  # 野狐不是前台时隐藏标注

    # ---------- 其它 ----------
    "manual_mode": False,         # True = 不自动连引擎，只画上次结果（调试用）
    "debug": False,
}


class Config:
    def __init__(self, path=None):
        self.path = path or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json"
        )
        self.data = dict(DEFAULTS)
        self.load()

    def load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    user = json.load(f)
                for k, v in user.items():
                    if k in DEFAULTS and isinstance(v, dict) and isinstance(DEFAULTS[k], dict):
                        self.data[k].update(v)
                    else:
                        self.data[k] = v
            except Exception as e:  # 配置坏了不能拖垮整个程序
                print(f"[config] 读取 {self.path} 失败，用默认值：{e}")
        return self.data

    def save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
            f.write("\n")

    def __getitem__(self, k):
        return self.data[k]

    def __setitem__(self, k, v):
        self.data[k] = v


def resource_path(*parts):
    """脚本内资源（cfg 模板等）。"""
    base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, *parts)


if __name__ == "__main__":
    c = Config()
    print(json.dumps(c.data, ensure_ascii=False, indent=2))
    c.save()
    print("已写出:", c.path)
