**English** | [简体中文](README.zh-CN.md)

# Window Border — native borders for undecorated windows

In a Wayland session, many windows have no visible window edge at all:

- **Tauri / WebView apps** (`decorations: false`) draw their own title bar — on the KWin side there is neither a title bar nor a border;
- **GTK / libadwaita apps** draw their own CSD;
- to KWin they are just bare rectangles, hard to tell apart from the desktop background and from each other (most obvious on dark wallpapers or over a transparent terminal).

This project gives such apps **a single native border**: it uses a KWin window rule to force server-side decorations, then a Breeze "window-specific override" to hide the title bar and set the border size to 0, leaving only that 1px outline. The border is drawn by KWin itself, so dragging, animations, occlusion, rounded corners and multi-monitor scaling all come for free, and you can still resize a window by dragging its edge with the mouse (the top edge needs Plasma ≥ 6.8, see "Requirements" below).

Three entry points, all taking effect immediately:

- **Window menu** (`Alt+F3` or right-click a title bar → "More Actions" → "Window Border"): add or remove the border for the current window's app;
- **Settings panel** (System Settings → Window Management → KWin Scripts → Window Border → Configure): maintain the list of enabled apps;
- **Command line** `windowborder-native`: shares one and the same implementation with the two entries above.

## Requirements

