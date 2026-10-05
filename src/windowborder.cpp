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

/**
 * Converts a logical geometry into the coordinate space the scene renderer and
 * RenderViewport::projectionMatrix() work in: global logical coordinates
 * multiplied by the output scale, rounded to whole device pixels.
 *
 * This is deliberately *not* RenderViewport::mapToRenderTarget(): that one
 * returns output local device coordinates (it subtracts the output's position in
 * the virtual desktop) and is meant for placing output layers/planes, not for
 * OpenGL vertices. Using it here shifted the border by the output's global
 * origin, i.e. by 1920 px on a monitor that starts at x=1920.
 */
static Rect sceneDeviceRect(const RectF &logicalGeometry, qreal scale)
{
    return RectF(logicalGeometry.x() * scale,
                 logicalGeometry.y() * scale,
                 logicalGeometry.width() * scale,
                 logicalGeometry.height() * scale)
        .rounded();
}

/// Same as sceneDeviceRect(), for a whole region. Rounds inwards so that the
/// result never leaves the region it was derived from.
static Region sceneDeviceRegion(const Region &logicalRegion, qreal scale)
{
    Region ret;
    for (const Rect &rect : logicalRegion.rects()) {
        ret |= RectF(rect.x() * scale, rect.y() * scale, rect.width() * scale, rect.height() * scale).roundedIn();
    }
    return ret;
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
    // Which window is on top decides which one is bordered, so follow restacks.
    connect(effects, &EffectsHandler::stackingOrderChanged, this, [this]() {
        effects->addRepaintFull();
    });

    const QList<EffectWindow *> windows = effects->stackingOrder();
    for (EffectWindow *window : windows) {
        slotWindowAdded(window);
    }
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
    // "TopmostPerScreen" is the modern name; ActiveWindowOnly is kept as a
    // fallback for configurations written by older versions.
    m_topmostPerScreen = config.readEntry(QStringLiteral("TopmostPerScreen"), config.readEntry(QStringLiteral("ActiveWindowOnly"), true));
    m_activeWindowOnly = config.readEntry(QStringLiteral("ActiveWindowOnly"), true);
    m_excludeFullScreen = config.readEntry(QStringLiteral("ExcludeFullScreen"), true);
    m_excludeMaximized = config.readEntry(QStringLiteral("ExcludeMaximized"), false);
    m_perWindowColors = config.readEntry(QStringLiteral("PerWindowColors"), false);
    m_hideWhileMoving = config.readEntry(QStringLiteral("HideWhileMoving"), true);
    if (!m_hideWhileMoving) {
        m_movingWindows.clear();
    }

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
    connect(window, &EffectWindow::windowStartUserMovedResized, this, &WindowBorderEffect::slotWindowMoveResizeStarted);
    connect(window, &EffectWindow::windowFinishUserMovedResized, this, &WindowBorderEffect::slotWindowMoveResizeFinished);

    repaintWindow(window);
}

void WindowBorderEffect::slotWindowClosed(EffectWindow *window)
{
    m_movingWindows.remove(window);
    repaintWindow(window);
}

void WindowBorderEffect::slotWindowMoveResizeStarted(EffectWindow *window)
{
    if (!window) {
        return;
    }
    m_movingWindows.insert(window);
    // Paint the border away: the window keeps moving, so it would only lag
    // behind and leave copies of itself along the drag path.
    repaintWindow(window);
}

void WindowBorderEffect::slotWindowMoveResizeFinished(EffectWindow *window)
{
    if (!window) {
        return;
    }
    m_movingWindows.remove(window);
    repaintWindow(window);
}

