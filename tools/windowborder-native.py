#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 KWin Window Border effect contributors
# SPDX-License-Identifier: GPL-2.0-or-later
#
# Window Border (native) — 按应用给窗口加边框，走 KWin/Breeze 原生装饰管线。
#
# 原理（KWin 6.7.x 实测）：
#   1) 窗口规则「无标题栏和边框 = 否 + 强制」会把该窗口的 decorationPolicy
#      变成 Server（见 kwin/src/rules.cpp checkDecorationPolicy），于是 KWin
#      为该窗口创建服务端装饰。
#   2) Breeze 的「窗口特定覆盖」(breezerc [Windeco Exception N]) 按窗口类正则
#      匹配，可以设 HideTitleBar=true + BorderSize=None：
#        - 边框为 0        → 窗口几何完全不变（不挤压客户端内容）
#        - 隐藏标题栏      → 不会和客户端自己的标题栏叠成双层
#        - 保留 1px outline → 这就是可见的边框（活动/非活动配色不同）
#        - BorderSize=None 时 Breeze 会 setResizeOnlyBorders(左右/下)
#                          → 鼠标拖边框可以缩放窗口
#
# 两条配置分别落在 ~/.config/kwinrulesrc 和 ~/.config/breezerc。

from __future__ import annotations

import argparse
import fcntl
import os
import re
import shutil
import subprocess
import time
import sys
import uuid
from pathlib import Path

CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
KWINRULES = CONFIG_HOME / "kwinrulesrc"
BREEZERC = CONFIG_HOME / "breezerc"
OUR_CONFIG = CONFIG_HOME / "windowborder-native.conf"
KWINRC = CONFIG_HOME / "kwinrc"
LOCK_FILE = CONFIG_HOME / "windowborder-native.lock"

# KWin 脚本扩展（窗口菜单 + 设置面板）把「启用的应用」放在 kwinrc 的这个组里，
# 设置面板由 kcm_kwin4_genericscripted 按 contents/config/main.xml 读写它。
SCRIPT_GROUP = "Script-windowborder-menu"
SCRIPT_APPS_KEY = "apps"
# 我们最后一次镜像写进 kwinrc 的名单。用来区分「设置面板改过」和「我们自己回写造成的
# 回声」，也用来区分「键不存在」——否则 apps 键被删掉会被误当成「用户清空了名单」。
SCRIPT_MIRROR_KEY = "mirror"

RULE_PREFIX = "windowborder: "
EXCEPTION_GROUP = "Windeco Exception {}"
EXCEPTION_MASK_BORDER_SIZE = 1 << 4  # Breeze::BorderSize

# Breeze InternalSettings::BorderSize 枚举下标
BORDER_SIZES = {
    "None": 0,
    "NoSides": 1,
    "Tiny": 2,
    "Normal": 3,
    "Large": 4,
    "VeryLarge": 5,
    "Huge": 6,
    "VeryHuge": 7,
    "Oversized": 8,
}


# --------------------------------------------------------------------------
# KConfig (INI) 最小读写：保留组的顺序和未知内容
# --------------------------------------------------------------------------

class Group:
    def __init__(self, name: str):
        self.name = name
        self.lines: list[tuple[str, str | None]] = []  # (key, value) 或 ("#raw", None)

    def get(self, key: str, default: str | None = None) -> str | None:
        for k, v in self.lines:
            if k == key:
                return v
        return default

    def set(self, key: str, value: str) -> None:
        for i, (k, _) in enumerate(self.lines):
            if k == key:
                self.lines[i] = (key, value)
                return
        self.lines.append((key, value))

    def pop(self, key: str) -> None:
        self.lines = [(k, v) for (k, v) in self.lines if k != key]


def read_kconfig(path: Path) -> list[Group]:
    groups: list[Group] = []
    current: Group | None = None
    if not path.exists():
        return groups
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            current = Group(line[1:-1])
            groups.append(current)
            continue
        if line.startswith("#") or line.startswith(";"):
            if current is not None:
                current.lines.append(("#raw", raw))
            continue
        if current is None:
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            current.lines.append((key.strip(), value))
    return groups


