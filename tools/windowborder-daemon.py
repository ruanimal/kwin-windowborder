#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
#
# Window Border 的 D-Bus 后端服务。
#
# 为什么需要它：KWin 脚本（extension/contents/code/main.js）只能 readConfig /
# callDBus / 注册快捷键和窗口菜单，**不能写文件、不能起进程**，而给窗口加边框必须写
# ~/.config/kwinrulesrc 和 ~/.config/breezerc。这个守护进程就是那条通路：
#
#   窗口菜单点击 → callDBus(org.kde.windowborder /WindowBorder AddApp "dbx")
#   这里 → subprocess 调 windowborder-native.py request add:dbx → 写配置并让 KWin 重新读
#
# 同时它每 2 秒看一眼 kwinrc：设置面板保存只是写了
# kwinrc [Script-windowborder-menu] apps，KWin 自己不会重新解析，脚本也不会重跑
# （kcm_kwin4_genericscripted 的 ScriptingConfig::reload() 是 TODO），所以必须有人
# 盯着它 → 触发一次同步。这也是为什么本服务需要常驻（退出后只剩菜单那条路可用）。
#
# 依赖：python3-dbus、python3-gi（发行版里都是现成包）。不需要 systemd。

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

try:
    import dbus
    import dbus.service
    from dbus.mainloop.glib import DBusGMainLoop
    from gi.repository import GLib
except ImportError as exc:  # pragma: no cover - 环境问题，直接说清楚
    sys.exit(f"windowborder-daemon: 需要 python3-dbus 和 python3-gi（{exc}）")

BUS_NAME = "org.kde.windowborder"
OBJECT_PATH = "/WindowBorder"
INTERFACE = "org.kde.windowborder"

CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
KWINRC = CONFIG_HOME / "kwinrc"
SCRIPT_GROUP = "Script-windowborder-menu"
# 告诉扩展「后端装好了」的标记，扩展读不到它就只在菜单里显示安装提示。
BACKEND_KEY = "backend"
BACKEND_VALUE = "dbus"

# kwinrc 的轮询间隔（秒）。写配置的是我们自己或 KCM，2 秒足够及时，
# 代价也只是每 2 秒一次 stat()。
POLL_SECONDS = 2


def log(message: str) -> None:
    print(f"[windowborder-daemon] {message}", file=sys.stderr, flush=True)


def find_backend() -> Path | None:
    """后端脚本的位置：先看自己旁边（打包/用户级安装都是同一目录），再找 PATH。"""
    here = Path(__file__).resolve().parent
    for candidate in (here / "windowborder-native", here / "windowborder-native.py"):
        if candidate.is_file():
            return candidate
    found = shutil.which("windowborder-native")
    return Path(found) if found else None


class Backend:
    """后端就是 windowborder-native.py 的 request 子命令，一行都不重复实现。"""

    def __init__(self, python: str, script: Path, verbose: bool):
        self.python = python
        self.script = script
        self.verbose = verbose

    def run(self, request: str) -> bool:
        cmd = [self.python, str(self.script), "request", request]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True)
        except OSError as exc:
            log(f"无法执行后端: {exc}")
            return False
        if proc.returncode != 0:
            log(f"request {request} 失败: {proc.stderr.strip() or proc.stdout.strip()}")
        elif self.verbose and proc.stdout.strip():
            log(f"request {request}: {proc.stdout.strip()}")
        return proc.returncode == 0

    def apps(self) -> list[str]:
        cmd = [self.python, str(self.script), "request", "list"]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True)
        except OSError:
            return []
        if proc.returncode != 0:
            return []
        return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


class KwinrcWatcher:
    """盯着 kwinrc：设置面板一保存就把名单同步成规则。

    比较 (mtime_ns, size)，变化后等一小会儿让写入落定再同步；同步完刷新基线，
    所以我们自己镜像回写 kwinrc 造成的变化不会再来一轮（后端那边也有 mirror 回执
    做第二层保护）。
    """

    def __init__(self, sync=None):
        self._sync = sync
        self._signature = self._stat()
        self._dirty_since: float | None = None

    def _stat(self) -> tuple[int, int] | None:
        try:
            info = KWINRC.stat()
        except OSError:
            return None
        return (info.st_mtime_ns, info.st_size)

    def set_sync(self, sync) -> None:
        self._sync = sync

    def note_own_write(self) -> None:
        """我们刚写过 kwinrc：把基线更新掉，别把自己写的东西当成面板改动。"""
        self._signature = self._stat()
        self._dirty_since = None

    def poll(self) -> bool:
        current = self._stat()
        if current != self._signature:
            if self._dirty_since is None:
                self._dirty_since = time.monotonic()
            elif time.monotonic() - self._dirty_since >= POLL_SECONDS / 2:
                self._signature = current
                self._dirty_since = None
                if self._sync is not None:
                    self._sync()
            return True
        self._dirty_since = None
        return True


