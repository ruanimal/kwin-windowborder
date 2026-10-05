/*
    SPDX-FileCopyrightText: 2025 KWin Window Border effect contributors
    SPDX-License-Identifier: GPL-2.0-or-later
*/

#include "windowborder.h"

namespace KWin
{

KWIN_EFFECT_FACTORY_SUPPORTED(WindowBorderEffect,
                              "windowborder.json",
                              return WindowBorderEffect::supported();)

} // namespace KWin

#include "main.moc"
