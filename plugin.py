import os

from qgis.PyQt import sip
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QApplication

from .dialog import MagVarDialog

MENU = "&Isogonic Lines && MagVar"


class MagVarPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.dialog = None

    def initGui(self):
        icon = QIcon(os.path.join(os.path.dirname(__file__), "icon.png"))
        self.action = QAction(icon, "Isogonic Lines && MagVar",
                              self.iface.mainWindow())
        self.action.triggered.connect(self.run)
        self.iface.addPluginToMenu(MENU, self.action)
        self.iface.addToolBarIcon(self.action)

    def unload(self):
        self.iface.removePluginMenu(MENU, self.action)
        self.iface.removeToolBarIcon(self.action)
        if self.dialog:
            self.dialog.reset_state()
            if self.dialog.card is not None:
                self.dialog.card.deleteLater()
                self.dialog.card = None
            if self.dialog._esc is not None:
                self.dialog._esc.setEnabled(False)
                self.dialog._esc.deleteLater()
                self.dialog._esc = None
            self.dialog.close()
            self.dialog.deleteLater()
            self.dialog = None

    def run(self):
        if self.dialog is not None and sip.isdeleted(self.dialog):
            self.dialog = None
        if self.dialog is None:
            # No parent: the window gets its own taskbar entry, so it can be
            # found again after it is minimised.
            self.dialog = MagVarDialog(self.iface, None)
            app = QApplication.instance()
            if app is not None:
                app.aboutToQuit.connect(self.dialog.close)
        else:
            self.dialog.refresh_extent(set_output=True)
        if self.dialog.isMinimized():
            self.dialog.showNormal()
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()
