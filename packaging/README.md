**English** | [简体中文](README.zh-CN.md)

# Packaging & publishing

This directory holds "how to ship it to other people". For what the tool does, see the repository root [README](../README.md).

## Artifacts

| Command | Artifact | For whom |
| --- | --- | --- |
| `packaging/make-deb.sh` | `packaging/build/kwin-windowborder_<version>_all.deb` | Debian / KDE neon / Ubuntu users (recommended) |
| `packaging/pack.sh` | `packaging/build/windowborder-menu_<version>.kwinscript` | KDE Store / "install from file", extension only |
| `dpkg-buildpackage -b -uc -us` | the same .deb (via `debian/` + debhelper) | PPA / OBS / Launchpad |
| `makepkg -si` (`packaging/PKGBUILD`) | Arch package | Arch / AUR |

The two deb paths lay down the same manifest: `packaging/install-layout.sh` (called from both `debian/rules`' `override_dh_auto_install` and `make-deb.sh`), so the resulting contents match; both pass `lintian` with no warnings.

## What's in the package

```
/usr/share/kwin/scripts/windowborder-menu/           KWin script extension (window menu + settings panel)
/usr/bin/windowborder-native                         backend (writes kwinrulesrc + breezerc, also the CLI)
/usr/bin/windowborder-daemon                         D-Bus service
/usr/share/dbus-1/services/org.kde.windowborder.service    D-Bus activation on demand
/etc/xdg/autostart/windowborder-daemon.desktop       resident at every user login
/usr/share/man/man1/windowborder-{native,daemon}.1.gz
/usr/share/doc/kwin-windowborder/{copyright,changelog.gz}
```

Dependencies: `python3`, `python3-dbus`, `python3-gi`, `kwin-wayland (>= 4:6.6) | kwin-x11 (>= 4:6.6)` (on Arch the equivalent is `kwin>=6.6`). The KWin floor is not arbitrary: the rule semantics that force server-side decorations (`noborder=false` → `DecorationPolicy::Server`) only exist from Plasma 6.6; older versions would accept the rule but do nothing — so let the package manager block them instead of installing something that silently doesn't work. Details under "Requirements" in the root README. Everything is text + pure Python, hence `Architecture: all` and a single package serving both Ubuntu and neon at the same level.

The extension's `metadata.json` has `EnabledByDefault: true`: a system-installed KPackage is enabled as soon as it's installed, without touching the user's `kwinrc`; D-Bus activation and `/etc/xdg/autostart` are "drop in and it works", so **there is no per-user enabling step**.

## What a regular user does

1. Install the package: double-click the `.deb` in Discover, or `sudo apt install ./kwin-windowborder_1.0_all.deb`;
2. **Log out and back in once** (KWin loads the script extension at that point, and autostart brings up the D-Bus service);
3. Use it: right-click any window's title bar (or `Alt+F3`) → More Actions → Window Border → add a border to this app.

The package is installed outside a user session, so step 2 cannot be avoided (there is no per-user autostart to install, and the running KWin can't be notified). Everything is automatic after re-login.

## Distribution channels

- **KDE Store** (`store.kde.org`, KWin Scripts category): upload only the `.kwinscript`. The KWin scripts KCM ships "Get New Scripts" (`/usr/share/knsrcfiles/kwinscripts.knsrc`), so users can install the extension itself with one click. **But it cannot install the backend** (a KWin/Script KPackage has no install hook and cannot carry executables or `.service` files), so Store-only users will see the "backend not installed" notice in the menu. Either also have users install the deb, or treat the Store as an "extension + updates" channel only.
- **Distribution package**: put the `make-deb.sh` output into a PPA, or submit `debian/` to OBS/Launchpad; Arch users use the AUR (the `source` in `packaging/PKGBUILD` points to the GitHub tag archive).
- **Source**: `git clone && tools/kwin-windowborder-menu-setup.sh install` (user-level, no root needed).

## CI

`.github/workflows/build.yml` is already in the repository, three jobs:

| job | what it does |
| --- | --- |
| `packages` | syntax checks (py_compile / bash -n / node --check / XML+JSON) → `make-deb.sh` + `pack.sh` → `lintian --fail-on error` → upload artifacts |
| `debian-dir` | installs debhelper, runs `dpkg-buildpackage -b -uc -us` + lintian once, to make sure the PPA/OBS path doesn't silently break (lays down the same manifest as `packages`) |
| `release` | only on `v*` tags: downloads the artifacts and creates a Release with `gh release create`, attaching `.deb` + `.kwinscript` |

When a tag is pushed, the workflow first rewrites `extension/metadata.json` and `debian/changelog` with the tag number (`v1.1.0-rc1` → `1.1.0~rc1`; native package versions can't contain `-`), so the released package version matches the tag. Pushes to master / PRs only build, never release; a warning is emitted when the two disagree.

Local equivalent commands (identical to CI):

```bash
python3 -m py_compile tools/*.py && node --check extension/contents/code/main.js
packaging/make-deb.sh && packaging/pack.sh
lintian --fail-on error packaging/build/kwin-windowborder_*_all.deb
```

## Known pitfalls

- **The `[Plugins]` key is shared by effects and scripts**: `kwinrc [Plugins] <id>Enabled`. That's why the script id is `windowborder-menu`; system-installed KPackages are enabled via `EnabledByDefault` without writing the user's kwinrc;
- **Don't start the daemon with `#!/usr/bin/env python3`**: a venv/conda interpreter may come first in PATH and not have `python3-dbus`. The `.service` / autostart files use `/usr/bin/python3 /usr/bin/windowborder-daemon`; the user-level install does the same (see `python_bin()` in the setup script);
- **After updating the script you must unload and reload it**: KWin doesn't re-run an already-loaded script; just overwriting the files doesn't count. The setup script's `install` does this step;
- **`dpkg-buildpackage` writes artifacts to the parent directory** (`../kwin-windowborder_*`); `.gitignore` already ignores `packaging/build/`, `*.deb`, `*.kwinscript` and the `debian/` build leftovers.