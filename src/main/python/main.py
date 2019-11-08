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
import argparse
import asyncio
import darkdetect
import logging
import sys
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
    QMenu,
    QSystemTrayIcon,
)


#
# Logging
#
#logging.basicConfig(level=logging.INFO)
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


#
# Classes
#
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


class HIDIOWorker(QObject):
    finished = Signal(int)
    initiated = Signal(str)
    connected = Signal(str, str, list)
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
        self.core_version_action = QAction("", self)
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
            self.core_version_string = "Not Connected"

        # Tools menu
        self.tools_menu = QMenu("Tools")
        # TODO - Log window
        # TODO - Support bundle
        # TODO - Connection watcher

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
        print(nodes)

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

        # Update menu
        self.update_menu()


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

    try:
        exit_code = 0
        while not systray.exit_app:
            time.sleep(0.01)
            qApp.processEvents(maxtime=10)
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
    sys.exit(exit_code)
