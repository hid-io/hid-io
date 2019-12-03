#!/usr/bin/env python3

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

from fbs import path
from fbs.cmdline import command

import logging
import os
import shutil

import fbs.builtin_commands
import fbs.cmdline
import fbs_runtime.platform


#
# Logging
#

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


#
# Functions
#

def dircopy(srcdir):
    '''
    Copies srcdir into freeze_dir of the project
    '''
    # Lookup freeze directory
    freezedir = path('${freeze_dir}')
    # Handle macOS builds
    if fbs_runtime.platform.is_mac():
        freezedir = os.path.join(freezedir, 'Contents', 'MacOS')

    dstdir = os.path.join(freezedir, os.path.basename(srcdir))
    if os.path.exists(dstdir):
        shutil.rmtree(dstdir)
    logger.info("Copying %s -> %s", srcdir, dstdir)
    shutil.copytree(srcdir, dstdir)


@command
def freeze(debug=False):
    fbs.builtin_commands.freeze(debug)

    # Import the modules that fbs has a difficulty in finding
    # Locate the source directories
    # And copy the necessary files

    # HID-IO Core must be copied as the .capnp files are compiled at run-time into Python code
    import hidiocore
    dircopy(os.path.dirname(hidiocore.__file__))


#
# Entry Point
#

if __name__ == '__main__':
    project_dir = os.path.dirname(__file__)
    fbs.cmdline.main(project_dir)
