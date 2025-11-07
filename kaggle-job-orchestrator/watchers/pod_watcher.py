import logging
from kubernetes import client
from kubernetes.client.rest import ApiException
from sqlalchemy.orm import Session
from pathlib import Path
import os

logger = logging.getLogger(__name__)


class PodWatcher:
    def __init__(self, core_v1: client.CoreV1Api):
        self.core_v1 = core_v1
        self.namespace = os.getenv("K8S_NAMESPACE", "kaggle-agent")
        self.shared_storage_path = "/shared/submissions"
    
    def sync_pods(self, db: Session):
        """Watch Pods and extract results when completed"""
        from api.services.job_service import JobService
        from api.models.schemas import JobStatus
        
        try:
            pods = self.core_v1.list_namespaced_pod(
                namespace=self.namespace,
                label_selector="app=kaggle-agent"
            )
            
            for pod in pods.items:
                job_id = pod.metadata.labels.get('job-id')
                if not job_id:
                    continue
                
                db_job = JobService.get_job(db, job_id)
                if not db_job:
                    continue
                
                # Update pod name if not set
                if not db_job.k8s_pod_name:
                    JobService.update_job_status(
                        db, job_id, db_job.status,
                        k8s_pod_name=pod.metadata.name
                    )
                    db.commit()
                
                phase = pod.status.phase
                
                if phase == "Running":
                    self._handle_running_pod(db, db_job, pod)
                elif phase == "Succeeded":
                    self._handle_succeeded_pod(db, db_job, pod)
                elif phase == "Failed":
                    self._handle_failed_pod(db, db_job, pod)
            
        except ApiException as e:
            logger.error(f"K8s API error in pod watcher: {e}")
        except Exception as e:
            logger.error(f"Error in pod watcher: {e}", exc_info=True)
    
    def _handle_running_pod(self, db: Session, db_job, pod):
        """Handle pod in Running phase"""
        from api.services.job_service import JobService
        from api.models.schemas import JobStatus
        
        if db_job.status != JobStatus.RUNNING:
            JobService.update_job_status(
                db, db_job.job_id, JobStatus.RUNNING,
                metadata={"progress": "Agent is executing"}
            )
            db.commit()
    
    def _handle_succeeded_pod(self, db: Session, db_job, pod):
        """Handle pod that succeeded"""
        from api.services.job_service import JobService
        from api.models.schemas import JobStatus
        
        if db_job.status == JobStatus.SUCCESS and db_job.submission_path:
            return
        
        submission_path = self._find_submission_file(db_job.job_id)
        
        if submission_path:
            JobService.update_job_status(
                db, db_job.job_id, JobStatus.SUCCESS,
                metadata={"progress": "Completed successfully"}
            )
            JobService.set_submission_path(db, db_job.job_id, submission_path)
            db.commit()
        else:
            JobService.update_job_status(
                db, db_job.job_id, JobStatus.FAILED,
                error_message="No submission.csv generated"
            )
            db.commit()
    
    def _handle_failed_pod(self, db: Session, db_job, pod):
        """Handle pod that failed"""
        from api.services.job_service import JobService
        from api.models.schemas import JobStatus
        
        if db_job.status in [JobStatus.FAILED, JobStatus.TIMEOUT]:
            return
        
        error_message = "Pod failed"
        container_statuses = pod.status.container_statuses
        
        if container_statuses:
            terminated = container_statuses[0].state.terminated
            if terminated:
                error_message = f"Exit code {terminated.exit_code}: {terminated.reason}"
        
        status = JobStatus.TIMEOUT if "DeadlineExceeded" in error_message else JobStatus.FAILED
        
        JobService.update_job_status(
            db, db_job.job_id, status,
            error_message=error_message
        )
        db.commit()
    
    def _find_submission_file(self, job_id: str) -> str:
        """Find submission.csv in shared storage"""
        job_output_dir = Path(self.shared_storage_path) / job_id
        submission_file = job_output_dir / "submission.csv"
        
        if submission_file.exists():
            return str(submission_file)
        
        return None

