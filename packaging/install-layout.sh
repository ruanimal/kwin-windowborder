#!/usr/bin/env bash
#
# SPDX-License-Identifier: GPL-2.0-or-later
#
# 把「系统级布局」铺到 DESTDIR 里（发行版包 / 打包脚本共用这一份清单）。
#
#   packaging/install-layout.sh <DESTDIR> [PREFIX=/usr]
#
# 铺出来的东西：
#   $PREFIX/share/kwin/scripts/windowborder-menu/   KWin 脚本扩展（KWin 会扫这个目录）
#   $PREFIX/bin/windowborder-native                 后端（写 kwinrulesrc + breezerc）
#   $PREFIX/bin/windowborder-daemon                 D-Bus 服务
#   $PREFIX/share/man/man1/windowborder-{native,daemon}.1
#   $PREFIX/share/dbus-1/services/org.kde.windowborder.service
#   /etc/xdg/autostart/windowborder-daemon.desktop  每个用户登录即常驻（不需要 per-user 启用）
#
# 注意：系统装的扩展 EnabledByDefault=true，所以装完即启用，不用写用户的 kwinrc。
# 也正因为全是文本 + 纯 Python，包是 Architecture: all，不需要为每个发行版编译。
#
set -euo pipefail

DESTDIR="${1:?用法: install-layout.sh <DESTDIR> [PREFIX]}"
PREFIX="${2:-/usr}"

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXTENSION_DIR="${REPO_DIR}/extension"
FILES_DIR="${REPO_DIR}/packaging/files"

HOST_PYTHON="${HOST_PYTHON:-/usr/bin/python3}"
EXEC_LINE="${HOST_PYTHON} ${PREFIX}/bin/windowborder-daemon"

install -d "${DESTDIR}${PREFIX}/share/kwin/scripts/windowborder-menu"
cp -a "${EXTENSION_DIR}/." "${DESTDIR}${PREFIX}/share/kwin/scripts/windowborder-menu/"

install -Dm755 "${REPO_DIR}/tools/windowborder-native.py" \
    "${DESTDIR}${PREFIX}/bin/windowborder-native"
install -Dm755 "${REPO_DIR}/tools/windowborder-daemon.py" \
    "${DESTDIR}${PREFIX}/bin/windowborder-daemon"

install -d "${DESTDIR}${PREFIX}/share/dbus-1/services"
sed "s|@EXEC@|${EXEC_LINE}|g" "${FILES_DIR}/org.kde.windowborder.service.in" \
    > "${DESTDIR}${PREFIX}/share/dbus-1/services/org.kde.windowborder.service"

for manpage in "${REPO_DIR}"/man/*.1; do
    install -Dm644 "${manpage}" "${DESTDIR}${PREFIX}/share/man/man1/$(basename "${manpage}")"
done

install -d "${DESTDIR}/etc/xdg/autostart"
sed "s|@EXEC@|${EXEC_LINE}|g" "${FILES_DIR}/windowborder-daemon.desktop.in" \
    > "${DESTDIR}/etc/xdg/autostart/windowborder-daemon.desktop"

# 仓库目录是 775、文件是 664（umask 0002），包里要归一化，不然 lintian 会报
find "${DESTDIR}" -type d -exec chmod 0755 {} +
find "${DESTDIR}" -type f -exec chmod 0644 {} +
chmod 0755 "${DESTDIR}${PREFIX}/bin/windowborder-native" \
           "${DESTDIR}${PREFIX}/bin/windowborder-daemon"

echo "已铺到 ${DESTDIR}（PREFIX=${PREFIX}）"
