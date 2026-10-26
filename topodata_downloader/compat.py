# -*- coding: utf-8 -*-
"""Aliases de enums que funcionam no QGIS 3.28+ (Qt5) e no QGIS 4 (Qt6)."""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QAbstractItemView, QHeaderView, QMessageBox
from qgis.core import Qgis, QgsCoordinateReferenceSystem, QgsTask, QgsWkbTypes
from qgis.gui import QgsFileWidget

try:
    from qgis.PyQt.QtGui import QAction             # Qt6
except ImportError:
    from qgis.PyQt.QtWidgets import QAction         # Qt5   # noqa: F401

WGS84 = QgsCoordinateReferenceSystem("EPSG:4326")


def _first(*candidates):
    """Primeiro atributo existente, ex.: (Qgis, 'GeometryType', 'Polygon')."""
    for owner, *path in candidates:
        obj = owner
        try:
            for name in path:
                obj = getattr(obj, name)
            return obj
        except AttributeError:
            continue
    raise AttributeError(str(candidates[-1]))


GEOM_POLYGON = _first((Qgis, "GeometryType", "Polygon"), (QgsWkbTypes, "PolygonGeometry"))
MSG_INFO = _first((Qgis, "MessageLevel", "Info"), (Qgis, "Info"))
MSG_WARNING = _first((Qgis, "MessageLevel", "Warning"), (Qgis, "Warning"))
MSG_CRITICAL = _first((Qgis, "MessageLevel", "Critical"), (Qgis, "Critical"))
TASK_CAN_CANCEL = _first((QgsTask, "Flag", "CanCancel"), (QgsTask, "CanCancel"))
DIRECTORY_MODE = _first((QgsFileWidget, "StorageMode", "GetDirectory"),
                        (QgsFileWidget, "GetDirectory"))

LEFT = _first((Qt, "MouseButton", "LeftButton"), (Qt, "LeftButton"))
KEY_ESCAPE = _first((Qt, "Key", "Key_Escape"), (Qt, "Key_Escape"))
CROSS_CURSOR = _first((Qt, "CursorShape", "CrossCursor"), (Qt, "CrossCursor"))
CHECKED = _first((Qt, "CheckState", "Checked"), (Qt, "Checked"))
UNCHECKED = _first((Qt, "CheckState", "Unchecked"), (Qt, "Unchecked"))
ITEM_ENABLED = _first((Qt, "ItemFlag", "ItemIsEnabled"), (Qt, "ItemIsEnabled"))
ITEM_CHECKABLE = _first((Qt, "ItemFlag", "ItemIsUserCheckable"), (Qt, "ItemIsUserCheckable"))
ITEM_SELECTABLE = _first((Qt, "ItemFlag", "ItemIsSelectable"), (Qt, "ItemIsSelectable"))
USER_ROLE = _first((Qt, "ItemDataRole", "UserRole"), (Qt, "UserRole"))
ALIGN_RIGHT = _first((Qt, "AlignmentFlag", "AlignRight"), (Qt, "AlignRight"))
ALIGN_VCENTER = _first((Qt, "AlignmentFlag", "AlignVCenter"), (Qt, "AlignVCenter"))
TEXT_SELECTABLE = _first((Qt, "TextInteractionFlag", "TextSelectableByMouse"),
                         (Qt, "TextSelectableByMouse"))
TEXT_KEYBOARD = _first((Qt, "TextInteractionFlag", "TextSelectableByKeyboard"),
                       (Qt, "TextSelectableByKeyboard"))
PLAIN_TEXT = _first((Qt, "TextFormat", "PlainText"), (Qt, "PlainText"))
NO_EDIT = _first((QAbstractItemView, "EditTrigger", "NoEditTriggers"),
                 (QAbstractItemView, "NoEditTriggers"))
SINGLE_SELECTION = _first((QAbstractItemView, "SelectionMode", "SingleSelection"),
                          (QAbstractItemView, "SingleSelection"))
SELECT_ROWS = _first((QAbstractItemView, "SelectionBehavior", "SelectRows"),
                     (QAbstractItemView, "SelectRows"))
STRETCH = _first((QHeaderView, "ResizeMode", "Stretch"), (QHeaderView, "Stretch"))
RESIZE_TO_CONTENTS = _first((QHeaderView, "ResizeMode", "ResizeToContents"),
                            (QHeaderView, "ResizeToContents"))
MB_YES = _first((QMessageBox, "StandardButton", "Yes"), (QMessageBox, "Yes"))
MB_NO = _first((QMessageBox, "StandardButton", "No"), (QMessageBox, "No"))
