from sqlalchemy.orm import Session
from sqlalchemy import func
from api.models.database import Job
from api.models.schemas import JobStatus
from typing import Optional, List, Dict
from datetime import datetime
import uuid
import re


class JobService:
    @staticmethod
    def create_job(
        db: Session,
        kaggle_url: str,
        priority: int = 0,
        resources: dict = None
    ) -> Job:
        job_id = str(uuid.uuid4())
        
        # Extract competition name from URL
        competition_name = kaggle_url.rstrip('/').split('/')[-1]
        
        # Create K8s-compliant job name
        k8s_job_name = f"kaggle-{competition_name[:40]}-{job_id[:8]}".lower()
        k8s_job_name = re.sub(r'[^a-z0-9-]', '-', k8s_job_name)
        k8s_job_name = k8s_job_name.strip('-')[:63]
        
        # Default resources (optimized for Kind/local development)
        if resources is None:
            resources = {"cpu": "1", "memory": "2Gi"}
        
        job = Job(
            job_id=job_id,
            kaggle_url=kaggle_url,
            competition_name=competition_name,
            k8s_job_name=k8s_job_name,
            k8s_namespace="kaggle-agent",
            status=JobStatus.PENDING,
            created_at=datetime.utcnow(),
            resources_requested=resources,
            job_metadata={
                "progress": "Job created, awaiting controller",
                "priority": priority
            }
        )
        
        db.add(job)
        db.commit()
        db.refresh(job)
        
        return job
    
    @staticmethod
    def get_job(db: Session, job_id: str) -> Optional[Job]:
        return db.query(Job).filter(Job.job_id == job_id).first()
    
    @staticmethod
    def get_job_by_k8s_name(db: Session, k8s_job_name: str) -> Optional[Job]:
        return db.query(Job).filter(Job.k8s_job_name == k8s_job_name).first()
    
    @staticmethod
    def update_job_status(
        db: Session,
        job_id: str,
        status: JobStatus,
        k8s_pod_name: Optional[str] = None,
        error_message: Optional[str] = None,
        metadata: Optional[dict] = None,
        resources_used: Optional[dict] = None
    ) -> Optional[Job]:
        job = JobService.get_job(db, job_id)
        if not job:
            return None
        
        job.status = status
        
        if status == JobStatus.QUEUED and not job.queued_at:
            job.queued_at = datetime.utcnow()
        
        if status == JobStatus.RUNNING and not job.started_at:
            job.started_at = datetime.utcnow()
        
        if status in [JobStatus.SUCCESS, JobStatus.FAILED, JobStatus.TIMEOUT]:
            job.completed_at = datetime.utcnow()
        
        if k8s_pod_name:
            job.k8s_pod_name = k8s_pod_name
        
        if error_message:
            job.error_message = error_message
        
        if metadata:
            job.job_metadata.update(metadata)
        
        if resources_used:
            job.resources_used = resources_used
        
        db.commit()
        db.refresh(job)
        
        return job
    
    @staticmethod
    def set_submission_path(db: Session, job_id: str, path: str):
        job = JobService.get_job(db, job_id)
        if job:
            job.submission_path = path
            db.commit()
    
    @staticmethod
    def get_pending_jobs(db: Session, limit: int = 100) -> List[Job]:
        """Get jobs awaiting K8s Job creation"""
        from sqlalchemy import desc, cast, Integer as SQLInteger, func
        return db.query(Job).filter(
            Job.status == JobStatus.PENDING
        ).order_by(
            desc(cast(Job.job_metadata['priority'].as_string(), SQLInteger)),
            Job.created_at
        ).limit(limit).all()
    
    @staticmethod
    def get_jobs_by_status(db: Session, status: JobStatus) -> List[Job]:
        return db.query(Job).filter(Job.status == status).all()
    
    @staticmethod
    def get_recent_jobs(db: Session, limit: int = 100) -> List[Job]:
        return db.query(Job).order_by(Job.created_at.desc()).limit(limit).all()
    
    @staticmethod
    def count_by_status(db: Session) -> Dict[str, int]:
        results = db.query(
            Job.status,
            func.count(Job.job_id)
        ).group_by(Job.status).all()
        return {status: count for status, count in results}

