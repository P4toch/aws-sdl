import logging
from datetime import datetime

import boto3

from rtech.connector.connector_factory import ConnectorFactory
from rtech.job.job import Job


class AvayaCallDetailRedshiftJob(Job):
    def __init__(self, config, job_config):
        super(AvayaCallDetailRedshiftJob, self).__init__(config)

        self.logger.info('Initializing AvayaCallDetailRedshiftJob ...')

        self.job_config = job_config
        self.bucket_data = job_config['config']['bucket_data']
        self.bucket_data_s3 = job_config['config']['bucket_data_s3']
        self.bucket_data_http = job_config['config']['bucket_data_http']
        self.bucket_conf = job_config['config']['bucket_conf']
        self.prefix_conf = job_config['config']['prefix_conf']
        self.prefix_stage = job_config['config']['prefix_stage']
        self.prefix_public = job_config['config']['prefix_public']
        self.redshift_copy_cmd = job_config['config']['redshift_copy_cmd']
        self.redshift_copy_cmd_iam_role = job_config['config']['redshift_copy_cmd_iam_role']
        self.redshift_copy_cmd_delimiter = job_config['config']['redshift_copy_cmd_delimiter']
        self.stage_to_public_sql = job_config['config']['stage_to_public_sql']
        self.redshift = ConnectorFactory(self.config).new_connector('databases', 'redshift', None)

        self.s3_client = boto3.client('s3')
        self.s3_resource = boto3.resource('s3')

        # To have boto3 less verbose in our log files
        logging.getLogger('boto3').setLevel(logging.CRITICAL)

    # run
    def run(self):
        self.logger.info('')

        self.__read_job_config()
        # self.__dev_drop_stage_public_tables()  # TODO: Comment this line before release. This is just for testing
        self.__create_stage_tables()
        self.__create_public_tables()
        self.__truncate_stage_tables()
        # self.__truncate_public_tables()  # TODO: Comment this line before release. This is just for testing

        self.logger.info('')

        file = '/tmp/avaya_call_detail_uniqeid.txt'
        with open(file, 'r') as uniqe_file:
            uniqeid = uniqe_file.read()
        self.logger.info(f'Getting unique-id {uniqeid} from {file}')
        
        for gf in self.job_config['get_data']:
            if gf['source']['is_active'] == 1:
                prefix_stage = f"{self.prefix_stage}{gf['source']['location']}/{uniqeid}/files/"
                self.logger.info(f'Getting data from {prefix_stage}')

                try:
                    self.redshift.connect()

                    table_name_stage = gf['source']['stage_table']
                    table_name_public = gf['source']['public_table']
                    column_list = ''

                    self.__insert_table_stage(table_name_stage, prefix_stage, column_list)

                    md5_hash_prepare_sql = """
                        select
                        case 
                            when charindex('boolean',data_type) > 0
                                then 'cast(coalesce(case ' + table_name + '.' + column_name + ' when TRUE then 1 else 0 end, 0) as varchar)'
                            when column_name like 'md5_hash_key'
                                then 'cast(0 as varchar)'
                            else 'cast(coalesce(' + table_name + '.' + column_name + ',''' + '0' + ''')' + ' as varchar)'  
                        end as md5_hash_prepare
                        from information_schema.columns 
                        where table_name = 'avaya_call_detail'
                        and table_schema = 'stage'
                        order by ordinal_position;
                    """
                    self.redshift.cur.execute(md5_hash_prepare_sql)
                    md5_hash_prepare = ''
                    for counter, rec in enumerate(self.redshift.cur.fetchall()):
                        if counter == 0:
                            md5_hash_prepare += f'{rec[0]}'
                        else:
                            md5_hash_prepare += f' + {rec[0]}'

                    md5_hash_key = f"md5({md5_hash_prepare})"

                    self.__update_md5_hashkey(table_name_stage, md5_hash_key)
                    self.__insert_table_public(table_name_stage, table_name_public)
                    self.__delete_files_from_s3_stage(prefix_stage)  # TODO: Uncomment before release

                except Exception:
                    self.redshift.conn.rollback()
                    self.logger.exception('{}: Something went wrong while inserting into redshift'.format(self.config.job.upper()))
                finally:
                    if not self.redshift.conn.closed:
                        self.redshift.close()

    def __read_job_config(self):
        self.logger.debug('Entering __read_job_config()')

        stage_tables = dict()
        create_stage_tables = dict()
        create_public_tables = dict()
        truncate_stage_tables = dict()
        truncate_public_tables = dict()
        try:
            for gf in self.job_config['get_data']:
                sql_table = gf['source']['target']
                is_active = gf['source']['is_active']
                stage_table = gf['source']['stage_table']
                public_table = gf['source']['public_table']
                create_stage_table = gf['source']['create_stage_table']
                create_public_table = gf['source']['create_public_table']
                truncate_stage_table = gf['source']['truncate_table']
                truncate_public_table = gf['source']['truncate_table']

                if is_active == 1:
                    stage_tables[sql_table] = stage_table
                    create_stage_tables[sql_table] = create_stage_table.format(table=stage_table)
                    create_public_tables[sql_table] = create_public_table.format(table=public_table)
                    truncate_stage_tables[sql_table] = truncate_stage_table.format(table=stage_table)
                    truncate_public_tables[sql_table] = truncate_public_table.format(table=public_table)

            self.stage_tables = stage_tables
            self.create_stage_tables = create_stage_tables
            self.create_public_tables = create_public_tables
            self.truncate_stage_tables = truncate_stage_tables
            self.truncate_public_tables = truncate_public_tables
        except Exception:
            self.logger.exception('{}: Something went wrong while reading job config'.format(self.config.job.upper()))
            return False

        return True

    def __dev_drop_stage_public_tables(self):
        self.logger.info('Dropping Avaya_call_detail stage and public tables')

        try:
            self.redshift.connect()

            self.redshift.cur.execute("drop table if exists stage.avaya_call_detail;")
            self.redshift.conn.commit()
            self.redshift.cur.execute("drop table if exists public.avaya_call_detail;")
            self.redshift.conn.commit()
            return True
        except Exception:
            self.redshift.conn.rollback()
            self.logger.exception('{}: Something went wrong while dropping stage or public table'.format(self.config.job.upper()))
            return False
        finally:
            if not self.redshift.conn.closed:
                self.redshift.close()

    def __create_stage_tables(self):
        self.logger.info('Initializing Avaya_call_detail staging tables')

        self.__create_tables(self.create_stage_tables, 'stage')
        return True

    def __create_public_tables(self):
        self.logger.info('Initializing Avaya_call_detail public tables')

        self.__create_tables(self.create_public_tables, 'public')
        return True

    def __create_tables(self, create_tables_list, schema):
        try:
            my_schema = schema
            self.redshift.connect()
            for table in create_tables_list:
                self.logger.info('table: {}'.format(table))

                self.redshift.cur.execute(create_tables_list[table])
                self.redshift.conn.commit()
        except Exception:
            self.redshift.conn.rollback()
            self.logger.exception('{}: Something went wrong while creating {schema}'.format(self.config.job.upper(), schema=my_schema))
            return False
        finally:
            if not self.redshift.conn.closed:
                self.redshift.close()

    def __truncate_stage_tables(self):
        self.logger.info('Truncating Avaya_call_detail staging_tables')

        self.__truncate_tables(self.truncate_stage_tables, 'stage')
        return True

    def __truncate_public_tables(self):
        self.logger.info('Truncating Avaya_call_detail public tables')

        self.__truncate_tables(self.truncate_public_tables, 'public')
        return True

    def __truncate_tables(self, truncate_tables_list, schema):
        try:
            my_schema = schema
            self.redshift.connect()

            for table in truncate_tables_list:
                self.logger.info('table: {}'.format(table))

                self.redshift.cur.execute(truncate_tables_list[table])
                self.redshift.conn.commit()
            return True
        except Exception:
            self.redshift.conn.rollback()
            self.logger.exception('{}: Something went wrong while truncating {schema} tables'.format(self.config.job.upper(), schema=my_schema))
            return False
        finally:
            if not self.redshift.conn.closed:
                self.redshift.close()

    def __insert_table_stage(self, table_name_stage, prefix, column_list):
        self.logger.info('Inserting data into staging table')

        cmd = self.redshift_copy_cmd.format(
            table=table_name_stage,
            column_list=column_list,
            bucket=self.bucket_data,
            prefix=prefix,
            iam_role=self.redshift_copy_cmd_iam_role,
            delimiter=self.redshift_copy_cmd_delimiter
        )

        try:
            self.logger.info('Copying into stage table')
            self.redshift.cur.execute(cmd)
            self.redshift.conn.commit()
            return True
        except Exception:
            self.redshift.conn.rollback()
            self.logger.exception('{}: Something went wrong while inserting into stage table'.format(self.config.job.upper()))
            return False

    def __insert_table_public(self, table_name_stage, table_name_public):
        self.logger.info('Inserting data into public table')

        cmd = self.stage_to_public_sql.format(
            public_table=table_name_public,
            stage_table=table_name_stage
        )

        try:
            self.logger.info('Copying into public table')
            self.redshift.cur.execute(cmd)
            self.redshift.conn.commit()
            return True
        except Exception:
            self.redshift.conn.rollback()
            self.logger.exception('{}: Something went wrong while inserting into public table'.format(self.config.job.upper()))
            return False

    def __delete_files_from_s3_stage(self, prefix_stage):
        self.logger.info('Deleting files from S3 stage folder')

        bucket = self.bucket_data
        my_filter = prefix_stage.replace('files/', '')
        if my_filter[-1] != '/':
            my_filter = my_filter + '/'

        self.s3_resource.Bucket(bucket).objects.filter(Prefix=my_filter).delete()

    def __update_md5_hashkey(self, table_name, md5_hash_key):
        self.logger.info('Updating md5_hash_key for table {}'.format(table_name))
        try:
            try:
                self.redshift.cur.execute('update {table} set md5_hash_key = {md5_hash_key}'.format(
                        table=table_name,
                        md5_hash_key=md5_hash_key
                    )
                )
                self.redshift.conn.commit()
            except Exception:
                self.redshift.conn.rollback()
                raise
        except Exception:
            raise Exception('{}: Unable to update md5_hash_key for {}'.format(self.config.job.upper(), table_name))
