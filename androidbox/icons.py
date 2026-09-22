"""Toolbar glyphs drawn in code so every platform shows identical icons."""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

GRID = 24   # Glyphs are designed on a 24x24 grid.
SCALE = 4   # They are rendered four times larger to stay crisp where they land.


def _fill(painter, color, path):
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawPath(path)


def _stroke(painter, color, path, width=2.0):
    painter.setPen(QPen(QColor(color), width, Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(path)


def _play(painter, color):
    path = QPainterPath()
    path.moveTo(7.5, 5.0)
    path.lineTo(19.0, 12.0)
    path.lineTo(7.5, 19.0)
    path.closeSubpath()
    _fill(painter, color, path)


def _stop(painter, color):
    path = QPainterPath()
    path.addRoundedRect(QRectF(7.0, 7.0, 10.0, 10.0), 2.0, 2.0)
    _fill(painter, color, path)


def _install(painter, color):
    box = QPainterPath()
    box.addRoundedRect(QRectF(4.5, 4.5, 15.0, 15.0), 3.0, 3.0)
    _stroke(painter, color, box)
    stem = QPainterPath()
    stem.addRoundedRect(QRectF(10.8, 6.5, 2.4, 6.5), 1.2, 1.2)
    _fill(painter, color, stem)
    head = QPainterPath()
    head.moveTo(7.8, 11.5)
    head.lineTo(16.2, 11.5)
    head.lineTo(12.0, 16.3)
    head.closeSubpath()
    _fill(painter, color, head)


def _gear(painter, color):
    for index in range(8):
        painter.save()
        painter.translate(12.0, 12.0)
        painter.rotate(index * 45.0)
        painter.translate(0.0, -8.0)
        tooth = QPainterPath()
        tooth.addRoundedRect(QRectF(-2.1, -2.9, 4.2, 5.8), 1.2, 1.2)
        _fill(painter, color, tooth)
        painter.restore()
    ring = QPainterPath()
    ring.addEllipse(QRectF(6.2, 6.2, 11.6, 11.6))
    _fill(painter, color, ring)
    destination_out = getattr(QPainter, "CompositionMode_DestinationOut", None)
    if destination_out is None:  # PySide6 renamed the modes between versions
        destination_out = QPainter.CompositionMode.DestinationOut
    painter.setCompositionMode(destination_out)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(0, 0, 0))
    painter.drawEllipse(QRectF(8.8, 8.8, 6.4, 6.4))
    source_over = getattr(QPainter, "CompositionMode_SourceOver", None)
    if source_over is None:
        source_over = QPainter.CompositionMode.SourceOver
    painter.setCompositionMode(source_over)


def _exclamation(painter, color):
    bar = QPainterPath()
    bar.addRoundedRect(QRectF(10.6, 5.5, 2.8, 10.0), 1.4, 1.4)
    _fill(painter, color, bar)
    dot = QPainterPath()
    dot.addEllipse(QRectF(10.5, 17.0, 3.0, 3.0))
    _fill(painter, color, dot)


def _fullscreen(painter, color):
    path = QPainterPath()
    for points in (((5.5, 10.5), (5.5, 5.5), (10.5, 5.5)),
                   ((13.5, 5.5), (18.5, 5.5), (18.5, 10.5)),
                   ((5.5, 13.5), (5.5, 18.5), (10.5, 18.5)),
                   ((13.5, 18.5), (18.5, 18.5), (18.5, 13.5))):
        path.moveTo(QPointF(*points[0]))
        for point in points[1:]:
            path.lineTo(QPointF(*point))
    _stroke(painter, color, path)


def _computer(painter, color):
    screen = QPainterPath()
    screen.addRoundedRect(QRectF(4.0, 5.0, 16.0, 11.0), 2.0, 2.0)
    stand = QPainterPath()
    stand.moveTo(QPointF(12.0, 16.0))
    stand.lineTo(QPointF(12.0, 19.0))
    base = QPainterPath()
    base.moveTo(QPointF(8.0, 19.0))
    base.lineTo(QPointF(16.0, 19.0))
    for path in (screen, stand, base):
        _stroke(painter, color, path)


GLYPHS = {
    "play": _play,
    "stop": _stop,
    "install": _install,
    "gear": _gear,
    "exclamation": _exclamation,
    "fullscreen": _fullscreen,
    "computer": _computer,
}


def icon(name, color, grid=GRID, scale=SCALE):
    """Return the toolbar QIcon for a glyph, tinted with color.

    The pixmap is drawn at grid*scale device pixels without a device pixel
    ratio: QIcon rescales plain pixmaps reliably, while icons built from
    device-pixel-ratio pixmaps render only a corner of the glyph on some
    Qt/PySide combinations.
    """
    try:
        glyph = GLYPHS[name]
    except KeyError:
        raise ValueError(f"Unknown toolbar icon: {name}") from None
    grid, scale = int(grid), int(scale)
    pixmap = QPixmap(grid * scale, grid * scale)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.scale(float(scale), float(scale))
        glyph(painter, QColor(color))
    finally:
        painter.end()
    result = QIcon()
    result.addPixmap(pixmap)
    return result
