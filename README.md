# fox-ai-marker

在野狐围棋的棋盘上，标出 AI 觉得值得下的几个点。

![preview](docs/preview.png)

> **只用来提高棋力，别用来作弊。**
>
> 它不会替你落子，不点棋盘，不碰野狐的任何东西。
> 下完再看，看 AI 当时是怎么想的 —— 那才涨棋。
> 在线对局里当提示器是作弊，后果自负。

---

## 下载

到 [Releases](https://github.com/Stelle888/fox-ai-marker/releases/latest) 下 `fox-ai-marker-win64.zip`（约 300 MB），解压即可。

**不用装 Python**，不用装引擎。引擎、权重、Python 运行时都在包里的：

```
fox-ai-marker\
├─ 启动.bat            ← 双击这个
├─ python\            ← 自带的 Python（别删）
├─ katago\katago.exe  ← 引擎
└─ weights\           ← 权重
```

---

## 用

1. 打开野狐，进**对局页**（能看见棋盘）。
2. 双击 **`启动.bat`**。
3. 把野狐窗口放前面，点面板上的 **开始分析**。

落一手，棋盘上马上出点：

- 🟢 **青绿 = 一选**　🟡 **琥珀 = 二选**　🔵 **天蓝 = 三选**
- 圆里是胜率
- 一选二选差得多时，只标一选

点会先冒出来，然后随搜索加深微调一两次，一两秒后稳住。

---

## 面板

| 操作 | 效果 |
| --- | --- |
| 按住空白处拖 | 挪位置 |
| **停止分析** | 清掉标注、停止 |
| **✕** | 退出程序 |

野狐切到后台，标注自动隐藏；切回来立刻出现。

第一次启动等十几秒（引擎加载），之后就好了。

---

## 复盘时怎么用

对局结束 → 打开这盘的回放 → 一手一手往回翻。

每翻一手，标注就更新一次。这就是看「当时 AI 觉得该下哪、你实际下在哪」最快的办法。

---

## 想调

第一次运行生成 `config.json`，改完重启生效：

| 键 | 默认 | 说明 |
| --- | --- | --- |
| `max_visits` | 120 | 每手算多深，调大更准但更慢 |
| `show_candidates` | 3 | 最多标几个点 |
| `dot_radius_ratio` | 0.38 | 圆点大小 |
| `capture_interval_ms` | 80 | 多久看一次棋盘 |

标不到点（换了皮肤）：`python tools\calibrate.py`，按提示点两下棋盘角。

---

## Credits

引擎 [KataGo](https://github.com/lightvector/KataGo)（MIT），
判子思路参考 [LizzieYzy](https://github.com/yzyray/lizzieyzy)。

## License

MIT
