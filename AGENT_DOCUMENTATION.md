# Kaggle ML Agent - Complete Documentation

## Overview

The Kaggle ML Agent is an **autonomous machine learning system** that automatically solves Kaggle competitions end-to-end. Given a competition URL, it downloads data, analyzes the problem, generates ML code, trains models, and creates valid submissions - all without human intervention.

**Status**: ✅ Production-ready, fully functional

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         USER REQUEST                             │
│              POST /api/v1/jobs                                   │
│              {"kaggle_url": "..."}                               │
└──────────────────────────┬──────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│                      API SERVER (FastAPI)                        │
│  - Receives job request                                          │
│  - Stores in PostgreSQL database                                 │
│  - Returns job_id                                                │
└──────────────────────────┬──────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│                   JOB CONTROLLER (Kubernetes)                    │
│  - Polls database for pending jobs                               │
│  - Creates Kubernetes Job with agent pod                         │
│  - Monitors job status                                           │
│  - Updates database with results                                 │
└──────────────────────────┬──────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│                     AGENT POD (Python)                           │
│                                                                   │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ STAGE 1: Competition Analysis                              │ │
│  │ - Download data via Kaggle API                             │ │
│  │ - Parse submission schema (sample_submission.csv)          │ │
│  │ - Identify target column                                   │ │
│  │ - Scrape competition page for metadata                     │ │
│  │ Output: competition_info dict                              │ │
│  └────────────────────────────────────────────────────────────┘ │
│                           ↓                                       │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ STAGE 2: Strategy Planning                                 │ │
│  │ - Query Claude AI with competition details                 │ │
│  │ - Get ML approach, models, feature engineering             │ │
│  │ - Fallback to rule-based if LLM fails                      │ │
│  │ Output: strategy dict                                      │ │
│  └────────────────────────────────────────────────────────────┘ │
│                           ↓                                       │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ STAGE 3: Code Generation                                   │ │
│  │ - Generate Python ML script with Claude                    │ │
│  │ - Validate code statically (syntax, imports, refs)         │ │
│  │ - Retry up to 3 times with feedback if invalid            │ │
│  │ - Fallback to template if all attempts fail               │ │
│  │ Output: generated_solution.py                              │ │
│  └────────────────────────────────────────────────────────────┘ │
│                           ↓                                       │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ STAGE 4: Model Training & Validation                       │ │
│  │ - Execute generated Python script                          │ │
│  │ - Train ML model on real data                              │ │
│  │ - Create submission.csv                                    │ │
│  │ - Validate submission (6 comprehensive checks)             │ │
│  │ - Auto-correct common errors                               │ │
│  │ - Create fallback if needed                                │ │
│  │ Output: submission.csv                                     │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                   │
└──────────────────────────┬──────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│                     PERSISTENT STORAGE                           │
│  /shared/submissions/{job_id}/                                   │
│  ├── data/                     # Downloaded competition data     │
│  ├── generated_solution.py     # AI-generated code              │
│  └── submission.csv            # Final submission                │
└─────────────────────────────────────────────────────────────────┘
```

---

## Technology Stack

### Backend Services

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **API Server** | FastAPI + Python 3.11 | REST API for job management |
| **Database** | PostgreSQL 15 | Job state and metadata storage |
| **Job Controller** | Python + Kubernetes Client | Job orchestration and monitoring |
| **Agent** | Python 3.11 | Autonomous ML pipeline execution |

### Infrastructure

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **Container Runtime** | Docker | Application containerization |
| **Orchestration** | Kubernetes (Kind) | Container orchestration and scheduling |
| **Storage** | Kubernetes PVC | Persistent storage for submissions |
| **Networking** | Kubernetes Services | Service discovery and load balancing |

### AI & ML Libraries

| Library | Version | Purpose |
|---------|---------|---------|
| **Anthropic Claude** | 0.39.0 | Strategy planning and code generation |
| **pandas** | 2.1.3 | Data manipulation and analysis |
| **scikit-learn** | 1.3.2 | ML algorithms and preprocessing |
| **LightGBM** | 4.1.0 | Gradient boosting models |
| **XGBoost** | 2.0.2 | Gradient boosting models |
| **Kaggle API** | 1.5.16 | Competition data download |
| **BeautifulSoup4** | 4.12.2 | Web scraping for competition metadata |

### Supporting Libraries

- **requests** - HTTP client for web scraping
- **numpy** - Numerical computing
- **httpx** - Async HTTP client for Anthropic SDK
- **lxml** - XML/HTML parsing

---

## Detailed Stage Breakdown

### Stage 1: Competition Analysis

**Duration**: 5-10 minutes  
**Module**: `kaggle-ml-agent/analyzer/competition_analyzer.py`

#### What It Does:

1. **Download Competition Data**
   ```python
   # Uses Kaggle CLI with environment variables
   subprocess.run(['kaggle', 'competitions', 'download', '-c', competition_name])
   ```
   - Downloads: train.csv, test.csv, sample_submission.csv
   - Extracts zip files automatically
   - Stores in `/shared/submissions/{job_id}/data/`

2. **Parse Submission Schema** ⭐ Key Feature
   ```python
   # Parse sample_submission.csv as source of truth
   submission_schema = {
       'id_column': 'PassengerId',
       'target_columns': ['Survived'],
       'expected_columns': ['PassengerId', 'Survived'],
       'expected_rows': 418,
       'target_info': {...}
   }
   ```
   - Identifies exact column names and order required
   - Determines target type (binary/multiclass/regression)
   - Extracts expected row count

3. **Identify Target Column**
   - **Strategy 1**: Match target from submission schema (most reliable)
   - **Strategy 2**: Find columns in train but not in test
   - **Strategy 3**: Common naming patterns (survived, target, label)
   - **Strategy 4**: Last column fallback

4. **Scrape Competition Metadata**
   ```python
   # Extract metric, description, task type from competition page
   metadata = {
       'metric': 'accuracy',  # or auc, rmse, etc.
       'description': '...',
       'task_indicators': ['survival', 'classification']
   }
   ```

#### Output:
```python
competition_info = {
    'name': 'titanic',
    'url': 'https://www.kaggle.com/c/titanic',
    'task_type': 'classification',
    'metric': 'accuracy',
    'target_column': 'Survived',
    'data_dir': '/shared/submissions/{job_id}/data',
    'submission_schema': {...},  # Full schema details
    'train_shape': (891, 12),
    'test_shape': (418, 11)
}
```

---

### Stage 2: Strategy Planning

**Duration**: 2-3 minutes  
**Module**: `kaggle-ml-agent/planner/strategy_planner.py`

#### What It Does:

1. **Build Context for AI**
   ```python
   context = f"""
   You are an expert data scientist analyzing a Kaggle competition.
   
   Competition: {name}
   Task Type: {task_type}
   Evaluation Metric: {metric}
   Train shape: {train_shape}
   Features: {num_features} columns
   
   Create a winning strategy...
   """
   ```

2. **Query Claude AI**
   ```python
   response = anthropic.Anthropic().messages.create(
       model="claude-sonnet-4-20250514",
       max_tokens=2000,
       messages=[{"role": "user", "content": context}]
   )
   ```

3. **Parse JSON Response**
   ```json
   {
     "approach": "Gradient boosting with feature engineering",
     "models": ["LightGBM", "XGBoost"],
     "feature_engineering": "Handle missing values, encode categoricals",
     "validation_strategy": "5-fold stratified cross-validation"
   }
   ```

4. **Fallback Strategy**
   - If Claude fails, use rule-based strategy
   - Classification: LightGBM + XGBoost with cross-validation
   - Regression: LightGBM + XGBoost with RMSE scoring

#### Output:
```python
strategy = {
    "approach": "Gradient boosting with cross-validation",
    "models": ["LightGBM", "XGBoost"],
    "feature_engineering": "Handle missing values, encode categoricals, scale numerics",
    "validation_strategy": "5-fold stratified cross-validation"
}
```

---

### Stage 3: Code Generation

**Duration**: 3-5 minutes (up to 3 attempts)  
**Module**: `kaggle-ml-agent/generator/code_generator.py`

#### What It Does:

1. **Multi-Attempt Generation with Feedback Loop**
   ```python
   for attempt in 1..3:
       code = generate_with_claude(feedback)
       is_valid, errors = validate_code(code)
       if is_valid:
           return code
       else:
           feedback = format_errors(errors)
   ```

2. **Static Code Validation**
   - ✅ Syntax valid (AST parsing)
   - ✅ Required imports present (pandas, numpy)
   - ✅ Target column referenced
   - ✅ Submission path correct (`/shared/.../submission.csv`)
   - ✅ Schema columns referenced
   - ✅ Data directory referenced
   - ✅ ML workflow present (fit, predict, to_csv)

3. **Enhanced Prompt with Schema**
   ```python
   prompt = f"""
   Generate a complete Python script for Kaggle competition.
   
   CRITICAL: submission.csv MUST have columns: {schema['expected_columns']}
   - ID Column: {id_column} (copy from test.csv)
   - Target: {target_columns}
   - Expected Rows: {expected_rows}
   
   Save to: {output_dir}/submission.csv
   """
   ```

4. **Template Fallback**
   - If all Claude attempts fail, use pre-built template
   - Separate templates for classification and regression
   - Templates include proper schema handling

#### Output:
```python
# generated_solution.py - Example snippet
import pandas as pd
from lightgbm import LGBMClassifier

