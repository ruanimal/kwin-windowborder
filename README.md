# Window Border — 给没有窗口装饰的窗口加原生边框

Wayland 会话下，很多窗口完全没有可见的窗口边界：

- **Tauri / WebView 应用**（`decorations: false`）自己画标题栏，KWin 这边既没有标题栏、也没有边框；
- **GTK / libadwaita** 应用自己画 CSD；
- 对 KWin 来说它们就是一块光秃秃的矩形，和桌面背景、以及多个窗口之间都难以分辨（深色壁纸或透明终端上尤其明显）。

这个项目给这类应用加**一圈原生边框**：用 KWin 的窗口规则强制出服务端装饰，再用 Breeze 的「窗口特定覆盖」把标题栏藏掉、边框设为 0，只留那条 1px 的 outline。边框是 KWin 自己画的，所以拖拽、动画、遮挡、圆角、多屏缩放全都不用操心，鼠标还能拖窗口边缘缩放窗口（顶边要 Plasma ≥ 6.8，见下面「版本要求」）。

三个入口，都立即生效：

- **窗口菜单**（`Alt+F3` 或标题栏右键 →「扩展」→「窗口边框」）：给当前窗口的应用加/去边框；
- **设置面板**（系统设置 → 窗口管理 → KWin 脚本 → Window Border → 配置）：维护「启用的应用」名单；
- **命令行** `windowborder-native`：和上面两个入口共用同一份实现。

## 版本要求

