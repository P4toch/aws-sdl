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

import os
import sys
import json
import argparse
import logging.config

from rtech.container.container_config import ConfigContainer
from rtech.job.job_factory import JobFactory


# _____________________________________________________________________
# init_args
def init_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--environment', default='lab', required=True, choices=['lab', 'corp'])
    parser.add_argument('--job', required=True, choices=['eptica', 'expert', 'avaya', 'avaya_call_detail'])
    parser.add_argument('--step', required=True, choices=['s3', 'redshift'])
    my_args = parser.parse_args()

    return my_args


# _____________________________________________________________________
# init_config
def init_config(environment):
    current_directory = os.path.dirname(os.path.abspath(__file__))

    my_config = None

    if os.path.exists(current_directory + '/resources/config/' + environment + '/config.json'):
        with open(current_directory + '/resources/config/' + environment + '/config.json', 'rt') as f:
            my_config = json.load(f)

    # TODO Exception

    return my_config


# _____________________________________________________________________
# init_job_config
def init_job_config(environment, job):
    current_directory = os.path.dirname(os.path.abspath(__file__))

    my_job_config = None

    if os.path.exists(current_directory + '/resources/job/' + environment + '/' + job + '.json'):
        with open(current_directory + '/resources/job/' + environment + '/' + job + '.json', 'rt') as f:
            my_job_config = json.load(f)

    # TODO Exception

    return my_job_config


# _____________________________________________________________________
# init_logger
def init_logger(args, config):
    my_logger = logging.getLogger(__name__)

    # environment = args.environment
    # task = args.job + '_' + args.step
    # log_path = config['log_path']

    config_log = None
    current_directory = os.path.dirname(os.path.abspath(__file__))

    if os.path.exists(current_directory + '/resources/logger/' + args.environment + '/logger.json'):
        with open(current_directory + '/resources/logger/' + args.environment + '/logger.json', 'rt') as f:
            config_log = json.load(f)

    # TODO Exception

    # TODO Create Folder if not exists

    config_log["handlers"]["info"]["filename"] = \
        config_log["handlers"]["info"]["filename"].format(
            log_file=args.job + '_' + args.step + '_info',
            log_path=config['log_path'])

    config_log["handlers"]["debug"]["filename"] = \
        config_log["handlers"]["debug"]["filename"].format(
            log_file=args.job + '_' + args.step + '_debug',
            log_path=config['log_path'])

    # TODO Cloudwatch
    # config_log["handlers"]["cloudwatch"]["stream_name"] = \
    #     config_log["handlers"]["cloudwatch"]["stream_name"].format(
    #         stream_name=args.job + '_' + args.step)

    logging.config.dictConfig(config_log)

    return my_logger


# _____________________________________________________________________
if __name__ == "__main__":
    args       = init_args()
    config     = init_config(args.environment)
    job_config = init_job_config(args.environment, args.job)
    logger     = init_logger(args, config)

    logger.info('*********************************************************************')
    logger.info('START ' + __file__)
    logger.info('')
    logger.info(' * Parameter: environment = ' + args.environment)
    logger.info(' * Parameter: job         = ' + args.job)
    logger.info(' * Parameter: step        = ' + args.step)
    logger.info('')

    cc = ConfigContainer(args.environment, args.job, args.step, config)
    job = JobFactory(cc).new_job(cc.job_type, job_config)
    job.run()

    logger.info('')
    logger.info('FINISHED ' + __file__)
    logger.info('*********************************************************************')

    sys.exit()