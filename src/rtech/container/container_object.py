# *********************************************************************
# Copyright (C) Expedia, Inc. All rights reserved.
#
# Description:
#   -
#
# Result Set:
#   -
#
# Return values:
#   -
#
# Error codes:
#   -
#
# Change History:
#   Date        Author          Description
#   ----------  --------------- ------------------------------------
#   2017-09-20  reporting-tech  Created
# *********************************************************************

import logging


class ObjectContainer(object):
    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.logger.info('Initiating ObjectContainer') # TODO: This is just to visualise how many times this object is initiated per run
