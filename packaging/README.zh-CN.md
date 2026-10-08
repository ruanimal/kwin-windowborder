[English](README.md) | **简体中文**

# 打包与发布

这个目录放「怎么把它发给别人」的东西。功能说明看仓库根目录的 [README](../README.zh-CN.md)。

## 产物

| 命令 | 产物 | 给谁 |
| --- | --- | --- |
| `packaging/make-deb.sh` | `packaging/build/kwin-windowborder_<版本>_all.deb` | Debian / KDE neon / Ubuntu 用户（推荐） |
| `packaging/pack.sh` | `packaging/build/windowborder-menu_<版本>.kwinscript` | KDE Store / 「从文件安装」，只含扩展本体 |
| `dpkg-buildpackage -b -uc -us` | 同上的 .deb（走 `debian/` + debhelper） | PPA / OBS / Launchpad |
| `makepkg -si`（`packaging/PKGBUILD`） | Arch 包 | Arch / AUR |

两条 deb 路铺的是同一份清单：`packaging/install-layout.sh`（`debian/rules` 的
`override_dh_auto_install` 调它，`make-deb.sh` 也调它），所以产出内容一致；两个都过
`lintian` 无告警。

## 包里装了什么

```
/usr/share/kwin/scripts/windowborder-menu/           KWin 脚本扩展（窗口菜单 + 设置面板）
/usr/bin/windowborder-native                         后端（写 kwinrulesrc + breezerc，也是 CLI）
/usr/bin/windowborder-daemon                         D-Bus 服务
/usr/share/dbus-1/services/org.kde.windowborder.service    D-Bus 按需激活
/etc/xdg/autostart/windowborder-daemon.desktop       每个用户登录即常驻
/usr/share/man/man1/windowborder-{native,daemon}.1.gz
/usr/share/doc/kwin-windowborder/{copyright,changelog.gz}
```

依赖：`python3`、`python3-dbus`、`python3-gi`、`kwin-wayland (>= 4:6.6) | kwin-x11 (>= 4:6.6)`
（Arch 对应 `kwin>=6.6`）。KWin 的下限不是随手写的：强制服务端装饰的规则语义
（`noborder=false` → `DecorationPolicy::Server`）是 Plasma 6.6 才有的，更早的版本会收下
规则但不生效 —— 所以让包管理器直接挡住，而不是装完发现没反应。细节见根目录 README 的
「版本要求」。全是文本 + 纯 Python，所以 `Architecture: all`，一个包能给同级 Ubuntu/neon 用。

扩展的 `metadata.json` 里 `EnabledByDefault: true`：系统装的 KPackage 装完即启用，
不用写用户的 `kwinrc`；D-Bus 激活和 `/etc/xdg/autostart` 都是"放着就生效"，
所以**没有任何 per-user 的启用步骤**。

## 普通用户要做什么

1. 装包：Discover 里双击那个 `.deb`，或者 `sudo apt install ./kwin-windowborder_1.0_all.deb`；
2. **注销重登一次**（KWin 会在这时候加载脚本扩展，自启动也会把 D-Bus 服务带起来）；
3. 用：任意窗口标题栏右键（或 `Alt+F3`）→ 扩展 → 窗口边框 → 给这个应用加边框。

包安装时没有用户会话，所以第 2 步躲不掉（装不了 per-user 的自启动，也没法通知正在跑的
KWin）。重登之后一切自动。

## 发布渠道

- **KDE Store**（`store.kde.org`，KWin Scripts 分类）：只上传 `.kwinscript`。
  KWin 脚本 KCM 自带「获取新脚本」（`/usr/share/knsrcfiles/kwinscripts.knsrc`），
  用户一键就能装扩展本体。**但它装不了后端**（KWin/Script 的 KPackage 没有安装钩子，
  里面也不能放可执行文件和 `.service`），所以只走 Store 的用户会看到菜单里提示
  「后端未安装」。要么再让用户装 deb，要么把 Store 只当"扩展本体 + 更新"渠道。
- **发行版包**：把 `make-deb.sh` 的产物放进 PPA，或者把 `debian/` 提交给 OBS/Launchpad；
  Arch 用户走 AUR（`packaging/PKGBUILD` 里的 `source` 指向 GitHub 上的 tag 归档）。
- **源码**：`git clone && tools/kwin-windowborder-menu-setup.sh install`（用户级，不需要 root）。

## CI

`.github/workflows/build.yml` 已经在仓库里，三个 job：

| job | 做什么 |
| --- | --- |
| `packages` | 语法检查（py_compile / bash -n / node --check / XML+JSON）→ `make-deb.sh` + `pack.sh` → `lintian --fail-on error` → 传 artifact |
| `debian-dir` | 装 debhelper 跑一遍 `dpkg-buildpackage -b -uc -us` + lintian，保证 PPA/OBS 那条路不会悄悄坏掉（和 `packages` 铺的是同一份清单） |
| `release` | 只在推 `v*` tag 时跑：下载 artifact，用 `gh release create` 建 Release 并挂上 `.deb` + `.kwinscript` |

推 tag 时 workflow 会先用 tag 号改写 `extension/metadata.json` 和 `debian/changelog`
（`v1.1.0-rc1` → `1.1.0~rc1`，native 包的版本里不能有 `-`），所以发出来的包版本和
tag 一致。平时推 master / PR 只构建不发布；两边版本不一致时给一条 warning。

本地等价命令（和 CI 里的一模一样）：

```bash
python3 -m py_compile tools/*.py && node --check extension/contents/code/main.js
packaging/make-deb.sh && packaging/pack.sh
lintian --fail-on error packaging/build/kwin-windowborder_*_all.deb
```

## 已知的坑

- **`[Plugins]` 键是效果和脚本共用的**：`kwinrc [Plugins] <id>Enabled`。所以脚本 id 是
  `windowborder-menu`；系统装的 KPackage 靠 `EnabledByDefault` 启用，不再写用户的 kwinrc；
- **不要用 `#!/usr/bin/env python3` 启动守护进程**：PATH 里排前面的可能是 venv/conda 的
  解释器，那里没有 `python3-dbus`。`.service` / autostart 里写的是
  `/usr/bin/python3 /usr/bin/windowborder-daemon`，用户级安装同理（见 setup 脚本的
  `python_bin()`）；
- **更新脚本后必须 unload 再 load**：KWin 不会重新运行已经加载的脚本，只覆盖文件不算数。
  setup 脚本的 `install` 里带了这一步；
- **`dpkg-buildpackage` 会把产物写到上级目录**（`../kwin-windowborder_*`），
  `.gitignore` 里已经忽略了 `packaging/build/`、`*.deb`、`*.kwinscript` 和 `debian/` 的构建残留。
