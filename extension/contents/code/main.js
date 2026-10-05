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
// 点击后由后端（tools/windowborder-native.py，经 D-Bus 服务
// org.kde.windowborder）写 kwinrulesrc + breezerc，让 KWin 用 Breeze 的原生装饰给
// 这个应用画一圈 1px 边框（不改窗口几何、不显示标题栏），然后触发 reconfigure ——
// 和命令行 `windowborder-native.py add dbx` 完全等价，只是入口换成了菜单。
//
// 为什么不在这里直接干活：KWin 脚本引擎（见 kwin/src/scripting/scripting.cpp 的
// globalProperties）只暴露 readConfig / callDBus / registerShortcut /
// registerScreenEdge / registerUserActionsMenu / QTimer / workspace / options，
// **不能写文件、不能起进程**，而加边框必须改 ~/.config/kwinrulesrc 和
// ~/.config/breezerc。所以这里只发 D-Bus 请求，真正的写入由常驻的
// tools/windowborder-daemon.py 完成（它同时也盯着 kwinrc，让设置面板改完立即生效）。
//
// 设置面板里的应用名单存在 kwinrc [Script-windowborder-menu] apps；守护进程装好后
// 会往同一组写 backend=dbus，本脚本读这个键判断后端在不在，不在就只在菜单里显示
// 安装提示（见 backendReady()）。

// 子菜单标题尾部的空格：Breeze 在高亮那一项时会把子菜单箭头画得离文字很近，
// 中文标题的最后一个字会被箭头压住（和 kwin-window-size-presets 同样的处理）。
const SUBMENU_PADDING = "  ";

const BUS_NAME = "org.kde.windowborder";
const OBJECT_PATH = "/WindowBorder";
const INTERFACE = "org.kde.windowborder";

function log(message) {
    print("[windowborder] " + message);
}

// 当前名单。readConfig 每次都是现读 KConfigGroup，而每次生效后端都会让 KWin
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

// 守护进程装好后会写 backend=dbus；读不到就说明只有扩展本体（比如只从 KDE Store
// 装了脚本），菜单里给一条安装提示，否则点了没反应会让人以为是坏的。
function backendReady() {
    return String(readConfig("backend", "")) === "dbus";
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

// app 为空表示这个方法不带参数（Sync / Reapply）
function sendRequest(method, app) {
    if (app === undefined || app === "") {
        callDBus(BUS_NAME, OBJECT_PATH, INTERFACE, method, function (ok) {
            log(method + " -> " + ok);
        });
    } else {
        callDBus(BUS_NAME, OBJECT_PATH, INTERFACE, method, app, function (ok) {
            log(method + " -> " + ok);
        });
    }
}

function toggleItem(app, enabled) {
    return {
        text: (enabled ? "已启用边框：" : "给这个应用加边框：") + app,
        checkable: true,
        checked: enabled,
        triggered: function () {
            sendRequest(enabled ? "RemoveApp" : "AddApp", app);
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

    const items = [];
    if (backendReady()) {
        items.push(toggleItem(app, appList().indexOf(app) >= 0));
        items.push({
            text: "重新应用边框设置",
            triggered: function () {
                sendRequest("Reapply");
            },
        });
    } else {
        items.push({
            text: "后端未安装（见 README 的安装说明）",
            triggered: function () {
                log("后端未安装：菜单里只有提示，没有可执行的动作");
            },
        });
    }

    return {
        text: "窗口边框" + SUBMENU_PADDING,
        items: items,
    };
}

registerUserActionsMenu(buildMenu);

log("已加载；后端: " + (backendReady() ? "已安装" : "未安装")
    + "，当前名单: " + (appList().join(", ") || "（空）"));
