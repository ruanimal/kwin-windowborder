#!/usr/bin/env bash
#
# SPDX-License-Identifier: GPL-2.0-or-later
#
# 安装/卸载「窗口边框」KWin 脚本扩展（窗口菜单 + 设置面板），用户级、不需要 root。
#
#   kwin-windowborder-menu-setup.sh install     安装扩展、后端和 D-Bus 服务，并启用
#   kwin-windowborder-menu-setup.sh uninstall   卸载全部（不动已生成的 kwinrulesrc/breezerc）
#   kwin-windowborder-menu-setup.sh status      查看状态
#   kwin-windowborder-menu-setup.sh restart     重启 D-Bus 服务（改完后端/守护进程时用）
#   kwin-windowborder-menu-setup.sh reapply     按当前名单重新生成规则并生效
#
# 为什么需要一个常驻的 D-Bus 服务（tools/windowborder-daemon.py）：
# KWin 脚本只能 readConfig / callDBus，不能写文件、不能起进程，而加边框必须改
# ~/.config/kwinrulesrc 和 ~/.config/breezerc。于是：
#
#   窗口菜单点击 → callDBus(org.kde.windowborder … AddApp) → 守护进程写配置
#   设置面板保存 → 只写了 kwinrc，守护进程盯着它 → 自己触发同步
#                  （KWin 不会为脚本重新解析 kwinrc，脚本也不会重跑，
#                    所以必须有东西盯着这个文件）
#
# 装到哪儿（全在 $HOME 下）：
#   ~/.local/share/kwin/scripts/windowborder-menu/    KWin 脚本扩展（kpackagetool6）
#   ~/.local/bin/windowborder-native                  后端（真正写配置的那一半）
#   ~/.local/bin/windowborder-daemon                  D-Bus 服务
#   ~/.local/share/dbus-1/services/org.kde.windowborder.service
#   ~/.config/autostart/windowborder-daemon.desktop   登录即常驻
#
# 发行版包（装到 /usr + /etc/xdg/autostart，装完零配置）见 packaging/。
#
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT_PACKAGE="${REPO_DIR}/extension"
BACKEND_SRC="${REPO_DIR}/tools/windowborder-native.py"
DAEMON_SRC="${REPO_DIR}/tools/windowborder-daemon.py"
SERVICE_TEMPLATE="${REPO_DIR}/packaging/files/org.kde.windowborder.service.in"
AUTOSTART_TEMPLATE="${REPO_DIR}/packaging/files/windowborder-daemon.desktop.in"

SCRIPT_ID="windowborder-menu"
GROUP="Script-windowborder-menu"
BIN_DIR="${HOME}/.local/bin"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
SERVICE_DIR="${DATA_HOME}/dbus-1/services"
AUTOSTART_DIR="${CONFIG_HOME}/autostart"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}"
DAEMON_LOG="${STATE_DIR}/windowborder-daemon.log"
UNIT_DIR="${CONFIG_HOME}/systemd/user"

BACKEND="${BIN_DIR}/windowborder-native"
DAEMON="${BIN_DIR}/windowborder-daemon"

die() {
    echo "error: $*" >&2
    exit 1
}

# 优先用系统 python：PATH 里排前面的可能是 venv/conda 的解释器（本机就是 ~/.venv/bin/python3），
# 而 D-Bus 服务要 python3-dbus / python3-gi —— 只有系统解释器才确定有。
python_bin() {
    if [ -x /usr/bin/python3 ]; then
        echo /usr/bin/python3
    else
        command -v python3
    fi
}

need_tools() {
    local tool
    for tool in kpackagetool6 kwriteconfig6 kreadconfig6 qdbus6; do
        command -v "${tool}" >/dev/null || die "找不到 ${tool}"
    done
    [ -n "$(python_bin)" ] || die "找不到 python3"
    [ -d "${SCRIPT_PACKAGE}" ] || die "找不到扩展目录 ${SCRIPT_PACKAGE}"
    [ -f "${BACKEND_SRC}" ] || die "找不到 ${BACKEND_SRC}"
    [ -f "${DAEMON_SRC}" ] || die "找不到 ${DAEMON_SRC}"
    [ -f "${SERVICE_TEMPLATE}" ] || die "找不到 ${SERVICE_TEMPLATE}"
    [ -f "${AUTOSTART_TEMPLATE}" ] || die "找不到 ${AUTOSTART_TEMPLATE}"
    "$(python_bin)" -c "import dbus, gi" 2>/dev/null \
        || die "$(python_bin) 缺 python3-dbus / python3-gi（apt install python3-dbus python3-gi）"
}

