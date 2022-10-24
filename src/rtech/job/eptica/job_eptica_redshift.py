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
import boto3
import logging
import smart_open

from rtech.job.job import Job
from rtech.connector.connector_factory import ConnectorFactory


class EpticaRedShiftJob(Job):
    # _____________________________________________________________________
    # __init__
    def __init__(self, config, job_config):
        super(EpticaRedShiftJob, self).__init__(config)

        self.logger.info('Initializing EpticaRedShiftJob ...')

        self.job_config     = job_config
        self.region         = job_config['config']['region']
        self.bucket_data    = job_config['config']['bucket_data']
        self.bucket_data_s3 = job_config['config']['bucket_data_s3']
        self.bucket_conf    = job_config['config']['bucket_conf']
        self.prefix_conf    = job_config['config']['prefix_conf']
        self.prefix_raw     = job_config['config']['prefix_raw']
        self.prefix_stage   = job_config['config']['prefix_stage']
        self.prefix_public  = job_config['config']['prefix_public']

        self.redshift                    = ConnectorFactory(self.config).new_connector('databases', 'redshift', None)
        self.redshift_copy_cmd           = job_config['config']['redshift_copy_cmd']
        self.redshift_copy_cmd_iam_role  = job_config['config']['redshift_copy_cmd_iam_role']
        self.redshift_copy_cmd_delimiter = job_config['config']['redshift_copy_cmd_delimiter']
        self.redshift_public_schema      = job_config['config']['redshift_public_schema']

        self.s3_client     = boto3.client('s3')
        self.s3_resource   = boto3.resource('s3')

        # To have boto3 less verbose in our log files
        logging.getLogger('boto3').setLevel(logging.CRITICAL)

    # _____________________________________________________________________
    # run
    def run(self):

        self.redshift.connect()
        #run only once
        self.__create_table_public(self.redshift_public_schema)

        for gf in self.job_config['get_files']:
            instance = gf['source']['instance']

            if gf['is_active'] == 1:
                self.logger.info("Instance: " + instance)

                for stp in self.job_config['staging_to_public']:
                    file_name = stp ['file_name']

                    if stp['is_active'] == 1:
                        self.logger.info("  Processing: " + file_name)

                        table_name_stage  = 'stage.eptica_' + instance + '_' + os.path.splitext(os.path.basename(file_name))[0]
                        #table_name_public = 'public.eptica_' + os.path.splitext(os.path.basename(file_name))[0]
                        table_name_public = self.redshift_public_schema + '.eptica_' + os.path.splitext(os.path.basename(file_name))[0]

                        self.__drop_table_stage(table_name_stage)
                        self.__create_table_stage(
                            self.__create_table_stage_sql_statement(instance, file_name, table_name_stage),
                            table_name_stage
                        )
                        self.__insert_table_stage(instance, table_name_stage, file_name)
                        self.__delete_from_public(instance, table_name_public)
                        self.__insert_table_public(
                            instance,
                            table_name_public,
                            table_name_stage,
                            stp['sql_header'],
                            stp['sql_format'],
                            self.bucket_data,
                            file_name
                        )

        self.redshift.close()

        return True

    # _____________________________________________________________________
    # __drop_table_stage
    def __drop_table_stage(self, table_name_stage):
        try:
            self.redshift.cur.execute('drop table if exists ' + table_name_stage)
            self.redshift.conn.commit()
        except Exception as e:
            self.logger.error('{} Unable to drop redshift stage table: {}'.format(self.config.job.upper(),table_name_stage))
            self.logger.error(e)
            self.redshift.conn.rollback()
            self.redshift.close()
            sys.exit(1)

        return True


    # _____________________________________________________________________
    # __create_table_stage_sql_statement
    def __create_table_stage_sql_statement(self, instance, file_name, table_name_stage):
        try:
            sql = None

            for index, line in enumerate(smart_open.smart_open(self.bucket_data_s3 + instance + '/' + file_name)):
                if index == 0:
                    sql = str(line.lower()).replace('"', '').replace("b'", '').replace("'", '').replace(r"\r\n", r'')
                    # FR & BE file for RequestFieldInfo have french headers produit and produitid instead of product and productid
                    if file_name == 'RequestFieldInfo.csv':
                        sql = sql.replace('produit','product')
                    # Renaming of creationdate to createddate as it conflicts with additional fields added later
                    if file_name == 'CustomerFieldInfo.csv':
                        sql = sql.replace('creationdate','createddate')
                    # Adding default datatype varchar(255)
                    sql = 'create table ' + table_name_stage + ' (' + sql.replace(';',' varchar(300),') + ' varchar(300))'
                    break

            return sql
        except Exception as e:
            self.logger.error('{} Unable to create table stage sql statement for table: {}'.format(self.config.job.upper(),table_name_stage))
            self.logger.error(e)
            sys.exit(1)

    # _____________________________________________________________________
    # __create_table_stage
    def __create_table_stage(self, sql_statement, table_name_stage):
        try:
            self.redshift.cur.execute(sql_statement)
            self.redshift.conn.commit()
        except Exception as e:
            self.logger.error('{} Unable to create redshift stage table: {}'.format(self.config.job.upper(),table_name_stage))
            self.logger.error(e)
            self.redshift.conn.rollback()
            self.redshift.close()
            sys.exit(1)

        return True

    # _____________________________________________________________________
    # __insert_table_stage
    def __insert_table_stage(self, instance, table_name_stage, file_name):
        try:
            self.redshift.cur.execute(
                self.redshift_copy_cmd.format(
                    table     = table_name_stage,
                    bucket    = self.bucket_data,
                    prefix    = self.prefix_public + instance + '/',
                    file      = file_name,
                    iam_role  = self.redshift_copy_cmd_iam_role,
                    delimiter = self.redshift_copy_cmd_delimiter))
            self.redshift.conn.commit()
        except Exception as e:
            self.logger.error('{} Unable to insert into redshift stage table: {}'.format(self.config.job.upper(),table_name_stage))
            self.logger.error(e)
            self.redshift.conn.rollback()
            self.redshift.close()
            sys.exit(1)

        return True

        # _____________________________________________________________________
        # __delete_from_public

    def __create_table_public(self,schema_name):
        self.logger.info("Start creating public tables")
        try:
            for stp in self.job_config['staging_to_public']:
                file_name = stp['file_name']

                if stp['is_active'] == 1:
                    table_name_public = schema_name + '.eptica_' + os.path.splitext(os.path.basename(file_name))[0]
                    self.logger.info("  Processing: " + table_name_public)
                    self.redshift.cur.execute(stp['create_public_table'].format(table_name = table_name_public)
                    )
                    self.redshift.conn.commit()
            self.logger.info("Successfully created public tables")
        except Exception as e:
            self.logger.error('{} Unable to create public table: {}'.format(self.config.job.upper(),table_name_public))
            self.logger.error(e)
            self.redshift.conn.rollback()
            self.redshift.close()
            sys.exit(1)

        return True

    # _____________________________________________________________________
    # __delete_from_public
    def __delete_from_public(self, instance, table_name_public):
        try:
            self.redshift.cur.execute(
                "delete from " + table_name_public + " where epticainstanceid = '" + instance + "'"
            )
            self.redshift.conn.commit()
        except Exception as e:
            self.logger.error('{} Unable to delete from redshift public table: {}'.format(self.config.job.upper(),table_name_public))
            self.logger.error(e)
            self.redshift.conn.rollback()
            self.redshift.close()
            sys.exit(1)

        return True

    # _____________________________________________________________________
    # __insert_table_public
    def __insert_table_public(
            self,
            instance,
            table_name_public,
            table_name_stage,
            sql_header,
            sql_format,
            location,
            file_name
    ):
        additional_columns = ',epticainstanceid,isrecordactive,creationdate,updateddate,createdby'
        try:
            self.redshift.cur.execute(
                "insert into " + table_name_public + " (" + sql_header + additional_columns + ") select " + sql_format + ",'"
                    + instance + "',1,getdate(),getdate(),'awsuser' from " + table_name_stage)
            self.redshift.conn.commit()
        except Exception as e:
            self.logger.error('{} Unable to insert into redshift public table: {}'.format(self.config.job.upper(),table_name_public))
            self.logger.error(e)
            self.redshift.conn.rollback()
            self.redshift.close()
            sys.exit(1)

        return True