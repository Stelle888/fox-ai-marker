# fox-ai-marker

在野狐围棋的棋盘上实时标出 KataGo 认为最好的几个点。
不落子、不摆变化图、不碰野狐的任何文件。

![preview](docs/preview.png)

## 它长什么样

| 待机 | 分析中 |
| --- | --- |
| ![idle](docs/panel_idle.png) | ![running](docs/panel_running.png) |

棋盘上会出现三个发光圆点：**青绿 = 一选，琥珀 = 二选，天蓝 = 三选**，圆里是胜率。

---

## 怎么装

装一次就行。

1. **Python 依赖**

   ```powershell
   pip install -r requirements.txt
   ```

2. **引擎和权重**（约 100 MB，仓库里不带，一条命令下好）

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
   ```

   如果这条命令失败，也可以手动下：
   - 把 [KataGo v1.16.5 Windows OpenCL 版](https://github.com/lightvector/KataGo/releases/tag/v1.16.5) 解压，`katago.exe` 和那些 `.dll` 放进 `katago\`
   - 把 [b18c384nbt 权重](https://github.com/lightvector/KataGo/releases/tag/v1.12.4) 放进 `weights\`

---

## 怎么用

1. 打开野狐，进到**对局页**（能看见棋盘）
2. 双击 `启动.bat`（或者命令行 `python run.py`）
3. 把野狐窗口放到前面，点面板上的 **开始分析**

之后就不用管了。落一手，棋盘上零点零几秒就出点。

- 面板可以按住拖动，默认在屏幕右上角
- 想停就点 **停止分析**，想退出就点右上角的 ✕
- 野狐切到后台时标注自动隐藏，切回来立刻出现
- 野狐关了，或者窗口尺寸变了，程序会自己停或者自己重找棋盘

第一次启动要等几秒（引擎加载）。第一手会慢一点（约 2 秒，GPU 首次推理），
之后每手都在 100 毫秒以内。

---

## 想改点什么

第一次运行会生成 `config.json`，改完重启程序生效。

| 键 | 默认 | 说明 |
| --- | --- | --- |
| `max_visits` | 120 | 每手算多深。嫌不准则调大，但会更慢 |
| `show_candidates` | 3 | 最多标几个点 |
| `dot_radius_ratio` | 0.38 | 圆点大小 |
| `colors` | 青绿/琥珀/天蓝 | 三个点的颜色（hex） |
| `winrate_gap_1stone` | 1.5 | 一选二选胜率差 ≥ 这个值（百分点）就只标一选 |
| `capture_interval_ms` | 150 | 多久看一次棋盘 |
| `overlay_hide_when_other` | true | 野狐不在前台时隐藏标注 |

换权重：把 `*.bin.gz` 丢进 `weights\`，改 `config.json` 里的 `katago_model`。

---

## 标不到点怎么办

程序自己找棋盘，一般不用管。如果状态一直显示"没看到棋盘"：

```powershell
python tools\calibrate.py
```

会弹出野狐截图，先点**左上角那个交叉点**，再点**右下角那个交叉点**，读出棋子数后保存。
注意：野狐窗口大小变了要重新校准。

---

## 常见问题

**第一手慢**
GPU 第一次推理要两秒左右，之后就快了。

**点今天很慢 / 每手都要等好几秒**
`config.json` 里的 `max_visits` 调小（80 左右），或者换个小点的权重。

**白子被认成空点**
换皮肤导致的。跑一次 `tools\calibrate.py`。

**CPU 或风扇一直转**
说明引擎在满负荷算。把 `max_visits` 调小，或者用「停止分析」。

---

## 大致原理

1. 从野狐窗口截一块图（只截棋盘那块，13 毫秒左右）
2. 找出 19×19 网格，在每个交叉点采样，判黑 / 白 / 空
3. 局面变了就问 KataGo，每 0.2 秒收一次中间结果
4. 收到就画 —— 先画出来，后面算得更准了再挪位置
5. 画在一个置顶、点击穿透的透明窗口上，所以不影响下棋

---

## Credits

- [KataGo](https://github.com/lightvector/KataGo) —— 引擎与权重
- [LizzieYzy](https://github.com/yzyray/lizzieyzy) —— 参考它的思路

只读窗口、只画图层，不参与对局操作。

## License

MIT
