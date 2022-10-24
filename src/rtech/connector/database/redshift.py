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

import sys
import psycopg2
import traceback

from rtech.connector.connector import Connector


class RedShiftConnector(Connector):
    # _____________________________________________________________________
    # __init__
    def __init__(self, config, connector_name, connector_config):
        super(RedShiftConnector, self).__init__(config)

        self.logger.info('Initializing RedShiftConnector ...')

        self.connector_config = connector_config

        if connector_name == 'custom':
            self.name     = 'custom'
            self.type     = connector_config['type']
            self.server   = connector_config['server']
            self.login    = connector_config['login']
            self.password = connector_config['password']
            self.database = connector_config['database']
            self.port     = connector_config['port']
        else:
            self.name     = connector_name
            self.type     = self.config.databases[self.name]['type']
            self.server   = self.config.databases[self.name]['server']
            self.login    = self.config.databases[self.name]['login']
            self.password = self.config.databases[self.name]['password']
            self.database = self.config.databases[self.name]['database']
            self.port     = self.config.databases[self.name]['port']

        self.conn = None
        self.cur = None

    # _____________________________________________________________________
    # __enter__
    def __enter__(self):
        self.connect()
        return self

    # _____________________________________________________________________
    # __exit__
    def __exit__ (self, exc_type, exc_value, traceback):
        self.close()

    # _____________________________________________________________________
    # connect
    def connect(self):
        if not self.conn or self.conn.closed:
            self.logger.info('Opening RedShift Session: ' + self.name)
            try:
                self.conn = psycopg2.connect(
                    dbname   = self.database,
                    user     = self.login,
                    password = self.password,
                    host     = self.server,
                    port     = self.port)
                self.cur = self.conn.cursor()
            except Exception as e:
                if self.name == 'custom':
                    self.logger.exception('{}: Cannot connect to redshift database: {}'.format(self.config.job.upper(), self.server))
                else:
                    self.logger.exception('{}: Cannot connect to redshift database: {}'.format(self.config.job.upper(), self.name))
                    self.logger.error(e)
                self.logger.error(traceback.format_exc())

                # TODO should we hardly stop the program like this
                sys.exit(1)
        return self

    # _____________________________________________________________________
    # close
    def close(self):
        if self.conn:
            self.logger.info('Closing RedShift Session: ' + self.name)
            self.conn.close()
        return True