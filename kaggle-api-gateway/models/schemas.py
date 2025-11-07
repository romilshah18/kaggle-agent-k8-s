from pydantic import BaseModel, HttpUrl, Field, ConfigDict
from typing import Optional, Dict, Any
from datetime import datetime
from enum import Enum


class JobStatus(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"


class JobCreate(BaseModel):
    kaggle_url: HttpUrl = Field(..., description="Kaggle competition URL")
    priority: Optional[int] = Field(default=0, description="Job priority")
    resources: Optional[Dict[str, str]] = Field(
        default={"cpu": "1", "memory": "2Gi"},
        description="Resource requests (optimized for local Kind)"
    )


class JobResponse(BaseModel):
    job_id: str
    k8s_job_name: str
    status: JobStatus
    created_at: datetime
    message: str = "Job created successfully"
    
    model_config = ConfigDict(from_attributes=True)


class JobStatusResponse(BaseModel):
    job_id: str
    k8s_job_name: str
    k8s_pod_name: Optional[str] = None
    kaggle_url: str
    competition_name: Optional[str] = None
    status: JobStatus
    created_at: datetime
    queued_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    progress: Optional[str] = None
    resources_requested: Dict[str, Any] = {}
    resources_used: Dict[str, Any] = {}
    job_metadata: Dict[str, Any] = {}
    
    model_config = ConfigDict(from_attributes=True)


class JobDetailResponse(JobStatusResponse):
    submission_path: Optional[str] = None
    error_message: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    timestamp: datetime
    services: Dict[str, str]
    cluster_info: Dict[str, Any]
    pending_jobs: int
    running_jobs: int