def render_kconfig(groups: list[Group]) -> str:
    out: list[str] = []
    for g in groups:
        out.append(f"[{g.name}]")
        for k, v in g.lines:
            out.append(v if k == "#raw" else f"{k}={v}")
        out.append("")
    return "\n".join(out).rstrip("\n") + "\n"


def write_kconfig(path: Path, groups: list[Group]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".windowborder-tmp")
    tmp.write_text(render_kconfig(groups), encoding="utf-8")
    tmp.replace(path)


def apply_groups(path: Path, mutate) -> bool:
    """读-改-写一个 KConfig 文件；内容没变化就不落盘。

    返回是否真的改了文件。用来避免无谓的写盘 —— 尤其是 kwinrc：扩展的设置面板
    由 systemd path 单元盯着，多余的写入会白白再触发一轮同步。
    """
    groups = read_kconfig(path)
    before = render_kconfig(groups)
    mutate(groups)
    after = render_kconfig(groups)
    if before == after or not after.strip():
        return False
    write_kconfig(path, groups)
    return True


class apply_lock:
    """同一时刻只允许一个 apply 在跑。

    菜单请求（windowborder@add:...）和设置面板请求（path 单元触发）是两条独立的
    systemd 任务，几乎同时到达时会互相覆盖配置，所以串行化。
    """

    def __enter__(self):
        CONFIG_HOME.mkdir(parents=True, exist_ok=True)
        self._fh = open(LOCK_FILE, "w", encoding="utf-8")
        fcntl.flock(self._fh, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc_info):
        fcntl.flock(self._fh, fcntl.LOCK_UN)
        self._fh.close()



def find_group(groups: list[Group], name: str) -> Group | None:
    for g in groups:
        if g.name == name:
            return g
    return None


def ensure_group(groups: list[Group], name: str) -> Group:
    g = find_group(groups, name)
    if g is None:
        g = Group(name)
        groups.append(g)
    return g


# --------------------------------------------------------------------------
# 我们自己的配置
# --------------------------------------------------------------------------

def read_our_config() -> tuple[list[str], dict[str, str]]:
    groups = read_kconfig(OUR_CONFIG)
    general = find_group(groups, "General")
    apps: list[str] = []
    opts = {"BorderSize": "None", "HideTitleBar": "true"}
    if general:
        raw = general.get("Apps", "") or ""
        apps = [a for a in (x.strip() for x in raw.split(",")) if a]
        for key in opts:
            val = general.get(key)
            if val is not None:
                opts[key] = val
    return apps, opts


def write_our_config(apps: list[str], opts: dict[str, str], managed: list[str]) -> bool:
    def mutate(groups: list[Group]) -> None:
        general = Group("General")
        general.set("Apps", ",".join(apps))
        general.set("BorderSize", opts["BorderSize"])
        general.set("HideTitleBar", opts["HideTitleBar"])
        state = Group("State")
        state.set("ManagedApps", ",".join(managed))
        groups[:] = [general, state]

    return apply_groups(OUR_CONFIG, mutate)


def read_managed() -> list[str]:
    groups = read_kconfig(OUR_CONFIG)
    state = find_group(groups, "State")
    raw = (state.get("ManagedApps", "") if state else "") or ""
    return [a for a in (x.strip() for x in raw.split(",")) if a]


# --------------------------------------------------------------------------
# kwinrc：扩展的窗口菜单和设置面板读它，和上面的配置文件保持同一份应用列表
# --------------------------------------------------------------------------

def read_script_group() -> Group | None:
    return find_group(read_kconfig(KWINRC), SCRIPT_GROUP)


def read_script_apps() -> list[str]:
    group = read_script_group()
    raw = (group.get(SCRIPT_APPS_KEY, "") if group else "") or ""
    return [a for a in (x.strip() for x in raw.split(",")) if a]