# Load data
train = pd.read_csv("/shared/submissions/{job_id}/data/train.csv")
test = pd.read_csv("/shared/submissions/{job_id}/data/test.csv")

# Prepare features
X = train.drop(['Survived', 'PassengerId'], axis=1)
y = train['Survived']

# Train model
model = LGBMClassifier(n_estimators=500, random_state=42)
model.fit(X, y)

# Predict
predictions = model.predict(X_test)

# Create submission with exact schema
submission = pd.DataFrame({
    'PassengerId': test['PassengerId'],
    'Survived': predictions
})
submission.to_csv("/shared/submissions/{job_id}/submission.csv", index=False)
```

---

### Stage 4: Model Training & Validation

**Duration**: 20-60 minutes (depends on model complexity)  
**Module**: `kaggle-ml-agent/executor/model_executor.py` + `kaggle-ml-agent/validator/submission_validator.py`

#### What It Does:

1. **Execute Generated Code**
   ```python
   subprocess.run(['python', 'generated_solution.py'], timeout=6000)
   ```
   - 100-minute timeout
   - Captures stdout/stderr for debugging
   - Handles execution failures gracefully

2. **Comprehensive Validation** (6 checks)
   
   **Check 1: Column Validation**
   ```python
   # Verify exact column names and order
   expected = ['PassengerId', 'Survived']
   actual = submission.columns.tolist()
   assert actual == expected
   ```
   
   **Check 2: Row Count**
   ```python
   # Verify number of predictions matches test set
   assert len(submission) == expected_rows
   ```
   
   **Check 3: ID Matching**
   ```python
   # Verify IDs match test.csv exactly (same order)
   test_ids = pd.read_csv('test.csv')['PassengerId']
   assert (submission['PassengerId'] == test_ids).all()
   ```
   
   **Check 4: Target Values**
   ```python
   # Verify values are appropriate for target type
   if target_type == 'binary':
       assert submission['Survived'].isin([0, 1]).all()
   ```
   
   **Check 5: Null Values**
   ```python
   # No null values allowed
   assert not submission.isnull().any().any()
   ```
   
   **Check 6: Sanity Checks**
   ```python
   # Warning if all predictions are same
   if submission['Survived'].nunique() == 1:
       logger.warning("All predictions are the same value")
   ```

3. **Auto-Correction** ⭐ Key Feature
   
   If validation fails, attempt automatic fixes:
   
   ```python
   # Fix 1: Wrong column names
   if len(actual_cols) == len(expected_cols):
       submission.columns = expected_cols
   
   # Fix 2: Wrong ID order
   if set(submission_ids) == set(test_ids):
       submission = test_ids.merge(submission, on=id_col, how='left')
   
   # Fix 3: Label indexing (1/2 → 0/1)
   if set(unique_vals) == {1, 2}:
       submission[target] = submission[target] - 1
   
   # Fix 4: Fill null values
   submission.fillna(mode_value, inplace=True)
   ```

4. **Fallback Submission**
   
   If all else fails, create dummy submission with valid format:
   ```python
   fallback = pd.DataFrame({
       'PassengerId': test_df['PassengerId'],
       'Survived': 0  # Most common class
   })
   ```

#### Output:
```csv
# submission.csv
PassengerId,Survived
892,0
893,1
894,0
...
```

---

## Data Flow

### File System Structure

```
/shared/submissions/{job_id}/
├── data/
│   ├── train.csv                 # Downloaded training data
│   ├── test.csv                  # Downloaded test data
│   ├── sample_submission.csv     # Downloaded submission format
│   └── DATA_INFO.txt             # Metadata about files
├── generated_solution.py         # AI-generated Python script
└── submission.csv                # Final validated submission
```

### Database Schema

```sql
-- jobs table
CREATE TABLE jobs (
    id SERIAL PRIMARY KEY,
    job_id VARCHAR(36) UNIQUE NOT NULL,      -- UUID
    kaggle_url TEXT NOT NULL,
    competition_name VARCHAR(255),
    status VARCHAR(50) NOT NULL,              -- pending, running, completed, failed
    k8s_job_name VARCHAR(255),
    resources_requested JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    error_message TEXT,
    submission_path TEXT,
    logs TEXT
);
```

### Environment Variables

**Required:**
- `ANTHROPIC_API_KEY` - Claude API key for AI features
- `KAGGLE_USERNAME` - Kaggle username for data download
- `KAGGLE_KEY` - Kaggle API key for data download
- `DATABASE_URL` - PostgreSQL connection string

**Optional:**
- `K8S_NAMESPACE` - Kubernetes namespace (default: kaggle-agent)
- `AGENT_IMAGE` - Agent Docker image (default: kaggle-agent/agent:latest)
- `AGENT_AVAILABLE_LIBS` - Override available libraries list

---

## Lifecycle & State Management

### Job States

```
pending → running → completed
                 ↘ failed
