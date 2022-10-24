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
from rtech.job.job import Job
from rtech.job.eptica.job_eptica_s3 import EpticaS3Job
from rtech.job.eptica.job_eptica_redshift import EpticaRedShiftJob
from rtech.job.expert.job_expert_s3 import ExpertS3Job
from rtech.job.expert.job_expert_redshift import ExpertRedShiftJob
from rtech.job.avaya.job_avaya_s3 import AvayaS3Job
from rtech.job.avaya.job_avaya_redshift import AvayaRedShiftJob
from rtech.job.avaya_call_detail.job_avaya_call_detail_s3 import AvayaCallDetailS3Job
from rtech.job.avaya_call_detail.job_avaya_call_detail_redshift import AvayaCallDetailRedshiftJob


class JobFactory(Job):
    def __init__(self, config): # TODO: This will prevent multiple initialisations of Job/ObjectContainer objects.
        self.config = config

    # _____________________________________________________________________
    # new_job
    def new_job(self, job_type, job_config):

        if job_type == 'eptica_s3':
            return EpticaS3Job(self.config, job_config)

        if job_type == 'eptica_redshift':
            return EpticaRedShiftJob(self.config, job_config)

        if job_type == 'expert_s3':
            return ExpertS3Job(self.config, job_config)

        if job_type == 'expert_redshift':
            return ExpertRedShiftJob(self.config, job_config)

        if job_type == 'avaya_s3':
            return AvayaS3Job(self.config, job_config)

        if job_type == 'avaya_redshift':
            return AvayaRedShiftJob(self.config, job_config)

        if job_type == 'avaya_call_detail_s3':
            return AvayaCallDetailS3Job(self.config, job_config)

        if job_type == 'avaya_call_detail_redshift':
            return AvayaCallDetailRedshiftJob(self.config, job_config)

        else:
            return None
