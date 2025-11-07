from sqlalchemy import create_engine, Column, String, DateTime, Text, JSON, Integer
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import os

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://kaggle_user:password@postgres:5432/kaggle_agent"
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=10, max_overflow=20)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class Job(Base):
    __tablename__ = "jobs"
    
    job_id = Column(String(36), primary_key=True, index=True)
    kaggle_url = Column(Text, nullable=False)
    competition_name = Column(String(255), index=True)
    
    # K8s specific fields
    k8s_job_name = Column(String(255), index=True, unique=True)
    k8s_namespace = Column(String(63), default="kaggle-agent")
    k8s_pod_name = Column(String(255))
    
    status = Column(String(20), nullable=False, index=True, default="pending")
    # Status: pending, queued, running, success, failed, timeout
    
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    queued_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    
    submission_path = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    
    # Resource usage tracking
    resources_requested = Column(JSON, default=dict)
    resources_used = Column(JSON, default=dict)
    
    job_metadata = Column(JSON, default=dict)
    
    def __repr__(self):
        return f"<Job {self.job_id} - {self.status}>"


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    Base.metadata.create_all(bind=engine)

