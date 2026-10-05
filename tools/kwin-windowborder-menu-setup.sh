#!/usr/bin/env bash
#
# SPDX-License-Identifier: GPL-2.0-or-later
#
# 安装/卸载「窗口边框」KWin 脚本扩展（窗口菜单 + 设置面板）。
#
#   kwin-windowborder-menu-setup.sh install     安装 KPackage、systemd 单元并启用
#   kwin-windowborder-menu-setup.sh uninstall   卸载（不动已生成的 kwinrulesrc/breezerc）
#   kwin-windowborder-menu-setup.sh status      查看状态
#   kwin-windowborder-menu-setup.sh reapply     按当前名单重新生成并生效
#
# 为什么需要 systemd 单元：KWin 脚本（JS）只能 readConfig / callDBus，不能写文件、
# 不能起进程，而加边框必须改 ~/.config/kwinrulesrc 和 ~/.config/breezerc。所以：
#
#   windowborder@.service        菜单点击 → callDBus StartUnit → 后端执行请求
#                                （请求写在单元实例名里，如 windowborder@add:dbx.service）
#   windowborder-watch.path      盯着 kwinrc：设置面板写 kwinrc 后自动触发
#   windowborder-watch.service   → 后端执行 request panel（把面板里的名单同步过去）
#
# 后端是 tools/windowborder-native.py，和命令行用法共用同一份逻辑。
#
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT_PACKAGE="${REPO_DIR}/extension"
BACKEND="${REPO_DIR}/tools/windowborder-native.py"
SCRIPT_ID="windowborder-menu"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

die() {
    echo "error: $*" >&2
    exit 1
}

# 优先用系统 python：PATH 里排前面的可能是 venv/conda 的解释器（本机就是 ~/.venv/bin/python3），
# 把那种路径写进 systemd 单元，等 venv 一挪窝就全不工作了。
python_bin() {
    if [ -x /usr/bin/python3 ]; then
        echo /usr/bin/python3
    else
        command -v python3
    fi
}

need_tools() {
    local tool
    for tool in kpackagetool6 kwriteconfig6 qdbus6 systemctl; do
        command -v "${tool}" >/dev/null || die "找不到 ${tool}"
    done
    [ -n "$(python_bin)" ] || die "找不到 python3"
    [ -d "${SCRIPT_PACKAGE}" ] || die "找不到扩展目录 ${SCRIPT_PACKAGE}"
    [ -f "${BACKEND}" ] || die "找不到后端 ${BACKEND}"
}

reload_kwin() {
    qdbus6 org.kde.KWin /KWin org.kde.KWin.reconfigure >/dev/null 2>&1 || true
}

write_units() {
    local python
    python="$(python_bin)"
    mkdir -p "${UNIT_DIR}"

    cat > "${UNIT_DIR}/windowborder@.service" <<EOF
[Unit]
Description=Window Border request (%i)

[Service]
Type=oneshot
ExecStart="${python}" "${BACKEND}" request %i
EOF

    cat > "${UNIT_DIR}/windowborder-watch.service" <<EOF
[Unit]
Description=Sync Window Border settings from kwinrc

[Service]
Type=oneshot
ExecStart="${python}" "${BACKEND}" request panel
EOF

    # %E = 用户配置目录（$XDG_CONFIG_HOME，未设置时为 ~/.config）
    cat > "${UNIT_DIR}/windowborder-watch.path" <<'EOF'
[Unit]
Description=Watch kwinrc for Window Border settings

[Path]
PathChanged=%E/kwinrc
PathModified=%E/kwinrc

[Install]
WantedBy=default.target
EOF

    echo "已写入 systemd 用户单元: ${UNIT_DIR}/windowborder{@,-watch}.{service,path}"
}

remove_units() {
    systemctl --user stop windowborder-watch.path >/dev/null 2>&1 || true
    systemctl --user disable windowborder-watch.path >/dev/null 2>&1 || true
    rm -f "${UNIT_DIR}/windowborder@.service" \
          "${UNIT_DIR}/windowborder-watch.service" \
          "${UNIT_DIR}/windowborder-watch.path"
    systemctl --user daemon-reload >/dev/null 2>&1 || true
    echo "已删除 systemd 用户单元"
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

enable_script() {
    kwriteconfig6 --file kwinrc --group Plugins --key "${SCRIPT_ID}Enabled" true
}

disable_script() {
    kwriteconfig6 --file kwinrc --group Plugins --key "${SCRIPT_ID}Enabled" --delete
}

case "${1:-}" in
install)
    need_tools
    write_units
    systemctl --user daemon-reload
    systemctl --user enable --now windowborder-watch.path
    install_package
    enable_script
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
    remove_units
    kpackagetool6 --type KWin/Script -r "${SCRIPT_ID}" >/dev/null 2>&1 || true
    reload_kwin
    echo "已卸载扩展。"
    echo "注意：kwinrulesrc 里的规则和 breezerc 里的覆盖没有动（已加边框的窗口不受影响）。"
    echo "      要一并清掉：$(python_bin) ${BACKEND} reset"
    ;;
status)
    echo "扩展包: $(kpackagetool6 --type KWin/Script --list 2>/dev/null | grep -x "${SCRIPT_ID}" || echo '未安装')"
    echo "脚本已加载: $(qdbus6 org.kde.KWin /Scripting org.kde.kwin.Scripting.isScriptLoaded "${SCRIPT_ID}" 2>/dev/null || echo '未知')"
    echo "kwinrc [Plugins] ${SCRIPT_ID}Enabled: $(kreadconfig6 --file kwinrc --group Plugins --key "${SCRIPT_ID}Enabled" --default '(未设置)')"
    echo "watch 单元: $(systemctl --user is-active windowborder-watch.path 2>/dev/null || echo '未运行')"
    echo
    "$(python_bin)" "${BACKEND}" status
    ;;
reapply)
    need_tools
    "$(python_bin)" "${BACKEND}" request reapply
    ;;
*)
    cat >&2 <<EOF
用法: $0 <命令>

  install      安装 KWin 脚本扩展 + systemd 用户单元，并启用
  uninstall    卸载扩展和 systemd 单元（不动已生成的规则）
  status       查看扩展/脚本/单元/名单状态
  reapply      按当前名单重新生成规则并生效

对应关系：窗口菜单和设置面板都只是「发请求」的入口，真正写
kwinrulesrc + breezerc 的是 python3 ${BACKEND}
EOF
    exit 1
    ;;
esac