def panel_changed_list() -> list[str] | None:
    """kwinrc 里的名单是不是被设置面板（或手改）动过；是则返回新名单。

    判断依据（缺一不可，否则会误伤）：
      - apps 键不存在 → 不是给我们的信号，返回 None。
        设置面板保存时 KConfigSkeleton 会把「所有」注册项写盘，清空也是写 apps=，
        所以「键不存在」只可能是手改/误删；这时候绝不能当成「用户清空了名单」，
        否则一个键消失就会把名单连同 kwinrulesrc/breezerc 里的规则一起清掉。
      - apps 等于我们上次镜像写下的 mirror → 我们自己回写的回声，返回 None。
      - 其它 → 面板改了名单，以它为准；空字符串代表用户把名单清空了。
    """
    group = read_script_group()
    if group is None:
        return None

    apps_raw = group.get(SCRIPT_APPS_KEY)
    if apps_raw is None:
        return None

    mirror_raw = group.get(SCRIPT_MIRROR_KEY)
    apps = [a for a in (x.strip() for x in apps_raw.split(",")) if a]
    if mirror_raw is not None:
        mirror = [a for a in (x.strip() for x in mirror_raw.split(",")) if a]
        if sorted(apps) == sorted(mirror):
            return None
    return apps


def mirror_script_apps(apps: list[str]) -> bool:
    """把应用列表写进 kwinrc [Script-windowborder-menu]（apps + mirror 两个键）。

    菜单 add/remove 后写这里，让设置面板看到同一份名单；设置面板改这里，
    由 systemd path 单元触发同步（见 tools/kwin-windowborder-menu-setup.sh）。

    读用我们自己的解析器，写优先交给 kwriteconfig6 —— kwinrc 是 KWin 自己的配置文件，
    不想被我们重排。
    """
    value = ",".join(apps)
    if sorted(read_script_apps()) == sorted(apps) and (read_script_mirror() or "") == value:
        return False

    if shutil.which("kwriteconfig6"):
        rc = run(["kwriteconfig6", "--file", "kwinrc", "--group", SCRIPT_GROUP,
                  "--key", SCRIPT_APPS_KEY, value])
        rc |= run(["kwriteconfig6", "--file", "kwinrc", "--group", SCRIPT_GROUP,
                   "--key", SCRIPT_MIRROR_KEY, value])
        if rc == 0:
            return True

    def mutate(groups: list[Group]) -> None:
        group = ensure_group(groups, SCRIPT_GROUP)
        group.set(SCRIPT_APPS_KEY, value)
        group.set(SCRIPT_MIRROR_KEY, value)

    return apply_groups(KWINRC, mutate)


def read_script_mirror() -> str | None:
    group = read_script_group()
    return group.get(SCRIPT_MIRROR_KEY) if group else None


# --------------------------------------------------------------------------
# kwinrulesrc：每个应用一条规则，强制服务端装饰
# --------------------------------------------------------------------------

def strip_our_rules(groups: list[Group]) -> list[str]:
    removed: list[str] = []
    general = find_group(groups, "General")
    listed = []
    if general:
        listed = [x.strip() for x in (general.get("rules", "") or "").split(",") if x.strip()]

    keep: list[str] = []
    for g in groups:
        if g.name == "General":
            continue
        desc = g.get("Description", "") or ""
        if desc.startswith(RULE_PREFIX):
            removed.append(g.name)
        else:
            keep.append(g.name)

    listed = [r for r in listed if r not in removed]
    groups[:] = [g for g in groups if g.name == "General" or g.name in keep]

    if general is not None:
        general.set("count", str(len(listed)))
        general.set("rules", ",".join(listed))
    return removed


def expected_rule(app: str) -> dict[str, str]:
    return {
        "Description": f"{RULE_PREFIX}{app}",
        "types": "1",  # Normal window
        "wmclass": app,
        "wmclassmatch": "1",  # 精确匹配
        "noborder": "false",
        "noborderrule": "2",  # Force
    }


def rules_up_to_date(apps: list[str]) -> bool:
    """现有规则是否已经正好是这批应用。规则 id 是随机的，只能按内容判断。"""
    groups = read_kconfig(KWINRULES)
    ours = [g for g in groups if (g.get("Description", "") or "").startswith(RULE_PREFIX)]
    if len(ours) != len(set(apps)):
        return False
    by_app = {g.get("Description", "")[len(RULE_PREFIX):]: g for g in ours}
    for app in set(apps):
        rule = by_app.get(app)
        if rule is None:
            return False
        if any(rule.get(key) != value for key, value in expected_rule(app).items()):
            return False
    return True


