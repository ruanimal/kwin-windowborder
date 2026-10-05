#!/usr/bin/env bash
#
# SPDX-License-Identifier: GPL-2.0-or-later
#
# Enable/disable and configure the "Window Border" KWin effect at runtime.
#
#   kwin-windowborder-setup.sh enable            load the effect and enable it for future sessions
#   kwin-windowborder-setup.sh disable           unload the effect and disable it for future sessions
#   kwin-windowborder-setup.sh status            show current state and configuration
#   kwin-windowborder-setup.sh set KEY VALUE     write a config key and apply it immediately
#   kwin-windowborder-setup.sh reload            re-read the configuration
#
set -euo pipefail

EFFECT_ID="windowborder"
CONFIG_GROUP="Effect-windowborder"
KWINRC="kwinrc"

die() {
    echo "error: $*" >&2
    exit 1
}

need_tools() {
    command -v kwriteconfig6 >/dev/null || die "kwriteconfig6 not found"
    command -v kreadconfig6 >/dev/null || die "kreadconfig6 not found"
    command -v qdbus6 >/dev/null || die "qdbus6 not found"
}

# qdbus may or may not be able to reach KWin (e.g. when running from a TTY).
kwin_dbus() {
    qdbus6 org.kde.KWin /Effects "org.kde.kwin.Effects.$1" "${@:2}" 2>/dev/null
}

# Ask KWin to re-read kwinrc and reconfigure all effects.
reload_effect() {
    qdbus6 org.kde.KWin /KWin reconfigure >/dev/null 2>&1 || true
}

# KWin keeps using the plugin file it loaded at load time, so a re-installed .so
# is only picked up after an unload. Always unload first, otherwise "install a
# new build" silently keeps running the old code.
load_effect_fresh() {
    if [ "$(kwin_dbus isEffectLoaded "${EFFECT_ID}" 2>/dev/null || true)" = "true" ]; then
        kwin_dbus unloadEffect "${EFFECT_ID}" >/dev/null 2>&1 || true
    fi
    kwin_dbus loadEffect "${EFFECT_ID}"
}

case "${1:-}" in
enable)
    need_tools
    kwriteconfig6 --file "${KWINRC}" --group Plugins --key "${EFFECT_ID}Enabled" true
    if load_effect_fresh | grep -q true; then
        echo "effect '${EFFECT_ID}' loaded (plugin file re-read)"
    else
        echo "could not load '${EFFECT_ID}' into the running KWin (installed? logged in again?)" >&2
        echo "it is enabled for the next session anyway" >&2
    fi
    ;;
disable)
    need_tools
    kwriteconfig6 --file "${KWINRC}" --group Plugins --key "${EFFECT_ID}Enabled" false
    kwin_dbus unloadEffect "${EFFECT_ID}" >/dev/null 2>&1 || true
    echo "effect '${EFFECT_ID}' disabled"
    ;;
reload)
    need_tools
    reload_effect
    echo "configuration reloaded"
    ;;
set)
    need_tools
    key="${2:-}"
    value="${3:-}"
    [ -n "${key}" ] || die "usage: $0 set KEY VALUE"
    kwriteconfig6 --file "${KWINRC}" --group "${CONFIG_GROUP}" --key "${key}" "${value}"
    reload_effect
    echo "${CONFIG_GROUP}/${key} = ${value}"
    ;;
status)
    echo "kwinrc [Plugins] ${EFFECT_ID}Enabled : $(kreadconfig6 --file "${KWINRC}" --group Plugins --key "${EFFECT_ID}Enabled" --default '(unset)')"
    echo "kwinrc [${CONFIG_GROUP}]:"
    for key in Enabled BorderWidth ActiveBorderWidth BorderPlacement ActiveColor InactiveColor \
        BorderOnDecoratedWindows TopmostPerScreen ActiveWindowOnly ExcludeFullScreen ExcludeMaximized HideWhileMoving PerWindowColors; do
        printf '  %-26s %s\n' "${key}" "$(kreadconfig6 --file "${KWINRC}" --group "${CONFIG_GROUP}" --key "${key}" --default '(default)')"
    done
    echo "runtime:"
    if command -v qdbus6 >/dev/null; then
        echo "  loaded                     $(kwin_dbus isEffectLoaded "${EFFECT_ID}" || echo 'unknown (no D-Bus access)')"
    fi
    ;;
*)
    cat >&2 <<EOF
usage: $0 <command> [arguments]

  enable                     load the effect (unload+load, so a reinstalled .so is used)
  disable                    disable the effect
  status                     print the current configuration
  set KEY VALUE              write a configuration key and apply it
  reload                     re-read the configuration

configuration keys (kwinrc group [${CONFIG_GROUP}]):
  Enabled                    true|false   master switch
  BorderWidth                0-32         border thickness in pixels (0 disables)
  ActiveBorderWidth          0-32         0 = same as BorderWidth
  BorderPlacement            inside|center|outside
  ActiveColor                #RRGGBB or #AARRGGBB
  InactiveColor              #RRGGBB or #AARRGGBB
  BorderOnDecoratedWindows   true|false   also border windows that have a decoration
  TopmostPerScreen           true|false   border only the frontmost window of each output (default true)
  ActiveWindowOnly           true|false   with TopmostPerScreen=false: only border the focused window
  ExcludeFullScreen          true|false
  ExcludeMaximized           true|false
  HideWhileMoving            true|false   don't draw while the user moves/resizes the window
  PerWindowColors            true|false   derive a distinct colour per application

examples:
  $0 set BorderWidth 3
  $0 set ActiveColor '#00d1ff'
  $0 set InactiveColor '#60000000'
  $0 set BorderOnDecoratedWindows true
EOF
    exit 1
    ;;
esac