```

**State Transitions:**

1. **pending** → **running**
   - Trigger: Controller creates K8s Job
   - Action: Agent pod starts executing

2. **running** → **completed**
   - Trigger: Agent successfully creates valid submission
   - Action: Update database with submission_path

3. **running** → **failed**
   - Trigger: Agent encounters unrecoverable error
   - Action: Update database with error_message

### Monitoring & Observability

**Logs:**
- Agent logs streamed to stdout
- Accessible via `kubectl logs <pod-name>`
- Stored in database `logs` column

**Metrics:**
- Job duration
- Success/failure rates
- Stage completion times

**Health Checks:**
- API: `/health` endpoint
- Controller: Kubernetes liveness probe
- Agent: Exit code (0=success, 1=failure)

---

## Configuration

### Resource Allocation

**Default Resources:**
```yaml
requests:
  cpu: "1"
  memory: "2Gi"
limits:
  cpu: "2"      # 2x requests
  memory: "4Gi" # 2x requests
```

**Configurable via API:**
```json
{
  "kaggle_url": "...",
  "resources": {
    "cpu": "2",
    "memory": "4Gi"
  }
}
```

### Timeouts

- **API Request**: 30 seconds
- **Job Creation**: No limit (async)
- **Agent Execution**: 7200 seconds (2 hours)
- **Code Execution**: 6000 seconds (100 minutes)
- **Data Download**: 600 seconds (10 minutes)

### Retry Policies

- **Code Generation**: 3 attempts with feedback
- **K8s Job**: 2 retries (backoffLimit: 2)
- **Auto-correction**: 1 attempt after validation failure

---

## API Reference

### Create Job

```http
POST /api/v1/jobs
Content-Type: application/json

