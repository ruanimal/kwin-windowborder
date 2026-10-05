cmake_minimum_required(VERSION 3.20)

project(kwin-windowborder
    VERSION 1.0.0
    DESCRIPTION "KWin effect that draws a border around windows"
    LANGUAGES CXX
)

# kcoreaddons_add_plugin() builds a static library when BUILD_SHARED_LIBS is off,
# which is not what an effect plugin needs.
set(BUILD_SHARED_LIBS ON)

set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(ECM 6.26 REQUIRED NO_MODULE)
set(CMAKE_MODULE_PATH ${ECM_MODULE_PATH} ${CMAKE_MODULE_PATH})

include(KDEInstallDirs)
include(KDECMakeSettings)
include(KDECompilerSettings NO_POLICY_SCOPE)

find_package(Qt6 6.10 REQUIRED COMPONENTS Core Gui Widgets)
find_package(KF6 6.26 REQUIRED COMPONENTS Config CoreAddons)
find_package(KWin REQUIRED)

kcoreaddons_add_plugin(windowborder
    SOURCES
        src/main.cpp
        src/windowborder.cpp
        src/windowborder.json
    INSTALL_NAMESPACE "kwin/effects/plugins"
)

target_link_libraries(windowborder PRIVATE
    KWin::kwin
    Qt6::Core
    Qt6::Gui
    Qt6::Widgets
    KF6::ConfigCore
    KF6::CoreAddons
)

# Optional convenience: install the helper script next to the plugin.
install(PROGRAMS tools/kwin-windowborder-setup.sh DESTINATION ${KDE_INSTALL_BINDIR})
