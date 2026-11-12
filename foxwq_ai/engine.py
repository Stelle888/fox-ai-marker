"""KataGo analysis 引擎：一个子进程 + 每行一条 JSON。

为什么不走 GTP：analysis 引擎可以直接给"局面 + 初始子"，不需要从头 play 一遍，
也不需要解析 GTP 那一堆非标准返回，重连、丢请求都更容易处理。

协议要点：
  发 {"id":..., "initialStones":[["B","Q16"],...], "initialPlayer":"W",
      "moves":[], "analyzeTurns":[0], ...}
  收 {"id":..., "isDuringSearch":false, "moveInfos":[{"move":"Q16","winrate":0.55,...}]}
"""

import json
import os
import queue
import subprocess
import sys
import threading
import time


def board_size_from_cfg(cfg):
    return int(cfg["board_size"])


# --------------------------------------------------------------------------
# 坐标：KataGo 用 GTP 坐标（A-T 跳过 I，行号从下往上）
# --------------------------------------------------------------------------
GTP_COLS = "ABCDEFGHJKLMNOPQRST"


def gtp_to_xy(move, n):
    """'Q16' -> (i=15, j=2)（左上角为 0,0）。pass 返回 None。"""
    if not move or move.lower() == "pass":
        return None
    move = move.strip().upper()
    try:
        col = GTP_COLS.index(move[0])
        row = int(move[1:])
    except (ValueError, IndexError):
        return None
    if not (1 <= row <= n):
        return None
    return (col, n - row)


def xy_to_gtp(i, j, n):
    return f"{GTP_COLS[i]}{n - j}"


# --------------------------------------------------------------------------
class Candidate:
    __slots__ = ("move", "i", "j", "winrate", "score_lead", "visits", "order", "pv")

    def __init__(self, move, ij, winrate, score_lead, visits, order, pv):
        self.move = move
        self.i, self.j = ij if ij else (-1, -1)
        self.winrate = winrate
        self.score_lead = score_lead
        self.visits = visits
        self.order = order
        self.pv = pv

    def __repr__(self):
        return f"<{self.move} wr={self.winrate:.3f} v={self.visits}>"


class KataGoEngine:
    """后台跑 katago analysis，主线程只读最新结果。"""

    def __init__(self, cfg, log=None):
        self.cfg = cfg
        self.log = log or (lambda *a: None)
        self.proc = None
        self.alive = False
        self.results = {}          # id -> 解析后的结果
        self.lock = threading.Lock()
        self._seq = 0
        self.last_error = ""
        self.ready = False
        self._stderr_tail = []
        self._threads = []

    # ---------------- 生命周期 ----------------
    def start(self):
        exe = self.cfg["katago_exe"]
        model = self.cfg["katago_model"]
        conf = self.cfg["katago_config"]
        for p, name in ((exe, "katago.exe"), (model, "权重"), (conf, "analysis.cfg")):
            if not os.path.exists(p):
                self.last_error = f"找不到{name}: {p}"
                return False
        cmd = [exe, "analysis", "-model", model, "-config", conf]
        self.log("启动引擎:", " ".join(cmd))
        try:
            self.proc = subprocess.Popen(
                cmd,
                cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception as e:
            self.last_error = f"引擎启动失败: {e}"
            return False
        self.alive = True
        t = threading.Thread(target=self._read_stdout, daemon=True)
        t.start()
        self._threads.append(t)
        t = threading.Thread(target=self._read_stderr, daemon=True)
        t.start()
        self._threads.append(t)
        return True

    def stop(self):
        self.alive = False
        if self.proc:
            try:
                if self.proc.stdin:
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
    def _read_stdout(self):
        proc = self.proc
        if proc is None:
            return
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            if line[0] != "{":
                self.ready = True  # 引擎已经有输出了，说明起来了
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if "id" in obj and "moveInfos" in obj:
                self._handle_result(obj)
            elif "id" in obj and "isDuringSearch" not in obj:
                # 错误回包
                self.last_error = str(obj.get("error", obj))[:300]
                self.log("[引擎]", self.last_error)
        self.alive = False
        self.ready = False

    def _read_stderr(self):
        proc = self.proc
        if proc is None:
            return
        for line in proc.stderr:
            line = line.rstrip()
            if not line:
                continue
            self._stderr_tail.append(line)
            if len(self._stderr_tail) > 60:
                self._stderr_tail.pop(0)
            low = line.lower()
            if "ready to begin" in low or "loaded config" in low:
                self.ready = True
            if "error" in low or "failed" in low:
                self.log("[引擎 stderr]", line)

    def _handle_result(self, obj):
        rid = obj.get("id")
        n = self.cfg["board_size"]
        infos = obj.get("moveInfos") or []
        cands = []
        seen = set()
        for m in infos:
            move = m.get("move", "")
            if m.get("isSymmetryOf"):
                continue        # 对称重复的同一个点，跳过
            ij = gtp_to_xy(move, n)
            if ij is None:
                continue        # 过手不标
            if ij in seen:
                continue
            seen.add(ij)
            cands.append(
                Candidate(
                    move=move,
                    ij=ij,
                    winrate=float(m.get("winrate", 0.0)),
                    score_lead=float(m.get("scoreLead", 0.0)),
                    visits=int(m.get("visits", 0)),
                    order=int(m.get("order", 999999)),
                    pv=m.get("pv") or [],
                )
            )
        cands.sort(key=lambda c: c.order)
        with self.lock:
            self.results[rid] = {
                "id": rid,
                "during": bool(obj.get("isDuringSearch")),
                "turn": obj.get("turnNumber", 0),
                "candidates": cands[:12],
                "root_winrate": (obj.get("rootInfo") or {}).get("winrate"),
                "root_score": (obj.get("rootInfo") or {}).get("scoreLead"),
                "time": time.time(),
            }
            # 只留最近 20 个，防止内存慢慢涨
            if len(self.results) > 20:
                for k in sorted(self.results)[:-20]:
                    self.results.pop(k, None)

    # ---------------- 请求 ----------------
    def next_id(self):
        self._seq += 1
        return f"q{self._seq}"

    def analyze(self, stones, player, visits=None, rid=None):
        """stones: n x n，0 空 / 1 黑 / 2 白；player: 'B' 或 'W'（轮到谁）。"""
        if not self.alive or self.proc is None:
            return None
        n = self.cfg["board_size"]
        initial = []
        for j in range(n):
            for i in range(n):
                v = stones[j, i]
                if v == 1:
                    initial.append(["B", xy_to_gtp(i, j, n)])
                elif v == 2:
                    initial.append(["W", xy_to_gtp(i, j, n)])
        rid = rid or self.next_id()
        query = {
            "id": rid,
            "initialStones": initial,
            "initialPlayer": player,
            "moves": [],
            "rules": self.cfg["rules"],
            "komi": self.cfg["komi"],
            "boardXSize": n,
            "boardYSize": n,
            "analyzeTurns": [0],
            "maxVisits": int(visits or self.cfg["max_visits"]),
            "includeOwnership": False,
            "includeMovesOwnership": False,
        }
        try:
            self.proc.stdin.write(json.dumps(query) + "\n")
            self.proc.stdin.flush()
        except Exception as e:
            self.last_error = f"发送失败: {e}"
            return None
        return rid

    def get(self, rid):
        with self.lock:
            return self.results.get(rid)

    def clear(self):
        with self.lock:
            self.results.clear()

    def stderr_tail(self, k=12):
        return "\n".join(self._stderr_tail[-k:])