{
  "kaggle_url": "https://www.kaggle.com/c/titanic",
  "resources": {
    "cpu": "1",
    "memory": "2Gi"
  }
}
```

**Response:**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending",
  "created_at": "2025-11-07T20:00:00Z"
}
```

### Get Job Status

```http
GET /api/v1/jobs/{job_id}
```

**Response:**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "completed",
  "competition_name": "titanic",
  "submission_path": "/shared/submissions/.../submission.csv",
  "created_at": "2025-11-07T20:00:00Z",
  "started_at": "2025-11-07T20:00:05Z",
  "completed_at": "2025-11-07T20:45:23Z"
}
```

### List Jobs

```http
GET /api/v1/jobs?status=completed&limit=10
```

### Get Logs

```http
GET /api/v1/jobs/{job_id}/logs
```

### Delete Job

```http
DELETE /api/v1/jobs/{job_id}
```

---

## Example: Complete Execution

### Input

```bash
curl -X POST http://localhost:8000/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{"kaggle_url": "https://www.kaggle.com/c/titanic"}'
```

### Logs Output

```
[STAGE 1] Analyzing competition...
✓ Data downloaded to /shared/submissions/{job_id}/data
✓ Submission schema: ['PassengerId', 'Survived']
✓ Target identified from submission schema: Survived
✓ Train data: (891, 12), target: Survived
✓ Test data: (418, 11)

