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
import time
import json
import boto3
import logging
import smart_open
import unicodecsv as csv

from rtech.job.job import Job
from rtech.connector.connector_factory import ConnectorFactory


class ExpertS3Job(Job):
    # _____________________________________________________________________
    # __init__
    def __init__(self, config, job_config):
        super(ExpertS3Job, self).__init__(config)

        self.logger.info('Initializing ExpertS3Job ...')

        self.job_config         = job_config
        self.bucket_data        = job_config['config']['bucket_data']
        self.bucket_conf        = job_config['config']['bucket_conf']
        self.prefix_conf        = job_config['config']['prefix_conf']
        self.prefix_raw         = job_config['config']['prefix_raw']
        self.prefix_stage       = job_config['config']['prefix_stage']
        self.prefix_public      = job_config['config']['prefix_public']
        self.delta_loading_file = job_config['config']['delta_loading_file']

        self.s3_client          = boto3.client('s3')
        self.s3_resource        = boto3.resource('s3')

        self.expert             = ConnectorFactory(self.config).new_connector('databases', 'expert', None)
        self.full_load          = 0

        # To have boto3 less verbose in our log files
        logging.getLogger('boto3').setLevel(logging.CRITICAL)

    # _____________________________________________________________________
    # run
    def run(self):
        self.logger.info('')

        self.expert.connect()

        if self.__check_delta_loading_file_existence(self.delta_loading_file) is False:
            self.__create_delta_loading_file()
            #TODO set flag for full load
            self.full_load = 1

        delta_loading_file = self.__load_delta_loading_file()

        new_delta_loading_file = dict()

        for gf in self.job_config['get_data']:

            sql_table      = gf['source']['location']
            column         = gf['source']['columnid']
            sql_query      = gf['source']['sql_']
            is_active      = gf['source']['is_active']
            loading_method = gf['source']['loading_method']

            last_processed_id = -1
            max_id = -1

            # Only import active data sources
            if is_active == 1:
                self.logger.info("Processing: " + sql_table)
                if self.full_load == 1:
                    timestamp = time.strftime("20170101_000000")
                else:
                    if loading_method == 'full':
                        timestamp = time.strftime("20170101_000000")

                    if loading_method == 'delta':
                        timestamp = time.strftime("%Y%m%d_%H%M%S")

                if sql_table in delta_loading_file:
                    last_processed_id = delta_loading_file[sql_table]['last_processed_id']
                else:
                    last_processed_id = -1

                if loading_method == 'delta':
                    max_id = self.__get_new_max_id(column, sql_table, last_processed_id)

                new_delta_loading_file[sql_table] = {}
                new_delta_loading_file[sql_table]['loading_method'] = loading_method
                new_delta_loading_file[sql_table]['last_processed_id'] = max_id  #TODO -1000

                self.__move_to_s3_raw(
                    sql_query,
                    last_processed_id,
                    max_id,
                    sql_table,
                    timestamp,
                    loading_method
                )

        self.__update_delta_loading_file(new_delta_loading_file)

        self.expert.close()

    # _____________________________________________________________________
    # __check_delta_loading_file_existence
    def __check_delta_loading_file_existence(self, key):
        try:
            self.logger.info('Checking delta_loading_file existence')
            response = self.s3_client.list_objects_v2(
                Bucket=self.bucket_conf,
                Prefix=self.prefix_conf,
            )
            for obj in response.get('Contents', []):
                if obj['Key'] == self.prefix_conf + key:
                    return True

        except Exception as e:
            self.logger.error('{} Unable to check delta_loading_file existence'.format(self.config.job.upper()))
            self.logger.error(e)
            sys.exit(1)

        return False

    # _____________________________________________________________________
    # __load_delta_loading_file
    def __load_delta_loading_file(self):
        self.logger.info('Loading delta_loading_file')
        try:
            return json.load(
                self.s3_client.get_object(
                    Bucket=self.bucket_conf,
                    Key=self.prefix_conf + self.delta_loading_file)
                ['Body']
            )
        except Exception as e:
            self.logger.error('{} Unable to load delta_loading_file'.format(self.config.job.upper()))
            self.logger.error(e)
            sys.exit(1)

    # _____________________________________________________________________
    # __create_delta_loading_file
    def __create_delta_loading_file(self):
        try:
            self.logger.info('Creating delta_loading_file')

            self.s3_resource.Bucket(self.bucket_conf).put_object(
                Key=self.prefix_conf + self.delta_loading_file,
                Body=self.__init_delta_loading_file())
        except Exception as e:
            self.logger.error('{} Unable to create delta_loading_file'.format(self.config.job.upper()))
            self.logger.error(e)
            sys.exit(1)

        return True

    # _____________________________________________________________________
    # __init_delta_loading_file
    def __init_delta_loading_file(self):
        try:
            self.logger.info('Initializing delta_loading_file')

            my_json_file = dict()

            for gf in self.job_config['get_data']:
                sql_table      = gf['source']['location']
                is_active      = gf['source']['is_active']
                loading_method = gf['source']['loading_method']

                if is_active == 1:
                    my_json_file[sql_table] = {}
                    my_json_file[sql_table]['loading_method'] = loading_method
                    my_json_file[sql_table]['last_processed_id'] = -1

            return json.dumps(
                my_json_file,
                sort_keys=True,
                indent=2,
                separators=(',', ': ')
            )
        except Exception as e:
            self.logger.error('{} Unable to initialize delta_loading_file'.format(self.config.job.upper()))
            self.logger.error(e)
            sys.exit(1)

    # _____________________________________________________________________
    # __get_new_max_id
    def __get_new_max_id(self, column, sql_table, last_processed_id):

        try:
            self.logger.debug('Getting new max_id for table: ' + sql_table)

            request = "select max({column}) as MaxID from dbo.{sql_table} where {column} >= {last_processed_id}"

            my_request = request.format(
                column=column,
                sql_table=sql_table,
                last_processed_id=last_processed_id)

            self.expert.cur.execute(my_request)
            for row in self.expert.cur:
                return row[0]
        except Exception as e:
            self.logger.error('{} Unable to get new max_id for table: {}'.format(self.config.job.upper(),sql_table))
            self.logger.error(e)
            sys.exit(1)

    # _____________________________________________________________________
    # __move_to_s3_raw
    def __move_to_s3_raw(self, sql_query, last_processed_id, max_id, sql_table, timestamp, loading_method):
        try:
            my_sql = sql_query.format(last_processed_id=last_processed_id, max_id=max_id)
            self.logger.debug(my_sql)

            with smart_open.smart_open(
                's3://{bucket}/{prefix}{loading_method}{tablename}_{timestamp}.csv'.format(
                    bucket=self.bucket_data,
                    prefix=self.prefix_raw,
                    loading_method=loading_method + '_',
                    tablename=sql_table,
                    timestamp=timestamp
                ),
                'wb'
            ) as csv_file:
                writer = csv.writer(csv_file, quoting=csv.QUOTE_ALL, delimiter=';')
                self.expert.cur.execute(my_sql)
                column_names = [item[0] for item in self.expert.cur.description]
                writer.writerow(column_names)
                for row in self.expert.cur:
                    writer.writerow(row)
        except Exception as e:
            self.logger.error('{} Unable to move to S3 raw'.format(self.config.job.upper()))
            self.logger.error(e)
            sys.exit(1)

        return True

    # _____________________________________________________________________
    # __update_delta_loading_file
    def __update_delta_loading_file(self, delta_loading_file):
        try:
            self.logger.info('Updating delta_loading_file')

            new_delta_loading_file = json.dumps(
                delta_loading_file,
                sort_keys=True,
                indent=2,
                separators=(',', ': ')
            )

            self.s3_resource.Bucket(self.bucket_conf).put_object(
                Key=self.prefix_conf + self.delta_loading_file,
                Body=new_delta_loading_file
            )
        except Exception as e:
            self.logger.error('{} Unable to update delta_loading_file'.format(self.config.job.upper()))
            self.logger.error(e)
            sys.exit(1)

        return True