void WindowBorderEffect::slotActiveWindowChanged(EffectWindow *window)
{
    Q_UNUSED(window)

    // The active window decides the colour (and, with TopmostPerScreen off,
    // whether a window is bordered at all). Which window is active per output
    // is not observable from here, so repaint everything.
    effects->addRepaintFull();
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

int WindowBorderEffect::borderWidthFor(bool featured) const
{
    if (featured) {
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

QColor WindowBorderEffect::borderColorFor(const EffectWindow *window, bool featured) const
{
    if (featured) {
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

Region WindowBorderEffect::borderRegionFor(const EffectWindow *window, const Region &covered, const Region &damage, qreal scale, bool featured) const
{
    const Rect frame = sceneDeviceRect(window->frameGeometry(), scale);
    if (frame.isEmpty()) {
        return Region();
    }

    // Never let the border eat more than half of the window.
    const int maximumWidth = qMax(0, (qMin(frame.width(), frame.height()) - 1) / 2);
    const int width = qMin(qRound(borderWidthFor(featured) * scale), maximumWidth);
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

void WindowBorderEffect::paintWindow(const RenderTarget &renderTarget, const RenderViewport &viewport, EffectWindow *window, int mask, const Region &deviceRegion, WindowPaintData &data)
{
    // A window that is painted with a transform (move/resize animation, wobbly
    // windows, ...) is not where its frame geometry says it is, so its border
    // would be drawn at the wrong place. Remember it and skip it below.
    if (mask & PAINT_WINDOW_TRANSFORMED) {
        m_transformedWindows.insert(window);
    }
    effects->paintWindow(renderTarget, viewport, window, mask, deviceRegion, data);
}

void WindowBorderEffect::paintScreen(const RenderTarget &renderTarget, const RenderViewport &viewport, int mask, const Region &deviceRegion, LogicalOutput *screen)
{
    m_transformedWindows.clear();

    // The scene pass runs the other effects and calls paintWindow() for every
    // window it paints, which is what fills m_transformedWindows.
    effects->paintScreen(renderTarget, viewport, mask, deviceRegion, screen);

    // Overview, desktop grid, zoom, desktop switching slides and friends
    // transform the whole scene; borders would be drawn at the wrong place, so
    // stay out of their way.
    if (!isActive() || effects->hasActiveFullScreenEffect() || (mask & PAINT_SCREEN_TRANSFORMED)) {
        return;
    }

    const qreal scale = viewport.scale();
    const Region damage = sceneDeviceRegion(viewport.mapFromDeviceCoordinatesContained(deviceRegion), scale);
    if (damage.isEmpty()) {
        return;
    }

    QList<Border> borders;
    Region covered;
    m_featuredOutputs.clear();

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

        const Rect frame = sceneDeviceRect(window->frameGeometry(), scale);
        if (frame.isEmpty()) {
            continue;
        }

        // Decide who gets the "featured" (active colour / width) border. This is
        // deliberately done before the damage check below, so that the decision
        // does not depend on which part of the screen happens to be repainted -
        // otherwise the border would flicker while the pointer moves around.
        bool eligible = hasBorder(window);
        bool featured = window == effects->activeWindow();
        if (m_topmostPerScreen) {
            // Only the frontmost window of every output is bordered. Unlike the
            // focused window this does not change when the pointer moves to
            // another screen, so the border stays put.
            featured = false;
            if (eligible) {
                LogicalOutput *output = window->screen();
                if (output && m_featuredOutputs.contains(output)) {
                    eligible = false;
                } else {
                    featured = true;
                    if (output) {
                        m_featuredOutputs.insert(output);
                    }
                }
            }
        } else if (m_activeWindowOnly && !featured) {
            eligible = false;
        }

        const Region frameRegion(frame);
        if (!frameRegion.intersects(damage)) {
            continue;
        }

        const bool moving = m_movingWindows.contains(window);
        const bool transformed = m_transformedWindows.contains(window);
        if (eligible && !transformed && !(m_hideWhileMoving && moving)) {
            const Region region = borderRegionFor(window, covered, damage, scale, featured);
            if (!region.isEmpty()) {
                const QColor color = borderColorFor(window, featured);
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
        // `region` is already expressed in the scene renderer's coordinate space
        // (global logical coordinates * output scale), which is what
        // viewport.projectionMatrix() maps to the render target. Mapping it again
        // with mapToRenderTarget() would offset it by the output's global origin.
        GLVertexBuffer *vbo = GLVertexBuffer::streamingBuffer();
        vbo->reset();

        ShaderBinder binder(ShaderTrait::UniformColor | ShaderTrait::TransformColorspace);
        binder.shader()->setUniform(GLShader::Mat4Uniform::ModelViewProjectionMatrix, viewport.projectionMatrix());
        binder.shader()->setColorspaceUniforms(ColorDescription::sRGB, renderTarget.colorDescription(), RenderingIntent::Perceptual);
        binder.shader()->setUniform(GLShader::ColorUniform::Color, color);

        QList<QVector2D> vertices;
        vertices.reserve(region.rects().size() * 6);
        for (const Rect &rect : region.rects()) {
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
        // The QPainter scene renderer draws in global logical coordinates.
        const qreal inverseScale = 1.0 / viewport.scale();
        painter->save();
        painter->setPen(Qt::NoPen);
        painter->setBrush(color);
        for (const Rect &rect : region.rects()) {
            painter->drawRect(QRectF(rect.x() * inverseScale,
                                     rect.y() * inverseScale,
                                     rect.width() * inverseScale,
                                     rect.height() * inverseScale));
        }
        painter->restore();
    }
}

} // namespace KWin
