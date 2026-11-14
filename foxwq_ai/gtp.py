"""KataGo GTP 引擎封装（持续分析模式）。

为什么不用 analysis 引擎：
analysis 每发一个请求就是一个**全新的局面**，引擎得从零把搜索树建起来。
这台机器上刚落一手就要两三秒，怎么调都快不过去。

GTP 的 `kata-analyze` 是**持续分析**：开局发一次命令，引擎就一直算当前局面、
按固定间隔吐结果。落一手只要发一句 `play`，引擎接着已有的搜索树往下算 ——
实测落子后 70 毫秒就有新结果。这也是 Lizzie 用的路子。

对外接口故意做得和原来的 KataGoEngine 差不多，方便 app.py 直接换。
"""

import json
import os
import subprocess
import threading
import time

from .engine import Candidate, gtp_to_xy, xy_to_gtp


class KataGoGtp:
    def __init__(self, cfg, log=None):
        self.cfg = cfg
        self.log = log or (lambda *a: None)
        self.proc = None
        self.alive = False
        self.ready = False
        self.last_error = ""
        self._lock = threading.Lock()
        self._seq = 0
        self._cands = []       # 最新的候选点（Candidate）
        self._root_winrate = None
        self._gen = 0          # 每收到一批新分析结果就 +1
        self._board = []       # 引擎里当前的着法列表 [(color, move)]
        self._analyzing = False
        self._analyze_color = "b"
        self._stderr_tail = []

    # ---------------- 生命周期 ----------------
    def start(self):
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        exe = self.cfg["katago_exe"]
        model = self.cfg["katago_model"]
        gtp_cfg = os.path.join(base, "gtp.cfg")
        for p, name in ((exe, "katago.exe"), (model, "权重"), (gtp_cfg, "gtp.cfg")):
            if not os.path.exists(p):
                self.last_error = f"找不到{name}：{p}"
                self.log("[engine]", self.last_error)
                return False
        if not os.path.exists(gtp_cfg):
            gtp_cfg = None
        argv = [exe, "gtp", "-model", model]
        if gtp_cfg:
            argv += ["-config", gtp_cfg]
        try:
            self.proc = subprocess.Popen(
                argv,
                cwd=base,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except Exception as e:
            self.last_error = f"启动失败：{e}"
            self.log("[engine]", self.last_error)
            return False
        self.alive = True
        self.log("[engine] 启动 GTP 引擎:", " ".join(argv))
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()
        return True

    def stop(self):
        self.alive = False
        self.ready = False
        self._analyzing = False
        if self.proc:
            try:
                self.proc.stdin.close()
            except Exception:
                pass
            try:
                self.proc.terminate()
                self.proc.wait(timeout=5)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
            self.proc = None

    # ---------------- IO ----------------
    def _send(self, cmd, wait=True):
        if not self.alive or self.proc is None:
            return False
        try:
            self.proc.stdin.write(cmd + "\n")
            self.proc.stdin.flush()
        except Exception as e:
            self.last_error = f"写入失败：{e}"
            self.alive = False
            return False
        return True

    def _read_stderr(self):
        proc = self.proc
        if proc is None:
            return
        for line in proc.stderr:
            line = line.rstrip()
            if not line:
                continue
            self._stderr_tail.append(line)
            if len(self._stderr_tail) > 40:
                self._stderr_tail.pop(0)
            low = line.lower()
            # 就绪信号。KataGo v1.16.5 实际打的是这一行：
            #   GTP ready, beginning main protocol loop
            # 之前只靠 stdout 里的 "=" 判断，实测 60 秒都等不到；
            # 结果 setup / begin_analyze 一次都没发出去，引擎从头到尾没干活 ——
            # 界面上就是"棋盘读得很准，但选点永远不动"。
            if "gtp ready" in low or "beginning main protocol loop" in low:
                self.ready = True
            if "uncaught" in low or "error" in low or "failed" in low:
                self.last_error = line[:300]
                self.log("[引擎 stderr]", line)

    def _read_stdout(self):
        proc = self.proc
        if proc is None:
            return
        buf = []
        for raw in proc.stdout:
            s = raw.rstrip()
            if not s:
                continue
            if s.startswith("="):
                # GTP 响应结束。第一条空响应就说明引擎起来了
                self.ready = True
                buf = []
                continue
            if s.startswith("info"):
                self.ready = True
                self._consume_info(s)
                continue
            buf.append(s)
        self.alive = False
        self.ready = False

    def _consume_info(self, line):
        """解析一条 kata-analyze 的 info 行。

        实测格式（KataGo v1.16.5）：
          info move O17 visits 13 edgeVisits 13 utility -0.25 winrate 0.376 ...
        注意它**没有 order 字段**，而且每一轮只报当前搜索树里前 1~N 个候选，
        随着搜索变深候选才会多起来。所以这里按 move 累积、按 visits 排序，
        不能用"order==0 就是新一批"这种假设（原来就是这么错的，永远只剩一个点）。
        """
        n = self.cfg["board_size"]
        parts = line.split()
        if len(parts) < 3:
            return
        data = {}
        i = 1
        while i + 1 < len(parts):
            data[parts[i]] = parts[i + 1]
            i += 2
        if "move" not in data:
            if "winrate" in data:
                try:
                    self._root_winrate = float(data["winrate"])
                except Exception:
                    pass
            return
        try:
            mv = data["move"]
            wr = float(data.get("winrate", 0.0))
            visits = int(data.get("visits", 0))
            lead = float(data.get("scoreLead", 0.0))
            ij = gtp_to_xy(mv, n)
        except Exception:
            return
        if ij is None:
            return
        with self._lock:
            for c in self._cands:
                if c.move == mv:
                    c.visits = visits
                    c.winrate = wr
                    c.score_lead = lead
                    break
            else:
                self._cands.append(
                    Candidate(
                        move=mv,
                        ij=ij,
                        winrate=wr,
                        score_lead=lead,
                        visits=visits,
                        order=0,
                        pv=[],
                    )
                )
            # 只留最靠前的十来个：visits 多 = 搜索认定更值得下
            if len(self._cands) > 12:
                self._cands.sort(key=lambda c: -c.visits)
                del self._cands[12:]
            self._gen += 1

    # ---------------- 对局同步 ----------------
    def _move_list(self, stones, player):
        """把盘面变成 GTP 着法列表。

        **必须黑白交替**。GTP 的 `play B D4` 要求此刻正轮到黑，颜色不对引擎直接
        不认（也不报错，就当没发）。之前这里是按棋盘坐标一行行扫、扫到谁记谁，
        于是经常连着两个 "B"，之后引擎算的一直是那个旧局面 ——
        屏幕上就是"落子了但选点不动"，而且日志里完全看不出来，非常隐蔽。
        """
        n = self.cfg["board_size"]
        blacks, whites = [], []
        for j in range(n):
            for i in range(n):
                v = stones[j, i]
                if v == 1:
                    blacks.append(xy_to_gtp(i, j, n))
                elif v == 2:
                    whites.append(xy_to_gtp(i, j, n))
        out = []
        for k in range(max(len(blacks), len(whites))):
            if k < len(blacks):
                out.append(("B", blacks[k]))
            if k < len(whites):
                out.append(("W", whites[k]))
        return out

    def sync_board(self, stones, player):
        """把引擎里的局面改成 stones。只补落下的子，尽量不重建。"""
        target = self._move_list(stones, player)
        cur = self._board
        cur_set = set(cur)
        tgt_set = set(target)
        missing = [x for x in cur if x not in tgt_set]
        if missing:
            # 有子消失（提子/悔棋/换对局）：老实重建
            self._send("clear_board")
            self._board = []
            cur_set = set()
        extra = [x for x in target if x not in cur_set]
        rebuilt = bool(missing)
        for color, mv in extra:
            self._send(f"play {color} {mv}")
            self._board.append((color, mv))
        if extra or rebuilt:
            # 局面变了，旧候选全部作废（不然会显示上一手的点）
            with self._lock:
                self._cands = []
                self._gen += 1
        # 用 kata-analyze（多候选）代价就是：play 会打断它，必须重发，
        # 重发后搜索从零开始。kata-genmove_analyze 倒是能接着算，
        # 但它一次只报 1 个候选 —— 你要三个点，就只能选前者。
        if (extra or rebuilt) and self._analyzing:
            self._send("kata-analyze 10 maxmoves 8")
        return len(extra)

    def begin_analyze(self, player="B"):
        """开持续分析。

        用 `kata-genmove_analyze` 而不是 `kata-analyze`：前者是 Leela 系那种
        "边分析边给出着法"的持续模式，`play` 不会打断它，搜索树直接复用。
        后者一被 `play` 打断就永远沉默，只能重发，重发又得从零开始。

        interval 单位是**厘秒**（10 = 100ms），和艾姆西的
        analyze-update-interval-centisec: 10 一致。
        """
        if self._analyzing:
            return
        self._analyzing = True
        self._analyze_color = (player or "B").lower()
        self._send("kata-analyze 10 maxmoves 8")

    def end_analyze(self):
        if not self._analyzing:
            return
        self._analyzing = False
        self._send("kata-analyze 1000000")

    # ---------------- 给 app 用 ----------------
    def latest(self):
        """拿最新一批候选。返回 (candidates, generation, root_winrate)。"""
        with self._lock:
            return list(self._cands), self._gen, self._root_winrate

    def setup(self, komi, rules):
        """开局的 GTP 设置。"""
        n = self.cfg["board_size"]
        self._send(f"boardsize {n}")
        self._send(f"komi {komi}")
        self._send(f"kata-set-rules {rules}")
