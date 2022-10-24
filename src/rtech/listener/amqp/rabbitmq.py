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
import pika
import traceback

from rtech.listener.listener import Listener


class RabbitMQListener(Listener):
    # _____________________________________________________________________
    # __init__
    def __init__(self, config, listener_name, listener_config):
        super(RabbitMQListener, self).__init__(config)

        self.logger.info('Initializing RabbitMQListener ...')

        self.listener_name   = listener_name
        self.listener_config = listener_config

        if self.listener_name == 'custom':
            self.broker   = self.listener_config['broker']
            self.queue    = self.listener_config['queue']
            self.login    = self.listener_config['login']
            self.password = self.listener_config['password']
            self.port     = self.listener_config['port']
        else:
            self.broker   = self.config.listeners['amqp'][self.listener_name]['broker']
            self.queue    = self.config.listeners['amqp'][self.listener_name]['queue']
            self.login    = self.config.listeners['amqp'][self.listener_name]['login']
            self.password = self.config.listeners['amqp'][self.listener_name]['password']
            self.port     = self.config.listeners['amqp'][self.listener_name]['port']

        self.conn    = None
        self.channel = None


    # _____________________________________________________________________
    # listen
    def listen(self):
        if not self.channel:
            self.logger.info('Starting RabbitMQ Listener:')
            self.logger.info('  Broker : ' + self.broker)
            self.logger.info('  Queue  : ' + self.queue)

        try:
            self.connect()
            self.channel.basic_consume(self.callback, self.queue, no_ack=False)
            self.channel.start_consuming()
        except Exception as e:
            self.logger.error(e)
            self.logger.error(traceback.format_exc())

        return self

    # _____________________________________________________________________
    # connect
    def connect(self):
        try:
            credentials = pika.PlainCredentials(self.login, self.password)
            conn_params = pika.ConnectionParameters(
                host=self.broker,
                credentials=credentials)
            self.conn    = pika.BlockingConnection(conn_params)
            self.channel = self.conn.channel()
        except Exception as e:
            self.logger.error("Unable to connect to RabbitMQ")
            self.logger.error(e)
            self.logger.error(traceback.format_exc())

    # _____________________________________________________________________
    # callback
    def callback(self, channel, method, properties, payload):
        self.logger.info("")
        self.logger.info("#################################################")
        self.logger.info( "New work order message received.")
        self.logger.info("")

        self.logger.info("%s", payload)

        self.sendack(channel, method.delivery_tag)

    # _____________________________________________________________________
    # sendack
    def sendack(self, channel, delivery_tag):
        self.logger.debug("Start sending ack id :%d", delivery_tag)
        channel.basic_ack(delivery_tag)
        self.logger.debug("End sending ack")
