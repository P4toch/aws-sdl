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

from rtech.listener.listener import Listener
from rtech.listener.amqp.rabbitmq import RabbitMQListener


class ListenerFactory(Listener):
    # _____________________________________________________________________
    # new_job
    def new_listener(self, listener_type, listener_name, listener_config):

        li = None

        # _____________________________________________________________________
        # listener_type = advanced mewsage queuing protocol
        if listener_type == 'amqp':

            if listener_name == 'custom':
                if listener_config['type'] == 'rabbitmq':
                    li = RabbitMQListener(self.config, 'custom', listener_config)

            elif listener_name == 'rabbitmq':
                li = RabbitMQListener(self.config, listener_name, None)


        # _____________________________________________________________________
        # listener_type = something_else like local folder for exemple
        #   ...

        if li is None:
            logging.getLogger(__name__).error('Unknown connector_name = ' + listener_name)

        return li

