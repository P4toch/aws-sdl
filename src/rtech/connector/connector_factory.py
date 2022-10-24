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

from rtech.connector.connector import Connector
from rtech.connector.database.sqlserver import SqlServerConnector
from rtech.connector.database.redshift import RedShiftConnector
from rtech.connector.file_share.samba import SambaConnector


class ConnectorFactory(Connector):
    def __init__(self, config): # TODO: This will prevent multiple initialisations of Job/ObjectContainer objects.
        self.config = config

    # _____________________________________________________________________
    # new_job
    def new_connector(self, connector_type, connector_name, connector_config):

        # TODO Check that connector_type exists into ressources/config/config.json
        # TODO Check that connector_name exists into ressources/config/config.json

        con = None

        # _____________________________________________________________________
        # connector_type = database
        if connector_type == 'databases':

            if connector_name == 'custom':
                if connector_config['type'] == 'sqlserver':
                    con = SqlServerConnector(self.config, 'custom', connector_config)
                elif connector_config['type'] == 'redshift':
                    con = RedShiftConnector(self.config, 'custom', connector_config)

            elif connector_name == 'expert':
                con = SqlServerConnector(self.config, connector_name, None)

            elif connector_name == 'avaya':
                con = SqlServerConnector(self.config, connector_name, None)

            elif connector_name == 'redshift':
                con = RedShiftConnector(self.config, connector_name, None)

        # _____________________________________________________________________
        # connector_type = something_else like salesforce for exemple
        #   ...

        elif connector_type == 'file_shares':
            if connector_name == 'custom':
                raise NotImplementedError
            elif connector_name == 'avaya_cms':
                con = SambaConnector(self.config, connector_name, None)

        if con is None:
            logging.getLogger(__name__).error('Unknown connector_name = ' + connector_name)
        else:
            # TODO add { connector_name: my_connector } to an object
            pass

        return con
