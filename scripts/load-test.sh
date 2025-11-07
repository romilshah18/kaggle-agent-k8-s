#!/bin/bash
# Simple bash-based load test using curl and parallel

set -e

# Configuration
API_URL="http://localhost:8080"
NUM_JOBS=${1:-50}
MAX_PARALLEL=20

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Competitions to test
COMPETITIONS=(
    "titanic"
    "house-prices-advanced-regression-techniques"
    "digit-recognizer"
    "nlp-getting-started"
    "spaceship-titanic"
    "playground-series-s3e1"
    "store-sales-time-series-forecasting"
    "tabular-playground-series-jan-2021"
    "jane-street-market-prediction"
    "santander-customer-transaction-prediction"
)

echo "=========================================="
echo "🚀 KAGGLE AGENT LOAD TEST (Bash)"
echo "=========================================="
echo "Target: $API_URL"
echo "Jobs to create: $NUM_JOBS"
echo "Max parallel: $MAX_PARALLEL"
echo "=========================================="
echo ""

# Check API health
echo "🔍 Checking API health..."
if curl -s -f "$API_URL/health" > /dev/null; then
    echo -e "${GREEN}✅ API is healthy${NC}"
    HEALTH=$(curl -s "$API_URL/health" | jq -r '.status')
    echo "   Status: $HEALTH"
else
    echo -e "${RED}❌ Cannot connect to API${NC}"
    exit 1
fi

echo ""
echo "🔥 Starting load test..."
echo ""

# Create temp directory for results
RESULT_DIR=$(mktemp -d)
SUCCESS_COUNT=0
FAILED_COUNT=0

# Function to create a single job
create_job() {
    local job_num=$1
    
    # Recreate competitions array from exported string
    IFS=' ' read -ra COMPS <<< "$COMPETITIONS_STR"
    
    local comp_idx=$((job_num % NUM_COMPETITIONS))
    local competition="${COMPS[$comp_idx]}"
    local priority=$((job_num % 3))
    
    local start_time=$(date +%s.%N)
    
    local response=$(curl -s -w "\n%{http_code}" -X POST "$API_URL/run" \
        -H "Content-Type: application/json" \
        -d "{
            \"kaggle_url\": \"https://www.kaggle.com/competitions/$competition\",
            \"priority\": $priority,
            \"resources\": {\"cpu\": \"1\", \"memory\": \"2Gi\"}
        }")
    
    local http_code=$(echo "$response" | tail -1)
    local body=$(echo "$response" | sed '$d')
    local end_time=$(date +%s.%N)
    local duration=$(echo "$end_time - $start_time" | bc)
    
    if [ "$http_code" = "201" ]; then
        local job_id=$(echo "$body" | jq -r '.job_id')
        echo "$job_num,$competition,$job_id,$duration,success" >> "$RESULT_DIR/results.csv"
        echo -e "${GREEN}✓${NC} Job $job_num: $competition (${duration}s)"
    else
        echo "$job_num,$competition,N/A,$duration,failed" >> "$RESULT_DIR/results.csv"
        echo -e "${RED}✗${NC} Job $job_num: Failed (HTTP $http_code)"
    fi
}

# Export variables for parallel execution
export -f create_job
export API_URL
export RESULT_DIR
export GREEN RED NC

# Export array as string and recreate in function
export COMPETITIONS_STR="${COMPETITIONS[*]}"
export NUM_COMPETITIONS="${#COMPETITIONS[@]}"

# Initialize results file
echo "job_num,competition,job_id,duration,status" > "$RESULT_DIR/results.csv"

# Create all jobs in parallel
TEST_START=$(date +%s)
seq 0 $((NUM_JOBS - 1)) | xargs -P $MAX_PARALLEL -I {} bash -c 'create_job {}'
TEST_END=$(date +%s)

TEST_DURATION=$((TEST_END - TEST_START))

echo ""
echo "=========================================="
echo "📊 LOAD TEST RESULTS"
echo "=========================================="
echo ""

# Count results (exclude header line)
SUCCESS_COUNT=$(grep -c "success" "$RESULT_DIR/results.csv" 2>/dev/null || echo "0")
FAILED_COUNT=$(grep -c "failed" "$RESULT_DIR/results.csv" 2>/dev/null || echo "0")
TOTAL=$((SUCCESS_COUNT + FAILED_COUNT))

# If TOTAL is 0, set it to 1 to avoid division by zero
if [ $TOTAL -eq 0 ]; then
    TOTAL=1
fi

echo "Duration:         ${TEST_DURATION}s"
echo "Total Requests:   $TOTAL"
if [ $TEST_DURATION -gt 0 ]; then
    echo "Requests/second:  $((TOTAL / TEST_DURATION))"
fi
echo ""
echo -e "${GREEN}✅ Successful:${NC}    $SUCCESS_COUNT ($((SUCCESS_COUNT * 100 / TOTAL))%)"
echo -e "${RED}❌ Failed:${NC}        $FAILED_COUNT ($((FAILED_COUNT * 100 / TOTAL))%)"
echo ""

# Show sample job IDs
if [ $SUCCESS_COUNT -gt 0 ]; then
    echo "🎯 Sample job IDs created:"
    grep "success" "$RESULT_DIR/results.csv" | head -5 | while IFS=',' read -r num comp job_id dur status; do
        echo "   - $job_id ($comp)"
    done
    echo ""
fi

# Calculate average response time
if [ -f "$RESULT_DIR/results.csv" ]; then
    AVG_TIME=$(awk -F',' 'NR>1 {sum+=$4; count++} END {if(count>0) print sum/count; else print 0}' "$RESULT_DIR/results.csv")
    echo "Average response time: ${AVG_TIME}s"
fi

echo ""
echo "=========================================="
echo ""

# Save detailed results
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
RESULT_FILE="load_test_results_${TIMESTAMP}.csv"
cp "$RESULT_DIR/results.csv" "$RESULT_FILE"
echo -e "💾 Results saved to: ${BLUE}$RESULT_FILE${NC}"

# Cleanup
rm -rf "$RESULT_DIR"

echo ""
echo "📝 Check Kubernetes pods:"
echo "   kubectl get pods -n kaggle-agent"
echo ""
echo "📊 Monitor jobs via API:"
echo "   curl http://localhost:8080/jobs | jq"
echo ""
echo "🔍 View cluster status:"
echo "   kubectl top nodes"
echo "   kubectl top pods -n kaggle-agent"
echo ""

