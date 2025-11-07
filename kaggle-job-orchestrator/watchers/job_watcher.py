import logging
from kubernetes import client
from kubernetes.client.rest import ApiException
from sqlalchemy.orm import Session
import os

logger = logging.getLogger(__name__)


class JobWatcher:
    def __init__(self, batch_v1: client.BatchV1Api):
        self.batch_v1 = batch_v1
        self.namespace = os.getenv("K8S_NAMESPACE", "kaggle-agent")
    
    def sync_jobs(self, db: Session):
        """Watch K8s Jobs and sync their status to database"""
        from api.services.job_service import JobService
        from api.models.schemas import JobStatus
        
        try:
            jobs = self.batch_v1.list_namespaced_job(
                namespace=self.namespace,
                label_selector="app=kaggle-agent"
            )
            
            for k8s_job in jobs.items:
                job_name = k8s_job.metadata.name
                job_id = k8s_job.metadata.labels.get('job-id')
                
                if not job_id:
                    continue
                
                db_job = JobService.get_job(db, job_id)
                if not db_job:
                    continue
                
                self._sync_job_status(db, db_job, k8s_job)
            
        except ApiException as e:
            logger.error(f"K8s API error in job watcher: {e}")
        except Exception as e:
            logger.error(f"Error in job watcher: {e}", exc_info=True)
    
    def _sync_job_status(self, db: Session, db_job, k8s_job):
        """Sync individual job status"""
        from api.services.job_service import JobService
        from api.models.schemas import JobStatus
        
        job_status = k8s_job.status
        new_status = None
        error_message = None
        metadata_update = {}
        
        # Job succeeded
        if job_status.succeeded and job_status.succeeded > 0:
            if db_job.status != JobStatus.SUCCESS:
                new_status = JobStatus.SUCCESS
                metadata_update['progress'] = "Job completed successfully"
        
        # Job failed
        elif job_status.failed and job_status.failed > 0:
            if db_job.status not in [JobStatus.FAILED, JobStatus.TIMEOUT]:
                new_status = JobStatus.FAILED
                error_message = f"K8s Job failed after {job_status.failed} attempts"
                metadata_update['progress'] = "Job failed"
        
        # Job active (running)
        elif job_status.active and job_status.active > 0:
            if db_job.status != JobStatus.RUNNING:
                new_status = JobStatus.RUNNING
                metadata_update['progress'] = "Pod is running"
        
        # Update if status changed
        if new_status:
            JobService.update_job_status(
                db, db_job.job_id, new_status,
                error_message=error_message,
                metadata=metadata_update
            )
            db.commit()

