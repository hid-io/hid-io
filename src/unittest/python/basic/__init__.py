# Copyright (C) 2019 by Jacob Alexander
#
# This file is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This file is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this file.  If not, see <http://www.gnu.org/licenses/>.

#
# Imports
#

import asyncio
import os
import unittest

# Increase verbosity for import
os.environ['VERBOSE'] = 'true'

import hidiocore.client # noqa
import main # noqa


#
# Tests
#

class HIDIOClientTest(unittest.TestCase):
    '''
    Test HIDIOClient class, no UI required
    '''

    def setUp(self):
        self.client = main.HIDIOClient()
        self.loop = asyncio.new_event_loop()

    def tearDown(self):
        self.client = None
        self.tasks = None

    async def async_main(self, auth):
        '''
        Activity monitor
        '''
        # Connect to the server using a background task
        # This will automatically reconnect
        self.tasks = [
            asyncio.gather(
                *[self.client.connect(auth=auth)],
                return_exceptions=True
            )
        ]

        # TODO handle testing here
        while self.client.retry_connection_status():

            await asyncio.sleep(0.01)
            #return
            #await asyncio.sleep(0.01)

    def testHIDIOClientAuthNone(self):
        '''
        Attempts to start the HIDIOClient and verifies it is running
        '''
        self.loop.run_until_complete(self.async_main(hidiocore.client.HIDIOClient.AUTH_NONE))

    def testHIDIOClientAuthBasic(self):
        '''
        Attempts to start the HIDIOClient and verifies it is running
        Use basic auth
        '''
        self.loop.run_until_complete(self.async_main(hidiocore.client.HIDIOClient.AUTH_BASIC))

    def testHIDIOClientAuthAdmin(self):
        '''
        Attempts to start the HIDIOClient and verifies it is running
        Use basic auth
        '''
        self.loop.run_until_complete(self.async_main(hidiocore.client.HIDIOClient.AUTH_ADMIN))


class HIDIOWorkerTest(unittest.TestCase):
    '''
    Test HIDIOWorker class, no UI required
    '''

    def setUp(self):
        #self.hidio_worker = main.HIDIOWorker()
        pass

    def tearDown(self):
        self.hidio_worker = None

    def testHIDIOWorker(self):
        '''
        Attempts to start the HIDIOWorker thread and verifies it is running
        '''
        # TODO


#
# Entry Point
#

if __name__ == '__main__':
    unittest.main()
