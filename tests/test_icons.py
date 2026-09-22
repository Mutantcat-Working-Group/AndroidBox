import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import importlib.util
import unittest

QT_AVAILABLE = importlib.util.find_spec("PySide6") is not None

if QT_AVAILABLE:
    from PySide6.QtGui import QColor, QImage
    from androidbox.icons import GLYPHS, icon


def lit_pixels(pixmap):
    """Return the alpha>0 pixel count of a pixmap."""
    if pixmap.isNull():
        return 0
    image = pixmap.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    count = 0
    for y in range(image.height()):
        for x in range(image.width()):
            if QColor.fromRgba(image.pixel(x, y)).alpha() > 8:
                count += 1
    return count


@unittest.skipUnless(QT_AVAILABLE, "Install PySide6 to test the toolbar icons")
class IconTests(unittest.TestCase):
    def test_every_glyph_renders_visible_pixels(self):
        for name in GLYPHS:
            with self.subTest(glyph=name):
                pixmap = icon(name, "#000000").pixmap(24, 24)
                self.assertFalse(pixmap.isNull())
                self.assertGreater(lit_pixels(pixmap), 20)

    def test_glyphs_are_distinct(self):
        pixmaps = {name: icon(name, "#000000").pixmap(24, 24).toImage()
                   for name in GLYPHS}
        for name, image in pixmaps.items():
            for other, other_image in pixmaps.items():
                if name < other:
                    self.assertNotEqual(image, other_image, f"{name} matches {other}")

    def test_icon_takes_the_requested_color(self):
        pixmap = icon("play", "#ff0000").pixmap(24, 24)
        image = pixmap.toImage().convertToFormat(QImage.Format.Format_ARGB32)
        red = max(QColor.fromRgba(image.pixel(x, y)).red()
                  for y in range(image.height()) for x in range(image.width()))
        self.assertEqual(red, 255)

    def test_unknown_glyph_is_rejected(self):
        with self.assertRaises(ValueError):
            icon("does-not-exist", "#000000")

    def test_icon_scales_without_losing_the_glyph(self):
        # The toolbar renders at 20px and HiDPI screens ask for more; neither
        # request may fall back to a blank or cropped pixmap.
        for size in (16, 20, 24, 48):
            with self.subTest(size=size):
                pixmap = icon("gear", "#000000").pixmap(size, size)
                self.assertEqual(pixmap.width(), size)
                self.assertGreater(lit_pixels(pixmap), 20)