class WindowBorderService(dbus.service.Object):
    def __init__(self, bus_name, backend: Backend, watcher: KwinrcWatcher, verbose: bool):
        super().__init__(bus_name, OBJECT_PATH)
        self.backend = backend
        self.watcher = watcher
        self.verbose = verbose
        self.loop: GLib.MainLoop | None = None
        self.write_backend_marker()

    # ------------------------------------------------------------------ D-Bus

    @dbus.service.method(INTERFACE, in_signature="s", out_signature="b")
    def AddApp(self, app):
        """给一个应用加边框（列表里已有也算成功）。"""
        ok = self.backend.run(f"add:{app}")
        self.watcher.note_own_write()
        return ok

    @dbus.service.method(INTERFACE, in_signature="s", out_signature="b")
    def RemoveApp(self, app):
        """取消一个应用的边框。"""
        ok = self.backend.run(f"remove:{app}")
        self.watcher.note_own_write()
        return ok

    @dbus.service.method(INTERFACE, in_signature="", out_signature="b")
    def Sync(self):
        """把 kwinrc 里的名单同步成规则（设置面板保存后走这条）。"""
        ok = self.backend.run("panel")
        self.watcher.note_own_write()
        return ok

    @dbus.service.method(INTERFACE, in_signature="", out_signature="b")
    def Reapply(self):
        """按当前名单重新生成并生效（修漂移、或装饰没拿到最新覆盖时用）。"""
        ok = self.backend.run("reapply")
        self.watcher.note_own_write()
        return ok

    @dbus.service.method(INTERFACE, in_signature="", out_signature="as")
    def GetApps(self):
        return self.backend.apps()

    @dbus.service.method(INTERFACE, in_signature="", out_signature="s")
    def Version(self):
        return "1.0"

    @dbus.service.method(INTERFACE, in_signature="", out_signature="b")
    def Quit(self):
        """卸载时用它停掉守护进程（比 pkill 猜进程靠谱）。"""
        if self.loop is not None:
            GLib.idle_add(self.loop.quit)
        return True

    # ----------------------------------------------------------------- 内部

    def write_backend_marker(self) -> bool:
        """往 kwinrc [Script-windowborder-menu] 写 backend=dbus。

        扩展读这个键决定菜单里显示"加/去边框"还是"后端未安装"。
        设置面板保存时 KConfigSkeleton 只写自己声明的项，理论上不会动它；
        万一被动过，每次请求和每次同步都会补回来。
        """
        try:
            current = subprocess.run(
                ["kreadconfig6", "--file", "kwinrc", "--group", SCRIPT_GROUP,
                 "--key", BACKEND_KEY, "--default", ""],
                capture_output=True, text=True)
            if current.stdout.strip() == BACKEND_VALUE:
                return False
            subprocess.run(
                ["kwriteconfig6", "--file", "kwinrc", "--group", SCRIPT_GROUP,
                 "--key", BACKEND_KEY, BACKEND_VALUE],
                capture_output=True, text=True, check=False)
        except OSError:
            return False
        return True

    def sync_from_kwinrc(self) -> None:
        self.write_backend_marker()
        ok = self.backend.run("panel")
        self.watcher.note_own_write()
        if self.verbose:
            log(f"kwinrc 变化 → 同步: {'ok' if ok else 'failed'}")


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="windowborder-daemon",
        description="Window Border 的 D-Bus 后端（窗口菜单和设置面板都通过它写配置）",
    )
    parser.add_argument("--backend", type=Path, default=None,
                        help="windowborder-native.py 的路径（默认：自己旁边，或 PATH 里）")
    parser.add_argument("--python", default=sys.executable,
                        help="跑后端用的解释器（默认：当前解释器）")
    parser.add_argument("--no-watch", action="store_true",
                        help="不盯 kwinrc（只提供 D-Bus 接口）")
    parser.add_argument("--verbose", action="store_true", help="把每次请求都打到 stderr")
    args = parser.parse_args()

    backend_path = args.backend or find_backend()
    if backend_path is None or not backend_path.is_file():
        log("找不到 windowborder-native.py（用 --backend 指定）")
        return 1
    if not os.access(backend_path, os.R_OK):
        log(f"读不了后端: {backend_path}")
        return 1

    DBusGMainLoop(set_as_default=True)
    bus = dbus.SessionBus()
    try:
        bus_name = dbus.service.BusName(BUS_NAME, bus=bus, do_not_queue=True)
    except dbus.exceptions.NameExistsException:
        log(f"{BUS_NAME} 已经被另一个实例占着，退出")
        return 0

    backend = Backend(args.python, backend_path, args.verbose)
    watcher = KwinrcWatcher()
    service = WindowBorderService(bus_name, backend, watcher, args.verbose)
    watcher.set_sync(service.sync_from_kwinrc)

    if not args.no_watch:
        GLib.timeout_add_seconds(POLL_SECONDS, watcher.poll)

    log(f"已就绪: {BUS_NAME}{OBJECT_PATH}，后端 {backend_path}")
    service.loop = GLib.MainLoop()
    service.loop.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