[STAGE 2] Planning strategy...
Creating strategy with Claude...
✓ Strategy created with Claude
✓ Approach: Gradient boosting with feature engineering
✓ Models: LightGBM, XGBoost

[STAGE 3] Generating code with validation...
Generation attempt 1/3
✓ Code generated and validated successfully on attempt 1
✓ Code saved to generated_solution.py
✓ Code length: 5847 characters, 235 lines

[STAGE 4] Training model and creating submission...
Loading data...
Train shape: (891, 12), Test shape: (418, 11)
Features: 9, Target: Survived
Handling missing values...
Encoding categorical variables...
Training model...
CV Accuracy: 0.8237 (+/- 0.0234)
Model trained successfully
Making predictions...
✓ Submission saved to /shared/submissions/{job_id}/submission.csv
Submission shape: (418, 2)
Columns: ['PassengerId', 'Survived']

✓ Valid submission created: submission.csv
✓ Submission shape: (418, 2)
✓ Submission columns: ['PassengerId', 'Survived']

============================================================
SUCCESS: Agent completed successfully!
============================================================
```

### Output Files

```
/shared/submissions/550e8400-e29b-41d4-a716-446655440000/
├── data/
│   ├── train.csv              (113 KB, 892 rows)
│   ├── test.csv               (52 KB, 419 rows)
│   ├── gender_submission.csv  (5 KB, 419 rows)
│   └── DATA_INFO.txt          (1 KB)
├── generated_solution.py      (6 KB, 235 lines)
└── submission.csv             (5 KB, 419 rows)
```

---

## Performance Characteristics

### Timing Breakdown

| Stage | Typical Duration | Max Duration |
|-------|-----------------|--------------|
| Stage 1: Analysis | 5-10 minutes | 15 minutes |
| Stage 2: Planning | 2-3 minutes | 5 minutes |
| Stage 3: Generation | 3-5 minutes | 10 minutes |
| Stage 4: Training | 20-60 minutes | 100 minutes |
| **Total** | **30-80 minutes** | **120 minutes** |

### Success Rates

Based on reference implementation testing:

| Metric | Rate |
|--------|------|
| Target Detection | ~100% |
| Code Generation | ~90% |
| Validation Pass | ~95% |
| Overall Success | ~85% |

### Resource Usage

**Typical:**
- CPU: 1-2 cores
- Memory: 2-4 GB
- Storage: 100-500 MB per job

**Peak:**
- CPU: Up to 2 cores during training
- Memory: Up to 4 GB for large datasets
- Storage: Up to 1 GB for large competitions

---

## Error Handling & Recovery

### Common Errors & Solutions

| Error | Cause | Auto-Recovery | Manual Fix |
|-------|-------|---------------|------------|
| Auth Failed | Invalid Kaggle credentials | ❌ No | Update secrets |
| Target Not Found | Complex competition structure | ✅ Fallback to last column | Review logs |
| Code Syntax Error | LLM generation issue | ✅ Retry with feedback | Use template |
| Wrong Columns | Generated wrong format | ✅ Auto-rename | Regenerate code |
| Wrong ID Order | Sorting mismatch | ✅ Auto-reorder | Fix in code |
| All Same Predictions | Model/data issue | ⚠️ Warning only | Review data |

### Fallback Mechanisms

1. **Strategy**: Claude AI → Rule-based
2. **Code Gen**: Claude AI → Template
3. **Submission**: Generated → Auto-corrected → Fallback dummy
4. **Validation**: 6 checks → Auto-fix → Accept best effort

---

## Security Considerations

### Credentials Management

- ✅ API keys stored in Kubernetes Secrets
- ✅ Environment variables only (no files)
- ✅ Never logged or exposed in output
- ✅ Scoped to individual pods

### Code Execution

- ⚠️ Generated code executed without sandboxing
- ✅ Static validation before execution
- ✅ Resource limits prevent resource exhaustion
- ✅ Timeout prevents infinite loops

### Network Access

- ✅ Outbound only (Kaggle API, Claude API)
- ✅ No inbound connections to agent pods
- ✅ Internal services use Kubernetes networking

---

## Deployment

### Prerequisites

- Kubernetes cluster (Kind/EKS/GKE)
- Docker installed
- kubectl configured
- Secrets configured (ANTHROPIC_API_KEY, Kaggle credentials)

### Quick Deploy

```bash
# 1. Build images
docker build -f docker/Dockerfile.api -t kaggle-agent/api:latest .
docker build -f docker/Dockerfile.controller -t kaggle-agent/controller:latest .
docker build -f docker/Dockerfile.agent -t kaggle-agent/agent:latest .

