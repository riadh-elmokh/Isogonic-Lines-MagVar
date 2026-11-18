"""Default style and labels for the isogonic line layer."""
from qgis.core import (
    QgsCategorizedSymbolRenderer, QgsLineSymbol, QgsPalLayerSettings,
    QgsRendererCategory, QgsVectorLayerSimpleLabeling,
)


def style_isogonic(layer):
    normal = QgsLineSymbol.createSimple({"color": "#8e44ad", "width": "0.4"})
    zero = QgsLineSymbol.createSimple(
        {"color": "#c0392b", "width": "0.7", "line_style": "dash"})
    renderer = QgsCategorizedSymbolRenderer("is_zero", [
        QgsRendererCategory(0, normal, "Isogonic line"),
        QgsRendererCategory(1, zero, "Agonic line (0°)"),
    ])
    layer.setRenderer(renderer)
    settings = QgsPalLayerSettings()
    settings.fieldName = "decl_label"
    settings.enabled = True
    try:
        settings.placement = QgsPalLayerSettings.Placement.Line
    except AttributeError:
        pass
    layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
    layer.setLabelsEnabled(True)
    layer.triggerRepaint()
