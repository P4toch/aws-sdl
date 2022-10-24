import logging
import uuid
from datetime import datetime
from io import BytesIO

from rtech.connector.connector_factory import ConnectorFactory
from rtech.job.job import Job

import boto3


class AvayaCallDetailS3Job(Job):
    def __init__(self, config, job_config):
        super(AvayaCallDetailS3Job, self).__init__(config)

        self.logger.info('Initializing AvayaCallDetailS3Job ...')

        self.job_config = job_config
        self.bucket_data = job_config['config']['bucket_data']
        self.bucket_conf = job_config['config']['bucket_conf']
        self.prefix_conf = job_config['config']['prefix_conf']
        self.prefix_raw = job_config['config']['prefix_raw']
        self.prefix_stage = job_config['config']['prefix_stage']
        self.prefix_public = job_config['config']['prefix_public']

        self.s3_client = boto3.client('s3')
        self.s3_resource = boto3.resource('s3')

        # To have boto3 less verbose in our log files
        logging.getLogger('boto3').setLevel(logging.CRITICAL)

        # To have smb less verbose in our log files
        logging.getLogger('SMB.SMBConnection').setLevel(logging.CRITICAL)

        # To have smart_open less verbose in our log files
        logging.getLogger('smart_open').setLevel(logging.CRITICAL)

    def run(self):
        self.logger.info('')

        uniqeid = uuid.uuid4().hex

        for gf in self.job_config['get_data']:
            prefix_stage = f"{self.prefix_stage}{gf['source']['location']}/{uniqeid}/files/"
            self.__get_data(gf, prefix_stage)
            self.__copy_to_s3_raw_and_public(gf, prefix_stage)

            if self.config.environment.upper() == 'CORP':
                self.__delete_files_from_source(gf, prefix_stage)

        self.__store_uniqeid(uniqeid)

    def __get_data(self, gf, prefix_stage):
        service_name = gf['source']['service_name']
        path = gf['source']['path']
        pattern = gf['source']['pattern']
        share_name = gf['source']['share_name']

        with ConnectorFactory(self.config).new_connector('file_shares', share_name, None) as conn:
            self.logger.info(
                'Moving data from {type}://{server}/{service_name}/{path}/ to {stage}'.format(
                    type=conn.type,
                    server=conn.server,
                    service_name=service_name,
                    path=path,
                    stage=prefix_stage
                ))

            r = conn.conn.listPath(service_name=service_name, path=path, pattern=pattern)

            get_files_from_share = [x.filename for x in r]
            total_file_count = len(r)
            get_file_count = len(get_files_from_share)
            file_count = 0

            try:
                for i in get_files_from_share:
                    file_name = i

                    data = BytesIO()
                    attr, written_bytes = conn.conn.retrieveFile(
                        service_name=service_name,
                        path=path + "/" + file_name,
                        file_obj=data
                    )
                    data.seek(0)

                    key = f"{prefix_stage}{file_name}"

                    self.logger.debug(key)

                    self.s3_resource.Bucket(self.bucket_data).put_object(Key=key, Body=data, ServerSideEncryption='AES256')

                    data.close()

                    self.logger.debug('Moving {type}://{server}/{service_name}/{path}/{file} to {destination}'.format(
                            type=conn.type,
                            server=conn.server,
                            service_name=service_name,
                            path=path,
                            file=file_name,
                            destination=key
                        )
                    )

                    file_count += 1

                self.logger.info('Moved {} out of {} new files (total number of files on share: {})'.format(file_count, get_file_count, total_file_count))

            except Exception:
                self.logger.exception('{}: Failed while moving files to s3 stage'.format(self.config.job.upper()))

    def __delete_files_from_source(self, gf, prefix_stage):
        service_name = gf['source']['service_name']
        path = gf['source']['path']
        share_name = gf['source']['share_name']

        file_list = list(self.__get_file_list_from_prefix(self.bucket_data, prefix_stage))

        to_delete_count = len(file_list)
        delete_count = 0

        with ConnectorFactory(self.config).new_connector('file_shares', share_name, None) as conn:
            for file in file_list:
                file_name = file.key.split('/')[-1]
                conn.conn.deleteFiles(
                    service_name=service_name,
                    path_file_pattern=path + '/' + file_name
                )

                self.logger.debug('Deleting {type}://{server}/{service_name}/{path}/{file}'.format(
                        type=conn.type,
                        server=conn.server,
                        service_name=service_name,
                        path=path,
                        file=file_name
                    )
                )

                delete_count += 1
        self.logger.info('Deleted {} out of {} files from source'.format(delete_count, to_delete_count))

    def __copy_to_s3_raw_and_public(self, gf, prefix_stage):
        try:
            self.logger.info(f"Copying files from {prefix_stage} to raw and public")
            load_date = datetime.now()

            prefix_raw = self.prefix_raw + gf['source']['location'] + '/' + str(load_date.year) + '/' + str(load_date.month) + '/' + str(load_date.day) + '/'
            prefix_public = self.prefix_public + gf['source']['location'] + '/' + str(load_date.year) + '/' + str(load_date.month) + '/' + str(load_date.day) + '/'

            file_list = self.__get_file_list_from_prefix(self.bucket_data, prefix_stage)

            for obj in file_list:
                file_name = obj.key.split('/')[-1]
                try:
                    copy_source = {'Bucket': obj.bucket_name, 'Key': obj.key}
                    self.__copy_file_between_buckets(copy_source, obj.bucket_name, prefix_raw + file_name)
                    self.__copy_file_between_buckets(copy_source, obj.bucket_name, prefix_public + file_name)
                except Exception:
                    self.logger.exception('{}: Unable to copy file s3://{}/{}{} to raw and public'.format(self.config.job.upper(), self.bucket_data, prefix_stage, file_name))
        except Exception:
            self.logger.exception('{}: Something went wrong while copying data from S3 stage to S3 raw and public'.format(self.config.job.upper()))
            return None

    def __get_file_list_from_prefix(self, bucket, prefix):
        try:
            bucket = self.s3_resource.Bucket(bucket)
            return bucket.objects.filter(Prefix=prefix)
        except Exception:
            self.logger.exception('Unable to get file list from s3://{}/{}'.format(bucket, prefix))

    def __copy_file_between_buckets(self, copy_source, bucket, key):
        try:
            self.s3_resource.meta.client.copy(copy_source, bucket, key)
        except Exception:
            self.logger.exception('Unable to copy file to s3://{}/{}'.format(bucket, key))

    def __store_uniqeid(self, uniqeid):
        file = '/tmp/avaya_call_detail_uniqeid.txt'
        try:
            self.logger.info(f'Storing unique-id {uniqeid} in {file}')
            with open(file, 'w') as uniqe_file:
                uniqe_file.write(uniqeid)
        except Exception:
            self.logger.exception(f'Unable to store uniqeid in {file}')
