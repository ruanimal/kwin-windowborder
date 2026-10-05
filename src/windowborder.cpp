/*
    SPDX-FileCopyrightText: 2025 KWin Window Border effect contributors
    SPDX-License-Identifier: GPL-2.0-or-later
*/

#include "windowborder.h"

#include "core/output.h"
#include "core/region.h"
#include "core/rendertarget.h"
#include "core/renderviewport.h"
#include "effect/effecthandler.h"
#include "effect/effectwindow.h"
#include "opengl/glshader.h"
#include "opengl/glshadermanager.h"
#include "opengl/glvertexbuffer.h"
#include "window.h"

#include <KConfigGroup>

#include <QMargins>
#include <QPainter>
#include <QVector2D>

namespace KWin
{

static const QColor s_defaultActiveColor(61, 174, 233); // Breeze highlight blue
static const QColor s_defaultInactiveColor(0, 0, 0, 128);

static QColor readColor(const KConfigGroup &config, const QString &key, const QColor &fallback)
{
    const QString value = config.readEntry(key, QString());
    if (value.isEmpty()) {
        return fallback;
    }
    const QColor color = QColor::fromString(value);
    return color.isValid() ? color : fallback;
}

WindowBorderEffect::WindowBorderEffect()
{
    reconfigure(ReconfigureAll);

    connect(effects, &EffectsHandler::windowAdded, this, &WindowBorderEffect::slotWindowAdded);
    connect(effects, &EffectsHandler::windowClosed, this, &WindowBorderEffect::slotWindowClosed);
    connect(effects, &EffectsHandler::windowActivated, this, &WindowBorderEffect::slotActiveWindowChanged);
    connect(effects, &EffectsHandler::desktopChanged, this, [this]() {
        effects->addRepaintFull();
    });
    connect(effects, &EffectsHandler::currentActivityChanged, this, [this]() {
        effects->addRepaintFull();
    });
    connect(effects, &EffectsHandler::screenAdded, this, [this]() {
        effects->addRepaintFull();
    });
    connect(effects, &EffectsHandler::screenRemoved, this, [this]() {
        effects->addRepaintFull();
    });

    const QList<EffectWindow *> windows = effects->stackingOrder();
    for (EffectWindow *window : windows) {
        slotWindowAdded(window);
    }

    m_lastActiveWindow = effects->activeWindow();
}

WindowBorderEffect::~WindowBorderEffect() = default;

bool WindowBorderEffect::supported()
{
    return effects->isOpenGLCompositing() || effects->compositingType() == QPainterCompositing;
}

bool WindowBorderEffect::enabledByDefault()
{
    return false;
}

void WindowBorderEffect::reconfigure(ReconfigureFlags flags)
{
    Q_UNUSED(flags)

    KConfigGroup config(effects->config(), QStringLiteral("Effect-windowborder"));

    m_enabled = config.readEntry(QStringLiteral("Enabled"), true);
    m_borderWidth = qBound(0, config.readEntry(QStringLiteral("BorderWidth"), 2), 32);
    m_activeBorderWidth = qBound(0, config.readEntry(QStringLiteral("ActiveBorderWidth"), 0), 32);

    const QString placement = config.readEntry(QStringLiteral("BorderPlacement"), QStringLiteral("inside")).toLower();
    if (placement == QLatin1String("outside")) {
        m_placement = Placement::Outside;
    } else if (placement == QLatin1String("center")) {
        m_placement = Placement::Center;
    } else {
        m_placement = Placement::Inside;
    }

    m_activeColor = readColor(config, QStringLiteral("ActiveColor"), s_defaultActiveColor);
    m_inactiveColor = readColor(config, QStringLiteral("InactiveColor"), s_defaultInactiveColor);
    m_borderOnDecoratedWindows = config.readEntry(QStringLiteral("BorderOnDecoratedWindows"), false);
    m_activeWindowOnly = config.readEntry(QStringLiteral("ActiveWindowOnly"), false);
    m_excludeFullScreen = config.readEntry(QStringLiteral("ExcludeFullScreen"), true);
    m_excludeMaximized = config.readEntry(QStringLiteral("ExcludeMaximized"), false);
    m_perWindowColors = config.readEntry(QStringLiteral("PerWindowColors"), false);

    effects->addRepaintFull();
}

bool WindowBorderEffect::isEnabled() const
{
    return m_enabled;
}

void WindowBorderEffect::setEnabled(bool enabled)
{
    if (m_enabled == enabled) {
        return;
    }
    m_enabled = enabled;
    effects->addRepaintFull();
}

bool WindowBorderEffect::isActive() const
{
    return m_enabled && (m_borderWidth > 0 || m_activeBorderWidth > 0);
}

void WindowBorderEffect::slotWindowAdded(EffectWindow *window)
{
    if (!window) {
        return;
    }

    connect(window, &EffectWindow::windowFrameGeometryChanged, this, [this](EffectWindow *w, const RectF &oldGeometry) {
        repaintFrame(oldGeometry);
        repaintWindow(w);
    });
    connect(window, &EffectWindow::windowExpandedGeometryChanged, this, &WindowBorderEffect::repaintWindow);
    connect(window, &EffectWindow::windowDecorationChanged, this, &WindowBorderEffect::repaintWindow);
    connect(window, &EffectWindow::windowDesktopsChanged, this, &WindowBorderEffect::repaintWindow);
    connect(window, &EffectWindow::windowHiddenChanged, this, &WindowBorderEffect::repaintWindow);
    connect(window, &EffectWindow::minimizedChanged, this, &WindowBorderEffect::repaintWindow);
    connect(window, &EffectWindow::windowFullScreenChanged, this, &WindowBorderEffect::repaintWindow);
    connect(window, &EffectWindow::windowMaximizedStateChanged, this, [this](EffectWindow *w, bool, bool) {
        repaintWindow(w);
    });
    connect(window, &EffectWindow::windowOpacityChanged, this, [this](EffectWindow *w, qreal, qreal) {
        repaintWindow(w);
    });

    repaintWindow(window);
}

void WindowBorderEffect::slotWindowClosed(EffectWindow *window)
{
    repaintWindow(window);
}

void WindowBorderEffect::slotActiveWindowChanged(EffectWindow *window)
{
    repaintWindow(m_lastActiveWindow.data());
    repaintWindow(window);
    m_lastActiveWindow = window;
}

void WindowBorderEffect::repaintWindow(EffectWindow *window)
{
    if (!window) {
        return;
    }
    repaintFrame(window->frameGeometry());
}

void WindowBorderEffect::repaintFrame(const RectF &frame)
{
    if (!m_enabled || frame.isEmpty()) {
        return;
    }
    const qreal padding = qMax(m_borderWidth, m_activeBorderWidth) + 2;
    effects->addRepaint(frame.adjusted(-padding, -padding, padding, padding));
}

int WindowBorderEffect::borderWidthFor(const EffectWindow *window) const
{
    if (window && window == effects->activeWindow()) {
        return m_activeBorderWidth > 0 ? m_activeBorderWidth : m_borderWidth;
    }
    return m_borderWidth;
}

bool WindowBorderEffect::hasBorder(const EffectWindow *window) const
{
    if (!window) {
        return false;
    }
    if (window->isOutline() || window->isPopupWindow() || window->isSpecialWindow()) {
        return false;
    }
    if (!window->isNormalWindow() && !window->isDialog() && !window->isUtility()) {
        return false;
    }
    if (m_activeWindowOnly && window != effects->activeWindow()) {
        return false;
    }
    if (m_excludeFullScreen && window->isFullScreen()) {
        return false;
    }
    if (m_excludeMaximized) {
        const Window *internal = window->window();
        if (internal && internal->maximizeMode() != MaximizeRestore) {
            return false;
        }
    }
    if (!m_borderOnDecoratedWindows && window->hasDecoration()) {
        return false;
    }
    return true;
}

QColor WindowBorderEffect::borderColorFor(const EffectWindow *window) const
{
    if (window && window == effects->activeWindow()) {
        return m_activeColor;
    }
    if (m_perWindowColors && window) {
        const QString identifier = window->windowClass().isEmpty() ? window->caption() : window->windowClass();
        const uint hash = qHash(identifier);
        QColor color = QColor::fromHsv(int(hash % 360), 165, 205);
        color.setAlpha(m_inactiveColor.alpha());
        return color;
    }
    return m_inactiveColor;
}

Region WindowBorderEffect::borderRegionFor(const EffectWindow *window, const Region &covered, const Region &damage) const
{
    const Rect frame = window->frameGeometry().toAlignedRect();
    if (frame.isEmpty()) {
        return Region();
    }

    // Never let the border eat more than half of the window.
    const int maximumWidth = qMax(0, (qMin(frame.width(), frame.height()) - 1) / 2);
    const int width = qMin(borderWidthFor(window), maximumWidth);
    if (width <= 0) {
        return Region();
    }

    Rect outer = frame;
    Rect inner = frame;
    switch (m_placement) {
    case Placement::Inside:
        inner = frame.shrunkBy(QMargins(width, width, width, width));
        break;
    case Placement::Center: {
        const int outside = (width + 1) / 2;
        const int inside = width / 2;
        outer = frame.grownBy(QMargins(outside, outside, outside, outside));
        inner = frame.shrunkBy(QMargins(inside, inside, inside, inside));
        break;
    }
    case Placement::Outside:
        outer = frame.grownBy(QMargins(width, width, width, width));
        break;
    }

    const Region region = Region(outer).subtracted(covered).subtracted(inner);
    return region.intersected(damage);
}

void WindowBorderEffect::paintScreen(const RenderTarget &renderTarget, const RenderViewport &viewport, int mask, const Region &deviceRegion, LogicalOutput *screen)
{
    effects->paintScreen(renderTarget, viewport, mask, deviceRegion, screen);

    // Overview, desktop grid, zoom and friends transform the scene; borders
    // would be drawn at the wrong place, so stay out of their way.
    if (!isActive() || effects->hasActiveFullScreenEffect()) {
        return;
    }

    const Region damage = viewport.mapFromDeviceCoordinatesContained(deviceRegion);
    if (damage.isEmpty()) {
        return;
    }

    QList<Border> borders;
    Region covered;

    const QList<EffectWindow *> windows = effects->stackingOrder();
    for (auto it = windows.crbegin(); it != windows.crend(); ++it) {
        EffectWindow *window = *it;
        if (!window || window->isDeleted()) {
            continue;
        }
        if (!window->isVisible() || window->isMinimized() || window->isHidden()
            || !window->isOnCurrentDesktop() || !window->isOnCurrentActivity()) {
            continue;
        }

        const Rect frame = window->frameGeometry().toAlignedRect();
        if (frame.isEmpty()) {
            continue;
        }

        const Region frameRegion(frame);
        if (!frameRegion.intersects(damage)) {
            continue;
        }

        if (hasBorder(window)) {
            const Region region = borderRegionFor(window, covered, damage);
            if (!region.isEmpty()) {
                const QColor color = borderColorFor(window);
                bool merged = false;
                for (Border &border : borders) {
                    if (border.color == color) {
                        border.region = border.region.united(region);
                        merged = true;
                        break;
                    }
                }
                if (!merged) {
                    borders.append(Border{color, region});
                }
            }
        }

        // Opaque windows hide the borders of the windows below them.
        if (window->opacity() > 0.5) {
            covered = covered.united(frame);
        }
    }

    for (const Border &border : borders) {
        drawBorders(renderTarget, viewport, border.region, border.color);
    }
}

void WindowBorderEffect::drawBorders(const RenderTarget &renderTarget, const RenderViewport &viewport, const Region &region, const QColor &color)
{
    if (region.isEmpty() || !color.isValid() || color.alpha() == 0) {
        return;
    }

    if (effects->isOpenGLCompositing()) {
        const Region deviceRegion = viewport.mapToRenderTarget(region);
        if (deviceRegion.isEmpty()) {
            return;
        }

        GLVertexBuffer *vbo = GLVertexBuffer::streamingBuffer();
        vbo->reset();

        ShaderBinder binder(ShaderTrait::UniformColor | ShaderTrait::TransformColorspace);
        binder.shader()->setUniform(GLShader::Mat4Uniform::ModelViewProjectionMatrix, viewport.projectionMatrix());
        binder.shader()->setColorspaceUniforms(ColorDescription::sRGB, renderTarget.colorDescription(), RenderingIntent::Perceptual);
        binder.shader()->setUniform(GLShader::ColorUniform::Color, color);

        QList<QVector2D> vertices;
        vertices.reserve(deviceRegion.rects().size() * 6);
        for (const Rect &rect : deviceRegion.rects()) {
            const float left = rect.x();
            const float top = rect.y();
            const float right = rect.x() + rect.width();
            const float bottom = rect.y() + rect.height();
            vertices << QVector2D(right, top) << QVector2D(left, top) << QVector2D(left, bottom)
                     << QVector2D(left, bottom) << QVector2D(right, bottom) << QVector2D(right, top);
        }
        vbo->setVertices(vertices);

        glEnable(GL_BLEND);
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
        vbo->render(GL_TRIANGLES);
        glDisable(GL_BLEND);
    } else if (effects->compositingType() == QPainterCompositing) {
        QPainter *painter = effects->scenePainter();
        if (!painter) {
            return;
        }
        painter->save();
        painter->setPen(Qt::NoPen);
        painter->setBrush(color);
        for (const Rect &rect : region.rects()) {
            painter->drawRect(QRectF(rect.x(), rect.y(), rect.width(), rect.height()));
        }
        painter->restore();
    }
}

} // namespace KWin