| 项目 | 要求 | 原因 |
| --- | --- | --- |
| **Plasma / KWin** | **≥ 6.6**（开发环境：KDE neon / Plasma 6.7.5） | 「用窗口规则强制服务端装饰」这条路是 6.6 才有的：[kwin@bcdceae2](https://invent.kde.org/plasma/kwin/-/commit/bcdceae2) 把重载的 `noborder` 布尔换成了 `DecorationPolicy`，`WindowRules::checkDecorationPolicy()` 里 `noborder=false`（强制）→ `DecorationPolicy::Server`。6.5 及更早的 `XdgToplevelWindow::preferredDecorationMode()` 只会在 `noborder=true` 时返回 `None`，根本没有「强制 Server」这一档，所以对自绘 CSD / 完全不要装饰的客户端（GTK、Tauri `decorations:false`）不生效。 |
| **装饰插件** | 只能是 **Breeze**（`org.kde.breeze`） | 本工具靠 Breeze 的「窗口特定覆盖」（`breezerc` 里的 `[Windeco Exception N]`）按应用隐藏标题栏、把边框设成 0。Oxygen / Aurorae 等没有这套按应用生效的覆盖，换成它们功能不成立。（KDecoration3 版 Breeze 要求 Plasma ≥ 6.3，已被上面的 6.6 下限覆盖。） |
| **会话** | Wayland | 走的是 `xdg-decoration` / `xdg-toplevel-decoration` 那条路。X11 下同样的规则也会命中，但没实测过。 |
| **运行时** | `kpackagetool6`、`qdbus6`（KF6，随 Plasma 6 一起来）、`python3`、`python3-dbus`、`python3-gi` | 安装脚本用 `kpackagetool6` 装 KWin 脚本、`qdbus6` 让 KWin 重读配置；D-Bus 守护进程用 dbus-python + GLib 主循环。deb / PKGBUILD 里都已声明。 |

两条和版本绑定的行为（细则分别在「原理」和「已知限制」里）：

- **顶边缩放要 Plasma ≥ 6.8**：Breeze 6.7 及更早把 `setResizeOnlyBorders()` 的顶边写死成 0，上游已经修了（[breeze@6177e54b](https://invent.kde.org/plasma/breeze/-/commit/6177e54b4b1ef02bf0882be3b7dca1fadbe4f196)，bug [504225](https://bugs.kde.org/show_bug.cgi?id=504225)，FIXED-IN 6.8.0），本工具不需要为此改任何东西；6.7 及更早的兜底见「已知限制」。
- **Plasma ≥ 6.8 会改写规则键**：6.8 用三态 `decorationpolicy` 取代了 `noborder`（[kwin@065adbd3](https://invent.kde.org/plasma/kwin/-/commit/065adbd3)），旧键由 KWin 自己迁移，我们照旧写旧键即可 —— 细节见「原理」。

## 安装

### 发行版包（普通用户，推荐）

KDE neon / Ubuntu 用仓库里的 deb：

```bash
packaging/make-deb.sh                                  # → packaging/build/kwin-windowborder_1.0_all.deb
sudo apt install ./kwin-windowborder_1.0_all.deb        # 或者 Discover 里双击
```

装完**注销重登一次**（让 KWin 加载脚本、并让 D-Bus 服务自启动），之后就完事了 —— 不需要配置、不需要启用命令。包是 `Architecture: all`（纯文本 + 纯 Python），依赖只有 `python3-dbus`、`python3-gi` 和 `kwin-wayland`。

打包细节（deb / PKGBUILD / KDE Store）见 [packaging/README.md](packaging/README.md)。

### 源码（开发者 / 不想装包）

```bash
tools/kwin-windowborder-menu-setup.sh install     # 用户级，不需要 root
```

它做四件事：

1. `kpackagetool6 --type KWin/Script` 把 `extension/` 装到 `~/.local/share/kwin/scripts/windowborder-menu`；
2. 把后端和 D-Bus 服务装到 `~/.local/bin/`，并在 `~/.local/share/dbus-1/services/`、`~/.config/autostart/` 各放一个文件（按需激活 + 登录常驻）；
3. 打开 `kwinrc [Plugins] windowborder-menuEnabled`，把旧脚本实例卸掉再用新文件加载；
4. 按现有名单同步一次规则。

其它子命令：`status` / `restart` / `reapply` / `uninstall`。

## 使用

### 窗口菜单

```
Alt+F3 或 标题栏右键
└── 扩展
    └── 窗口边框
        ├── 已启用边框：dbx        ← 勾选状态 = 这个应用当前在不在名单里
        └── 重新应用边框设置
```

点第一项就是「加/去边框」，1~2 秒后生效（后端要写配置，再让 KWin 和每个装饰重新读一次）。

### 设置面板

系统设置 → 窗口管理 → KWin 脚本 → **Window Border** → 配置，一行「启用的应用」，逗号分隔的窗口类（Wayland 的 `app_id`，例如 `dbx,deepseek-harness-desktop`）。

保存后面板只是写了 `kwinrc [Script-windowborder-menu] apps`；D-Bus 服务盯着这个文件，发现变化就同步成规则，所以同样是立即生效。

### 命令行（同一份逻辑，不走 GUI）

```bash
windowborder-native add dbx                 # 给应用加边框
windowborder-native remove dbx              # 取消
windowborder-native status                  # 查看状态
windowborder-native set BorderSize Tiny     # 换边框粗细
windowborder-native set HideTitleBar false  # 保留标题栏（见「已知限制」）
windowborder-native apply                   # 按当前配置重新生成并生效
windowborder-native reset                   # 清掉本工具的全部配置
```

`add` / `remove` / `set` 内部本来就等于「改配置 + apply」，所以它们一直都是即时生效的。`apply` 单独存在是给「不改配置、只重新生成并生效」用的，主要用于：手改了 `~/.config/windowborder-native.conf`；规则被 KWin 升级、或你在「系统设置 → 窗口规则」里手动删掉而丢失；或者装饰没拿到最新覆盖（下面那个 KGlobalSettings 竞态）时重试。

## 原理

两步都是 KWin/Breeze 的原生机制，没有自研插件、没有补丁。

1. **KWin 窗口规则**（`~/.config/kwinrulesrc`）：每个应用一条 `wmclass=<app_id>` 精确匹配的规则，`noborder=false` + `noborderrule=2`（「无标题栏和边框 = 否，强制」；`Rules::Force`）。`rules.cpp` 里 `checkDecorationPolicy()`：

   ```cpp
   if (checkNoBorder(true, init) == false) return DecorationPolicy::Server;
   ```

   于是该窗口的 `decorationPolicy` 变成 `Server`，KWin 为它创建服务端装饰，并通过 `xdg-decoration` 发 `configure(server_side)` 通知客户端。这条路径从 Plasma 6.6 起存在（见「版本要求」）。

   **Plasma 6.8 起**这套键换成了三态 `decorationpolicy`（`none` / `client-preference` / `server` / `shadow`）。KWin 读 `kwinrulesrc` 时会把我们写的 `noborder=false` + `noborderrule=2` **就地迁移**成 `decorationpolicy=server` + `decorationpolicyrule=2`，并把旧的 `noborder*` 键删掉（`src/rulebooksettings.cpp`，注释写明 Plasma 7 之前保留这条迁移路径），所以功能不受影响、本工具也不用改。唯一的小后果：迁移后的规则内容和我们写的那份不同，`windowborder-native apply` 会因此把规则重建一次（规则 id 会换），下一次被 KWin 迁移回去 —— 只是键名来回，行为不变。

2. **Breeze 窗口特定覆盖**（`~/.config/breezerc`，组 `[Windeco Exception N]`）：按窗口类匹配，设 `HideTitleBar=true`、`BorderSize=None`、`Mask=16`。于是：

   - 边框为 0 → **窗口几何完全不变**，不挤压客户端内容；
   - 隐藏标题栏 → 不会和客户端自己画的标题栏叠成双层；
   - 保留 1px outline → 这就是可见的边框（活动/非活动配色不同）；
   - `BorderSize=None` 时 Breeze 会 `setResizeOnlyBorders(左右/下)` → 鼠标拖这三条边可以缩放窗口（Plasma ≤ 6.7 只有这三条，6.8 起顶边也在内，见「已知限制」）。

**为什么标题栏一定要藏**：我们处理的窗口本来就是「无系统标题栏 + 无装饰」（Tauri/WebView 自绘标题栏，或者 GTK 画 CSD），强制服务端装饰之后装饰自带的标题栏必须藏掉 —— 不藏的话，遵守 `xdg-decoration` 的客户端会撤掉自己的 CSD、换上一个 Breeze 标题栏；不遵守的（Tauri `decorations:false`）会变成「应用自己的标题栏 + Breeze 标题栏」双层。反过来，**有系统标题栏的窗口必然已经有窗口装饰**，它们不在处理范围内。所以 `HideTitleBar=true` + `BorderSize=None` 是写死的默认值，设置面板里也不需要这个开关。

生效方式（后端内置）：

```bash
qdbus6 org.kde.KWin /KWin org.kde.KWin.reconfigure
# reconfigure 是 Q_NOREPLY，等 KWin 处理完（它会重新解析 breezerc），
# 再让每个装饰重取一次设置 —— Breeze 的 Decoration::reconfigure() 挂在这个信号上：
dbus-send --session --type=signal /KGlobalSettings \
          org.kde.KGlobalSettings.notifyChange int32:0 int32:0
```

第二步不能省，否则装饰拿到的是上一轮的覆盖（表现为「慢一拍生效」）。

### 为什么不是自研效果 / 自研装饰插件

- **自研 KWin 效果（C++）**：画边框必须写二进制效果插件（KWin 脚本没有绘制能力）。但那样就等于在合成层之上再画一层，拖拽、窗口动画、遮挡、圆角、多屏缩放全得自己处理，还处理不干净（本项目早期版本就是这么做的，已经删掉了，见提交 `d910de0`）。
- **自研装饰插件**：`DecorationBridge` 全局只加载**一个**装饰插件（`kwinrc [org.kde.kdecoration2] library`），窗口规则里也没有按窗口选插件的选项。自研插件一旦启用就是全桌面生效，非名单内的窗口会全部失去标题栏 —— 除非在插件里重新实现一整套标准装饰。
- 正确做法就是 Breeze **自带的**窗口特定覆盖：它本身就是「装饰插件读配置文件、按应用生效」。

### 为什么需要一个常驻的 D-Bus 服务

KWin 脚本（`KWin/Script` 的 JS 扩展）能用的 API 只有 `readConfig` / `callDBus` / `registerShortcut` / 屏幕边缘 / `registerUserActionsMenu` / `workspace` / `options` / `QTimer`（见 kwin 源码 `src/scripting/scripting.cpp` 里的 `globalProperties` 列表）—— **不能写文件，也不能起进程**。而加边框必须改 `~/.config/kwinrulesrc` 和 `~/.config/breezerc`。所以扩展只做 UI，把「要做什么」用 `callDBus` 交给 `windowborder-daemon`：

| 谁 | 怎么触发 | 结果 |
| --- | --- | --- |
| 窗口菜单 | `callDBus("org.kde.windowborder", …, "AddApp"/"RemoveApp", app)` | 守护进程调后端写配置并生效 |
| 设置面板 | 面板只写 `kwinrc` | 守护进程每 2 秒看一眼 `kwinrc` → 触发同步 |

守护进程的启动有两层，互为兜底：`/usr/share/dbus-1/services/org.kde.windowborder.service`（D-Bus 按需激活，所以点菜单一定能拉起它）和 `/etc/xdg/autostart/windowborder-daemon.desktop`（登录即常驻，这样设置面板那条路随时有人盯着）。两个文件都是"放着就生效"，**不需要任何 per-user 的启用步骤**。

其它要点：

- **缺了它会怎样**：只有扩展本体（比如只从 KDE Store 装了 `.kwinscript`）时，`kwinrc [Script-windowborder-menu] backend=dbus` 没人写，菜单里就只显示一条「后端未安装」的提示，而不是点了没反应；
- **扩展本体装不了守护进程**：`KWin/Script` 的 KPackage 就是一堆文件，`kpackagetool6 -i` 只做拷贝，没有安装钩子，KWin 也不会替脚本跑命令。要么像本仓库这样用安装脚本，要么用发行版包（推荐）；
- 想换后端实现只需要改脚本里 `sendRequest()` 那一处。

### kwinrc 里的三个键

`kwinrc [Script-windowborder-menu]`：

- `apps`：设置面板编辑的就是它（`extension/contents/config/main.xml` 里声明的唯一配置项）；
- `mirror`：后端上一次镜像写下的值，用来区分「面板改了名单」和「我们自己回写造成的回声」，也用来区分「键根本不存在」。语义（`panel_changed_list()`）：`apps` 不存在 → 不当成指令，什么都不做；`apps` 等于 `mirror` → 是回声；其它 → 以 `apps` 为准（空字符串 = 清空名单）。没有 `mirror` 这一层的话，一个键被误删就会被当成「用户清空了名单」，把规则和 Breeze 覆盖一起清掉；
- `backend`：守护进程写下的标记（`dbus`），扩展读它决定菜单里显示真条目还是安装提示。

### 一个坑：`[Plugins]` 键是效果和脚本共用的

KWin 的效果和脚本都从 `kwinrc [Plugins]` 读 `<id>Enabled`。所以脚本 id **不能**叫 `windowborder`（那会和同名的 C++ 效果抢同一个键，互相把对方打开），这里的脚本叫 `windowborder-menu`，配置组因此是 `[Script-windowborder-menu]`。

## 已知限制

- **`decorationPolicy` 是单向的**：加规则会变 `Server`，删规则不会自动回滚（`Window::applyWindowRules()` 里是 `setDecorationPolicy(decorationPolicy())`，把当前值又传了回去）。所以 `remove` 之后，那个窗口要**重启应用**才会完全恢复客户端自带的装饰。
- 会遵守 `xdg-decoration` 的客户端（GTK/libadwaita）收到 `server_side` 后会撤掉自己的 CSD，于是窗口变成「只有边框、没有标题栏」。想让它们保留标题栏，用 `set HideTitleBar false`。
- 不遵守协议的客户端（Tauri `decorations:false`）会保留自己画的标题栏，结果是「应用自己的标题栏 + 一圈边框」——这不是双层标题栏。
- **上边不能拖动缩放（Plasma ≤ 6.7）**：这是「隐藏标题栏 + `BorderSize=None`」在旧版 Breeze 上的直接副作用，不是配置错误。Breeze 的 `recalculateBorders()` 里

  ```cpp
  setResizeOnlyBorders(QMarginsF(extSides, 0, extSides, extBottom));   // 顶边恒为 0（≤ 6.7）
  ```

  上游已经修了：[breeze@6177e54b](https://invent.kde.org/plasma/breeze/-/commit/6177e54b4b1ef02bf0882be3b7dca1fadbe4f196)（bug [504225](https://bugs.kde.org/show_bug.cgi?id=504225)，FIXED-IN 6.8.0）给顶边补上了 `extTop = largeSpacing`，所以 **Plasma ≥ 6.8 四条边都能拖，窗口几何和外观依旧零变化**（加的是窗口外侧一条 `largeSpacing` 宽的输入圈，随字体/缩放约 16px，不抢客户区点击）。还留在 6.7 及更早的话，兜底是默认的 `Meta` + 右键拖拽：它按指针在窗口内的位置取 gravity，在上 1/3 按下就是从顶边缩放（`[MouseBindings] CommandAll3 = MouseUnrestrictedResize`）。

  想在旧版上做到「无痕顶边缩放」，也可以选一个非 `None` 的 `BorderSize`，代价是出现可见实边框并改变窗口几何。各档实测像素占用：

  | `BorderSize` | 上 | 下 | 左 | 右 | 说明 |
  | --- | --- | --- | --- | --- | --- |
  | `None`（默认） | 0 | 0 | 0 | 0 | 只有 1px outline，几何零变化；左/右/下可缩放，**顶边只在 6.8+ 可拖** |
  | `NoSides` | 4.5 | 4.5 | 0 | 0 | 上下为实边框（可抓），左右仍是 resize-only |
  | `Tiny` | 4 | 4 | 2 | 2 | 四面实边框，四条边都可缩放 |
  | `Normal` | 4 | 4 | 4 | 4 | 同上，更粗 |

- 边框**颜色跟随 Breeze 主题与配色方案**，不能单独指定；`BorderSize=None` 只有 1px 细线。
- 全屏窗口不受影响（`preferredDecorationMode()` 对 fullscreen 直接返回 `None`）。
- 从点击到看见边框大约 1~2 秒：后端写文件 → `reconfigure` → 等 KWin 和装饰重取设置。
- 规则只作用于普通窗口（`types=1`）；面板、桌面、通知、工具提示不处理。
- 守护进程常驻一份 Python 进程（约 15~20 MB）。它退出后菜单仍然能用（D-Bus 会按需拉起），但设置面板保存后没人盯着 `kwinrc`，要等下一次菜单操作才会同步。

## 卸载

```bash
tools/kwin-windowborder-menu-setup.sh uninstall   # 卸载扩展、后端和 D-Bus 服务，保留规则
windowborder-native reset                         # 连 kwinrulesrc 规则和 Breeze 覆盖一起清掉
```

用 deb 装的：`sudo apt remove kwin-windowborder`（同样保留已生成的规则；要清干净再跑一次 `reset`）。

## 目录结构

```
extension/metadata.json                    KWin 脚本扩展元数据（KPackage，KWin/Script）
extension/contents/code/main.js            窗口菜单：加/去边框、重新应用、后端缺失提示
extension/contents/config/main.xml         设置面板的配置项（apps）
extension/contents/ui/config.ui            设置面板界面
tools/windowborder-native.py               后端 + 命令行（写 kwinrulesrc/breezerc 的唯一实现）
tools/windowborder-daemon.py               D-Bus 服务：菜单请求 + 盯 kwinrc
tools/kwin-windowborder-menu-setup.sh      用户级安装/卸载/状态/重启/重新应用
packaging/install-layout.sh                系统级布局（打包脚本和 debian/rules 共用这一份清单）
packaging/make-deb.sh                      不依赖 debhelper 直接出 .deb
packaging/pack.sh                          打 KDE Store 用的 .kwinscript
packaging/PKGBUILD                         Arch/AUR 骨架
packaging/files/                           D-Bus 激活 + 自启动的模板
debian/                                    dpkg-buildpackage（PPA / OBS）用的打包目录
man/                                       两个命令行工具的 man page
```

## 许可

GPL-2.0-or-later（与 KWin 插件接口要求一致）。
