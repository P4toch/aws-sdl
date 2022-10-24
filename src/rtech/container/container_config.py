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


class ConfigContainer:
    def __init__(self, environment, job, step, json_config):
        self.environment = environment
        self.job         = job
        self.step        = step
        self.job_type    = job + '_' + step
        self.json_config = json_config

        self.databases   = json_config['connectors']['databases']
        self.file_shares = json_config['connectors']['file_shares']
        self.listeners   = json_config['listeners']
