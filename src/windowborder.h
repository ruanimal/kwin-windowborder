/*
    SPDX-FileCopyrightText: 2025 KWin Window Border effect contributors
    SPDX-License-Identifier: GPL-2.0-or-later
*/

#pragma once

#include "core/rect.h"
#include "effect/effect.h"

#include <QColor>
#include <QList>
#include <QPointer>
#include <QSet>

namespace KWin
{

class EffectWindow;

/**
 * KWin effect that paints a coloured border around windows.
 *
 * It is meant for windows that have no server side decoration, e.g. GTK/CSD
 * applications or Tauri/WebKitGTK windows, which otherwise are hard to tell
 * apart from the desktop background or from each other.
 *
 * The border is drawn on top of the composited scene. Occlusion is taken into
 * account: the border of a window is clipped against the windows above it, so
 * borders never bleed over overlapping windows.
 */
class WindowBorderEffect : public Effect
{
    Q_OBJECT
    Q_PROPERTY(bool enabled READ isEnabled WRITE setEnabled)

public:
    WindowBorderEffect();
    ~WindowBorderEffect() override;

    static bool supported();
    static bool enabledByDefault();

    void reconfigure(ReconfigureFlags flags) override;
    void paintScreen(const RenderTarget &renderTarget, const RenderViewport &viewport, int mask, const Region &deviceRegion, LogicalOutput *screen) override;
    void paintWindow(const RenderTarget &renderTarget, const RenderViewport &viewport, EffectWindow *window, int mask, const Region &deviceRegion, WindowPaintData &data) override;
    bool isActive() const override;

    bool isEnabled() const;
    void setEnabled(bool enabled);

private:
    enum class Placement {
        Inside,
        Center,
        Outside,
    };

    struct Border {
        QColor color;
        Region region;
    };

    void slotWindowAdded(EffectWindow *window);
    void slotWindowClosed(EffectWindow *window);
    void slotActiveWindowChanged(EffectWindow *window);
    void slotWindowMoveResizeStarted(EffectWindow *window);
    void slotWindowMoveResizeFinished(EffectWindow *window);
    void repaintWindow(EffectWindow *window);
    void repaintFrame(const RectF &frame);

    int borderWidthFor(bool featured) const;
    bool hasBorder(const EffectWindow *window) const;
    QColor borderColorFor(const EffectWindow *window, bool featured) const;
    Region borderRegionFor(const EffectWindow *window, const Region &covered, const Region &damage, qreal scale, bool featured) const;

    void drawBorders(const RenderTarget &renderTarget, const RenderViewport &viewport, const Region &region, const QColor &color);

    bool m_enabled = true;
    int m_borderWidth = 2;
    int m_activeBorderWidth = 0;
    Placement m_placement = Placement::Inside;
    QColor m_activeColor;
    QColor m_inactiveColor;
    bool m_borderOnDecoratedWindows = false;
    /// Only one bordered window per output; see m_topmostPerScreen.
    bool m_topmostPerScreen = true;
    /// Only when m_topmostPerScreen is off: border only the focused window.
    bool m_activeWindowOnly = true;
    bool m_excludeFullScreen = true;
    bool m_excludeMaximized = false;
    bool m_perWindowColors = false;
    bool m_hideWhileMoving = true;
    /// Windows the user is currently moving or resizing.
    QSet<EffectWindow *> m_movingWindows;
    /// Windows this frame's scene pass painted with a transform (animations).
    QSet<EffectWindow *> m_transformedWindows;
    /// Outputs that already got their frontmost window bordered this frame.
    QSet<LogicalOutput *> m_featuredOutputs;
};

} // namespace KWin
