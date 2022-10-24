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


import csv
import json

import boto3
import logging
import datetime
import time

from smart_open import smart_open

from rtech.connector.connector_factory import ConnectorFactory
from rtech.job.job import Job


class AvayaS3Job(Job):
    def __init__(self, config, job_config):
        super(AvayaS3Job, self).__init__(config)

        self.logger.info('Initializing AvayaS3Job ...')

        self.job_config = job_config
        self.bucket_data = job_config['config']['bucket_data']
        self.bucket_conf = job_config['config']['bucket_conf']
        self.prefix_conf = job_config['config']['prefix_conf']
        self.prefix_raw = job_config['config']['prefix_raw']
        self.prefix_stage = job_config['config']['prefix_stage']
        self.prefix_public = job_config['config']['prefix_public']
        self.delta_loading_file = job_config['config']['delta_loading_file']
        self.loaded_to_public_file = job_config['config']['loaded_to_public_file']

        self.s3_client = boto3.client('s3')
        self.s3_resource = boto3.resource('s3')

        # To have boto3 less verbose in our log files
        logging.getLogger('boto3').setLevel(logging.CRITICAL)

    # run
    def run(self):
        self.logger.info('')
        try:
            with ConnectorFactory(self.config).new_connector('databases', 'avaya', None) as conn:
                if not self.__check_delta_loading_file_existence(self.delta_loading_file):
                    self.__create_delta_loading_file()

                if not self.__check_loaded_to_public_file_existence(self.loaded_to_public_file):
                    self.__create_loaded_to_public_file()

                delta_loading_file = self.__load_delta_loading_file()
                # new_delta_loading_file = dict()

                loaded_to_public_file = self.__load_loaded_to_public_file()

                # TODO: if delta_loading_file exists and a source go from is_active == 0 to is_active == 1,
                # the delta_loading_file entry for the new source_table will not be initiated

                for gf in self.job_config['get_data']:

                    sql_table = gf['source']['location']
                    column = gf['source']['columnid']
                    sql_query = gf['source']['sql']
                    is_active = gf['source']['is_active']
                    loading_method = gf['source']['loading_method']

                    last_processed_date = None
                    max_date = None

                    # Only import active data sources
                    if is_active == 1:
                        self.logger.info("Processing: {}".format(sql_table))

                        # if loading_method == 'full':
                        #     # timestamp = time.strftime("20171012_000000")
                        #     delta_loading_file[sql_table]['missing_dates'] = []
                        #     last_processed_date = (datetime.datetime.strptime(
                        #         gf['source']['full_load_min_date'], '%Y-%m-%d')
                        #                            - datetime.timedelta(days=1)).date()
                        #
                        # if loading_method == 'delta':
                            # timestamp = time.strftime("%Y%m%d_%H%M%S")
                        if sql_table in delta_loading_file:
                            last_processed_date = datetime.datetime.strptime(
                                delta_loading_file[sql_table]['last_processed_date'],
                                '%Y-%m-%d').date()
                        else:
                            last_processed_date = datetime.datetime.strptime(
                                gf['source']['full_load_min_date'], '%Y-%m-%d')

                        max_date = self.__get_new_max_date(sql_table)

                        date_to_be_processed = last_processed_date + datetime.timedelta(days=1)

                        while date_to_be_processed < max_date:  # TODO: AVAYA consider threading or coroutines for 'full_load' to speed up the process
                            timestamp = date_to_be_processed.strftime('%Y%m%d_000000')
                            moved_to_s3_raw = self.__move_to_s3_raw(
                                conn,
                                sql_query,
                                date_to_be_processed.strftime('%Y-%m-%d'),
                                max_date.strftime('%Y-%m-%d'),
                                sql_table,
                                timestamp
                            )

                            missing_date = {
                                'missing_date': date_to_be_processed.strftime('%Y-%m-%d')
                            }
                            if moved_to_s3_raw:
                                if missing_date in delta_loading_file[sql_table]['missing_dates']:
                                    delta_loading_file[sql_table]['missing_dates'].remove(missing_date)
                                delta_loading_file[sql_table] = {
                                    'loading_method': loading_method,
                                    'last_processed_date': date_to_be_processed.strftime('%Y-%m-%d'),
                                    'missing_dates': delta_loading_file[sql_table]['missing_dates']
                                }
                                moved_to_public = self.__move_to_s3_public(moved_to_s3_raw, sql_table)
                                if moved_to_public:
                                    moved = {
                                        'file': moved_to_public
                                    }
                                    if moved not in loaded_to_public_file[sql_table][
                                        'loaded_to_public']:
                                        loaded_to_public_file[sql_table]['loaded_to_public'].append(
                                            moved)
                            else:
                                if missing_date not in delta_loading_file[sql_table]['missing_dates']:
                                    delta_loading_file[sql_table]['missing_dates'].append(missing_date)
                                delta_loading_file[sql_table] = {
                                    'loading_method': delta_loading_file[sql_table]['loading_method'],
                                    'last_processed_date': delta_loading_file[sql_table][
                                        'last_processed_date'],
                                    'missing_dates': delta_loading_file[sql_table]['missing_dates']
                                }

                            date_to_be_processed += datetime.timedelta(days=1)

                        # Loop through missing dates from previous runs
                        missing_dates = list(delta_loading_file[sql_table]['missing_dates'])
                        for missing_date in missing_dates:
                            timestamp = datetime.datetime.strptime(
                                missing_date['missing_date'], '%Y-%m-%d'
                            ).strftime('%Y%m%d_000000')

                            moved_to_s3_raw = self.__move_to_s3_raw(
                                conn,
                                sql_query,
                                missing_date['missing_date'],
                                None,
                                sql_table,
                                timestamp
                            )
                            if moved_to_s3_raw:
                                if missing_date in delta_loading_file[sql_table]['missing_dates']:
                                    delta_loading_file[sql_table]['missing_dates'].remove(missing_date)
                                moved_to_public = self.__move_to_s3_public(moved_to_s3_raw, sql_table)
                                if moved_to_public:
                                    moved = {
                                        'file': moved_to_public
                                    }
                                    if moved not in loaded_to_public_file[sql_table][
                                        'loaded_to_public']:
                                        loaded_to_public_file[sql_table]['loaded_to_public'].append(
                                            moved)

                self.__update_delta_loading_file(delta_loading_file)
                self.__update_loaded_to_public_file(loaded_to_public_file)
        except Exception:
            self.logger.exception('{}: Unable to process'.format(self.config.job.upper()))

    # __check_delta_loading_file_existence
    def __check_delta_loading_file_existence(self, key):
        self.logger.info('Checking delta_loading_file existence')
        try:
            response = self.s3_client.list_objects_v2(
                Bucket=self.bucket_conf,
                Prefix=self.prefix_conf
            )
            for obj in response.get('Contents', []):
                if obj['Key'] == self.prefix_conf + key:
                    return True

            return False
        except Exception:
            self.logger.exception('{}: Unable to check "delta_loading_file_existence"'.format(self.config.job.upper()))
            return None

    # __load_delta_loading_file
    def __load_delta_loading_file(self):
        self.logger.info('Loading delta_loading_file')
        try:
            return json.load(
                self.s3_client.get_object(
                    Bucket=self.bucket_conf,
                    Key=self.prefix_conf + self.delta_loading_file
                )['Body']
            )
        except Exception:
            self.logger.exception('{}: Unable to load "delta_loading_file"'.format(self.config.job.upper()))
            return None

    # __create_delta_loading_file
    def __create_delta_loading_file(self):
        self.logger.info('Creating delta_loading_file')
        try:
            self.s3_resource.Bucket(self.bucket_conf).put_object(
                Key=self.prefix_conf + self.delta_loading_file,
                Body=self.__init_delta_loading_file()
            )

            return True
        except Exception:
            self.logger.exception('{}: Unable to create "delta_loading_file"'.format(self.config.job.upper()))

    # __init_delta_loading_file
    def __init_delta_loading_file(self):
        self.logger.info('Initialising delta_loading_file')
        try:
            my_json_file = dict()

            for gf in self.job_config['get_data']:
                sql_table = gf['source']['location']
                is_active = gf['source']['is_active']
                loading_method = gf['source']['loading_method']
                last_processed_date_string = datetime.datetime.strftime(
                    datetime.datetime.strptime(
                        gf['source']['full_load_min_date'], '%Y-%m-%d')
                    - datetime.timedelta(days=1), '%Y-%m-%d')

                if is_active == 1:
                    my_json_file[sql_table] = {}
                    my_json_file[sql_table]['loading_method'] = loading_method
                    my_json_file[sql_table]['last_processed_date'] = last_processed_date_string
                    my_json_file[sql_table]['missing_dates'] = []

            return json.dumps(
                my_json_file,
                sort_keys=True,
                indent=2,
                separators=(',', ': ')
            )
        except Exception:
            self.logger.exception('{}: Unable to init "delta_loading_file"'.format(self.config.job.upper()))

    # __update_delta_loading_file
    def __update_delta_loading_file(self, delta_loading_file):
        self.logger.info('Updating delta_loading_file')
        try:
            if len(delta_loading_file) is not 0:
                new_delta_loading_file = json.dumps(
                    delta_loading_file,
                    sort_keys=True,
                    indent=2,
                    separators=(',', ': ')
                )

                self.s3_resource.Bucket(self.bucket_conf).put_object(
                    Key=self.prefix_conf + self.delta_loading_file,
                    Body=new_delta_loading_file,
                    ServerSideEncryption='AES256'
                )
                self.logger.info('delta_loading_file updated')
            else:
                self.logger.info('delta_loading_file not updated. Nothing to update')

            return True
        except Exception:
            self.logger.exception('{}: Unable to update "delta_loading_file"'.format(self.config.job.upper()))

    # __check_loaded_to_public_file_existence
    def __check_loaded_to_public_file_existence(self, key):
        self.logger.info('Checking delta_loading_file_existence')
        try:
            response = self.s3_client.list_objects_v2(
                Bucket=self.bucket_conf,
                Prefix=self.prefix_conf
            )
            for obj in response.get('Contents', []):
                if obj['Key'] == self.prefix_conf + key:
                    return True
        except Exception:
            self.logger.exception('{}: Unable to check "loaded_to_public_file"'.format(self.config.job.upper()))
            return None

    # __load_loaded_to_public_file
    def __load_loaded_to_public_file(self):
        self.logger.info('Loading loaded_to_public_file')
        try:
            return json.load(
                self.s3_client.get_object(
                    Bucket=self.bucket_conf,
                    Key=self.prefix_conf + self.loaded_to_public_file
                )['Body']
            )
        except Exception:
            self.logger.exception('{}: Unable to load "loaded_to_public_file"'.format(self.config.job.upper()))
            return None

    # __create_loaded_to_public_file
    def __create_loaded_to_public_file(self):
        self.logger.info('Creating loaded_to_public_file')
        try:
            self.s3_resource.Bucket(self.bucket_conf).put_object(
                Key=self.prefix_conf + self.loaded_to_public_file,
                Body=self.__init_loaded_to_public_file()
            )

            return True
        except Exception:
            self.logger.exception('{}: Unable to create "loaded_to_public_file"'.format(self.config.job.upper()))
            return None

    # __init_loaded_to_public_file
    def __init_loaded_to_public_file(self):
        self.logger.info('Initialising loaded_to_public_file')
        try:
            my_json_file = dict()

            for gf in self.job_config['get_data']:
                sql_table = gf['source']['location']

                my_json_file[sql_table] = {}
                my_json_file[sql_table]['loaded_to_public'] = []

            return json.dumps(
                my_json_file,
                sort_keys=True,
                indent=2,
                separators=(',', ': ')
            )
        except Exception:
            self.logger.exception('{}: Unable to init "loaded_to_public_file"'.format(self.config.job.upper()))
            return None

    # __update_delta_loading_file
    def __update_loaded_to_public_file(self, loaded_to_public_file):
        self.logger.info('Updating loaded_to_public_file')
        try:
            if len(loaded_to_public_file) is not 0:
                new_loaded_to_public_file = json.dumps(
                    loaded_to_public_file,
                    sort_keys=True,
                    indent=2,
                    separators=(',', ': ')
                )

                self.s3_resource.Bucket(self.bucket_conf).put_object(
                    Key=self.prefix_conf + self.loaded_to_public_file,
                    Body=new_loaded_to_public_file,
                    ServerSideEncryption='AES256'
                )
                self.logger.info('loaded_to_public_file updated')
            else:
                self.logger.info('loaded_to_public_file not updated. Nothing to update')

            return True
        except Exception:
            self.logger.exception('{}: Unable to update "loaded_to_public_file"'.format(self.config.job.upper()))
            return None

    # __get_new_max_date
    def __get_new_max_date(self, sql_table):
        self.logger.debug('Getting new max_date for table: {}'.format(sql_table))
        try:
            return datetime.datetime.now().date() - datetime.timedelta(days=1)  # this is to prevent collection of a few records from sysdate - 2 days before the entire set is ready
        except Exception:
            self.logger.exception('{}: Unable to get new max date'.format(self.config.job.upper()))

    # __move_to_s3_raw
    def __move_to_s3_raw(self, conn, sql_query, last_processed_date, max_date, sql_table,
                         timestamp):
        try:
            my_sql = sql_query.format(the_date=last_processed_date)
            self.logger.debug(my_sql)

            filename = 's3://{bucket}/{prefix}{tablename}/{tablename}_{timestamp}.csv'.format(
                bucket=self.bucket_data,
                prefix=self.prefix_raw,
                tablename=sql_table,
                timestamp=timestamp
            )
            self.logger.info('Moving data from {sql_table} with row_date = {date} into {file}'.format(
                sql_table=sql_table,
                date=datetime.datetime.strptime(timestamp.split('_')[0], '%Y%m%d').strftime('%Y-%m-%d'),
                file=filename
            ))
            with smart_open(filename, 'wb') as csv_file:
                writer = csv.writer(csv_file, quoting=csv.QUOTE_MINIMAL, delimiter=';')
                # TODO: Exception
                conn.cur.execute(my_sql)
                column_names = [item[0] for item in conn.cur.description]
                writer.writerow(column_names)
                for row in conn.cur:
                    writer.writerow(row)

                if conn.cur.rowcount == 0:
                    return None
                else:
                    return filename
        except Exception:
            self.logger.exception('{}: Unable to move to s3 raw'.format(self.config.job.upper()))
            return None

    # __move_to_s3_public
    def __move_to_s3_public(self, path_to_raw_file, sql_table):
        try:
            key = (sql_table + '/'
                   + path_to_raw_file.rpartition('/')[2].rpartition('_')[0]
                   + path_to_raw_file.rpartition('.')[1]
                   + path_to_raw_file.rpartition('.')[2])
            self.s3_client.copy_object(
                # self.logger.info('Bucket={Bucket}, CopySource={CopySource}, Key={Key}, ServerSideEncryption={ServerSideEncryption}'.format(
                Bucket=self.bucket_data,
                CopySource=path_to_raw_file.replace('s3://', ''),
                Key=self.prefix_public + key,
                ServerSideEncryption='AES256'
            )
            return key
        except Exception:
            self.logger.exception('{}: Unable to move to s3 public'.format(self.config.job.upper()))
            return None

