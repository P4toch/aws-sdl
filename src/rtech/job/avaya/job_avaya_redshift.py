import json
import logging
import boto3

from rtech.connector.connector_factory import ConnectorFactory
from rtech.job.job import Job


class AvayaRedShiftJob(Job):
    def __init__(self, config, job_config):
        super(AvayaRedShiftJob, self).__init__(config)

        self.logger.info('Initialising AvayaRedShiftJob ...')

        self.job_config = job_config
        self.bucket_data = job_config['config']['bucket_data']
        self.bucket_data_s3 = job_config['config']['bucket_data_s3']
        self.bucket_data_http = job_config['config']['bucket_data_http']
        self.bucket_conf = job_config['config']['bucket_conf']
        self.prefix_conf = job_config['config']['prefix_conf']
        self.prefix_raw = job_config['config']['prefix_raw']
        self.prefix_stage = job_config['config']['prefix_stage']
        self.prefix_public = job_config['config']['prefix_public']
        self.redshift_copy_cmd = job_config['config']['redshift_copy_cmd']
        self.redshift_copy_cmd_iam_role = job_config['config']['redshift_copy_cmd_iam_role']
        self.redshift_copy_cmd_delimiter = job_config['config']['redshift_copy_cmd_delimiter']
        self.stage_to_public_sql = job_config['config']['stage_to_public_sql']
        self.loaded_to_public_file = job_config['config']['loaded_to_public_file']
        self.redshift = ConnectorFactory(self.config).new_connector('databases', 'redshift', None)

        self.s3_client = boto3.client('s3')
        self.s3_resource = boto3.resource('s3')

        # To have boto3 less verbose in our log files
        logging.getLogger('boto3').setLevel(logging.CRITICAL)

    # run
    def run(self):
        self.logger.info('')

        self.__read_job_config()
        self.__create_stage_tables()
        self.__create_public_tables()
        self.__truncate_stage_tables()
        # self.__truncate_public_tables() # This is only for testing purposes

        self.logger.info('')

        loaded_to_public_file = self.__load_loaded_to_public_file()
        if loaded_to_public_file:
            try:
                self.redshift.connect()
                for gf in self.job_config['get_data']:
                    load_list = list(
                        loaded_to_public_file[gf['source']['location']]['loaded_to_public'])
                    for file in load_list:
                        inserted_in_stage = self.__insert_table_stage(
                            gf['source']['stage_table'],
                            file['file']
                        )
                        if inserted_in_stage:
                            moved = {
                                'file': file['file']
                            }
                            if moved in loaded_to_public_file[gf['source']['location']][
                                'loaded_to_public']:
                                loaded_to_public_file[gf['source']['location']][
                                    'loaded_to_public'].remove(moved)

                    self.__insert_table_public(gf)

            except Exception:
                self.logger.exception('{}: '.format(self.config.job.upper()))
                if not self.redshift.conn.closed:
                    self.redshift.close()
            finally:
                self.__update_loaded_to_public_file(loaded_to_public_file)

    # __check_loaded_to_public_file_existence
    def __check_loaded_to_public_file_existence(self, key):
        self.logger.info('Checking delta_loading_file_existence')
        response = self.s3_client.list_objects_v2(
            Bucket=self.bucket_conf,
            Prefix=self.prefix_conf
        )
        for obj in response.get('Contents', []):
            if obj['Key'] == self.prefix_conf + key:
                return True

        return False

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
            self.logger.exception('{}: Unable to load loaded_to_public_file'.format(self.config.job.upper()))
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

    # __read_job_config()
    def __read_job_config(self):
        self.logger.debug('Entering __read_job_config()')
        try:
            stage_tables = dict()
            create_stage_tables = dict()
            create_public_tables = dict()
            truncate_stage_tables = dict()
            truncate_public_tables = dict()

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

            return True
        except Exception:
            self.logger.exception('{}: Unable to read job config'.format(self.config.job.upper()))

    # __create_stage_tables
    def __create_stage_tables(self):
        self.logger.info('Initialising Avaya staging tables')

        try:
            self.redshift.connect()

            for table in self.create_stage_tables:
                self.logger.info('table: {}'.format(table))

                # with ConnectorFactory(self.config).new_connector('databases', 'redshift', None) as conn:

                self.redshift.cur.execute(self.create_stage_tables[table])
                self.redshift.conn.commit()
            return True
        except Exception:
            self.logger.exception('{}: Unable to create stage tables'.format(self.config.job.upper()))
            self.redshift.conn.rollback()
            return False
        finally:
            if not self.redshift.conn.closed:
                self.redshift.close()

    # __create_public_tables
    def __create_public_tables(self):
        self.logger.info('Initialising Avaya public tables')

        try:
            self.redshift.connect()

            for table in self.create_public_tables:
                self.logger.info('table: {}'.format(table))

                # with ConnectorFactory(self.config).new_connector('databases', 'redshift', None) as conn:

                self.redshift.cur.execute(self.create_public_tables[table])
                self.redshift.conn.commit()
            return True
        except Exception:
            self.logger.exception('{}: Unable to create public tables'.format(self.config.job.upper()))
            self.redshift.conn.rollback()
            return False
        finally:
            if not self.redshift.conn.closed:
                self.redshift.close()

    # __truncate_stage_tables
    def __truncate_stage_tables(self):
        self.logger.info('Truncating Avaya stage tables')

        try:
            self.redshift.connect()

            for table in self.truncate_stage_tables:
                self.logger.info('table: {}'.format(table))

                # with ConnectorFactory(self.config).new_connector('databases', 'redshift', None) as conn:

                self.redshift.cur.execute(self.truncate_stage_tables[table])
                self.redshift.conn.commit()
            return True
        except Exception:
            self.logger.exception('{}: Unable to truncate stage tables'.format(self.job.config.upper()))
            self.redshift.conn.rollback()
            return False
        finally:
            if not self.redshift.conn.closed:
                self.redshift.close()

    # __truncate_public_tables
    def __truncate_public_tables(self):
        self.logger.info('Truncating Avaya public table')

        try:
            self.redshift.connect()

            for table in self.truncate_public_tables:
                self.logger.info('table: {}'.format(table))

                # with ConnectorFactory(self.config).new_connector('databases', 'redshift', None) as conn:

                self.redshift.cur.execute(self.truncate_public_tables[table])
                self.redshift.conn.commit()
            return True
        except Exception:
            self.logger.exception('{}: Unable to truncate public tables'.format(self.config.job.upper()))
            self.redshift.conn.rollback()
            return False
        finally:
            if not self.redshift.conn.closed:
                self.redshift.close()

    # __insert_table_stage
    def __insert_table_stage(self, table_name_stage, file_name):
        self.logger.info('Inserting data into staging table')

        # with ConnectorFactory(self.config).new_connector('databases', 'redshift', None) as conn:
        cmd = self.redshift_copy_cmd.format(
            table=table_name_stage,
            bucket=self.bucket_data,
            prefix=self.prefix_public,
            file=file_name,
            iam_role=self.redshift_copy_cmd_iam_role,
            delimiter=self.redshift_copy_cmd_delimiter
        )

        try:
            self.logger.info('Copying into {table} from {filename}'.format(
                table=table_name_stage,
                filename=self.bucket_data_http + self.bucket_data + '/' + self.prefix_public + file_name
            ))
            self.redshift.cur.execute(cmd)
            self.redshift.conn.commit()
            return True
        except Exception:
            self.logger.exception('{}: Unable to insert into stage table'.format(self.config.job.upper()))
            self.redshift.conn.rollback()
            return False

    # __insert_table_public
    def __insert_table_public(self, gf):
        self.logger.info('Inserting data into public table')

        # with ConnectorFactory(self.config).new_connector('databases', 'redshift', None) as conn:
        # for gf in self.job_config['get_data']:
        stage_table = gf['source']['stage_table']
        public_table = gf['source']['public_table']
        table_origin = gf['source']['location']
        cmd = self.stage_to_public_sql.format(
            stage_table=stage_table,
            public_table=public_table,
            http=self.bucket_data_http,
            bucket=self.bucket_data,
            prefix=self.prefix_public,
            table_origin=table_origin,
        )  # TODO: AVAYA consider using copy cmd with prefix and load all files in that prefix in parallel. Test run gave 55sec for parallel copy and 10min for current copy logic
        # http://docs.aws.amazon.com/redshift/latest/dg/t_loading-tables-from-s3.html

        try:
            self.logger.info('Inserting into {} from {}'.format(public_table, stage_table))
            self.redshift.cur.execute(cmd)
            self.redshift.conn.commit()
            return True
        except Exception:
            self.logger.exception('{}: Unable to insert into public table'.format(self.config.job.upper()))
            self.redshift.conn.rollback()
            return False