# 2. Load to Kind (if using Kind)
kind load docker-image kaggle-agent/api:latest --name kaggle-agent-cluster
kind load docker-image kaggle-agent/controller:latest --name kaggle-agent-cluster
kind load docker-image kaggle-agent/agent:latest --name kaggle-agent-cluster

# 3. Apply Kubernetes manifests
kubectl apply -f kaggle-infrastructure/kind/namespace.yaml
kubectl apply -f kaggle-infrastructure/kind/postgres.yaml
kubectl apply -f kaggle-infrastructure/kind/storage.yaml
kubectl apply -f kaggle-infrastructure/kind/api.yaml
kubectl apply -f kaggle-infrastructure/kind/controller.yaml

# 4. Verify deployment
kubectl get pods -n kaggle-agent
```

---

## Monitoring & Debugging

### View Logs

```bash
# API logs
kubectl logs -f deployment/kaggle-api -n kaggle-agent

# Controller logs
kubectl logs -f deployment/kaggle-controller -n kaggle-agent

# Agent logs (active job)
kubectl get pods -n kaggle-agent -l app=kaggle-agent
kubectl logs -f <pod-name> -n kaggle-agent
```

### Check Job Status

```bash
# List all jobs
kubectl get jobs -n kaggle-agent

# Get job details
kubectl describe job <job-name> -n kaggle-agent

# Get pod details
kubectl get pods -n kaggle-agent -l job-name=<job-name>
```

### Access Files

```bash
# List submissions
ls -la /path/to/storage/submissions/

# View generated code
cat /path/to/storage/submissions/{job_id}/generated_solution.py

# View submission
cat /path/to/storage/submissions/{job_id}/submission.csv
```

---

## Future Enhancements

### Planned Features

- [ ] Multi-model ensembling
- [ ] Hyperparameter optimization with Optuna
- [ ] Automated feature engineering
- [ ] Competition leaderboard tracking
- [ ] Submission quality scoring
- [ ] Result visualization dashboard

### Scalability Improvements

- [ ] Horizontal pod autoscaling
- [ ] Job priority queues
- [ ] Distributed training support
- [ ] Caching for repeated competitions

---

## Support & Troubleshooting

### Common Issues

**Issue**: Claude API rate limits  
**Solution**: Implement exponential backoff, use fallback strategy

**Issue**: Large dataset download timeout  
**Solution**: Increase timeout, implement chunked download

**Issue**: Memory overflow during training  
**Solution**: Increase memory limits, implement data sampling

### Getting Help

1. Check logs: `kubectl logs <pod-name>`
2. Review generated code: `cat generated_solution.py`
3. Check validation errors in agent logs
4. Review architecture docs: `AGENT_ARCHITECTURE_V2.md`

---

## Version Information

- **Agent Version**: 2.0
- **API Version**: v1
- **Last Updated**: 2025-11-07
- **Python Version**: 3.11
- **Kubernetes Version**: 1.27+

---

## License & Credits

**Built with:**
- Anthropic Claude AI
- Kaggle API
- Kubernetes
- FastAPI
- PostgreSQL

**Architecture inspired by:** AutoML systems and autonomous agents research

---

*For detailed architecture information, see `AGENT_ARCHITECTURE_V2.md`*  
*For quick start guide, see `QUICK_START.md`*  
*For implementation details, see `IMPLEMENTATION_SUMMARY.md`*

