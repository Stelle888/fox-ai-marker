"""主循环：看窗口 -> 读棋盘 -> 问引擎 -> 画点。

线程模型：所有窗口/截图/绘制都在 Qt 主线程（每帧几十毫秒，够用），
只有 KataGo 的收发在它自己的子线程里，互不阻塞。
"""

import time

import numpy as np
from PySide6.QtCore import QObject, QTimer

from . import winfox
from .boardreader import read_board
from .engine import KataGoEngine
from .overlay import BoardOverlay

COLOR_NAMES = ["一选", "二选", "三选"]


def choose_candidates(cands, max_show, gap1, gap2):
    """决定标几个点。

    规则（用户要的）：一选和二选胜率差 >= gap1 就只标一选；
    二选和三选差 >= gap2 就不标三选。差距小的时候才并列标出来。
    """
    if not cands:
        return []
    chosen = [cands[0]]
    if max_show >= 2 and len(cands) >= 2:
        if (cands[0].winrate - cands[1].winrate) * 100.0 < gap1:
            chosen.append(cands[1])
    if max_show >= 3 and len(chosen) == 2 and len(cands) >= 3:
        if (cands[1].winrate - cands[2].winrate) * 100.0 < gap2:
            chosen.append(cands[2])
    return chosen


class FoxAdvisor(QObject):
    def __init__(self, cfg, on_update=None):
        super().__init__()
        self.cfg = cfg
        self.on_update = on_update or (lambda *a, **k: None)
        self.overlay = BoardOverlay(cfg)
        self.engine = KataGoEngine(cfg, log=self._log)

        self.hwnd = None
        self.phys_rect = None
        self.running = False          # 只有用户点了"开始分析"才为 True
        self._panel_hwnd = 0          # 面板自己的窗口句柄（它在前台时不算"别的窗口"）
        self._rect_hint = None          # 上次成功识别的棋盘矩形
        self._grid = None

        self.last_stones = None         # 上一帧被接受的局面
        self._pending = None            # 待确认局面
        self._pending_n = 0
        self._last_move_color = 0       # 1 黑 / 2 白
        self._current_rid = None
        self._current_state = None
        self._analyzed_stones = None
        self._analysis_start = 0.0
        self._last_cands = []
        self._show = 0
        self.status = "启动中"
        self.engine_msg = ""
        self._fps_last = time.time()
        self._frame_count = 0
        self._fps = 0.0
        self._board_lost_since = None
        self._quality = None
        self._warmed = False

        self.timer = QTimer(self)
        self.timer.setInterval(int(cfg["capture_interval_ms"]))
        self.timer.timeout.connect(self.tick)
        self._stopping = False
        self._last_restart = 0.0

    # ------------------------------------------------------------------
    def _log(self, *a):
        msg = " ".join(str(x) for x in a)
        self.engine_msg = msg[:200]
        print("[engine]", msg, flush=True)

    def start(self):
        """启动引擎并开始空转（不截图，等用户点"开始分析"）。"""
        ok = self.engine.start()
        if not ok:
            self.status = "引擎启动失败：" + self.engine.last_error
        else:
            self.status = "准备好了，点「开始分析」"
        self.timer.start()

    def shutdown(self):
        self._stopping = True
        self.running = False
        self.timer.stop()
        self.overlay.hide()
        self.engine.stop()

    def set_panel_hwnd(self, hwnd):
        """面板自己的句柄：它在前台时不该算"别的窗口"。"""
        self._panel_hwnd = int(hwnd or 0)

    def start_analysis(self):
        """用户点「开始分析」：此刻把野狐窗口锁下来，之后不再反复枚举。"""
        if self.running:
            return True
        hwnd = winfox.find_window(self.cfg)
        if not hwnd:
            self.status = "没找到野狐窗口，先打开野狐并进到对局页"
            return False
        if winfox.is_minimized(hwnd):
            self.status = "野狐窗口是最小化的"
            return False
        self.hwnd = hwnd
        self._reset_board_state()
        self.running = True
        self.status = "已开始，等棋盘出现…"
        self._log("锁定野狐窗口")
        return True

    def stop_analysis(self, reason=""):
        self.running = False
        self.overlay.clear_points()
        self.overlay.hide()
        self._reset_board_state()
        self.status = reason or "已停止"
        self.hwnd = None

    def _reset_board_state(self):
        self._rect_hint = None
        self.last_stones = None
        self._pending = None
        self._pending_n = 0
        self._current_rid = None
        self._analyzed_stones = None
        self._current_state = None
        self._last_cands = []
        self._grid = None
        self.phys_rect = None

    def recalibrate(self):
        """忘掉棋盘位置和当前局面，下一帧重新找。"""
        self._reset_board_state()
        self.overlay.clear_points()
        self.status = "重新寻找棋盘…"

    # ------------------------------------------------------------------
    def _watchdog(self, now):
        """引擎挂了就自己拉起来一次，不用人管。"""
        if self._stopping:
            return
        if self.engine.alive:
            return
        if now - self._last_restart < 10.0:
            return
        self._last_restart = now
        self._log("引擎不在了，重新启动…")
        self.engine = KataGoEngine(self.cfg, log=self._log)
        if not self.engine.start():
            self.status = "引擎重启失败：" + self.engine.last_error
        else:
            self._analyzed_stones = None
            self._current_rid = None

    def tick(self):
        self._frame_count += 1
        now = time.time()
        self._watchdog(now)
        if now - self._fps_last >= 1.0:
            self._fps = self._frame_count / (now - self._fps_last)
            self._frame_count = 0
            self._fps_last = now

        if not self.running:
            self._watchdog(now)
            return

        # 窗口是在点"开始分析"那一刻锁定的，之后不再枚举；只有它真的没了才停
        if not winfox.window_alive(self.hwnd):
            self.stop_analysis("野狐窗口不见了")
            self._notify()
            return

        if winfox.is_minimized(self.hwnd):
            self.status = "野狐已最小化"
            self.overlay.hide()
            self._poll_engine()
            self._notify()
            return

        # 野狐不在前台时把标注藏起来（不然它盖在别人窗口上）。
        # 但面板自己在前台时不算"别人"，否则刚点完开始就什么都看不见。
        fg = winfox.foreground_hwnd()
        if self.cfg["overlay_hide_when_other"] and fg not in (self.hwnd, self._panel_hwnd):
            self.overlay.hide()
            self.status = "野狐不在前台，切回去就继续"
            self._poll_engine()
            self._notify()
            return

        img, rect = winfox.capture_window(self.hwnd)
        if img is None or rect is None:
            self.status = "截图失败"
            self.overlay.hide()
            self._poll_engine()
            self._notify()
            return

        if rect != self.phys_rect:
            self.phys_rect = rect
            self.overlay.place(rect)

        self._warmup()

        reading = read_board(
            img,
            n=self.cfg["board_size"],
            tol=self.cfg["color_tolerance"],
            manual_rect=self.cfg["manual_board"],
            hint_rect=self._rect_hint,
        )
        if reading is None or reading.quality < 0.30:
            self.status = "没看到棋盘（可能不在对局页）"
            if self._board_lost_since is None:
                self._board_lost_since = now
            elif now - self._board_lost_since > 1.5 and self._last_cands:
                self.overlay.clear_points()
                self._last_cands = []
            self._notify()
            return

        self._board_lost_since = None
        self._quality = reading.quality
        self._rect_hint = reading.rect
        self._grid = reading.grid

        self._ingest(reading.stones)

        self._maybe_analyze()
        self._poll_engine()
        self._render()
        self._notify()

    # ------------------------------------------------------------------
    def _ingest(self, stones):
        """把本帧局面并进对局状态（连续 2 帧一致才认，压掉偶发误判）。"""
        if self._pending is not None and np.array_equal(stones, self._pending):
            self._pending_n += 1
        else:
            self._pending = stones.copy()
            self._pending_n = 1

        if self._pending_n < 2:
            return

        stable = self._pending
        if self.last_stones is None:
            self.last_stones = stable
            return
        if np.array_equal(stable, self.last_stones):
            return

        prev, cur = self.last_stones, stable
        added = (cur > 0) & (prev == 0)
        removed = (prev > 0) & (cur == 0)
        n_add = int(added.sum())
        n_rm = int(removed.sum())

        if n_add == 1:
            color = int(cur[added][0])
            self._last_move_color = color
            self.last_stones = stable
            self._analyzed_stones = None
            return

        # 悔棋 / 新对局 / 切换棋盘：整盘重建
        self._log(f"局面重建（新增 {n_add} 子，消失 {n_rm} 子）")
        self.last_stones = stable
        self._analyzed_stones = None
        self._current_rid = None
        self._last_cands = []
        # 最后落子颜色未知，用子数推断下一手（黑白子数相等时轮黑）
        self._last_move_color = 0

    def _next_player(self):
        if self.last_stones is None:
            return "B"
        black = int((self.last_stones == 1).sum())
        white = int((self.last_stones == 2).sum())
        if black == white:
            return "B"
        if black == white + 1:
            return "W"
        # 让子或识别抖动：按黑多算，宁可给白方推荐
        return "W" if black > white else "B"

    # ------------------------------------------------------------------
    def _warmup(self):
        """引擎就绪后先空算一手：GPU 第一次推理要 5~6 秒，别让用户的第一手去等这个。"""
        if self._warmed or not (self.engine.alive and self.engine.ready):
            return
        self._warmed = True
        n = self.cfg["board_size"]
        empty = np.zeros((n, n), dtype=np.int8)
        self.engine.analyze(empty, "B", visits=2)
        self._log("预热一次推理")

    def _maybe_analyze(self):
        if self.last_stones is None or self._analyzed_stones is not None:
            return
        if not (self.engine.alive and self.engine.ready):
            if self.engine.alive:
                self.status = "引擎加载中…"
            else:
                self.status = "引擎已停止：" + (self.engine.last_error or "未知原因")
            return
        player = self._next_player()
        rid = self.engine.analyze(self.last_stones, player)
        if rid is None:
            self.status = "请求引擎失败：" + self.engine.last_error
            return
        self._current_rid = rid
        self._analyzed_stones = self.last_stones.copy()
        self._analysis_start = time.time()
        self._current_state = None
        self._last_cands = []
        self.status = f"分析中…（{'黑' if player == 'B' else '白'}方）"

    def _poll_engine(self):
        if not self._current_rid:
            return
        res = self.engine.get(self._current_rid)
        if not res:
            return
        # 已经有最终结果了就不再被中间结果覆盖
        if self._current_state is not None and not self._current_state["during"]:
            return
        self._current_state = res
        self._pick_candidates(res)
        if not res["during"]:
            n = self.cfg["board_size"]
            self.status = f"已出结果（{'黑' if self._next_player() == 'B' else '白'}方）"
            _ = n

    def _pick_candidates(self, res):
        cands = [c for c in res["candidates"] if c.visits > 0]
        chosen = choose_candidates(
            cands,
            int(self.cfg["show_candidates"]),
            float(self.cfg["winrate_gap_1stone"]),
            float(self.cfg["winrate_gap_2stone"]),
        )
        out = []
        for k, c in enumerate(chosen):
            color = self.cfg["colors"][min(k, len(self.cfg["colors"]) - 1)]
            label = f"{c.winrate * 100:.1f}"
            out.append((c.i, c.j, color, label))
        self._last_cands = out

    def _render(self):
        if self._grid is None or self.phys_rect is None:
            return
        self.overlay.place(self.phys_rect)
        status = ""
        if self.cfg["show_winrate_text"] and self.cfg["show_status"]:
            status = self._status_line()
        self.overlay.set_state(self._grid, self._last_cands, status)

    def _status_line(self):
        if not self._current_state:
            return self.status
        st = self._current_state
        player = self._next_player()
        wr = st.get("root_winrate")
        side = "黑" if player == "B" else "白"
        wr_txt = f"{wr * 100:.1f}%" if isinstance(wr, (int, float)) else "?"
        dt = st["time"] - self._analysis_start
        first = st["candidates"][0] if st["candidates"] else None
        v = first.visits if first else 0
        return f"{side}方 胜率 {wr_txt}  {v}v  {dt:.2f}s  {'点' * len(self._last_cands)}"

    # ------------------------------------------------------------------
    def _notify(self):
        try:
            self.on_update(self)
        except Exception:
            pass

    # ------------------------------------------------------------------
    def snapshot(self):
        st = self._current_state
        top = None
        if st and st.get("candidates"):
            c = st["candidates"][0]
            top = {"move": c.move, "visits": c.visits}
        return {
            "status": self.status,
            "engine_msg": self.engine_msg,
            "engine_ready": self.engine.ready,
            "engine_alive": self.engine.alive,
            "hwnd": self.hwnd,
            "grid": self._grid,
            "cands": [(c[0], c[1], c[2], c[3]) for c in self._last_cands],
            "fps": self._fps,
            "stones": int((self.last_stones > 0).sum()) if self.last_stones is not None else 0,
            "player": self._next_player(),
            "running": self.running,
            "ready": bool(self.engine.ready and self.engine.alive),
            "visits": top["visits"] if top else 0,
        }
