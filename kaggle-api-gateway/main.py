from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from datetime import datetime
from kubernetes import client, config
from kubernetes.client.rest import ApiException
import os
from pathlib import Path
from typing import Optional

from api.models.database import get_db, init_db
from api.models.schemas import (
    JobCreate, JobResponse, JobStatusResponse,
    JobDetailResponse, HealthResponse, JobStatus
)
from api.services.job_service import JobService

# Initialize Kubernetes client
try:
    config.load_incluster_config()
except:
    try:
        config.load_kube_config()
    except:
        print("Warning: Could not load Kubernetes config")

try:
    k8s_batch_v1 = client.BatchV1Api()
    k8s_core_v1 = client.CoreV1Api()
except:
    k8s_batch_v1 = None
    k8s_core_v1 = None
    print("Warning: Kubernetes client not initialized")

# Initialize FastAPI
app = FastAPI(
    title="Kaggle Competition Agent API (K8s Native)",
    description="""
## Production-Grade Autonomous Kaggle Competition Solver

Kubernetes-native architecture with:
* 🎯 K8s Jobs for execution isolation
* 📊 Automatic resource management
* 🚀 Cluster autoscaling
* 📈 Pod-level monitoring
* ⚡ High availability

### Architecture
API → PostgreSQL → Job Controller → K8s Jobs → Agent Pods
    """,
    version="2.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize database on startup
@app.on_event("startup")
async def startup_event():
    init_db()
    print("✓ Database initialized")
    print("✓ Kubernetes client configured")


@app.get("/health", response_model=HealthResponse)
async def health_check(db: Session = Depends(get_db)):
    """Health check with K8s cluster info"""
    
    # Get cluster info
    try:
        if k8s_core_v1:
            # Verify K8s connectivity by listing pods in our namespace
            pods = k8s_core_v1.list_namespaced_pod(namespace="kaggle-agent", limit=1)
            cluster_info = {
                "kubernetes_connected": True,
                "namespace": "kaggle-agent"
            }
            k8s_healthy = True
        else:
            cluster_info = {"error": "K8s client not initialized"}
            k8s_healthy = False
    except Exception as e:
        cluster_info = {"error": f"Cannot connect to K8s API: {str(e)}"}
        k8s_healthy = False
    
    # Get job counts
    job_counts = JobService.count_by_status(db)
    
    return HealthResponse(
        status="healthy" if k8s_healthy else "degraded",
        timestamp=datetime.utcnow(),
        services={
            "api": "healthy",
            "database": "healthy",
            "kubernetes": "healthy" if k8s_healthy else "unhealthy"
        },
        cluster_info=cluster_info,
        pending_jobs=job_counts.get("pending", 0),
        running_jobs=job_counts.get("running", 0)
    )


@app.post("/run", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
async def create_job(
    job_create: JobCreate,
    db: Session = Depends(get_db)
):
    """
    Create a new Kaggle competition job
    
    The job will be picked up by the Job Controller which will create a K8s Job.
    """
    # Validate URL
    url_str = str(job_create.kaggle_url)
    if "kaggle.com/competitions/" not in url_str:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="URL must be a Kaggle competition URL"
        )
    
    # Create job in database (status=PENDING)
    job = JobService.create_job(
        db,
        url_str,
        priority=job_create.priority,
        resources=job_create.resources
    )
    
    return JobResponse(
        job_id=job.job_id,
        k8s_job_name=job.k8s_job_name,
        status=job.status,
        created_at=job.created_at,
        message=f"Job created. K8s Job will be created by controller. Check status at /status/{job.job_id}"
    )


@app.get("/status/{job_id}", response_model=JobStatusResponse)
async def get_job_status(
    job_id: str,
    db: Session = Depends(get_db)
):
    """Get detailed job status including K8s pod information"""
    job = JobService.get_job(db, job_id)
    
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found"
        )
    
    # If job is running, get real-time pod status
    if job.status == JobStatus.RUNNING and job.k8s_pod_name and k8s_core_v1:
        try:
            pod = k8s_core_v1.read_namespaced_pod(
                name=job.k8s_pod_name,
                namespace=job.k8s_namespace
            )
            
            # Update metadata with pod info
            job.job_metadata['pod_phase'] = pod.status.phase
            if pod.status.pod_ip:
                job.job_metadata['pod_ip'] = pod.status.pod_ip
            
        except ApiException:
            pass
    
    return JobStatusResponse(
        job_id=job.job_id,
        k8s_job_name=job.k8s_job_name,
        k8s_pod_name=job.k8s_pod_name,
        kaggle_url=job.kaggle_url,
        competition_name=job.competition_name,
        status=job.status,
        created_at=job.created_at,
        queued_at=job.queued_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        progress=job.job_metadata.get("progress", "No progress information"),
        resources_requested=job.resources_requested,
        resources_used=job.resources_used,
        job_metadata=job.job_metadata
    )


