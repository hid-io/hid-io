from fbs_runtime.application_context.PySide2 import ApplicationContext
from PySide2.QtWidgets import (
    QMainWindow,
    QSystemTrayIcon,
    QMenu,
    QApplication,
    QAction,
    QLabel,
    QMessageBox,
    qApp,
)
from PySide2.QtGui import (
    QIcon,
    QPixmap,
)
from PySide2.QtCore import (
    QObject,
)

import sys

def show_tray_message(tray, QSystemTrayIcon):
    tray.showMessage("Hooo", "Message fram tray")


class SysTrayContext(ApplicationContext, QObject):
    def __init__(self):
        ApplicationContext.__init__(self)
        QObject.__init__(self)

    def run(self):                              # 2. Implement run()
        window = QMainWindow()
        version = self.build_settings['version']
        window.setWindowTitle("hid-io-systray v" + version)
        window.resize(250, 150)
        #window.show()
        myicon = QPixmap(self.get_resource("../icons/mac/256.png"))
        self.tray = QSystemTrayIcon(QIcon(myicon), self)

        quit_action = QAction("Exit", self)
        version_action = QAction("hid-io-systray v" + version, self)
        version_action.setEnabled(False)
        quit_action.triggered.connect(qApp.quit)
        tray_menu = QMenu()
        tray_menu.addAction(version_action)
        tray_menu.addSection("")
        tray_menu.addAction(quit_action)
        sub_menu = QMenu("THing")
        tray_menu.addMenu(sub_menu)
        self.tray.setContextMenu(tray_menu)
        self.tray.show()
        return self.app.exec_()                 # 3. End run() with this line

if __name__ == '__main__':
    appctxt = SysTrayContext()
    exit_code = appctxt.run()
    sys.exit(exit_code)
