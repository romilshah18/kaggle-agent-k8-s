import time
import logging
import signal
import sys
from kubernetes import client, config
from sqlalchemy.orm import Session

from controller.watchers.job_watcher import JobWatcher
from controller.watchers.pod_watcher import PodWatcher
from controller.handlers.job_creator import JobCreator
from controller.handlers.job_cleaner import JobCleaner
from api.models.database import SessionLocal, init_db

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


class JobController:
    def __init__(self):
        # Initialize K8s client
        try:
            config.load_incluster_config()
            logger.info("✓ Loaded in-cluster K8s config")
        except:
            config.load_kube_config()
            logger.info("✓ Loaded kubeconfig")
        
        self.batch_v1 = client.BatchV1Api()
        self.core_v1 = client.CoreV1Api()
        
        # Initialize database
        init_db()
        logger.info("✓ Database initialized")
        
        # Initialize handlers
        self.job_creator = JobCreator(self.batch_v1, self.core_v1)
        self.job_cleaner = JobCleaner(self.batch_v1, self.core_v1)
        
        # Initialize watchers
        self.job_watcher = JobWatcher(self.batch_v1)
        self.pod_watcher = PodWatcher(self.core_v1)
        
        self.running = True
        
        signal.signal(signal.SIGINT, self.shutdown)
        signal.signal(signal.SIGTERM, self.shutdown)
    
    def shutdown(self, signum, frame):
        logger.info(f"Received signal {signum}, shutting down...")
        self.running = False
    
    def process_pending_jobs(self, db: Session):
        """Check for PENDING jobs and create K8s Jobs"""
        from api.services.job_service import JobService
        from api.models.schemas import JobStatus
        
        pending_jobs = JobService.get_pending_jobs(db, limit=50)
        
        if not pending_jobs:
            return
        
        logger.info(f"Found {len(pending_jobs)} pending jobs")
        
        for job in pending_jobs:
            try:
                k8s_job = self.job_creator.create_job(job)
                
                if k8s_job:
                    JobService.update_job_status(
                        db, job.job_id, JobStatus.QUEUED,
                        metadata={"progress": "K8s Job created"}
                    )
                    
            except Exception as e:
                logger.error(f"Error processing job {job.job_id}: {e}")
                JobService.update_job_status(
                    db, job.job_id, JobStatus.FAILED,
                    error_message=f"Controller error: {str(e)}"
                )
    
    def sync_k8s_jobs(self, db: Session):
        """Sync K8s Job status back to database"""
        self.job_watcher.sync_jobs(db)
    
    def sync_pods(self, db: Session):
        """Sync Pod status and extract results"""
        self.pod_watcher.sync_pods(db)
    
    def cleanup_old_jobs(self, db: Session):
        """Clean up completed K8s Jobs"""
        self.job_cleaner.cleanup(db, retention_hours=24)
    
    def run(self):
        """Main controller loop"""
        logger.info("="*60)
        logger.info("KAGGLE AGENT JOB CONTROLLER STARTED")
        logger.info("="*60)
        
        iteration = 0
        
        while self.running:
            try:
                iteration += 1
                
                db = SessionLocal()
                
                try:
                    # Process pending jobs
                    self.process_pending_jobs(db)
                    
                    # Sync K8s Job status
                    self.sync_k8s_jobs(db)
                    
                    # Sync Pod status
                    self.sync_pods(db)
                    
                    # Cleanup old jobs
                    if iteration % 10 == 0:
                        self.cleanup_old_jobs(db)
                    
                    db.commit()
                    
                except Exception as e:
                    logger.error(f"Error in controller loop: {e}", exc_info=True)
                    db.rollback()
                
                finally:
                    db.close()
                
                time.sleep(5)
                
            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"Unexpected error: {e}", exc_info=True)
                time.sleep(10)
        
        logger.info("Controller stopped")


if __name__ == "__main__":
    controller = JobController()
    controller.run()

