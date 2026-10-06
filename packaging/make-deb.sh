#!/usr/bin/env bash
#
# SPDX-License-Identifier: GPL-2.0-or-later
#
# 直接产出 .deb（不依赖 debhelper，只要有 dpkg-deb）：
#
#   packaging/make-deb.sh
#   → packaging/build/kwin-windowborder_<版本>_all.deb
#
# 装法（普通用户）：Discover 里双击，或者
#   sudo apt install ./kwin-windowborder_1.0_all.deb
# 装完注销重登一次即可（KWin 加载脚本 + 自启动拉起 D-Bus 服务）。
#
# 要进 PPA / OBS 的话用仓库根目录的 debian/（dpkg-buildpackage，走 debhelper），
# 两边铺的是同一份清单：packaging/install-layout.sh。
#
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${REPO_DIR}/packaging/build"
VERSION="$(python3 - "${REPO_DIR}/extension/metadata.json" <<'PY'
import json, sys
print(json.load(open(sys.argv[1], encoding="utf-8"))["KPlugin"]["Version"])
PY
)"

PKG="kwin-windowborder"
ROOT="${BUILD_DIR}/${PKG}_${VERSION}_all"
OUT="${BUILD_DIR}/${PKG}_${VERSION}_all.deb"

rm -rf "${ROOT}"
mkdir -p "${ROOT}/DEBIAN"

"${REPO_DIR}/packaging/install-layout.sh" "${ROOT}"

# 依赖里的 KWin 版本下限和 debian/control 保持一致：强制服务端装饰的规则语义
# （noborder=false → DecorationPolicy::Server）是 Plasma 6.6 才有的，更早的版本
# 装了也不会生效，所以让 apt 直接挡住。
cat > "${ROOT}/DEBIAN/control" <<EOF
Package: ${PKG}
Version: ${VERSION}
Architecture: all
Maintainer: ruan.lj <ruan.lj@foxmail.com>
Depends: python3, python3-dbus, python3-gi, kwin-wayland (>= 4:6.6) | kwin-x11 (>= 4:6.6)
Section: kde
Priority: optional
Description: Native window border for applications without window decoration
 Adds a "Window Border" submenu to the KWin window menu (Alt+F3 or
 right-click on the titlebar) and a settings panel that give an
 application the native KWin/Breeze window border: a 1px outline without
 a title bar and without changing the window geometry.
 .
 Tauri/WebView and GTK/libadwaita windows draw their own title bar (or
 none at all), so KWin sees a plain rectangle with no visible boundary.
 The border is created by KWin itself (window rule + Breeze per-window
 override), so drag, animations, occlusion, rounded corners and output
 scaling are handled by KWin.
 .
 KWin >= 6.6 is required: forcing a server side decoration through a
 window rule (noborder=false -> DecorationPolicy::Server) only exists
 since then. On older Plasma the rule is accepted but ignored, so the
 package refuses to install instead of silently doing nothing.
EOF

cat > "${ROOT}/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = "configure" ]; then
    cat <<'MSG'
kwin-windowborder: 已安装。请注销并重新登录一次，让 KWin 加载脚本扩展、
并让 D-Bus 服务（窗口菜单/设置面板的后端）自启动。
登录后在任意窗口标题栏右键（或 Alt+F3）→ 扩展 → 窗口边框。
MSG
fi
exit 0
EOF
chmod 0755 "${ROOT}/DEBIAN/postinst"

# /etc 下的自启动项必须标成 conffile（用户/管理员可以改，升级时保留）
echo "/etc/xdg/autostart/windowborder-daemon.desktop" > "${ROOT}/DEBIAN/conffiles"

# Debian 要求的文档；debian/ 那条路（dh_installchangelogs / dh_installdocs）自己做这些
DOC_DIR="${ROOT}/usr/share/doc/${PKG}"
install -d "${DOC_DIR}"
install -m 0644 "${REPO_DIR}/debian/copyright" "${DOC_DIR}/copyright"
gzip -9n -c "${REPO_DIR}/debian/changelog" > "${DOC_DIR}/changelog.gz"
chmod 0644 "${DOC_DIR}/changelog.gz"

# dh_compress 等价物：man 页压缩
find "${ROOT}/usr/share/man" -type f -name "*.1" -exec gzip -9n {} +

dpkg-deb --root-owner-group --build "${ROOT}" "${OUT}" >/dev/null
echo "已生成: ${OUT}"
dpkg-deb -I "${OUT}" | sed -n '1,12p'
