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

import io
import sys
import time
import boto3
import logging
import urllib.request
import zipfile

from rtech.job.job import Job



class EpticaS3Job(Job):
    # _____________________________________________________________________
    # __init__
    def __init__(self, config, job_config):
        super(EpticaS3Job, self).__init__(config)

        self.logger.info('Initializing EpticaS3Job ...')

        self.job_config    = job_config
        self.bucket_data   = job_config['config']['bucket_data']
        self.bucket_conf   = job_config['config']['bucket_conf']
        self.prefix_conf   = job_config['config']['prefix_conf']
        self.prefix_raw    = job_config['config']['prefix_raw']
        self.prefix_stage  = job_config['config']['prefix_stage']
        self.prefix_public = job_config['config']['prefix_public']

        self.s3_client     = boto3.client('s3')
        self.s3_resource   = boto3.resource('s3')

        # To have boto3 less verbose in our log files
        logging.getLogger('boto3').setLevel(logging.CRITICAL)

    # _____________________________________________________________________
    # run
    def run(self):

        for gf in self.job_config['get_files']:

            url       = gf['source']['location']
            instance  = gf['source']['instance']
            is_active = gf['is_active']

            # Only import active data sources
            if is_active == 1:
                self.logger.info('')
                #filename = time.strftime("%Y%m%d-%H%M%S") + url.split('/')[-1]
                filename = url.split('/')[-1]
                data = self.__download_file(url)
                self.__move_to_s3_raw(filename, self.bucket_data, data)
                self.__unzip_to_s3_stage(filename, self.bucket_data, instance)
                self.__delete_public_instance_content(self.bucket_data, instance)
                self.__move_to_s3_public(self.bucket_data, instance)
                #self.__create_public_timestamp_file(self.bucket_data, instance)

    # _____________________________________________________________________
    # __download_file
    def __download_file(self, url):
        self.logger.debug('Downloading ' + url)
        self.logger.info ('Downloading ' + url.split('/')[-1])

        return urllib.request.urlopen(url).read()

    # _____________________________________________________________________
    # __move_to_s3_raw
    def __move_to_s3_raw(self, file, bucket, data):
        try:
            self.logger.info('Moving to S3 raw')
            self.s3_resource.Bucket(bucket).put_object(Key = self.prefix_raw + file, Body=data)
        except Exception as e:
            self.logger.error('{} Unable to move to S3 raw'.format(self.config.job.upper()))
            self.logger.error(e)
            sys.exit(1)

        return True

    # _____________________________________________________________________
    # __unzip_to_s3_stage
    def __unzip_to_s3_stage(self, file, bucket, instance):
        try:
            self.logger.info('Unzipping')
            obj = self.s3_client.get_object(Bucket = bucket, Key = self.prefix_raw + file)
            put_objects = []
            with io.BytesIO(obj['Body'].read()) as tf:
                # Rewind the file
                tf.seek(0)
                # Read the file as a zip file and process the members
                with zipfile.ZipFile(tf, mode='r') as zipf:
                    for f in zipf.infolist():
                        putFile = self.s3_client.put_object(
                            Bucket = bucket,
                            Key    = self.prefix_stage + instance + '/' + f.filename,
                            Body   = zipf.read(f))
                        put_objects.append(putFile)

                        # Applying public read policy to unzipped files
                        object_acl = self.s3_resource.ObjectAcl(bucket, self.prefix_stage + instance + '/' + f.filename)
                        object_acl.put(ACL = 'public-read')
        except Exception as e:
            self.logger.error('{} Unable to unzip to S3 stage'.format(self.config.job.upper()))
            self.logger.error(e)
            sys.exit(1)

        return True

    # _____________________________________________________________________
    # __delete_public_bucket_instance_content
    def __delete_public_instance_content(self, bucket, instance):
        self.logger.info('Deleting S3 public ' + instance)
        try:
            bucket = self.s3_resource.Bucket(bucket)
            for obj in bucket.objects.filter(Prefix = self.prefix_public + instance):
                self.s3_resource.Object(bucket.name, obj.key).delete()
        except Exception as e:
            self.logger.error('{} Unable to unable to delete S3 public'.format(self.config.job.upper()))
            self.logger.error(e)
            sys.exit(1)

        return True

    # _____________________________________________________________________
    # __move_to_s3_public
    def __move_to_s3_public(self, bucket, instance):
        self.logger.info('Moving to S3 public')
        try:
            for stp in self.job_config['staging_to_public']:
                file_name = stp['file_name']
                is_active = stp['is_active']

                if is_active == 1:
                    tmp_bucket = self.s3_resource.Bucket(bucket)
                    for obj in tmp_bucket.objects.filter(Prefix = self.prefix_stage + instance + '/' + file_name):
                        # copy from
                        copy_source = {'Bucket': bucket, 'Key': self.prefix_stage + instance + '/' + file_name}
                        # copy to
                        self.s3_resource.meta.client.copy(
                            copy_source,
                            bucket,
                            self.prefix_public + instance + '/' + file_name)
                        object_acl = self.s3_resource.ObjectAcl(bucket, self.prefix_public + instance + '/' + file_name)
                        object_acl.put(ACL = 'public-read')
        except Exception as e:
            self.logger.error('{} Unable to move to S3 public'.format(self.config.job.upper()))
            self.logger.error(e)
            sys.exit(1)

        return True

    # _____________________________________________________________________
    # __create_public_timestamp_file
    def __create_public_timestamp_file(self, bucket, instance):
        self.logger.info('Creating S3 public ' + instance + ' timestamp file')
        try:
            timestamp = time.strftime("%Y%m%d-%H%M%S")
            tmp_bucket = self.s3_resource.Bucket(bucket)
            n = 0
            for obj in tmp_bucket.objects.filter(Prefix = self.prefix_public + instance):
                n += 1

            self.s3_client.put_object(
                Bucket = bucket,
                Body   = '',
                Key    = self.prefix_public + instance + '/' + str(n) + '_files_copied_' + timestamp + '.txt')
        except Exception as e:
            self.logger.error('{} Unable to create S3 public {} timestamp file'.format(self.config.job.upper(),instance))
            self.logger.error(e)
            sys.exit(1)

        return True