def build_rules(apps: list[str]) -> bool:
    """按应用列表重建规则；已经是最新状态就什么都不做。

    必须在同一次读-改-写里把所有规则都加上：strip_our_rules() 会剥掉全部本工具的
    规则，如果每个应用各调用一次读-改-写，后面的调用会把前面的规则冲掉。
    """
    if rules_up_to_date(apps):
        return False

    def mutate(groups: list[Group]) -> None:
        strip_our_rules(groups)

        general = ensure_group(groups, "General")
        listed = [x.strip() for x in (general.get("rules", "") or "").split(",") if x.strip()]

        for app in apps:
            rule_id = str(uuid.uuid4())
            rule = Group(rule_id)
            for key, value in expected_rule(app).items():
                rule.set(key, value)
            groups.append(rule)
            listed.append(rule_id)

        general.set("count", str(len(listed)))
        general.set("rules", ",".join(listed))

    return apply_groups(KWINRULES, mutate)


# --------------------------------------------------------------------------
# breezerc：每个应用一条窗口特定覆盖
# --------------------------------------------------------------------------

def bump_exception_groups(groups: list[Group]) -> tuple[list[Group], list[Group]]:
    """把 [Windeco Exception N] 抽出来，其余原样保留。"""
    exceptions = [g for g in groups if re.fullmatch(r"Windeco Exception \d+", g.name)]
    others = [g for g in groups if g not in exceptions]
    return others, exceptions


def apply_exceptions(apps: list[str], opts: dict[str, str], managed: list[str]) -> bool:
    def mutate(groups: list[Group]) -> None:
        others, exceptions = bump_exception_groups(groups)

        # 我们的异常：pattern 正好等于我们管理过的某个应用 id
        owned = set(managed) | set(apps)
        kept = [g for g in exceptions if (g.get("ExceptionPattern", "") or "") not in owned]

        for app in apps:
            g = Group("")  # 名字稍后统一重排
            g.set("Enabled", "true")
            g.set("ExceptionType", "0")  # ExceptionWindowClassName
            g.set("ExceptionPattern", app)
            g.set("HideTitleBar", opts["HideTitleBar"])
            g.set("Mask", str(EXCEPTION_MASK_BORDER_SIZE))
            g.set("BorderSize", str(BORDER_SIZES.get(opts["BorderSize"], 0)))
            kept.append(g)

        result = list(others)
        result.extend(Group(EXCEPTION_GROUP.format(i)) for i in range(len(kept)))
        for i, src in enumerate(kept):
            result[len(others) + i].lines = list(src.lines)

        groups[:] = result

    return apply_groups(BREEZERC, mutate)


def remove_all_exceptions(managed: list[str]) -> bool:
    def mutate(groups: list[Group]) -> None:
        others, exceptions = bump_exception_groups(groups)
        kept = [g for g in exceptions if (g.get("ExceptionPattern", "") or "") not in set(managed)]
        result = list(others)
        result.extend(Group(EXCEPTION_GROUP.format(i)) for i in range(len(kept)))
        for i, src in enumerate(kept):
            result[len(others) + i].lines = list(src.lines)
        groups[:] = result

    return apply_groups(BREEZERC, mutate)


# --------------------------------------------------------------------------
# 生效
# --------------------------------------------------------------------------

def notify_kg() -> None:
    """让每个 Breeze Decoration 重新取一次 InternalSettings。

    Breeze 的 Decoration::reconfigure() 挂在这个信号上；少了它，装饰就拿不到
    更新后的窗口特定覆盖。
    """
    if shutil.which("dbus-send"):
        run([
            "dbus-send", "--session", "--type=signal", "/KGlobalSettings",
            "org.kde.KGlobalSettings.notifyChange", "int32:0", "int32:0",
        ])
    elif shutil.which("gdbus"):
        run([
            "gdbus", "emit", "--session", "--object-path", "/KGlobalSettings",
            "--signal", "org.kde.KGlobalSettings.notifyChange", "0", "0",
        ])


