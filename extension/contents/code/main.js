// SPDX-License-Identifier: GPL-2.0-or-later
//
// Window Border — KWin 脚本扩展
//
// 在窗口菜单（Alt+F3 / 标题栏右键）的「扩展」下加一个「窗口边框」子菜单：
//
//   扩展 ▸ 窗口边框
//       ├── 已启用边框：dbx          ← 勾选状态 = 当前应用是否在名单里
//       └── 重新应用边框设置
//
// 点条目后，后端（tools/windowborder-native.py）会写 kwinrulesrc + breezerc，
// 让 KWin 用 Breeze 的原生装饰给这个应用画一圈 1px 边框（不改窗口几何、不显示
// 标题栏），然后触发 reconfigure —— 和命令行 `windowborder-native.py add dbx`
// 完全等价，只是入口换成了菜单。
//
// 为什么不在这里直接干活：KWin 脚本引擎（见 kwin/src/scripting/scripting.cpp）
// 只暴露 readConfig / callDBus / registerShortcut / registerScreenEdge /
// registerUserActionsMenu / QTimer / workspace / options，**不能写文件、不能起进程**，
// 而加边框必须改 ~/.config/kwinrulesrc 和 ~/.config/breezerc。所以只能 callDBus，
// 由 systemd 用户模板单元 windowborder@<请求>.service 把请求交给后端脚本执行
// （单元实例名不能带空格/斜杠等，所以应用名在这里编码，见 encodeToken）。
//
// 设置面板里的应用名单存在 kwinrc [Script-windowborder-menu] apps（由
// tools/kwin-windowborder-menu-setup.sh 安装的 path 单元盯着，改完自动同步）。

// 子菜单标题尾部的空格：Breeze 在高亮那一项时会把子菜单箭头画得离文字很近，
// 中文标题的最后一个字会被箭头压住（和 kwin-window-size-presets 同样的处理）。
const SUBMENU_PADDING = "  ";

function log(message) {
    print("[windowborder] " + message);
}

// 应用名 → systemd 单元实例名里安全的 token。
// 单元名只允许 [A-Za-z0-9:_.\-]，所以除了 [A-Za-z0-9.-] 之外都编码：
//   < 256   → _hh（十六进制两位）
//   >= 256  → _uhhhh（十六进制四位）
// 后端 tools/windowborder-native.py 的 decode_token() 负责解回来。
function encodeToken(text) {
    const safe = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789.-";
    let out = "";
    for (let i = 0; i < text.length; ++i) {
        const ch = text.charAt(i);
        const code = text.charCodeAt(i);
        if (code < 128 && safe.indexOf(ch) >= 0) {
            out += ch;
        } else if (code < 256) {
            out += "_" + ("0" + code.toString(16)).slice(-2);
        } else {
            out += "_u" + ("000" + code.toString(16)).slice(-4);
        }
    }
    return out;
}

// 当前名单。readConfig 每次都是现读 KConfigGroup，而后端每次生效都会让 KWin
// 重新解析 kwinrc，所以菜单打开时拿到的是最新值。
function appList() {
    const parts = String(readConfig("apps", "")).split(",");
    const apps = [];
    for (let i = 0; i < parts.length; ++i) {
        const app = parts[i].trim();
        if (app && apps.indexOf(app) < 0) {
            apps.push(app);
        }
    }
    return apps;
}

// 窗口的应用标识。KWin 窗口规则的 wmclass 精确匹配的是 resourceClass
// （rules.cpp: matchWMClass(resourceClass, resourceName)，wmclasscomplete 默认关），
// 所以菜单也用 resourceClass，保证和规则/后端写进 kwinrulesrc 的值一致。
function windowApp(window) {
    const resourceClass = String(window.resourceClass || "").trim();
    if (resourceClass) {
        return resourceClass;
    }
    return String(window.desktopFileName || "").trim().replace(/\.desktop$/, "");
}

function sendRequest(request) {
    callDBus("org.freedesktop.systemd1", "/org/freedesktop/systemd1",
             "org.freedesktop.systemd1.Manager", "StartUnit",
             "windowborder@" + request + ".service", "replace",
             function (job) {
                 log("request " + request + " -> " + job);
             });
}

function toggleItem(app, enabled) {
    return {
        text: (enabled ? "已启用边框：" : "给这个应用加边框：") + app,
        checkable: true,
        checked: enabled,
        triggered: function () {
            sendRequest((enabled ? "remove:" : "add:") + encodeToken(app));
        },
    };
}

function buildMenu(window) {
    // 只对普通窗口给入口：面板、桌面、通知、工具提示这些窗口不该加边框，
    // 而且 kwinrulesrc 里的规则也是 types=1（Normal window）。
    if (!window || !window.normalWindow) {
        return null;
    }
    const app = windowApp(window);
    if (!app) {
        return null;
    }

    return {
        text: "窗口边框" + SUBMENU_PADDING,
        items: [
            toggleItem(app, appList().indexOf(app) >= 0),
            {
                text: "重新应用边框设置",
                triggered: function () {
                    sendRequest("reapply");
                },
            },
        ],
    };
}

registerUserActionsMenu(buildMenu);

log("已加载；当前名单: " + (appList().join(", ") || "（空）"));
