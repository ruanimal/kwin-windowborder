#!/usr/bin/env bash
#
# SPDX-License-Identifier: GPL-2.0-or-later
#
# 打 KDE Store 用的 .kwinscript（就是 KPackage 的 zip：metadata.json + contents/）。
#
#   packaging/pack.sh
#   → packaging/build/windowborder-menu_<版本>.kwinscript
#
# 用户可以双击/在「系统设置 → 窗口管理 → KWin 脚本 → 从文件安装」里装它，
# 或者发布到 store.kde.org 后由「获取新脚本」一键装。
#
# 注意：这个文件只含扩展本体（窗口菜单 + 设置面板）。后端（D-Bus 服务）装不进去
# —— KWin/Script 的 KPackage 没有安装钩子，装不了可执行文件和 .service。
# 所以只从 Store 装的用户会看到菜单里提示「后端未安装」；要么装发行版包
# （packaging/make-deb.sh 产出的那个），要么跑 tools/kwin-windowborder-menu-setup.sh install。
#
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${REPO_DIR}/packaging/build"
VERSION="$(python3 - "${REPO_DIR}/extension/metadata.json" <<'PY'
import json, sys
print(json.load(open(sys.argv[1], encoding="utf-8"))["KPlugin"]["Version"])
PY
)"

OUT="${BUILD_DIR}/windowborder-menu_${VERSION}.kwinscript"
mkdir -p "${BUILD_DIR}"
rm -f "${OUT}"
(cd "${REPO_DIR}/extension" && zip -qr "${OUT}" metadata.json contents)
echo "已生成: ${OUT}"
unzip -l "${OUT}"