def reload_kwin() -> None:
    # 顺序很重要：
    #   1. reconfigure 是 Q_NOREPLY，调用立刻返回；KWin 随后才会重新读配置，
    #      经 Workspace::configChanged -> SettingsImpl::readSettings()
    #      -> DecorationSettings::reconfigured -> SettingsProvider::reconfigure()
    #      把 breezerc 重新解析一遍。
    #   2. 等它处理完，再发 KGlobalSettings 信号让 Decoration 取新设置。
    # 两步之间不等待的话，装饰会拿到上一轮的覆盖（表现为"慢一拍生效"）。
    run(["qdbus6", "org.kde.KWin", "/KWin", "org.kde.KWin.reconfigure"])
    time.sleep(0.8)
    notify_kg()
    time.sleep(0.4)
    # 兜底再发一次：KWin 处理 reconfigure 的路径偶尔比 0.8s 更慢。
    notify_kg()
    time.sleep(0.4)


def run(cmd: list[str]) -> int:
    try:
        return subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
    except FileNotFoundError:
        return 127


def apply_all(apps: list[str], opts: dict[str, str], managed: list[str], force: bool = False) -> bool:
    """把配置落到 kwinrulesrc + breezerc + 自己的配置 + kwinrc 镜像，然后让 KWin 重新读。

    只有真的有改动（或 force）才触发 reload：重新配置 KWin 不便宜，而且多余的写入会
    让盯着 kwinrc 的 path 单元白跑一轮。
    """
    changed = build_rules(apps)
    changed |= apply_exceptions(apps, opts, managed)
    changed |= write_our_config(apps, opts, apps)
    changed |= mirror_script_apps(apps)
    if changed or force:
        reload_kwin()
    return changed


# --------------------------------------------------------------------------
# 子命令
# --------------------------------------------------------------------------

def cmd_add(args) -> int:
    with apply_lock():
        apps, opts = read_our_config()
        managed = read_managed()
        for app in args.app:
            if app not in apps:
                apps.append(app)
        apply_all(apps, opts, managed)
    print(f"已启用（{len(apps)} 个应用）: {', '.join(apps) or '无'}")
    return 0


def cmd_remove(args) -> int:
    with apply_lock():
        apps, opts = read_our_config()
        managed = read_managed()
        for app in args.app:
            if app in apps:
                apps.remove(app)
        apply_all(apps, opts, managed)
    print(f"剩余应用: {', '.join(apps) or '无'}")
    return 0


def cmd_set(args) -> int:
    with apply_lock():
        apps, opts = read_our_config()
        managed = read_managed()
        if args.key not in opts:
            print(f"未知配置项 {args.key}（可用: {', '.join(opts)}）", file=sys.stderr)
            return 1
        if args.key == "BorderSize" and args.value not in BORDER_SIZES:
            print(f"BorderSize 取值: {', '.join(BORDER_SIZES)}", file=sys.stderr)
            return 1
        opts[args.key] = args.value
        apply_all(apps, opts, managed)
    print(f"{args.key}={args.value}")
    return 0


def cmd_apply(args) -> int:
    with apply_lock():
        apps, opts = read_our_config()
        managed = read_managed()
        apply_all(apps, opts, managed)
    print(f"已应用: {', '.join(apps) or '无'}")
    return 0


# --------------------------------------------------------------------------
# 请求入口：供 tools/windowborder-daemon.py（D-Bus 服务）和命令行使用
#
#   窗口菜单点击 → windowborder-daemon 的 AddApp/RemoveApp → request add:<应用>
#   设置面板保存 → 守护进程发现 kwinrc 变了 → request panel
#   D-Bus 直接调（调试）→ request add:<应用> / remove:<应用> / panel / reapply / list
#
# 应用名由命令行原样传入；D-Bus 那边是普通字符串参数，不再需要编码。
# --------------------------------------------------------------------------

def cmd_request(args) -> int:
    action, _, token = args.request.partition(":")

    with apply_lock():
        if action == "reset":
            return reset_locked()

        apps, opts = read_our_config()
        managed = read_managed()

        if action == "list":
            # 给 windowborder-daemon 的 GetApps() 用：一行一个
            for app in apps:
                print(app)
            return 0

        if action in ("panel", "sync"):
            wanted = panel_changed_list()
            if wanted is None:
                # kwinrc 这次改动和名单无关（改别的设置、或我们回写的回声）
                return 0
            apps = wanted
        elif action == "add":
            app = token
            if not app:
                print("add 请求缺少应用名", file=sys.stderr)
                return 1
            if app not in apps:
                apps.append(app)
        elif action == "remove":
            app = token
            if not app:
                print("remove 请求缺少应用名", file=sys.stderr)
                return 1
            if app in apps:
                apps.remove(app)
        elif action == "reapply":
            # 先看看设置面板有没有改过名单：不然会把面板里新写的名单用旧配置覆盖掉
            wanted = panel_changed_list()
            if wanted is not None:
                apps = wanted
            apply_all(apps, opts, managed, force=True)
            print(f"已重新应用: {', '.join(apps) or '（无）'}")
            return 0
        else:
            print(f"未知请求 {args.request!r}", file=sys.stderr)
            return 1

        apply_all(apps, opts, managed)

    print(f"启用边框的应用（{len(apps)}）: {', '.join(apps) or '（无）'}")
    return 0


