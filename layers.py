"""Create, save and load vector layers (QGIS side)."""
import os
import time

from qgis.core import (
    QgsFeature, QgsProject, QgsVectorFileWriter, QgsVectorLayer,
)

from .compat import make_field


def unique_names(existing, wanted, shapefile):
    """Return field names that do not clash with `existing` (case-insensitive)."""
    used = {n.lower() for n in existing}
    out = []
    for base in wanted:
        name, n = base, 1
        while name.lower() in used:
            suffix = "_%d" % n
            n += 1
            name = (base[:10 - len(suffix)] if shapefile else base) + suffix
        used.add(name.lower())
        out.append(name)
    return out


def new_memory_layer(geom, crs_authid, name, specs):
    """specs: list of (field_name, kind)."""
    layer = QgsVectorLayer("%s?crs=%s" % (geom, crs_authid), name, "memory")
    layer.dataProvider().addAttributes([make_field(n, k) for n, k in specs])
    layer.updateFields()
    return layer


def add_features(layer, rows):
    """rows: iterable of (QgsGeometry, list_of_attributes)."""
    feats = []
    for geom, attrs in rows:
        f = QgsFeature(layer.fields())
        f.setGeometry(geom)
        f.setAttributes(attrs)
        feats.append(f)
    layer.dataProvider().addFeatures(feats)
    layer.updateExtents()
    return len(feats)


def run_stamp():
    return time.strftime("%Y%m%d_%H%M%S")


def save_layer(layer, folder, base, fmt, stamp, file_base="magvar"):
    """Write `layer`. fmt: 'gpkg' (one file per run, one layer per call) or
    'shp'. Returns the URI to load it back."""
    opts = QgsVectorFileWriter.SaveVectorOptions()
    opts.fileEncoding = "UTF-8"
    if fmt == "gpkg":
        path = os.path.join(folder, "%s_%s.gpkg" % (file_base, stamp))
        opts.driverName = "GPKG"
        opts.layerName = base
        exists = os.path.exists(path)
        opts.actionOnExistingFile = (
            QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteLayer if exists
            else QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteFile)
        uri = "%s|layername=%s" % (path, base)
    else:
        path = os.path.join(folder, "%s_%s.shp" % (base, stamp))
        opts.driverName = "ESRI Shapefile"
        uri = path
    res = QgsVectorFileWriter.writeAsVectorFormatV3(
        layer, path, QgsProject.instance().transformContext(), opts)
    if res[0] != QgsVectorFileWriter.WriterError.NoError:
        raise RuntimeError(res[1])
    return uri


def load_layer(uri, name, add=True):
    vl = QgsVectorLayer(uri, name, "ogr")
    if not vl.isValid():
        raise RuntimeError("Could not load the saved layer: %s" % uri)
    if add:
        QgsProject.instance().addMapLayer(vl)
    return vl
