# Copyright (C) 2019 by Jacob Alexander
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

#
# Imports
#
import aiofiles
import argparse
import asyncio
import darkdetect
import logging
import logging.handlers
import os
import sys
import tempfile
import time

import hidiocore.client

from fbs_runtime.application_context import ApplicationContext
from PySide2.QtCore import (
    QFile,
    QObject,
    QThread,
    Signal,
    Slot,
)
from PySide2.QtGui import (
    QIcon,
    QPixmap,
)
from PySide2.QtUiTools import (
    QUiLoader,
)
from PySide2.QtWidgets import (
    qApp,
    QAction,
    QApplication,
    QMenu,
    QSystemTrayIcon,
)


#
# Variables
#
hidio_log_file = os.path.join(tempfile.gettempdir(), "hidio.log")
hidio_log_level = logging.INFO

# Increase verbosity
if 'VERBOSE' in os.environ:
    hidio_log_level = logging.DEBUG


#
# Logging
#

logging.basicConfig(
    format='%(asctime)s %(levelname)-8s %(message)s',
    level=hidio_log_level,
    handlers=[
        logging.StreamHandler(),
        logging.handlers.RotatingFileHandler(
            hidio_log_file,
            maxBytes=1000000,
            backupCount=2
        ),
    ],
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger()

loglevel_lookup = {
    50: 'CRITICAL',
    40: 'ERROR',
    30: 'WARNING',
    20: 'INFO',
    10: 'DEBUG',
    0: 'NOTSET',
}
logger.info(
    "Opening logfile (%s) -> %s",
    loglevel_lookup[hidio_log_level],
    hidio_log_file
)
logger.info('---------------------------- hid-io starting! ----------------------------')


#
# Classes
#
class HIDIOLogHandler(logging.Handler):
    '''
    Internal log handler used for the log viewer updates
    '''
    def __init__(self, parent):
        logging.Handler.__init__(self)
        # Use configured log format
        self.setFormatter(logger.handlers[0].formatter)
        self.parent = parent


    def emit(self, record):
        '''
        Append message to viewer
        '''
        msg = self.format(record)
        self.parent.logmsg.emit(msg)


class HIDIOClient(hidiocore.client.HIDIOClient):
    '''
    Callback class for HID-IO Core client library
    '''
    def __init__(self, parent):
        hidiocore.client.HIDIOClient.__init__(self, 'HID-IO Client')
        self.parent = parent


    def nodes_as_dicts(self, nodes):
        '''
        Returns the list of nodes as a list of dictionaries

        Does not include interfaces as these do not transmit over
        Signals easily
        '''
        node_dict = []
        for node in nodes:
            node_dict.append({
                'type': node.type._as_str(),
                'name': node.name,
                'serial': node.serial,
                'id': node.id,
            })

        return node_dict


    async def on_connect(self, cap, cap_auth):
        '''
        Called whenever a connection is established to HID-IO Core

        @param cap: Reference to capnp HIDIOServer interface
        @param cap_auth: Reference to capnp HIDIO interface
                         (May be set to None, if not authenticated)
        '''
        logger.info("Connected!")

        # Build list of nodes (that can be sent via Signals and Slots)
        node_dicts = {}
        if cap_auth:
            node_dicts = self.nodes_as_dicts(
                (await cap_auth.nodes().a_wait()).nodes
            )

        # Send connection information to UI
        self.parent.connected.emit(
            self.name(),
            self.version().version,
            node_dicts,
        )


    async def on_disconnect(self):
        '''
        Called whenever the connection to HID-IO Core is broken
        '''
        logger.info("Disconnected!")
        self.parent.disconnected.emit()


    def on_nodesupdate(self, nodes):
        '''
        Called whenever the list of available nodes changes
        '''
        logger.info("Nodes Update")
        node_dicts = self.nodes_as_dicts(nodes)

        # Send nodes information to UI
        self.parent.nodesupdate.emit(
            node_dicts,
        )


class HIDIOWorker(QObject):
    finished = Signal(int)
    initiated = Signal(str)
    connected = Signal(str, str, list)
    nodesupdate = Signal(list)
    disconnected = Signal()

    def __init__(self, parent=None):
        super(self.__class__, self).__init__(parent)


    def __del__(self):
        '''
        Thread clean on object removal
        '''
        self.stop()


    async def async_main(self, parent):
        '''
        Main async entry point
        '''
        self.client = HIDIOClient(parent)
        self.initiated.emit(self.client.serial)

        # Connect to the server using a background task
        # This will automatically reconnect
        self.tasks = [asyncio.gather(*[self.client.connect(auth=hidiocore.client.HIDIOClient.AUTH_BASIC)], return_exceptions=True)]

        while self.client.retry_connection_status():
            await asyncio.sleep(0.01)


    @Slot()
    def start(self):
        '''
        Start asyncio HIDIO client loop
        '''
        self.loop = asyncio.new_event_loop()
        try:
            exit_code = self.loop.run_until_complete(self.async_main(self))
        except Exception as err:
            logger.error("Async exceptionCtrl+C detected, exiting...")
            logger.error(err)
            exit_code = 1
        self.finished.emit(exit_code)


    @Slot()
    def stop(self):
        '''
        Manually stop thread
        '''
        asyncio.ensure_future(self.client.disconnect(), loop=self.loop)


class SysTrayContext(ApplicationContext, QObject):
    logmsg = Signal(str)

    def __init__(self):
        ApplicationContext.__init__(self)
        QObject.__init__(self)

        # Setup HID-IO Core thread
        self.hidio_worker = HIDIOWorker()
        self.hidio_worker_thread = QThread()
        self.hidio_worker.moveToThread(self.hidio_worker_thread)
        self.hidio_worker_thread.started.connect(self.hidio_worker.start)

        # Signal -> Slot connections
        self.hidio_worker.connected.connect(self.connection)
        self.hidio_worker.nodesupdate.connect(self.nodesupdate)
        self.hidio_worker.disconnected.connect(self.disconnection)
        self.hidio_worker.finished.connect(self.hidio_worker_thread.quit)
        self.hidio_worker.finished.connect(self.quit)
        self.hidio_worker.initiated.connect(self.initiation)

        # Variables
        self.core_name = None
        self.core_version = None
        self.client_serial = ""
        self.nodes = {}

        # Maintain object
        self.exit_app = False

        # Initialize systray menus
        icon_resource = self.get_resource("icons/White_IO-48.png")
        if darkdetect.isLight():
            # Show black icon when not in macOS dark mode
            icon_resource = self.get_resource("icons/Black_IO-48.png")
        myicon = QPixmap(icon_resource)
        self.tray = QSystemTrayIcon(QIcon(myicon), self)

        # Setup systray menu
        self.tray_menu = QMenu()
        self.tray.setContextMenu(self.tray_menu)
        self.core_version_action = QAction("Not Connected", self)
        self.core_version_action.setEnabled(False)
        self.update_menu()

        # Setup utilities menu
        ui_file = QFile(self.get_resource("hidio_utilities.ui"))
        ui_file.open(QFile.ReadOnly)
        loader = QUiLoader()
        self.utilities_window = loader.load(ui_file)
        ui_file.close()

        # Setup cmd prompt window
        # This window has to be instantiated per possible keyboard on demand
        self.cmd_prompt_ui_file = QFile(self.get_resource("hidio_utilities.ui"))
        self.cmd_prompt_ui_file.open(QFile.ReadOnly)


    def __del__(self):
        # Close cmd prompt ui file
        self.cmd_prompt_ui_file.close()

        # Cleanup
        ApplicationContext.__del__(self)
        QObject.__del__(self)


    def update_menu(self):
        '''
        Refreshes systray menu
        This is needed whenever new supported devices are added
        '''
        # Clear menu
        self.tray.contextMenu().clear()

        # Exit action
        quit_action = QAction("Exit", self)
        quit_action.triggered.connect(self.stop_hidio)

        # HID-IO Version
        version = self.build_settings['version']
        version_action = QAction(
            "hid-io v{} ({})".format(
                version,
                self.client_serial,
            ),
            self
        )
        version_action.setEnabled(False)

        # HID-IO Core Version
        if self.core_version and self.core_name:
            self.core_version_action.setText("{} v{}".format(
                self.core_name,
                self.core_version,
            ))
        else:
            self.core_version_action.setText("Not Connected")

        # Tools menu
        self.tools_menu = QMenu("Tools")
        diagnostics_action = QAction("Diagnostics", self)
        diagnostics_action.triggered.connect(self.diagnostics_window_show)
        log_action = QAction("HID-IO Log", self)
        log_action.triggered.connect(self.log_window_show)
        core_log_action = QAction("HID-IO Core Log", self)
        core_log_action.triggered.connect(self.core_log_window_show)
        support_bundle_action = QAction("Support Bundle", self)

        self.tools_menu.addAction(diagnostics_action)
        self.tools_menu.addAction(log_action)
        self.tools_menu.addAction(core_log_action)
        self.tools_menu.addAction(support_bundle_action)

        # Others menu
        self.others_menu = QMenu("Other Devices")
        # TODO - List of unsupported devices

        # Api usage menu
        self.api_usage_menu = QMenu("API Usage")
        # TODO - List of API
        # Build list of devices and apis
        for node in self.nodes:
            if node['type'] == 'hidioApi':
                self.api_usage_menu.addAction(
                    "[{id}] {name} ({serial})".format(
                        **node
                    )
                ).setEnabled(False)
            if node['type'] == 'hidioDaemon':
                self.others_menu.addAction(
                    "[{id}] {name} ({serial})".format(
                        **node
                    )
                ).setEnabled(False)
            if node['type'] == 'usbKeyboard':
                pass


        # Setup menu layout
        self.tray_menu.addAction(version_action)
        self.tray_menu.addAction(self.core_version_action)
        self.tray_menu.addSection("")
        self.tray_menu.addMenu(self.others_menu)
        self.tray_menu.addMenu(self.api_usage_menu)
        self.tray_menu.addSection("")
        self.tray_menu.addMenu(self.tools_menu)
        self.tray_menu.addAction(quit_action)


    def run(self):
        '''
        Show systray icon
        '''
        self.hidio_worker_thread.start()
        self.tray.show()
        logger.debug("Ready!")


    @Slot()
    def stop_hidio(self):
        '''
        Stops HIDIO Client
        '''
        logger.debug("stop_hidio initiated")
        self.hidio_worker.stop()
        logger.debug("stop_hidio finished")


    @Slot()
    def quit(self):
        '''
        Exit GUI
        stop_hidio must be called first
        Use the finished signal from the thread to call this slot
        '''
        logger.debug("quit initiated")
        self.exit_app = True


    @Slot()
    def initiation(self, client_serial):
        '''
        Called after the thread has started, but before connecting to HID-IO Core
        '''
        # Set the client serial number (generated by hidiocore.client)
        self.client_serial = client_serial

        # Update menu
        self.update_menu()


    @Slot()
    def connection(self, name, version, nodes):
        '''
        Called when HID-IO Core connection is made
        '''
        # Set daemon version and name
        self.core_version = version
        self.core_name = name
        self.nodes = nodes

        # Update menu
        self.update_menu()


    @Slot()
    def nodesupdate(self, nodes):
        '''
        Called whenever the nodes list changes
        '''
        self.nodes = nodes

        # Update menu
        self.update_menu()


    @Slot()
    def disconnection(self):
        '''
        Called when HID-IO Core is disconnected
        '''
        # Unset daemon version and name
        self.core_version = None
        self.core_name = None

        # Clear nodes list
        self.nodes = {}

        # Update menu
        self.update_menu()


    @Slot()
    def diagnostics_window_show(self):
        '''
        Show diagnostics dialog
        '''
        self.utilities_window.show()


    @Slot()
    def log_window_show(self):
        '''
        Show log window for the HID-IO Client
        '''
        # Setup log window
        ui_file = QFile(self.get_resource("log_viewer.ui"))
        ui_file.open(QFile.ReadOnly)
        loader = QUiLoader()
        self.log_window = loader.load(ui_file)
        ui_file.close()

        # Setup log handler
        self.log_window.log_handler = HIDIOLogHandler(self)
        self.logmsg.connect(self.log_window.logViewer.append)

        # Write past logs to viewers
        with open(hidio_log_file, 'r') as log:
            self.log_window.logViewer.setPlainText(log.read()[:-1])

        # Add log handler
        logger.addHandler(self.log_window.log_handler)

        self.log_window.show()

        # Scroll to bottom
        self.log_window.logViewer.verticalScrollBar().setValue(
            self.log_window.logViewer.verticalScrollBar().maximum()
        )


    @Slot()
    def core_log_window_show(self):
        '''
        Show log window for HID-IO Core
        '''
        ui_file = QFile(self.get_resource("core_log_viewer.ui"))
        ui_file.open(QFile.ReadOnly)
        loader = QUiLoader()
        self.core_log_window = loader.load(ui_file)
        ui_file.close()

        # TODO Attach to log

        self.core_log_window.show()


#
# Initialization
#
def main():
    '''
    Main entry point
    '''
    parser = argparse.ArgumentParser(
        description='HID-IO Client Application for HID-IO Core'
    )
    args = parser.parse_args()

    # Setup PySide2
    # Instead of using quamash (which has issues) or asyncqt
    # setup PySide2 and use a separate thread for asyncio
    systray = SysTrayContext()
    systray.run()
    qapp = qApp
    if isinstance(qapp, type(None)):
        # macOS fbs/PySide2 doesn't start QApplication automatically
        qapp = QApplication([])

    try:
        exit_code = 0
        while not systray.exit_app:
            time.sleep(0.01)
            qapp.processEvents(maxtime=10)
    except KeyboardInterrupt:
        logger.warning("Ctrl+C detected, exiting...")
        exit_code = 1
    except RuntimeError:
        logger.warning("Application exited")
        exit_code = 0
    return exit_code


if __name__ == '__main__':
    exit_code = main()
    logger.info("Exiting with returncode: %s", exit_code)
    logger.info('---------------------------- hid-io exiting! ----------------------------')
    sys.exit(exit_code)