@app.get("/result/{job_id}/submission.csv")
async def get_submission(
    job_id: str,
    db: Session = Depends(get_db)
):
    """Download submission.csv for completed job"""
    job = JobService.get_job(db, job_id)
    
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found"
        )
    
    if job.status != JobStatus.SUCCESS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Job is not complete. Current status: {job.status}"
        )
    
    if not job.submission_path or not Path(job.submission_path).exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission file not found"
        )
    
    return FileResponse(
        path=job.submission_path,
        filename="submission.csv",
        media_type="text/csv"
    )


@app.get("/logs/{job_id}")
async def get_job_logs(
    job_id: str,
    tail_lines: Optional[int] = 1000,
    db: Session = Depends(get_db)
):
    """Get job execution logs from K8s pod"""
    job = JobService.get_job(db, job_id)
    
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found"
        )
    
    if not job.k8s_pod_name:
        return JSONResponse(
            content={"job_id": job_id, "logs": "Pod not yet created"}
        )
    
    if not k8s_core_v1:
        return JSONResponse(
            content={"job_id": job_id, "logs": "K8s client not available"}
        )
    
    try:
        logs = k8s_core_v1.read_namespaced_pod_log(
            name=job.k8s_pod_name,
            namespace=job.k8s_namespace,
            tail_lines=tail_lines
        )
        
        return JSONResponse(
            content={"job_id": job_id, "pod_name": job.k8s_pod_name, "logs": logs}
        )
        
    except ApiException as e:
        if e.status == 404:
            return JSONResponse(
                content={"job_id": job_id, "logs": "Pod not found or not started yet"}
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error fetching logs: {str(e)}"
            )


@app.delete("/jobs/{job_id}")
async def cancel_job(
    job_id: str,
    db: Session = Depends(get_db)
):
    """Cancel a running job by deleting its K8s Job"""
    job = JobService.get_job(db, job_id)
    
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found"
        )
    
    if job.status not in [JobStatus.PENDING, JobStatus.QUEUED, JobStatus.RUNNING]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Job cannot be cancelled in status: {job.status}"
        )
    
    # Delete K8s Job
    if k8s_batch_v1:
        try:
            k8s_batch_v1.delete_namespaced_job(
                name=job.k8s_job_name,
                namespace=job.k8s_namespace,
                propagation_policy='Background'
            )
        except ApiException as e:
            if e.status != 404:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Error deleting K8s Job: {str(e)}"
                )
    
    # Update job status
    JobService.update_job_status(
        db,
        job_id,
        JobStatus.FAILED,
        error_message="Job cancelled by user",
        metadata={"progress": "Cancelled"}
    )
    
    return {"message": "Job cancelled successfully", "job_id": job_id}


@app.get("/jobs")
async def list_jobs(
    status_filter: Optional[JobStatus] = None,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """List all jobs with optional status filter"""
    if status_filter:
        jobs = JobService.get_jobs_by_status(db, status_filter)
    else:
        jobs = JobService.get_recent_jobs(db, limit)
    
    return {
        "total": len(jobs),
        "jobs": [
            JobStatusResponse(
                job_id=job.job_id,
                k8s_job_name=job.k8s_job_name,
                k8s_pod_name=job.k8s_pod_name,
                kaggle_url=job.kaggle_url,
                competition_name=job.competition_name,
                status=job.status,
                created_at=job.created_at,
                queued_at=job.queued_at,
                started_at=job.started_at,
                completed_at=job.completed_at,
                progress=job.job_metadata.get("progress"),
                resources_requested=job.resources_requested,
                resources_used=job.resources_used,
                job_metadata=job.job_metadata
            )
            for job in jobs
        ]
    }


@app.get("/cluster/nodes")
async def get_cluster_nodes():
    """Get information about cluster nodes"""
    if not k8s_core_v1:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="K8s client not available"
        )
    
    try:
        nodes = k8s_core_v1.list_node()
        
        node_info = []
        for node in nodes.items:
            node_info.append({
                "name": node.metadata.name,
                "status": node.status.conditions[-1].type if node.status.conditions else "Unknown",
                "capacity": {
                    "cpu": node.status.capacity.get('cpu'),
                    "memory": node.status.capacity.get('memory'),
                    "pods": node.status.capacity.get('pods')
                },
                "allocatable": {
                    "cpu": node.status.allocatable.get('cpu'),
                    "memory": node.status.allocatable.get('memory'),
                    "pods": node.status.allocatable.get('pods')
                },
                "labels": node.metadata.labels
            })
        
        return {"total_nodes": len(node_info), "nodes": node_info}
        
    except ApiException as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching cluster nodes: {str(e)}"
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

