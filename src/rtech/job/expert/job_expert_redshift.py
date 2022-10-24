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

import re
import sys
import boto3
import logging
import traceback

from rtech.job.job import Job
from rtech.connector.connector_factory import ConnectorFactory


class ExpertRedShiftJob(Job):
    # _____________________________________________________________________
    # __init__
    def __init__(self, config, job_config):
        super(ExpertRedShiftJob, self).__init__(config)

        self.logger.info('Initializing ExpertRedShiftJob ...')

        self.job_config                  = job_config
        self.bucket_data                 = job_config['config']['bucket_data']
        self.bucket_data_http            = job_config['config']['bucket_data_http']
        self.bucket_conf                 = job_config['config']['bucket_conf']
        self.prefix_conf                 = job_config['config']['prefix_conf']
        self.prefix_raw                  = job_config['config']['prefix_raw']
        self.prefix_stage                = job_config['config']['prefix_stage']
        self.prefix_public               = job_config['config']['prefix_public']

        self.delta_loading_file          = job_config['config']['delta_loading_file']

        self.stage_tables                = None
        self.create_stage_tables         = None
        self.create_public_tables        = None
        self.truncate_stage_tables       = None
        self.truncate_public_tables      = None
        self.delta_queries_part_1        = None
        self.delta_queries_part_2        = None

        self.redshift                    = ConnectorFactory(self.config).new_connector('databases', 'redshift', None)
        self.redshift_copy_cmd           = job_config['config']['redshift_copy_cmd']
        self.redshift_copy_cmd_iam_role  = job_config['config']['redshift_copy_cmd_iam_role']
        self.redshift_copy_cmd_delimiter = job_config['config']['redshift_copy_cmd_delimiter']

        self.s3_client                   = boto3.client('s3')
        self.s3_resource                 = boto3.resource('s3')

        # To have boto3 less verbose in our log files
        logging.getLogger('boto3').setLevel(logging.CRITICAL)

    # _____________________________________________________________________
    # run
    def run(self):
        self.logger.info('')

        self.redshift.connect()

        self.__read_job_config()

        self.__create_stage_tables()

        self.__create_public_tables()

        self.__truncate_stage_tables()

        self.__truncate_public_tables()

        self.logger.info('')

        bucket = self.s3_resource.Bucket(self.bucket_data)

        for obj in bucket.objects.filter(Prefix = self.prefix_raw):

            m = re.match('_+(?P<filename>[A-Za-z]+)_\w+', obj.key.replace(self.prefix_raw, '').replace('delta','').replace('full',''))

            #if re.search('DELTA_([A-Za-z]+)_\w+', obj.key.replace(self.prefix_raw, '')):

            self.logger.info('Processing file: ' + obj.key.replace(self.prefix_raw, ''))

            self.__insert_table_stage(
                self.stage_tables[m.group('filename')],
                obj.key.replace(self.prefix_raw, '')
            )

            self.__insert_table_public(m.group('filename'))

            self.__copy_processed_file(obj, bucket)

        self.redshift.close()

    # _____________________________________________________________________
    # __read_job_config
    def __read_job_config(self):
        self.logger.debug('Entering __read_job_config(self)')

        stage_tables            = dict()
        create_stage_tables     = dict()
        create_public_tables    = dict()
        truncate_stage_tables   = dict()
        truncate_public_tables  = dict()
        delta_queries_part_1    = dict()
        delta_queries_part_2    = dict()

        for gf in self.job_config['get_data']:
            sql_table             = gf['source']['location']
            is_active             = gf['source']['is_active']
            stage_table           = gf['source']['stage_table']
            create_stage_table    = gf['source']['create_stage_table']
            create_public_table   = gf['source']['create_public_table']
            truncate_stage_table  = gf['source']['truncate_stage_table']
            truncate_public_table = gf['source']['truncate_public_table']
            loading_method        = gf['source']['loading_method']

            delta_query_part_1    = gf['source']['delta_query_part_1']
            delta_query_part_2    = gf['source']['delta_query_part_2']

            if is_active == 1:
                stage_tables[sql_table]          = stage_table
                create_stage_tables[sql_table]   = create_stage_table
                create_public_tables[sql_table]  = create_public_table
                truncate_stage_tables[sql_table] = truncate_stage_table

                if loading_method == 'full':
                    truncate_public_tables[sql_table] = truncate_public_table

                delta_queries_part_1[sql_table]  = delta_query_part_1
                delta_queries_part_2[sql_table]  = delta_query_part_2

        self.stage_tables           = stage_tables
        self.create_stage_tables    = create_stage_tables
        self.create_public_tables   = create_public_tables
        self.truncate_stage_tables  = truncate_stage_tables
        self.truncate_public_tables = truncate_public_tables
        self.delta_queries_part_1   = delta_queries_part_1
        self.delta_queries_part_2   = delta_queries_part_2

        return True

    # _____________________________________________________________________
    # __create_stage_tables
    def __create_stage_tables(self):
        self.logger.info('Initializing ExpeRT staging tables')

        for table in self.create_stage_tables:
            try:
                self.redshift.cur.execute(self.create_stage_tables[table])
                self.redshift.cur.execute('commit')
            except Exception as e:
                self.logger.error('{} Unable to initialize expert stage table: {}'.format(self.config.job.upper(),table))
                self.logger.error(e)
                self.logger.error(traceback.format_exc())
                self.redshift.conn.rollback()
                self.redshift.close()
                sys.exit(1)

        return True

    # _____________________________________________________________________
    # __create_public_tables
    def __create_public_tables(self):
        self.logger.info('Initializing ExpeRT public tables')

        for table in self.create_public_tables:
            try:
                self.redshift.cur.execute(self.create_public_tables[table])
                self.redshift.cur.execute('commit')
            except Exception as e:
                self.logger.error('{} Unable to initialize expert public table: {}'.format(self.config.job.upper(),table))
                self.logger.error(e)
                self.logger.error(traceback.format_exc())
                self.redshift.conn.rollback()
                self.redshift.close()
                sys.exit(1)

        return True

    # _____________________________________________________________________
    # __truncate_stage_tables
    def __truncate_stage_tables(self):
        self.logger.debug('Truncating ExpeRT stage tables')

        for table in self.truncate_stage_tables:
            try:
                self.redshift.cur.execute(self.truncate_stage_tables[table])
                self.redshift.cur.execute('commit')
            except Exception as e:
                self.logger.error('{} Unable to truncate expert stage table: {}'.format(self.config.job.upper(),table))
                self.logger.error(e)
                self.logger.error(traceback.format_exc())
                self.redshift.conn.rollback()
                self.redshift.close()
                sys.exit(1)

        return True

    # _____________________________________________________________________
    # __insert_table_stage
    def __insert_table_stage(self, table_name_stage, file_name):
        self.logger.debug('  Inserting data into staging table')

        try:
            self.redshift.cur.execute(
                self.redshift_copy_cmd.format(
                    table     = table_name_stage,
                    bucket    = self.bucket_data,
                    prefix    = self.prefix_raw,
                    file      = file_name,
                    iam_role  = self.redshift_copy_cmd_iam_role,
                    delimiter = self.redshift_copy_cmd_delimiter
                )
            )
            self.redshift.conn.commit()
        except Exception as e:
            self.logger.error('{} Unable to insert into redshift stage table: {}'.format(self.config.job.upper(),table_name_stage))
            self.logger.error(e)
            self.logger.error(traceback.format_exc())
            self.redshift.conn.rollback()
            self.redshift.close()
            sys.exit(1)

        return True

    # _____________________________________________________________________
    # __truncate_public_tables

    def __truncate_public_tables(self):
        self.logger.debug('Truncating ExpeRT public table')

        for table in self.truncate_public_tables:
            try:
                self.redshift.cur.execute(self.truncate_public_tables[table])
                self.redshift.cur.execute('commit')
            except Exception as e:
                self.logger.error('{} Unable to truncate expert public table: {}'.format(self.config.job.upper(),table))
                self.logger.error(e)
                self.logger.error(traceback.format_exc())
                self.redshift.conn.rollback()
                self.redshift.close()
                sys.exit(1)

        return True

    # _____________________________________________________________________
    # __insert_table_public
    def __insert_table_public(self, key):
        self.logger.debug('  Inserting data into public table')

        try:
            self.redshift.cur.execute(
                self.delta_queries_part_1[key] +
                " 1, getdate(), getdate(), 'awsuser'" +
                self.delta_queries_part_2[key]
            )
            self.redshift.conn.commit()
        except Exception as e:
            self.logger.error('{} Unable to insert into redshift public table: {}'.format(self.config.job.upper(),key))
            self.logger.error(e)
            self.logger.error(traceback.format_exc())
            self.redshift.conn.rollback()
            self.redshift.close()
            sys.exit(1)

        return True

    # _____________________________________________________________________
    # __copy_processed_file
    def __copy_processed_file(self, obj, bucket):
        self.logger.debug('  Copying processed file')

        try:
            self.s3_resource.meta.client.copy(
                {'Bucket': self.bucket_data, 'Key': obj.key},
                self.bucket_data,
                self.prefix_public + obj.key.replace(self.prefix_raw, '').replace('full_','').replace('delta_','')
            )
            self.s3_resource.Object(bucket.name, obj.key).delete()
        except Exception as e:
            self.logger.error('{} Unable to copy and delete file'.format(self.config.job.upper()))
            self.logger.error(e)
            self.redshift.conn.rollback()
            self.redshift.close()
            sys.exit(1)

        return True