# Kaggle Agent - Autonomous Competition Solver

> **Production-grade Kubernetes implementation for autonomous Kaggle competition solving**

[![Kubernetes](https://img.shields.io/badge/Kubernetes-326CE5?style=flat&logo=kubernetes&logoColor=white)](https://kubernetes.io/)
[![Python](https://img.shields.io/badge/Python-3.11-blue?style=flat&logo=python)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-316192?style=flat&logo=postgresql&logoColor=white)](https://postgresql.org)

---

## 📑 Table of Contents

1. [Architecture Analysis & Design](#1-architecture-analysis--design)
   - [1.1 Architecture Options Considered](#11-architecture-options-considered)
   - [1.2 Option 1: Synchronous REST API](#12-option-1-synchronous-rest-api)
   - [1.3 Option 2: Serverless Functions](#13-option-2-serverless-functions-aws-lambdacloud-functions)
   - [1.4 Option 3: REST + Celery + Docker](#14-option-3-rest--celery--docker-sandboxing)
   - [1.5 Option 4: Kubernetes Jobs + REST API](#15-option-4-kubernetes-jobs--rest-api-chosen)
   - [1.6 Final Architecture Decision](#16-final-architecture-decision)

2. [Implementation Overview](#2-implementation-overview)
3. [Quick Start](#3-quick-start)
4. [API Reference](#4-api-reference)
5. [Areas of Improvement](#5-areas-of-improvement)
   - [5.1 Infrastructure & Resource Management](#51-infrastructure--resource-management)
   - [5.2 Storage & Persistence](#52-storage--persistence)
   - [5.3 Orchestration & Observability](#53-orchestration--observability)
   - [5.4 ML Agent Improvements](#54-ml-agent-improvements)
     - [5.4.1 Advanced Agent Architecture](#541-advanced-agent-architecture)
     - [5.4.2 Result Validation & Improvement Loop](#542-result-validation--improvement-loop)
     - [5.4.3 Specialized Micro-Agents](#543-specialized-micro-agents)
     - [5.4.4 Hardware Requirements Predictor](#544-hardware-requirements-predictor)
     - [5.4.5 Dynamic Dependency Management](#545-dynamic-dependency-management)
     - [5.4.6 Multi-Modality Support](#546-multi-modality-support)
---

## 1. Architecture Analysis & Design

### 1.1 Architecture Options Considered

During system design, **four distinct architectures** were evaluated. Each option was analyzed for:
- ✅ **Concurrency handling** (50+ simultaneous requests)
- ✅ **Scalability** (production growth)
- ✅ **Isolation** (job sandboxing)
- ✅ **Complexity** (implementation & maintenance)
- ✅ **Extensibility** (future features & enhancements)

---

### 1.2 Option 1: Synchronous REST API

#### Architecture Diagram
```
User Request → API Server → Process Competition → Return Result
                  ↓
            (Blocks until done)
```

#### Description
Simple REST API where each request blocks until the entire competition is solved. The server processes training synchronously and returns the submission file in the HTTP response.

#### Pros
✅ **Simplest implementation** - Minimal code, no external dependencies  
✅ **No additional infrastructure** - Single server deployment  
✅ **Easy debugging** - Synchronous flow is straightforward to trace  
✅ **Direct request-response model** - Familiar HTTP pattern  

#### Cons
❌ **Timeout issues** - Training can take hours, HTTP timeouts after 30-120s  
❌ **No concurrency handling** - One request at a time  
❌ **Server resource exhaustion** - Memory leaks, CPU saturation  
❌ **Single point of failure** - Server crash loses all jobs  
❌ **Can't handle 50 concurrent requests** - Fails core requirement  
❌ **HTTP timeout limits** - Browser/proxy timeouts unavoidable  

#### Verdict
**❌ REJECTED** - Fails core concurrency requirement. Cannot handle 50 simultaneous requests. Training time exceeds HTTP timeout limits.

---

### 1.3 Option 2: Serverless Functions (AWS Lambda/Cloud Functions)

#### Architecture Diagram
```
User Request → API Gateway → Lambda (15min timeout) → Step Functions
                  ↓                                         ↓
            Job ID                                   Orchestrate workflow
                                                            ↓
                                                      S3/Storage
```

#### Description
API Gateway triggers Lambda function for each request. Lambda spawns a Step Functions workflow to orchestrate the multi-stage pipeline. Results stored in S3.

#### Pros
✅ **Auto-scaling** - Handles concurrency automatically (1000+ concurrent)  
✅ **Pay-per-use** - No idle costs  
✅ **Managed infrastructure** - No server maintenance  
✅ **Built-in timeout handling** - Step Functions orchestrate long workflows  
✅ **High availability** - AWS-managed fault tolerance  

#### Cons
❌ **Lambda 15-min execution limit** - Model training often exceeds this  
❌ **Vendor lock-in** - Tied to AWS ecosystem  
❌ **Cold start latency** - 1-5s delay for infrequent requests  
❌ **Difficult local development** - Requires cloud simulation (LocalStack)  
❌ **Cost unpredictability** - Can be expensive at scale  

#### Verdict
**⚠️ NOT IDEAL** - Training time exceeds Lambda limits. Strong for certain use cases but requires workarounds for long-running ML training tasks.

---

### 1.4 Option 3: REST + Celery + Docker Sandboxing (Implemented: https://github.com/romilshah18/kaggle-agent-system)

#### Architecture Diagram
```
User Request → FastAPI → Celery Queue → Worker (spawns Docker container)
                  ↓           ↓                     ↓
            Job ID      Redis/PostgreSQL    Isolated execution
                            ↓                       ↓
            Poll Status     Job State          submission.csv
```

#### Description
FastAPI creates job records and publishes to Celery queue. Workers pick tasks, spawn Docker containers for isolated execution. Results stored in shared volume/database.

#### Pros
✅ **Best balance: scalability + simplicity** - Proven pattern  
✅ **Handles 50+ concurrent** - Celery autoscaling workers  
✅ **Sandbox isolation** - Docker per job  
✅ **Familiar Python ecosystem** - Widespread adoption  
✅ **Easy to extend** - Well-understood architecture  
✅ **Retry/failure handling built-in** - Celery task retries  
✅ **Resource limiting** - Docker CPU/memory constraints  
✅ **Can run locally or cloud** - Flexible deployment  

#### Cons
⚠️ **Manual worker scaling** - Needs manual handlings for scaling
  

#### Verdict
**✅ INITIALLY SELECTED** - Strong option with working implementation. However, identified improvement opportunity: **manual scaling is operational burden**.
Implemented: https://github.com/romilshah18/kaggle-agent-system
**Decision**: Move to more production-grade approach with automatic scaling as there was more time.

---

### 1.5 Option 4: Kubernetes Jobs + REST API (CHOSEN)

#### Architecture Diagram
```
User Request → API Server → PostgreSQL DB (PENDING job)
                  ↓                  ↓
            Job ID (return)   Job Controller (polls every 5s)
                                     ↓
                              Creates K8s Job → K8s API
                                     ↓               ↓
                              Updates DB      Spawns Pod → Executes in sandbox
                                                               ↓
                              User polls API ← DB ← Controller ← Results in PV

Components:
┌─────────────────┐
│   FastAPI       │ ← Creates job records in DB
└────────┬────────┘
         │
┌────────▼────────┐
│  PostgreSQL     │ ← Job state (pending/running/complete)
└────────┬────────┘
         │
┌────────▼────────┐
│ Job Controller  │ ← Watches DB, creates K8s Jobs
└────────┬────────┘
         │
┌────────▼────────┐
│ Kubernetes Jobs │ ← Isolated pods execute training
└─────────────────┘
```

#### Description
**Operator Pattern**: FastAPI writes job specs to PostgreSQL. A dedicated Job Controller watches the database and creates Kubernetes Job resources. Each Job spawns an isolated pod that executes the competition pipeline. Results stored in Persistent Volumes.

#### Pros
✅ **True isolation** - Container per job (namespace + resource quotas)  
✅ **Resource limits enforcement** - CPU/memory/GPU limits per pod  
✅ **Excellent concurrency handling** - K8s schedules 100+ pods  
✅ **Cloud-native scalability** - Cluster Autoscaler adds nodes automatically  
✅ **Dead job cleanup** - TTL controller removes completed jobs  
✅ **Production-grade orchestration** - Tested by industry  
✅ **Observability built-in** - Prometheus, Grafana, kubectl logs  
✅ **Fault tolerance** - Pod rescheduling on node failures  
✅ **Cost optimization** - Spot instances, scale-to-zero  
✅ **Extensibility** - Easy to add features like multi-tenancy, GPU support  

#### Cons
⚠️ **Requires K8s cluster** - Higher initial complexity  
⚠️ **Longer setup time** - 30 min to bootstrap cluster  

#### Verdict
**✅ PRODUCTION IDEAL** - Selected as final architecture.

---

### 1.6 Final Architecture Decision

#### Chosen Architecture: **Kubernetes Jobs + REST API**

#### Why

1. Kubernetes scheduler handles concurrent jobs automatically with cluster autoscaler adding nodes dynamically, eliminating manual worker management.

2. Each job runs in a separate pod with enforced CPU/memory limits, namespace isolation.

3. Automatic pod restarts on failure, self-healing through rescheduling, and native observability with Prometheus metrics and centralized logging.

4. Handles unlimited horizontal scaling bounded only by cluster capacity.

---

## 2. Implementation Overview

### 2.1 High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                           KAGGLE AGENT SYSTEM                                 │
│                     Kubernetes-Native ML Pipeline                             │
└──────────────────────────────────────────────────────────────────────────────┘

                                    USER
                                     │
                                     │ HTTP Request
                                     │ POST /run?url=<kaggle-competition>
                                     ▼
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃                            API LAYER (Stateless)                            ┃
┃  ╔═══════════════════════════════════════════════════════════════════╗      ┃
┃  ║  kaggle-api Deployment (2 replicas)                              ║      ┃
┃  ║  Service: kaggle-api (NodePort 30080)                            ║      ┃
┃  ║  Code: /kaggle-api-gateway/                                      ║      ┃
┃  ║  ┌──────────────┐        ┌──────────────┐                        ║      ┃
┃  ║  │  API Pod 1   │        │  API Pod 2   │                        ║      ┃
┃  ║  │              │        │              │                        ║      ┃
┃  ║  │  - POST /run │        │  - POST /run │                        ║      ┃
┃  ║  │  - GET /status        │  - GET /status                        ║      ┃
┃  ║  │  - GET /result│        │  - GET /result                        ║      ┃
┃  ║  │  - GET /logs │        │  - GET /logs │                        ║      ┃
┃  ║  └──────┬───────┘        └──────┬───────┘                        ║      ┃
┃  ╚═════════╪════════════════════════╪═══════════════════════════════╝      ┃
┗━━━━━━━━━━━━┿━━━━━━━━━━━━━━━━━━━━━━━━┿━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
              │                        │
              │  Write Job Record      │  Read Job Status
              │  (status=PENDING)      │
              ▼                        ▼
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃                        DATABASE LAYER (Persistent)                          ┃
┃  ╔═══════════════════════════════════════════════════════════════════╗      ┃
┃  ║  PostgreSQL StatefulSet                                           ║      ┃
┃  ║  ┌────────────────────────────────────────────────────────┐       ║      ┃
┃  ║  │  Jobs Table                                             │       ║      ┃
┃  ║  │  ------------------------------------------------       │       ║      ┃
┃  ║  │  job_id | kaggle_url | status | k8s_job_name |...      │       ║      ┃
┃  ║  │  ------------------------------------------------       │       ║      ┃
┃  ║  │  uuid-1 | titanic    | PENDING | kaggle-uuid-1 |       │       ║      ┃
┃  ║  │  uuid-2 | house-pr.. | RUNNING | kaggle-uuid-2 |       │       ║      ┃
┃  ║  │  uuid-3 | mnist      | SUCCESS | kaggle-uuid-3 |       │       ║      ┃
┃  ║  └────────────────────────────────────────────────────────┘       ║      ┃
┃  ║                                                                     ║      ┃
┃  ║  + 5Gi Persistent Volume (job metadata, history, audit logs)       ║      ┃
┃  ╚═══════════════════════════════════════════════════════════════════╝      ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┯━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
                                │
                                │  Watch for PENDING jobs
                                │  (Poll every 5 seconds)
                                ▼
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃                     ORCHESTRATION LAYER                 ┃
┃  ╔═══════════════════════════════════════════════════════════════════╗      ┃
┃  ║  job-controller Deployment (1 replica)                           ║      ┃
┃  ║  Code: /kaggle-job-orchestrator/                                 ║      ┃
┃  ║  ┌───────────────────────────────────────────────────────┐        ║      ┃
┃  ║  │  Controller Pod                                        │        ║      ┃
┃  ║  │                                                        │        ║      ┃
┃  ║  │  Control Loop (every 5s):                             │        ║      ┃
┃  ║  │  1. Watch DB for PENDING jobs                         │        ║      ┃
┃  ║  │  2. Create K8s Job resources                          │        ║      ┃
┃  ║  │  3. Watch K8s Jobs (status sync)                      │        ║      ┃
┃  ║  │  4. Watch Pods (extract results)                      │        ║      ┃
┃  ║  │  5. Update DB with status                             │        ║      ┃
┃  ║  │  6. Cleanup completed jobs (TTL)                      │        ║      ┃
┃  ║  └───────────────────────┬───────────────────────────────┘        ║      ┃
┃  ╚══════════════════════════╪═══════════════════════════════════════════╝   ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━┿━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
                               │
                               │  Create K8s Job (kubectl apply)
                               ▼
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃                        EXECUTION LAYER (Isolated Workloads)                 ┃
┃  ╔═══════════════════════════════════════════════════════════════════╗      ┃
┃  ║  Kubernetes Jobs (batch/v1)                                       ║      ┃
┃  ║  Image: kaggle-agent/agent:latest                                 ║      ┃
┃  ║  Code: /kaggle-ml-agent/                                          ║      ┃
┃  ║                                                                    ║      ┃
┃  ║  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐               ║      ┃
┃  ║  │ K8s Job 1   │  │ K8s Job 2   │  │ K8s Job 3   │  ...          ║      ┃
┃  ║  │ (titanic)   │  │ (house-pr)  │  │ (mnist)     │               ║      ┃
┃  ║  │             │  │             │  │             │               ║      ┃
┃  ║  │ ┌─────────┐ │  │ ┌─────────┐ │  │ ┌─────────┐ │               ║      ┃
┃  ║  │ │ Pod     │ │  │ │ Pod     │ │  │ │ Pod     │ │               ║      ┃
┃  ║  │ │ Agent   │ │  │ │ Agent   │ │  │ │ Agent   │ │               ║      ┃
┃  ║  │ │ ┌──────┐│ │  │ │ ┌──────┐│ │  │ │ ┌──────┐│ │               ║      ┃
┃  ║  │ │ │Stage1││ │  │ │ │Stage1││ │  │ │ │Stage1││ │               ║      ┃
┃  ║  │ │ │Analyze││ │  │ │ │Analyze││ │  │ │ │Analyze││ │               ║      ┃
┃  ║  │ │ └───┬──┘│ │  │ │ └───┬──┘│ │  │ │ └───┬──┘│ │               ║      ┃
┃  ║  │ │ ┌───▼──┐│ │  │ │ ┌───▼──┐│ │  │ │ ┌───▼──┐│ │               ║      ┃
┃  ║  │ │ │Stage2││ │  │ │ │Stage2││ │  │ │ │Stage2││ │               ║      ┃
┃  ║  │ │ │Plan  ││ │  │ │ │Plan  ││ │  │ │ │Plan  ││ │               ║      ┃
┃  ║  │ │ └───┬──┘│ │  │ │ └───┬──┘│ │  │ │ └───┬──┘│ │               ║      ┃
┃  ║  │ │ ┌───▼──┐│ │  │ │ ┌───▼──┐│ │  │ │ ┌───▼──┐│ │               ║      ┃
┃  ║  │ │ │Stage3││ │  │ │ │Stage3││ │  │ │ │Stage3││ │               ║      ┃
┃  ║  │ │ │Generate││ │  │ │Generate││ │  │ │Generate││ │               ║      ┃
┃  ║  │ │ └───┬──┘│ │  │ │ └───┬──┘│ │  │ │ └───┬──┘│ │               ║      ┃
┃  ║  │ │ ┌───▼──┐│ │  │ │ ┌───▼──┐│ │  │ │ ┌───▼──┐│ │               ║      ┃
┃  ║  │ │ │Stage4││ │  │ │ │Stage4││ │  │ │ │Stage4││ │               ║      ┃
┃  ║  │ │ │Execute││ │  │ │Execute││ │  │ │Execute││ │               ║      ┃
┃  ║  │ │ └───┬──┘│ │  │ │ └───┬──┘│ │  │ │ └───┬──┘│ │               ║      ┃
┃  ║  │ │     │   │ │  │ │     │   │ │  │ │     │   │ │               ║      ┃
┃  ║  │ └─────┼───┘ │  │ └─────┼───┘ │  │ └─────┼───┘ │               ║      ┃
┃  ║  └───────┼─────┘  └───────┼─────┘  └───────┼─────┘               ║      ┃
┃  ╚══════════╪════════════════╪════════════════╪═══════════════════════════╝┃
┗━━━━━━━━━━━━━┿━━━━━━━━━━━━━━━━┿━━━━━━━━━━━━━━━━┿━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
               │                │                │
               │ Write          │ Write          │ Write
               ▼                ▼                ▼
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃                         STORAGE LAYER (Shared State)                        ┃
┃  ╔═══════════════════════════════════════════════════════════════════╗      ┃
┃  ║  PersistentVolume (50Gi)                                          ║      ┃
┃  ║  PVC: submissions-storage                                         ║      ┃
┃  ║  Host Path: /storage/ (in project root)                           ║      ┃
┃  ║  ┌────────────────────────────────────────────────────────┐       ║      ┃
┃  ║  │  /shared/submissions/  (mounted in pods)               │       ║      ┃
┃  ║  │  ├── {job-id-1}/                                        │       ║      ┃
┃  ║  │  │   ├── submission.csv         ✓                       │       ║      ┃
┃  ║  │  │   ├── generated_solution.py                          │       ║      ┃
┃  ║  │  ├── {job-id-2}/                                        │       ║      ┃
┃  ║  │  │   └── submission.csv         ✓                       │       ║      ┃
┃  ║  │  └── {job-id-3}/                                        │       ║      ┃
┃  ║  │      └── submission.csv         ✓                       │       ║      ┃
┃  ║  └────────────────────────────────────────────────────────┘       ║      ┃
┃  ╚═══════════════════════════════════════════════════════════════════╝      ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

                          API reads from /shared/submissions/{job-id}/submission.csv
                                        Returns to User
```

### 2.2 Detailed Architecture: Concurrency & Scalability

```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃                   DETAILED SYSTEM FLOW: 50+ CONCURRENT JOBS                 ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

                         50 Users Submit Simultaneously
                                      │
                    ┌─────────────────┼─────────────────┐
                    │                 │                 │
                    ▼                 ▼                 ▼
              Request 1         Request 25        Request 50

┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃  LAYER 1: API GATEWAY (Load Balanced, Horizontal Scaling)                  ┃
┃                                                                             ┃
┃   NodePort Service (30080)                                                  ┃
┃         │                                                                   ┃
┃         │  Round-Robin Load Balancing                                      ┃
┃         ├──────────────────┬────────────────────┐                          ┃
┃         ▼                  ▼                    ▼                           ┃
┃  ┌─────────────┐    ┌─────────────┐     ┌─────────────┐                   ┃
┃  │  API Pod 1  │    │  API Pod 2  │     │  (HPA can   │                   ┃
┃  │             │    │             │     │  add more)  │                   ┃
┃  │ CPU: 200m   │    │ CPU: 200m   │     │             │                   ┃
┃  │ Mem: 256Mi  │    │ Mem: 256Mi  │     │             │                   ┃
┃  │             │    │             │     │             │                   ┃
┃  │ Handles:    │    │ Handles:    │     │             │                   ┃
┃  │ Req 1-25    │    │ Req 26-50   │     │             │                   ┃
┃  └──────┬──────┘    └──────┬──────┘     └─────────────┘                   ┃
┃         │                  │                                               ┃
┃         │ Async DB Write   │ Async DB Write                                ┃
┃         │ (Non-blocking)   │ (Non-blocking)                                ┃
┃         │                  │                                               ┃
┃         └────────┬─────────┘                                               ┃
┃                  │                                                          ┃
┃         Returns job_id immediately                                          ┃
┃         User doesn't wait for training                                     ┃
┗━━━━━━━━━━━━━━━━━┿━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
                   │
                   │  50 DB Writes (batched)
                   ▼
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃  LAYER 2: DATABASE (Persistent Job Queue)                                  ┃
┃                                                                             ┃
┃   PostgreSQL StatefulSet                                                    ┃
┃   ┌─────────────────────────────────────────────────────────┐              ┃
┃   │  INSERT INTO jobs (job_id, kaggle_url, status) VALUES   │              ┃
┃   │  ('uuid-1', 'titanic', 'PENDING'),                      │              ┃
┃   │  ('uuid-2', 'house-prices', 'PENDING'),                 │              ┃
┃   │  ...                                                     │              ┃
┃   │  ('uuid-50', 'mnist', 'PENDING')                        │              ┃
┃   │                                                          │              ┃
┃   └─────────────────────────────────────────────────────────┘              ┃
┃                                                                             ┃
┃   State Transitions:                                                        ┃
┃   PENDING → QUEUED → RUNNING → SUCCESS/FAILED                              ┃
┗━━━━━━━━━━━━━━━━━━━━━┯━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
                       │
                       │  Controller polls every 5s
                       │  SELECT * FROM jobs WHERE status='PENDING' LIMIT 50
                       ▼
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃  LAYER 3: JOB CONTROLLER (Kubernetes Operator Pattern)                     ┃
┃                                                                             ┃
┃   Single Controller Pod (Stateless, can be replicated with leader election)┃
┃   ┌───────────────────────────────────────────────────────┐                ┃
┃   │  Control Loop (Every 5 seconds):                       │                ┃
┃   │                                                        │                ┃
┃   │  1. Fetch PENDING jobs (50 found)                     │                ┃
┃   │     ├─ Job 1: titanic                                 │                ┃
┃   │     ├─ Job 2: house-prices                            │                ┃
┃   │     └─ ...Job 50: mnist                               │                ┃
┃   │                                                        │                ┃
┃   │  2. For each job, create K8s Job:                     │                ┃
┃   │     ├─ Set resource requests (CPU: 1, Mem: 2Gi)       │                ┃
┃   │     ├─ Set resource limits (CPU: 2, Mem: 4Gi)         │                ┃
┃   │     ├─ Attach PVC (shared storage)                    │                ┃
┃   │     ├─ Set backoff limit: 2 (retry failed pods)       │                ┃
┃   │     ├─ Set active deadline: 7200s (2hr timeout)       │                ┃
┃   │     ├─ Set TTL: 86400s (cleanup after 24hr)           │                ┃
┃   │                                                        │                ┃
┃   │  3. Update DB: status = 'QUEUED'                      │                ┃
┃   │                                                        │                ┃
┃   │  4. Watch K8s Jobs for status changes:                │                ┃
┃   │     ├─ Job Active → DB status = RUNNING               │                ┃
┃   │     ├─ Job Complete → DB status = SUCCESS             │                ┃
┃   │     └─ Job Failed → DB status = FAILED                │                ┃
┃   │                                                        │                ┃
┃   │  5. Watch Pods:                                        │                ┃
┃   │     ├─ Extract submission.csv from /shared            │                ┃
┃   │     ├─ Update DB with submission_path                 │                ┃
┃   │     └─ Record resource usage metrics                  │                ┃
┃   └───────────────────────────────────────────────────────┘                ┃
┗━━━━━━━━━━━━━━━━━━━━━┯━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
                       │
                       │  Creates 50 K8s Jobs
                       ▼
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃  LAYER 4: KUBERNETES SCHEDULER (Resource Orchestration)                    ┃
┃                                                                             ┃
┃   K8s Scheduler analyzes:                                                   ┃
┃   ┌──────────────────────────────────────────────────────────┐             ┃
┃   │  For each Job:                                            │             ┃
┃   │  - Resource requests: CPU=1, Memory=2Gi                  │             ┃
┃   │  - Node selector: workload=kaggle-jobs                   │             ┃
┃   │  - Find node with available capacity                     │             ┃
┃   │  - Schedule pod to node                                  │             ┃
┃   └──────────────────────────────────────────────────────────┘             ┃
┃                                                                             ┃
┃   Cluster Capacity:                                                         ┃
┃   ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                       ┃
┃   │  Worker 1   │  │  Worker 2   │  │  Worker 3   │                       ┃
┃   │  (8 CPU,    │  │  (8 CPU,    │  │  (8 CPU,    │                       ┃
┃   │   16Gi RAM) │  │   16Gi RAM) │  │   16Gi RAM) │                       ┃
┃   │             │  │             │  │             │                       ┃
┃   │  Can run:   │  │  Can run:   │  │  Can run:   │                       ┃
┃   │  8 pods     │  │  8 pods     │  │  8 pods     │                       ┃
┃   │  (1 CPU ea.)│  │  (1 CPU ea.)│  │  (1 CPU ea.)│                       ┃
┃   └─────────────┘  └─────────────┘  └─────────────┘                       ┃
┃                                                                             ┃
┗━━━━━━━━━━━━━━━━━━━━━┯━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
                       │
                       │  Pods start executing
                       ▼
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃  LAYER 5: AGENT PODS (Isolated Execution)                                  ┃
┃                                                                             ┃
┃   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                    ┃
┃   │  Pod 1       │  │  Pod 2       │  │  Pod 50      │                    ┃
┃   │  (titanic)   │  │  (house-pr)  │  │  (mnist)     │                    ┃
┃   │              │  │              │  │              │                    ┃
┃   │  Resources:  │  │  Resources:  │  │  Resources:  │                    ┃
┃   │  CPU: 1 core │  │  CPU: 1 core │  │  CPU: 1 core │                    ┃
┃   │  Mem: 2Gi    │  │  Mem: 2Gi    │  │  Mem: 2Gi    │                    ┃
┃   │              │  │              │  │              │                    ┃
┃   │  Volumes:    │  │  Volumes:    │  │  Volumes:    │                    ┃
┃   │  - /output   │  │  - /output   │  │  - /output   │                    ┃
┃   │    (EmptyDir)│  │    (EmptyDir)│  │    (EmptyDir)│                    ┃
┃   │  - /shared   │  │  - /shared   │  │  - /shared   │                    ┃
┃   │    (PVC)     │  │    (PVC)     │  │    (PVC)     │                    ┃
┃   │              │  │              │  │              │                    ┃
┃   │  Execution:  │  │  Execution:  │  │  Execution:  │                    ┃
┃   │  ────────────│  │  ────────────│  │  ────────────│                    ┃
┃   │  [Running]   │  │  [Running]   │  │  [Pending]   │                    ┃
┃   │  Stage 3/4   │  │  Stage 2/4   │  │  Waiting for │                    ┃
┃   │  Generating  │  │  Planning    │  │  node...     │                    ┃
┃   │  code...     │  │  strategy... │  │              │                    ┃
┃   │              │  │              │  │              │                    ┃
┃   │  Timeout:    │  │  Timeout:    │  │  Timeout:    │                    ┃
┃   │  2 hours     │  │  2 hours     │  │  2 hours     │                    ┃
┃   │  Retry: 2x   │  │  Retry: 2x   │  │  Retry: 2x   │                    ┃
┃   └──────┬───────┘  └──────┬───────┘  └──────┬───────┘                    ┃
┃          │                 │                 │                             ┃
┃          │ Write           │ Write           │                             ┃
┃          ▼                 ▼                 ▼                             ┃
┃   submission.csv    submission.csv    (waiting...)                         ┃
┃                                                                             ┃
┗━━━━━━━━━━━━━━━━━━━━━┯━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
                       │
                       │  Write to shared Storage
                       ▼
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃  LAYER 6: PERSISTENT STORAGE (Result Collection)                           ┃
┃                                                                             ┃
┃   PersistentVolume (Local Storage / EBS / GCE PD)                          ┃
┃   ┌──────────────────────────────────────────────────────────┐             ┃
┃   │  /shared/submissions/                                     │             ┃
┃   │  ├── uuid-1/                                              │             ┃
┃   │  │   ├── submission.csv           (✓ Job 1 complete)     │             ┃
┃   │  │   ├── generated_solution.py                           │             ┃
┃   │  ├── uuid-2/                                              │             ┃
┃   │  │   └── submission.csv           (✓ Job 2 complete)     │             ┃
┃   │  ├── uuid-3/                                              │             ┃
┃   │  │   └── (in progress...)                                │             ┃
┃   │  ...                                                      │             ┃
┃   │  └── uuid-50/                                             │             ┃
┃   │      └── (pending)                                        │             ┃
┃   └──────────────────────────────────────────────────────────┘             ┃
┃                                                                             ┃
┃                                                                           ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

```

### Component Responsibilities

**kaggle-api (FastAPI Server - 2 replicas)**
- **Folder**: `/kaggle-api-gateway/`
- **Service**: `kaggle-api` (NodePort 30080)
- **Image**: `kaggle-agent/api:latest`
- REST API for job submission (`POST /run`)
- Job status queries (`GET /status/{job_id}`)
- Result download (`GET /result/{job_id}/submission.csv`)
- Logs retrieval (`GET /logs/{job_id}`)

**postgres (PostgreSQL Database - StatefulSet)**
- **Service**: `postgres` (ClusterIP)
- **Image**: `postgres:16-alpine`
- Job metadata storage (job_id, kaggle_url, status, timestamps)
- Status tracking (PENDING → QUEUED → RUNNING → SUCCESS/FAILED)

**job-controller (Job Controller - 1 replica)**
- **Folder**: `/kaggle-job-orchestrator/`
- **Image**: `kaggle-agent/controller:latest`
- Watches database for PENDING jobs (poll every 5s)
- Creates Kubernetes Job resources via K8s API
- Syncs K8s Job status back to database
- Watches Pods to extract results from /shared volume

**kaggle-agent (Agent Pods - Kubernetes Jobs)**
- **Folder**: `/kaggle-ml-agent/`
- **Image**: `kaggle-agent/agent:latest`
- Execute 4-stage competition pipeline:
  1. **Analyze**: Download data, parse competition requirements (`analyzer/`)
  2. **Plan**: Select models, design features (`planner/`)
  3. **Generate**: Create training script with Claude AI (`generator/`)
  4. **Execute**: Train model, create submission.csv (`executor/`)
- Isolated execution per job
- Resource limits: 1-2 CPU, 2-4Gi Memory
- Timeout: 2 hours, Retry: 2 attempts
- Auto-cleanup after completion (TTL)

**submissions-storage (Persistent Storage)**
- **Folder**: `/storage/` (project root)
- **PVC**: `submissions-storage`
- 50Gi PersistentVolume (local or cloud block storage)
- Mounted at `/shared` in controller and agent pods
- Directory per job: `/shared/submissions/{job-id}/`
- Stores: submission.csv, train.csv, test.csv, generated code

---

## 3. Quick Start

### Prerequisites
- Docker Desktop installed and running
- kubectl installed
- kind installed (Kubernetes in Docker)
- Anthropic API key (set in `kaggle-infrastructure/kind/api.yaml`)

### How to Start

#### Step 1: Setup Everything with Persistent Storage

Run the setup script which will create the cluster, build images, and deploy all components:

```bash
# Make script executable
chmod +x scripts/setup-persistent-storage.sh

# Run complete setup
./scripts/setup-persistent-storage.sh
```

This script will:
- Create local storage directory at `./storage/submissions/`
- Create kind cluster with persistent volume mounts
- Deploy PostgreSQL and Redis
- Build Docker images (api, controller, agent)
- Load images into kind cluster
- Deploy API and Job Controller
- Wait for all components to be ready

**Note**: The setup takes ~5-10 minutes depending on your machine.

#### Step 2: Verify Everything is Running

```bash
# Check all pods are running
kubectl get pods -n kaggle-agent

# Check persistent storage
kubectl get pv,pvc -n kaggle-agent

# Verify API health
curl http://localhost:8080/health | jq
```

#### Step 3: Submit Your First Job

```bash
# Create a job for Titanic competition
curl -X POST "http://localhost:8080/run" \
  -H "Content-Type: application/json" \
  -d '{"kaggle_url": "https://www.kaggle.com/competitions/titanic"}' | jq

# Save the job_id from response
```

**Expected Response**:
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "k8s_job_name": "kaggle-titanic-550e8400",
  "status": "pending",
  "message": "Job created. K8s Job will be created by controller..."
}
```

#### Step 4: Check Job Status

```bash
# Replace {job-id} with your actual job_id
curl http://localhost:8080/status/{job-id} | jq

# Watch Kubernetes Jobs
kubectl get jobs -n kaggle-agent -w

# Watch Pods
kubectl get pods -n kaggle-agent -w
```

**Status Progression**: `pending` → `queued` → `running` → `success`

#### Step 5: View Logs (Optional)

```bash
# View job logs via API
curl http://localhost:8080/logs/{job-id} | jq

# Or view pod logs directly
kubectl logs -l job-id={job-id} -n kaggle-agent -f
```

#### Step 6: Download Result

```bash
# Once status is "success", download submission.csv
curl http://localhost:8080/result/{job-id}/submission.csv > submission.csv

# Verify the file
head submission.csv
```

#### Step 7: Test Concurrency (Load Testing)

To test the system with **50 concurrent jobs**:

```bash
# Make script executable
chmod +x scripts/load-test.sh

# Run load test with 50 jobs (default)
./scripts/load-test.sh

# Or specify custom number of jobs
./scripts/load-test.sh 100
```

The load test will:
- Create 50 jobs in parallel (max 20 concurrent)
- Test different Kaggle competitions
- Measure response times and success rates
- Save detailed results to CSV file

#### Monitoring Commands

```bash
# View all jobs
curl http://localhost:8080/jobs | jq

# Check cluster resources
kubectl top nodes
kubectl top pods -n kaggle-agent

# View controller logs
kubectl logs -f deployment/job-controller -n kaggle-agent

# View API logs
kubectl logs -f deployment/kaggle-api -n kaggle-agent

# Check storage usage
ls -la storage/submissions/
```

#### Cleanup

```bash
# Delete cluster (keeps local storage)
kind delete cluster --name kaggle-agent

# Delete everything including storage
kind delete cluster --name kaggle-agent
rm -rf storage/
```

---

## 4. API Reference

### POST /run
Create a new job

**Request**:
```json
{
  "kaggle_url": "https://www.kaggle.com/competitions/titanic",
  "priority": 0,
  "resources": {
    "cpu": "4",
    "memory": "8Gi"
  }
}
```

**Response**:
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "k8s_job_name": "kaggle-titanic-550e8400",
  "status": "pending",
  "message": "Job created successfully"
}
```

### GET /status/{job_id}
Check job status

**Response**:
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "running",
  "progress": "Training model...",
  "created_at": "2024-01-15T10:30:00Z",
  "started_at": "2024-01-15T10:31:00Z"
}
```

### GET /result/{job_id}/submission.csv
Download submission file

**Response**: CSV file (binary)

### GET /logs/{job_id}
View job logs

**Response**:
```json
{
  "job_id": "...",
  "pod_name": "kaggle-titanic-550e8400-xxxxx",
  "logs": "Starting agent...\nAnalyzing competition..."
}
```

---

## 5. Areas of Improvement

This section outlines potential enhancements to evolve the system from a working prototype to a more robust production-grade platform.

### 5.1 Infrastructure & Resource Management

**Dynamic Resource Allocation**
- **Current**: Fixed resource allocation (1-2 CPU, 2-4Gi RAM) for all competitions
- **Improvement**: Implement competition-aware resource profiling
  - Analyze competition dataset size, problem type, and historical requirements
  - Classify competitions into resource tiers (small/medium/large/gpu)
  - Dynamically set pod resource requests/limits based on classification

**Deployment Manifests**
- **Current**: Only kind configurations available for local development
- **Improvement**: Add production-ready manifests for cloud deployments

### 5.2 Storage & Persistence

**Cloud-Native Storage**
- **Current**: Local storage used for development
- **Improvement**: Migrate to cloud object storage
  - Use S3/GCS/Azure Blob for submission storage


**Log Persistence & Centralization**
- **Current**: Logs stored in pods, lost after cleanup
- **Improvement**: Implement centralized logging infrastructure
  - Deploy Elasticsearch + Fluentd + Kibana (EFK stack)
  - Stream logs to CloudWatch Logs (AWS) / Cloud Logging (GCP)

### 5.3 Orchestration & Observability

**Event-Driven Job Completion**
- **Current**: Controller polls filesystem to check for submission.csv
- **Improvement**: Implement event-driven architecture
  - Agent pods publish completion events to message broker
  - Controller subscribes to events for real-time status updates
  - Reduce polling overhead and improve latency

**Distributed Tracing**
- **Current**: No correlation between API, controller, and agent logs
- **Improvement**: Implement distributed tracing system
  - Generate trace_id at API level, propagate through all components
  - Enable end-to-end request tracking (API → Controller → Agent → Result)
  - Add trace_id to all log entries for easy correlation

**Error Tracking & Alerting**
- **Current**: Failures are handled but not persisted or analyzed
- **Improvement**: Implement comprehensive error tracking
  - Deploy Sentry or similar for error aggregation
  - Store failure metadata in database (error type, stack trace, context)


### 5.4 ML Agent Improvements

#### 5.4.1 Advanced Agent Architecture

**Deep Agent with Planning**
- **Current**: Single-pass agent with fixed 4-stage pipeline
- **Improvement**: Implement hierarchical planning agent
  - Add LLM-based task decomposition to create dynamic TODO lists
  - Enable iterative refinement based on intermediate results
  - Implement self-reflection and error correction loops with max loops limit
  - Use multi-agent coordination for complex competitions
  - Add memory/context management and summarization for long-running tasks

#### 5.4.2 Result Validation & Improvement Loop

**Submission Evaluation**
- **Current**: No validation of generated submissions before submission
- **Improvement**: Add pre-submission validation pipeline
  - LLM-based evaluation of submission quality
  - Cross-validation score prediction
  - Automated feedback loop for iterative improvement

#### 5.4.3 Hardware Requirements Predictor

**Intelligent Resource Estimation**
- **Current**: Fixed resource allocation regardless of competition
- **Improvement**: LLM-based hardware requirements prediction
  - Initial agent analyzes competition data and requirements
  - Predicts optimal CPU/memory/GPU configuration
  - Estimates training time and resource costs
  - Dynamically adjusts pod resources before execution
  - Learns from historical data to improve predictions

#### 5.4.4 Dynamic Dependency Management

**Runtime Environment Configuration**
- **Current**: Agent image has pre-installed fixed libraries
- **Improvement**: Dynamic dependency installation
  - Parse competition requirements to identify needed libraries
  - Generate requirements.txt on-the-fly
  - Install dependencies at runtime using pip/conda
  - Cache common dependency combinations
  - Support custom package sources and versions

#### 5.4.6 Multi-Modality Support

**Comprehensive Problem Type Handling**
- **Current**: Limited to regression/classification with tabular data
- **Improvement**: Expand to all Kaggle competition types
  - **Computer Vision**: Image classification, object detection, segmentation
  - **Natural Language Processing**: Text classification, NER, generation
  - **Time Series**: Forecasting, anomaly detection
  - **Recommendation Systems**: Collaborative filtering, ranking
  - **Reinforcement Learning**: Simulation environments, game playing
  - **Multi-Modal**: Combining images, text, and tabular data
  - **Generative Tasks**: GANs, VAEs, diffusion models

**Self-Learning & Adaptation**
- Enable agent to recognize new problem types
- Automatically research and apply appropriate techniques
- Build knowledge base of competition strategies
- Implement meta-learning for faster adaptation


---
