import logging
from kubernetes import client
from kubernetes.client.rest import ApiException
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import os

logger = logging.getLogger(__name__)


class JobCleaner:
    def __init__(self, batch_v1: client.BatchV1Api, core_v1: client.CoreV1Api):
        self.batch_v1 = batch_v1
        self.core_v1 = core_v1
        self.namespace = os.getenv("K8S_NAMESPACE", "kaggle-agent")
    
    def cleanup(self, db: Session, retention_hours: int = 24):
        """Clean up old completed K8s Jobs"""
        cutoff_time = datetime.utcnow() - timedelta(hours=retention_hours)
        
        try:
            jobs = self.batch_v1.list_namespaced_job(
                namespace=self.namespace,
                label_selector="app=kaggle-agent"
            )
            
            cleaned = 0
            
            for k8s_job in jobs.items:
                if not k8s_job.status.completion_time:
                    continue
                
                completion_time = k8s_job.status.completion_time
                if completion_time > cutoff_time:
                    continue
                
                try:
                    self.batch_v1.delete_namespaced_job(
                        name=k8s_job.metadata.name,
                        namespace=self.namespace,
                        propagation_policy='Background'
                    )
                    cleaned += 1
                except ApiException as e:
                    if e.status != 404:
                        logger.error(f"Error deleting job: {e}")
            
            if cleaned > 0:
                logger.info(f"✓ Cleaned up {cleaned} old K8s Jobs")
            
        except ApiException as e:
            logger.error(f"K8s API error in job cleaner: {e}")