def cmd_reset(args) -> int:
    with apply_lock():
        return reset_locked()


def reset_locked() -> int:
    apps, opts = read_our_config()
    managed = read_managed()
    removed: list[str] = []

    def strip(groups: list[Group]) -> None:
        removed.extend(strip_our_rules(groups))

    apply_groups(KWINRULES, strip)
    remove_all_exceptions(list(set(managed) | set(apps)))
    if OUR_CONFIG.exists():
        OUR_CONFIG.unlink()
    mirror_script_apps([])

    reload_kwin()
    print(f"已移除 {len(removed)} 条规则、清理了 Breeze 覆盖，并删除 {OUR_CONFIG.name}")
    return 0


def cmd_status(args) -> int:
    apps, opts = read_our_config()
    managed = read_managed()
    print(f"配置: {OUR_CONFIG}")
    print(f"应用: {', '.join(apps) or '（无）'}")
    print(f"  BorderSize   = {opts['BorderSize']}  (Breeze 边框粗细；None = 不改变窗口几何)")
    print(f"  HideTitleBar = {opts['HideTitleBar']}  (true = 只留边框，不要标题栏)")
    script_apps = read_script_apps()
    print(f"kwinrc [{SCRIPT_GROUP}] {SCRIPT_APPS_KEY}: {', '.join(script_apps) or '（无）'}"
          + ("" if sorted(script_apps) == sorted(apps) else "   ← 与上面的应用列表不一致"))

    groups = read_kconfig(KWINRULES)
    ours = [g for g in groups if (g.get("Description", "") or "").startswith(RULE_PREFIX)]
    print(f"kwinrulesrc 里的规则: {len(ours)} 条")
    for g in ours:
        print(f"  - {g.get('Description')}  wmclass={g.get('wmclass')}")

    groups = read_kconfig(BREEZERC)
    _, exceptions = bump_exception_groups(groups)
    print(f"breezerc 里的窗口特定覆盖: {len(exceptions)} 条（含非本工具的）")
    for g in exceptions:
        mark = " *" if (g.get("ExceptionPattern", "") or "") in (set(managed) | set(apps)) else ""
        print(f"  - pattern={g.get('ExceptionPattern')} HideTitleBar={g.get('HideTitleBar')} "
              f"BorderSize={g.get('BorderSize')}{mark}")
    print("（带 * 的是本工具管理的）")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="windowborder-native",
        description="按应用给窗口加原生边框（KWin 窗口规则 + Breeze 窗口特定覆盖）",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("add", help="为指定应用启用边框")
    p.add_argument("app", nargs="+", help="窗口类（Wayland app_id，如 dbx）")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("remove", help="取消指定应用的边框")
    p.add_argument("app", nargs="+")
    p.set_defaults(func=cmd_remove)

    p = sub.add_parser("set", help="修改外观配置")
    p.add_argument("key", choices=["BorderSize", "HideTitleBar"])
    p.add_argument("value")
    p.set_defaults(func=cmd_set)

    p = sub.add_parser("apply", help="按当前配置重新生成并生效")
    p.set_defaults(func=cmd_apply)

    p = sub.add_parser("status", help="查看当前状态")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("reset", help="移除本工具的全部配置")
    p.set_defaults(func=cmd_reset)

    p = sub.add_parser("request",
                       help="（扩展内部用）处理 KWin 脚本发来的请求：panel / add:<应用> / remove:<应用> / reapply / reset")
    p.add_argument("request")
    p.set_defaults(func=cmd_request)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