| Item | Requirement | Why |
| --- | --- | --- |
| **Plasma / KWin** | **≥ 6.6** (development environment: KDE neon / Plasma 6.7.5) | "Force server-side decorations via a window rule" only exists from 6.6 onwards: [kwin@bcdceae2](https://invent.kde.org/plasma/kwin/-/commit/bcdceae2) replaced the overloaded `noborder` boolean with `DecorationPolicy`, and in `WindowRules::checkDecorationPolicy()` a `noborder=false` (force) maps to `DecorationPolicy::Server`. On 6.5 and earlier, `XdgToplevelWindow::preferredDecorationMode()` only returns `None` when `noborder=true` — there is no "force Server" tier at all, so it has no effect on clients that draw their own CSD or want no decorations (GTK, Tauri `decorations:false`). |
| **Decoration plugin** | **Breeze only** (`org.kde.breeze`) | The tool relies on Breeze's window-specific overrides (`[Windeco Exception N]` in `breezerc`) to hide the title bar and set the border to 0 per app. Oxygen / Aurorae and others have no such per-app override mechanism; switching to them breaks the feature. (The KDecoration3 variant of Breeze requires Plasma ≥ 6.3, already covered by the 6.6 floor above.) |
| **Session** | Wayland | This works through the `xdg-decoration` / `xdg-toplevel-decoration` path. The same rules would also match under X11, but that has not been tested. |
| **Runtime** | `kpackagetool6`, `qdbus6` (KF6, shipped with Plasma 6), `python3`, `python3-dbus`, `python3-gi` | The install script uses `kpackagetool6` to install the KWin script and `qdbus6` to make KWin re-read its config; the D-Bus daemon uses dbus-python with a GLib main loop. All declared in the deb / PKGBUILD. |

Two behaviors tied to versions (details under "How it works" and "Known limitations"):

- **Top-edge resizing needs Plasma ≥ 6.8**: Breeze 6.7 and earlier hard-codes the top edge of `setResizeOnlyBorders()` to 0; upstream has fixed it ([breeze@6177e54b](https://invent.kde.org/plasma/breeze/-/commit/6177e54b4b1ef02bf0882be3b7dca1fadbe4f196), bug [504225](https://bugs.kde.org/show_bug.cgi?id=504225), FIXED-IN 6.8.0), and this tool needs no changes for that; the fallback on 6.7 and earlier is under "Known limitations".
- **Plasma ≥ 6.8 rewrites the rule keys**: 6.8 replaced `noborder` with the tri-state `decorationpolicy` ([kwin@065adbd3](https://invent.kde.org/plasma/kwin/-/commit/065adbd3)); the old keys are migrated by KWin itself. The backend keeps writing the old keys and accepts both key shapes, so the migration neither affects functionality nor causes rule rebuilds — details under "How it works".

## Installation

### Distribution package (regular users, recommended)

For KDE neon / Ubuntu, use the deb from this repository:

```bash
packaging/make-deb.sh                                  # → packaging/build/kwin-windowborder_1.0_all.deb
sudo apt install ./kwin-windowborder_1.0_all.deb        # or double-click it in Discover
```

After installing, **log out and back in once** (so KWin loads the script and the D-Bus service autostarts). That's it — no configuration, no command to enable. The package is `Architecture: all` (plain text + pure Python); the only dependencies are `python3-dbus`, `python3-gi` and `kwin-wayland (>= 4:6.6)` (the reason for the floor is under "Requirements" above; older Plasma is blocked by apt instead of installing and silently doing nothing).

Packaging details (deb / PKGBUILD / KDE Store) are in [packaging/README.md](packaging/README.md).

### From source (developers / no package)

```bash
tools/kwin-windowborder-menu-setup.sh install     # user-level, no root needed
```

It does four things:

1. `kpackagetool6 --type KWin/Script` installs `extension/` into `~/.local/share/kwin/scripts/windowborder-menu`;
2. installs the backend and the D-Bus service into `~/.local/bin/`, and drops one file each into `~/.local/share/dbus-1/services/` and `~/.config/autostart/` (activation on demand + resident at login);
3. flips `kwinrc [Plugins] windowborder-menuEnabled` on, unloads the old script instance and loads the new files;
4. syncs the rules once according to the current list.

Other subcommands: `status` / `restart` / `reapply` / `uninstall`.

## Usage

### Window menu

```
Alt+F3 or right-click a title bar
└── More Actions
    └── Window Border
        ├── Border enabled: dbx        ← checked state = whether this app is currently in the list
        └── Re-apply border settings
```

Clicking the first item adds or removes the border; it takes effect after 1–2 seconds (the backend writes config, then makes KWin and every decoration re-read it).

### Settings panel

System Settings → Window Management → KWin Scripts → **Window Border** → Configure — a single "Enabled applications" line with comma-separated window classes (the Wayland `app_id`, e.g. `dbx,deepseek-harness-desktop`).

On save, the panel only writes `kwinrc [Script-windowborder-menu] apps`; the D-Bus service watches that file and syncs it into rules as soon as it changes, so this takes effect immediately too.

### Command line (same logic, no GUI)

```bash
windowborder-native add dbx                 # add a border to an app
windowborder-native remove dbx              # remove it
windowborder-native status                  # show status
windowborder-native set BorderSize Tiny     # change the border width
windowborder-native set HideTitleBar false  # keep the title bar (see "Known limitations")
windowborder-native apply                   # regenerate and apply from the current config
windowborder-native reset                   # wipe all configuration made by this tool
```

`add` / `remove` / `set` are internally just "change config + apply", so they are always immediate. `apply` exists on its own for "don't change config, just regenerate and apply", mainly for: hand-editing `~/.config/windowborder-native.conf`; rules lost to a KWin upgrade or to manual deletion in System Settings → Window Rules; or retrying when a decoration didn't pick up the newest override (the KGlobalSettings race below).

## How it works

Both steps are native KWin/Breeze mechanisms — no custom plugin, no patch.

1. **KWin window rules** (`~/.config/kwinrulesrc`): one rule per app with an exact `wmclass=<app_id>` match, `noborder=false` + `noborderrule=2` ("no title bar and frame = no, force"; `Rules::Force`). In `rules.cpp`, `checkDecorationPolicy()`:

   ```cpp
   if (checkNoBorder(true, init) == false) return DecorationPolicy::Server;
   ```

   So the window's `decorationPolicy` becomes `Server`, KWin creates server-side decorations for it, and notifies the client with `configure(server_side)` via `xdg-decoration`. This path has existed since Plasma 6.6 (see "Requirements").

   **From Plasma 6.8 on**, these keys are replaced by the tri-state `decorationpolicy` (`none` / `client-preference` / `server` / `shadow`). When reading `kwinrulesrc`, KWin **migrates in place** the `noborder=false` + `noborderrule=2` we write into `decorationpolicy=server` + `decorationpolicyrule=2` and deletes the old `noborder*` keys (`src/rulebooksettings.cpp`; the comment says the migration path is kept until Plasma 7). So this tool keeps writing the old keys: 6.6/6.7 accept them directly, 6.8+ migrates them. When deciding "is the rule in effect", both key shapes count (the backend's `FORCE_RULE_KEYS`) — otherwise, once KWin has migrated them, every `apply` would think the rules were lost and rebuild them.

2. **Breeze window-specific overrides** (`~/.config/breezerc`, group `[Windeco Exception N]`): matched by window class, with `HideTitleBar=true`, `BorderSize=None`, `Mask=16`. Therefore:

   - border size 0 → **the window geometry is completely unchanged** and no client content is squeezed;
   - title bar hidden → it won't stack as a second layer on top of the title bar the client draws itself;
   - the 1px outline is kept → that is the visible border (active/inactive use different colors);
   - with `BorderSize=None`, Breeze calls `setResizeOnlyBorders(left/right/bottom)` → dragging those three edges resizes the window (only those three on Plasma ≤ 6.7; from 6.8 the top edge is included too, see "Known limitations").

**Why the title bar must be hidden**: the windows we handle are by definition "no system title bar + no decoration" (Tauri/WebView drawing their own title bar, or GTK drawing CSD). Once server-side decorations are forced, the title bar that comes with the decoration must be hidden — otherwise clients that honor `xdg-decoration` drop their own CSD and get a Breeze title bar instead, and clients that don't (Tauri `decorations:false`) end up with "the app's own title bar + a Breeze title bar" stacked. Conversely, **windows that have a system title bar already have window decorations**, so they are out of scope. That is why `HideTitleBar=true` + `BorderSize=None` are hard-coded defaults and the settings panel does not need that switch.

How it takes effect (built into the backend):

```bash
qdbus6 org.kde.KWin /KWin org.kde.KWin.reconfigure
# reconfigure is Q_NOREPLY; wait for KWin to finish (it re-parses breezerc),
# then make every decoration re-fetch its settings — Breeze's
# Decoration::reconfigure() is connected to this signal:
dbus-send --session --type=signal /KGlobalSettings \
          org.kde.KGlobalSettings.notifyChange int32:0 int32:0
```

The second step cannot be skipped, otherwise decorations get the previous round of overrides (which shows up as "taking effect one step late").

### Why not a custom effect / custom decoration plugin

- **Custom KWin effect (C++)**: drawing a border requires a binary effect plugin (KWin scripts cannot paint). But that means painting a layer on top of the compositor, so dragging, window animations, occlusion, rounded corners and multi-monitor scaling would all have to be handled by hand — and never cleanly (early versions of this project did exactly that; it has been removed, see commit `d910de0`).
- **Custom decoration plugin**: `DecorationBridge` loads exactly **one** decoration plugin globally (`kwinrc [org.kde.kdecoration2] library`), and window rules have no per-window plugin selector. Once a custom plugin is enabled it applies to the whole desktop, and every window not on the list loses its title bar — unless a full standard decoration is reimplemented inside the plugin.
- The right answer is Breeze's **built-in** window-specific overrides: that mechanism already is "a decoration plugin reading a config file and applying per app".

### Why a resident D-Bus service is needed

The only APIs available to a KWin script (a `KWin/Script` JS extension) are `readConfig` / `callDBus` / `registerShortcut` / screen edges / `registerUserActionsMenu` / `workspace` / `options` / `QTimer` (see the `globalProperties` list in kwin's `src/scripting/scripting.cpp`) — it **cannot write files or spawn processes**. But adding a border requires editing `~/.config/kwinrulesrc` and `~/.config/breezerc`. So the extension only does the UI and hands "what to do" to `windowborder-daemon` via `callDBus`:

| Who | Trigger | Result |
| --- | --- | --- |
| Window menu | `callDBus("org.kde.windowborder", …, "AddApp"/"RemoveApp", app)` | the daemon calls the backend to write the config and apply |
| Settings panel | the panel only writes `kwinrc` | the daemon checks `kwinrc` every 2 seconds → triggers a sync |

The daemon is started through two layers that back each other up: `/usr/share/dbus-1/services/org.kde.windowborder.service` (D-Bus activation on demand, so clicking the menu always brings it up) and `/etc/xdg/autostart/windowborder-daemon.desktop` (resident at login, so the settings-panel path always has a watcher). Both are "drop in and it works" — **no per-user enabling step**.

Other points:

- **What happens without it**: with only the extension itself (e.g. a `.kwinscript` installed from the KDE Store), nothing writes `kwinrc [Script-windowborder-menu] backend=dbus`, so the menu just shows a "backend not installed" notice instead of silently doing nothing on click;
- **The extension alone cannot install the daemon**: a `KWin/Script` KPackage is just a bunch of files, `kpackagetool6 -i` only copies them, there is no install hook, and KWin will not run commands for a script. Either use an install script like this repo's, or use a distribution package (recommended);
- Swapping the backend implementation only requires changing `sendRequest()` in the script.

### The three keys in kwinrc

`kwinrc [Script-windowborder-menu]`:

- `apps`: what the settings panel edits (the only config item declared in `extension/contents/config/main.xml`);
- `mirror`: the value the backend last wrote when mirroring; it distinguishes "the panel changed the list" from "the echo of our own write-back", and "the key doesn't exist at all". Semantics (`panel_changed_list()`): `apps` missing → not a command, do nothing; `apps` equal to `mirror` → it is an echo; anything else → `apps` wins (empty string = clear the list). Without the `mirror` layer, an accidentally deleted key would be read as "the user cleared the list" and wipe both the rules and the Breeze overrides;
- `backend`: the marker written by the daemon (`dbus`); the extension reads it to decide whether to show the real entries or the install notice.

### One gotcha: the `[Plugins]` key is shared by effects and scripts

KWin effects and scripts both read `<id>Enabled` from `kwinrc [Plugins]`. So the script id **must not** be `windowborder` (it would fight over the same key with a C++ effect of the same name, each turning the other on); the script here is called `windowborder-menu`, hence the config group `[Script-windowborder-menu]`.

## Known limitations

- **`decorationPolicy` is one-way**: adding a rule changes it to `Server`, but removing the rule does not roll it back automatically (`Window::applyWindowRules()` calls `setDecorationPolicy(decorationPolicy())`, passing the current value back in). So after `remove`, that window only fully gets its client-side decorations back after **restarting the app**.
- Clients that honor `xdg-decoration` (GTK/libadwaita) drop their own CSD once they receive `server_side`, so the window becomes "border only, no title bar". To keep their title bar, use `set HideTitleBar false`.
- Clients that don't honor the protocol (Tauri `decorations:false`) keep drawing their own title bar, resulting in "the app's own title bar + a border" — that is not a double title bar.
- **The top edge cannot be dragged to resize (Plasma ≤ 6.7)**: this is a direct side effect of "hidden title bar + `BorderSize=None`" on older Breeze, not a configuration error. In Breeze's `recalculateBorders()`:

  ```cpp
  setResizeOnlyBorders(QMarginsF(extSides, 0, extSides, extBottom));   // top edge always 0 (≤ 6.7)
  ```

  Upstream has fixed it: [breeze@6177e54b](https://invent.kde.org/plasma/breeze/-/commit/6177e54b4b1ef02bf0882be3b7dca1fadbe4f196) (bug [504225](https://bugs.kde.org/show_bug.cgi?id=504225), FIXED-IN 6.8.0) added `extTop = largeSpacing` to the top edge, so **on Plasma ≥ 6.8 all four edges can be dragged, with zero change to window geometry and appearance** (what is added is an input strip `largeSpacing` wide outside the window, roughly 16px depending on font/scaling, which does not steal clicks from the client area). Still on 6.7 or earlier, the fallback is the default `Meta` + right-click drag: it picks the gravity from the pointer's position inside the window, so pressing in the top third resizes from the top edge (`[MouseBindings] CommandAll3 = MouseUnrestrictedResize`).

  To get seamless top-edge resizing on older versions you can also pick a non-`None` `BorderSize`, at the cost of a visible solid border that changes window geometry. Measured pixels per step:

  | `BorderSize` | Top | Bottom | Left | Right | Notes |
  | --- | --- | --- | --- | --- | --- |
  | `None` (default) | 0 | 0 | 0 | 0 | 1px outline only, zero geometry change; left/right/bottom resizable, **top only draggable on 6.8+** |
  | `NoSides` | 4.5 | 4.5 | 0 | 0 | solid border on top/bottom (grabbable), left/right still resize-only |
  | `Tiny` | 4 | 4 | 2 | 2 | solid border on all four sides, all edges resizable |
  | `Normal` | 4 | 4 | 4 | 4 | same, thicker |

- The border **color follows the Breeze theme and color scheme** and cannot be set separately; `BorderSize=None` is only the 1px thin line.
- Fullscreen windows are unaffected (`preferredDecorationMode()` returns `None` for fullscreen).
- It takes roughly 1–2 seconds from clicking to seeing the border: the backend writes files → `reconfigure` → wait for KWin and the decorations to re-read settings.
- The rules only apply to normal windows (`types=1`); panels, the desktop, notifications and tooltips are not handled.
- The daemon keeps one resident Python process (about 15–20 MB). If it exits, the menu still works (D-Bus activates it on demand), but after the settings panel saves, nobody is watching `kwinrc` — it only syncs on the next menu action.

## Uninstall

```bash
tools/kwin-windowborder-menu-setup.sh uninstall   # remove the extension, backend and D-Bus service; keep the rules
windowborder-native reset                         # also clear the kwinrulesrc rules and the Breeze overrides
```

Installed via deb: `sudo apt remove kwin-windowborder` (also keeps the generated rules; run `reset` once more to clean up completely).

## Repository layout

```
extension/metadata.json                    KWin script extension metadata (KPackage, KWin/Script)
extension/contents/code/main.js            window menu: add/remove border, re-apply, missing-backend notice
extension/contents/config/main.xml         settings panel config item (apps)
extension/contents/ui/config.ui            settings panel UI
tools/windowborder-native.py               backend + CLI (the only implementation that writes kwinrulesrc/breezerc)
tools/windowborder-daemon.py               D-Bus service: menu requests + watching kwinrc
tools/kwin-windowborder-menu-setup.sh      user-level install/uninstall/status/restart/re-apply
packaging/install-layout.sh                system-level layout (shared manifest for the packaging scripts and debian/rules)
packaging/make-deb.sh                      build a .deb without debhelper
packaging/pack.sh                          build the KDE Store .kwinscript
packaging/PKGBUILD                         Arch/AUR skeleton
packaging/files/                           D-Bus activation + autostart templates
debian/                                    packaging directory for dpkg-buildpackage (PPA / OBS)
man/                                       man pages for the two command-line tools
```

## License

GPL-2.0-or-later (matching the KWin plugin interface requirements).