reload_kwin() {
    qdbus6 org.kde.KWin /KWin org.kde.KWin.reconfigure >/dev/null 2>&1 || true
}

# KWin 不会重新运行已经加载的脚本，所以更新完必须 unload 一次，
# 后续的 reconfigure 才会用新文件重新加载（和 KWin 效果插件的 .so 是同一个坑）。
unload_script() {
    qdbus6 org.kde.KWin /Scripting org.kde.kwin.Scripting.unloadScript "${SCRIPT_ID}" \
        >/dev/null 2>&1 || true
}

# 1.0 用的是 systemd 用户单元；装上就把它们清掉，免得两套桥同时存在
remove_legacy_units() {
    local found=0
    if [ -e "${UNIT_DIR}/windowborder-watch.path" ] || [ -e "${UNIT_DIR}/windowborder@.service" ]; then
        found=1
        if command -v systemctl >/dev/null; then
            systemctl --user stop windowborder-watch.path >/dev/null 2>&1 || true
            systemctl --user disable windowborder-watch.path >/dev/null 2>&1 || true
        fi
        rm -f "${UNIT_DIR}/windowborder@.service" \
              "${UNIT_DIR}/windowborder-watch.service" \
              "${UNIT_DIR}/windowborder-watch.path"
        if command -v systemctl >/dev/null; then
            systemctl --user daemon-reload >/dev/null 2>&1 || true
        fi
    fi
    [ "${found}" = 1 ] && echo "已清理旧版本的 systemd 单元"
    return 0
}

install_package() {
    # -i 对已安装的包会报错，这时改用 -u 升级
    if kpackagetool6 --type KWin/Script -i "${SCRIPT_PACKAGE}" >/dev/null 2>&1; then
        echo "已安装 KWin 脚本扩展 ${SCRIPT_ID}"
    else
        kpackagetool6 --type KWin/Script -u "${SCRIPT_PACKAGE}" >/dev/null
        echo "已更新 KWin 脚本扩展 ${SCRIPT_ID}"
    fi
}

install_files() {
    local python exec_line
    python="$(python_bin)"
    mkdir -p "${BIN_DIR}" "${SERVICE_DIR}" "${AUTOSTART_DIR}" "${STATE_DIR}"

    install -m 0755 "${BACKEND_SRC}" "${BACKEND}"
    install -m 0755 "${DAEMON_SRC}" "${DAEMON}"

    exec_line="${python} ${DAEMON}"
    sed "s|@EXEC@|${exec_line}|g" "${SERVICE_TEMPLATE}" > "${SERVICE_DIR}/org.kde.windowborder.service"
    sed "s|@EXEC@|${exec_line}|g" "${AUTOSTART_TEMPLATE}" > "${AUTOSTART_DIR}/windowborder-daemon.desktop"

    echo "已安装: ${BACKEND}"
    echo "已安装: ${DAEMON}"
    echo "已安装: ${SERVICE_DIR}/org.kde.windowborder.service（D-Bus 按需激活）"
    echo "已安装: ${AUTOSTART_DIR}/windowborder-daemon.desktop（登录即常驻）"
}

daemon_running() {
    qdbus6 org.kde.windowborder /WindowBorder org.kde.windowborder.Version >/dev/null 2>&1
}

start_daemon() {
    # force: 不管现在有没有在跑，都起一个（restart 用）。
    # 注意不要拿 daemon_running 当"停干净了没"的判据：探活本身就会触发 D-Bus 激活。
    local force="${1:-}"
    if [ "${force}" != "force" ] && daemon_running; then
        echo "D-Bus 服务已在运行"
        return 0
    fi
    # D-Bus 激活本来就会按需拉起它；这里主动起一份，好让设置面板那条路立刻可用
    setsid "$(python_bin)" "${DAEMON}" >>"${DAEMON_LOG}" 2>&1 &
    local waited=0
    while [ "${waited}" -lt 50 ]; do
        if daemon_running; then
            echo "D-Bus 服务已启动（日志 ${DAEMON_LOG}）"
            return 0
        fi
        sleep 0.1
        waited=$((waited + 1))
    done
    echo "警告: D-Bus 服务没起来，看 ${DAEMON_LOG}" >&2
    return 0
}

