def classFactory(iface):
    from .plugin import MagVarPlugin
    return MagVarPlugin(iface)
