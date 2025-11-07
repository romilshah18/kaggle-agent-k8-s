import logging
from kubernetes import client
from kubernetes.client.rest import ApiException
import os

logger = logging.getLogger(__name__)


class JobCreator:
    def __init__(self, batch_v1: client.BatchV1Api, core_v1: client.CoreV1Api):
        self.batch_v1 = batch_v1
        self.core_v1 = core_v1
        self.namespace = os.getenv("K8S_NAMESPACE", "kaggle-agent")
        self.agent_image = os.getenv("AGENT_IMAGE", "kaggle-agent/agent:latest")
    
    def create_job(self, db_job) -> bool:
        """
        Create a K8s Job for the given database job
        
        Args:
            db_job: Job object from database
            
        Returns:
            bool: True if job created successfully
        """
        try:
            # Check if job already exists
            try:
                existing = self.batch_v1.read_namespaced_job(
                    name=db_job.k8s_job_name,
                    namespace=self.namespace
                )
                logger.warning(f"K8s Job {db_job.k8s_job_name} already exists")
                return True
            except ApiException as e:
                if e.status != 404:
                    raise
            
            # Create ConfigMap for job-specific data
            self._create_config_map(db_job)
            
            # Create K8s Job manifest
            job_manifest = self._build_job_manifest(db_job)
            
            # Create the job
            created_job = self.batch_v1.create_namespaced_job(
                namespace=self.namespace,
                body=job_manifest
            )
            
            logger.info(f"✓ Created K8s Job: {db_job.k8s_job_name}")
            return True
            
        except ApiException as e:
            logger.error(f"K8s API error creating job {db_job.k8s_job_name}: {e}")
            return False
        except Exception as e:
            logger.error(f"Error creating job {db_job.k8s_job_name}: {e}", exc_info=True)
            return False
    
    def _create_config_map(self, db_job):
        """Create ConfigMap with job-specific configuration"""
        config_map = client.V1ConfigMap(
            metadata=client.V1ObjectMeta(
                name=f"{db_job.k8s_job_name}-config",
                namespace=self.namespace,
                labels={
                    "app": "kaggle-agent",
                    "job-id": db_job.job_id
                }
            ),
            data={
                "job_id": db_job.job_id,
                "kaggle_url": db_job.kaggle_url,
                "competition_name": db_job.competition_name or ""
            }
        )
        
        try:
            self.core_v1.create_namespaced_config_map(
                namespace=self.namespace,
                body=config_map
            )
        except ApiException as e:
            if e.status != 409:  # Ignore if already exists
                raise
    
    def _build_job_manifest(self, db_job):
        """Build K8s Job manifest"""
        
        # Parse resources
        cpu_request = db_job.resources_requested.get("cpu", "1")
        memory_request = db_job.resources_requested.get("memory", "2Gi")
        
        # Calculate limits (2x requests for CPU, fixed for memory)
        try:
            cpu_limit = str(int(float(cpu_request)) * 2)
        except:
            cpu_limit = "2"
        
        # Parse memory and double it for limit
        try:
            mem_value = int(memory_request.replace("Gi", "").replace("Mi", ""))
            if "Gi" in memory_request:
                memory_limit = f"{mem_value * 2}Gi"
            else:
                memory_limit = f"{mem_value * 2}Mi"
        except:
            memory_limit = "4Gi"
        
        # Container definition
        container = client.V1Container(
            name="agent",
            image=self.agent_image,
            image_pull_policy="IfNotPresent",  # Use local images for Kind
            args=[
                "--job-id", db_job.job_id,
                "--url", db_job.kaggle_url
            ],
            env=[
                client.V1EnvVar(
                    name="KAGGLE_USERNAME",
                    value_from=client.V1EnvVarSource(
                        secret_key_ref=client.V1SecretKeySelector(
                            name="api-secrets",
                            key="KAGGLE_USERNAME",
                            optional=True
                        )
                    )
                ),
                client.V1EnvVar(
                    name="KAGGLE_KEY",
                    value_from=client.V1EnvVarSource(
                        secret_key_ref=client.V1SecretKeySelector(
                            name="api-secrets",
                            key="KAGGLE_KEY",
                            optional=True
                        )
                    )
                ),
                client.V1EnvVar(
                    name="ANTHROPIC_API_KEY",
                    value_from=client.V1EnvVarSource(
                        secret_key_ref=client.V1SecretKeySelector(
                            name="api-secrets",
                            key="ANTHROPIC_API_KEY",
                            optional=True
                        )
                    )
                ),
                client.V1EnvVar(name="JOB_ID", value=db_job.job_id)
            ],
            resources=client.V1ResourceRequirements(
                requests={
                    "cpu": cpu_request,
                    "memory": memory_request
                },
                limits={
                    "cpu": cpu_limit,
                    "memory": memory_limit
                }
            ),
            volume_mounts=[
                client.V1VolumeMount(
                    name="output",
                    mount_path="/output"
                ),
                client.V1VolumeMount(
                    name="shared-storage",
                    mount_path="/shared"
                )
            ]
        )
        
        # Pod template
        pod_template = client.V1PodTemplateSpec(
            metadata=client.V1ObjectMeta(
                labels={
                    "app": "kaggle-agent",
                    "job-id": db_job.job_id,
                    "k8s-job-name": db_job.k8s_job_name,
                    "workload": "kaggle-jobs"
                },
                annotations={
                    "kaggle.url": db_job.kaggle_url,
                    "created.at": db_job.created_at.isoformat()
                }
            ),
            spec=client.V1PodSpec(
                restart_policy="Never",
                containers=[container],
                volumes=[
                    client.V1Volume(
                        name="output",
                        empty_dir=client.V1EmptyDirVolumeSource()
                    ),
                    client.V1Volume(
                        name="shared-storage",
                        persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(
                            claim_name="submissions-storage"
                        )
                    )
                ],
                # For Kind, use node labels (no taints needed)
                node_selector={
                    "workload": "kaggle-jobs"
                }
            )
        )
        
        # Job spec
        job_spec = client.V1JobSpec(
            template=pod_template,
            backoff_limit=2,  # Retry up to 2 times
            active_deadline_seconds=7200,  # 2 hour timeout
            ttl_seconds_after_finished=86400  # Keep for 24 hours
        )
        
        # Job object
        job = client.V1Job(
            api_version="batch/v1",
            kind="Job",
            metadata=client.V1ObjectMeta(
                name=db_job.k8s_job_name,
                namespace=self.namespace,
                labels={
                    "app": "kaggle-agent",
                    "job-id": db_job.job_id,
                    "managed-by": "job-controller"
                }
            ),
            spec=job_spec
        )
        
        return job