stop_daemon() {
    if daemon_running; then
        qdbus6 org.kde.windowborder /WindowBorder org.kde.windowborder.Quit >/dev/null 2>&1 || true
        # 等进程真的退出。这里只看进程，不要再用 D-Bus 探活 —— 那会把它重新激活起来。
        local waited=0
        while pgrep -f "${DAEMON}$" >/dev/null 2>&1 && [ "${waited}" -lt 30 ]; do
            sleep 0.1
            waited=$((waited + 1))
        done
        pgrep -f "${DAEMON}$" >/dev/null 2>&1 && pkill -f "${DAEMON}$" >/dev/null 2>&1 || true
    fi
    return 0
}

enable_script() {
    kwriteconfig6 --file kwinrc --group Plugins --key "${SCRIPT_ID}Enabled" true
}

disable_script() {
    kwriteconfig6 --file kwinrc --group Plugins --key "${SCRIPT_ID}Enabled" --delete
}

case "${1:-}" in
install)
    need_tools
    remove_legacy_units
    install_package
    install_files
    enable_script
    start_daemon
    unload_script
    reload_kwin
    # 把现有名单同步进 kwinrc（设置面板读它），并确认规则/覆盖都已生成
    "$(python_bin)" "${BACKEND}" apply
    echo
    echo "装好了。用法："
    echo "  窗口菜单（Alt+F3 / 标题栏右键）→ 扩展 → 窗口边框 → 给这个应用加边框"
    echo "  设置面板：系统设置 → 窗口管理 → KWin 脚本 → Window Border → 配置"
    echo "  命令行：${BACKEND} add <应用> / remove <应用> / status"
    ;;
uninstall)
    need_tools
    disable_script
    stop_daemon
    remove_legacy_units
    rm -f "${SERVICE_DIR}/org.kde.windowborder.service" \
          "${AUTOSTART_DIR}/windowborder-daemon.desktop" \
          "${BACKEND}" "${DAEMON}"
    kpackagetool6 --type KWin/Script -r "${SCRIPT_ID}" >/dev/null 2>&1 || true
    unload_script
    reload_kwin
    echo "已卸载扩展、后端和 D-Bus 服务。"
    echo "注意：kwinrulesrc 里的规则和 breezerc 里的覆盖没有动（已加边框的窗口不受影响）。"
    echo "      要一并清掉：$(python_bin) ${BACKEND_SRC} reset"
    ;;
status)
    echo "扩展包: $(kpackagetool6 --type KWin/Script --list 2>/dev/null | grep -x "${SCRIPT_ID}" || echo '未安装')"
    echo "脚本已加载: $(qdbus6 org.kde.KWin /Scripting org.kde.kwin.Scripting.isScriptLoaded "${SCRIPT_ID}" 2>/dev/null || echo '未知')"
    echo "kwinrc [Plugins] ${SCRIPT_ID}Enabled: $(kreadconfig6 --file kwinrc --group Plugins --key "${SCRIPT_ID}Enabled" --default '(未设置)')"
    echo "D-Bus 服务: $(daemon_running && echo '运行中' || echo '未运行')"
    echo "后端标记: $(kreadconfig6 --file kwinrc --group "${GROUP}" --key backend --default '(无)')"
    if [ -e "${UNIT_DIR}/windowborder@.service" ]; then
        echo "注意: 还存在旧版本的 systemd 单元（再跑一次 install 会清掉）"
    fi
    echo
    "$(python_bin)" "${BACKEND_SRC}" status
    ;;
restart)
    need_tools
    stop_daemon
    start_daemon force
    ;;
reapply)
    need_tools
    "$(python_bin)" "${BACKEND_SRC}" request reapply
    ;;
*)
    cat >&2 <<EOF
用法: $0 <命令>

  install      安装扩展 + 后端 + D-Bus 服务（用户级，不需要 root），并启用
  uninstall    卸载全部（不动已生成的规则）
  status       查看扩展/脚本/服务/名单状态
  restart      重启 D-Bus 服务
  reapply      按当前名单重新生成规则并生效

窗口菜单和设置面板都只是「发请求」的入口，真正写 kwinrulesrc + breezerc 的是
$(python_bin) ${BACKEND_SRC}（由常驻的 windowborder-daemon 调用）。
发行版包的安装方式见 packaging/README.zh-CN.md。
EOF
    exit 1
    ;;
esac
