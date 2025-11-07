#!/usr/bin/env python3
"""
Load Testing Script for Kaggle Agent K8s
Creates multiple parallel job submissions to test scaling
"""

import asyncio
import aiohttp
import time
import json
from datetime import datetime
from typing import List, Dict
import sys

# Configuration
API_BASE_URL = "http://localhost:8080"
NUM_JOBS = 50
TIMEOUT = 30  # seconds per request

# Various Kaggle competition URLs for testing
COMPETITION_URLS = [
    "https://www.kaggle.com/competitions/titanic",
    "https://www.kaggle.com/competitions/house-prices-advanced-regression-techniques",
    "https://www.kaggle.com/competitions/digit-recognizer",
    "https://www.kaggle.com/competitions/nlp-getting-started",
    "https://www.kaggle.com/competitions/spaceship-titanic",
    "https://www.kaggle.com/competitions/playground-series-s3e1",
    "https://www.kaggle.com/competitions/store-sales-time-series-forecasting",
    "https://www.kaggle.com/competitions/tabular-playground-series-jan-2021",
    "https://www.kaggle.com/competitions/jane-street-market-prediction",
    "https://www.kaggle.com/competitions/santander-customer-transaction-prediction",
]


class LoadTester:
    def __init__(self, num_jobs: int = NUM_JOBS):
        self.num_jobs = num_jobs
        self.results = []
        self.start_time = None
        self.end_time = None
        
    async def create_job(self, session: aiohttp.ClientSession, job_num: int) -> Dict:
        """Create a single job"""
        # Cycle through competition URLs
        competition_url = COMPETITION_URLS[job_num % len(COMPETITION_URLS)]
        
        payload = {
            "kaggle_url": competition_url,
            "priority": job_num % 3,  # Vary priorities (0, 1, 2)
            "resources": {
                "cpu": "1",
                "memory": "2Gi"
            }
        }
        
        job_start = time.time()
        
        try:
            async with session.post(
                f"{API_BASE_URL}/run",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=TIMEOUT)
            ) as response:
                response_time = time.time() - job_start
                
                if response.status == 201:
                    data = await response.json()
                    return {
                        "job_num": job_num,
                        "status": "success",
                        "response_time": response_time,
                        "job_id": data.get("job_id"),
                        "k8s_job_name": data.get("k8s_job_name"),
                        "competition": competition_url.split("/")[-1]
                    }
                else:
                    error_text = await response.text()
                    return {
                        "job_num": job_num,
                        "status": "failed",
                        "response_time": response_time,
                        "error": f"HTTP {response.status}: {error_text}",
                        "competition": competition_url.split("/")[-1]
                    }
                    
        except asyncio.TimeoutError:
            return {
                "job_num": job_num,
                "status": "timeout",
                "response_time": TIMEOUT,
                "error": "Request timeout",
                "competition": competition_url.split("/")[-1]
            }
        except Exception as e:
            return {
                "job_num": job_num,
                "status": "error",
                "response_time": time.time() - job_start,
                "error": str(e),
                "competition": competition_url.split("/")[-1]
            }
    
    async def run_load_test(self):
        """Run the load test"""
        print("=" * 80)
        print(f"🚀 KAGGLE AGENT LOAD TEST")
        print("=" * 80)
        print(f"Target: {API_BASE_URL}")
        print(f"Jobs to create: {self.num_jobs}")
        print(f"Timeout per request: {TIMEOUT}s")
        print(f"Competitions: {len(COMPETITION_URLS)} different URLs")
        print("=" * 80)
        print()
        
        # Check API health first
        print("🔍 Checking API health...")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{API_BASE_URL}/health") as response:
                    if response.status == 200:
                        health = await response.json()
                        print(f"✅ API Status: {health.get('status')}")
                        print(f"   Pending jobs: {health.get('pending_jobs', 0)}")
                        print(f"   Running jobs: {health.get('running_jobs', 0)}")
                    else:
                        print(f"⚠️  API returned status {response.status}")
        except Exception as e:
            print(f"❌ Cannot connect to API: {e}")
            print("   Make sure the API is running at", API_BASE_URL)
            sys.exit(1)
        
        print()
        print("🔥 Starting load test in 3 seconds...")
        await asyncio.sleep(3)
        print()
        
        # Start the load test
        self.start_time = time.time()
        
        # Create all jobs in parallel
        async with aiohttp.ClientSession() as session:
            tasks = [
                self.create_job(session, i)
                for i in range(self.num_jobs)
            ]
            
            # Show progress
            print(f"📤 Sending {self.num_jobs} parallel requests...")
            self.results = await asyncio.gather(*tasks)
        
        self.end_time = time.time()
        
        # Print results
        self.print_results()
        
        # Save detailed results
        self.save_results()
        
        # Monitor job execution
        await self.monitor_jobs()
    
    def print_results(self):
        """Print test results"""
        duration = self.end_time - self.start_time
        
        successful = [r for r in self.results if r["status"] == "success"]
        failed = [r for r in self.results if r["status"] == "failed"]
        errors = [r for r in self.results if r["status"] == "error"]
        timeouts = [r for r in self.results if r["status"] == "timeout"]
        
        response_times = [r["response_time"] for r in self.results]
        avg_response_time = sum(response_times) / len(response_times)
        min_response_time = min(response_times)
        max_response_time = max(response_times)
        
        print()
        print("=" * 80)
        print("📊 LOAD TEST RESULTS")
        print("=" * 80)
        print()
        print(f"Total Duration:        {duration:.2f}s")
        print(f"Total Requests:        {self.num_jobs}")
        print(f"Requests/second:       {self.num_jobs / duration:.2f}")
        print()
        print(f"✅ Successful:         {len(successful)} ({len(successful)/self.num_jobs*100:.1f}%)")
        print(f"❌ Failed:             {len(failed)} ({len(failed)/self.num_jobs*100:.1f}%)")
        print(f"⏱️  Timeouts:           {len(timeouts)} ({len(timeouts)/self.num_jobs*100:.1f}%)")
        print(f"💥 Errors:             {len(errors)} ({len(errors)/self.num_jobs*100:.1f}%)")
        print()
        print(f"Response Times:")
        print(f"  Average:             {avg_response_time:.3f}s")
        print(f"  Min:                 {min_response_time:.3f}s")
        print(f"  Max:                 {max_response_time:.3f}s")
        print()
        
        if successful:
            print(f"🎯 Job IDs created: {len(successful)}")
            print("   Sample job IDs:")
            for result in successful[:5]:
                print(f"   - {result['job_id']} ({result['competition']})")
            if len(successful) > 5:
                print(f"   ... and {len(successful) - 5} more")
        
        if failed or errors:
            print()
            print("⚠️  Errors encountered:")
            for result in (failed + errors)[:5]:
                print(f"   Job {result['job_num']}: {result.get('error', 'Unknown')}")
        
        print()
        print("=" * 80)
    
    def save_results(self):
        """Save detailed results to file"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"load_test_results_{timestamp}.json"
        
        output = {
            "test_config": {
                "num_jobs": self.num_jobs,
                "api_url": API_BASE_URL,
                "timeout": TIMEOUT,
                "timestamp": datetime.now().isoformat()
            },
            "summary": {
                "duration": self.end_time - self.start_time,
                "total_requests": self.num_jobs,
                "successful": len([r for r in self.results if r["status"] == "success"]),
                "failed": len([r for r in self.results if r["status"] != "success"]),
                "avg_response_time": sum(r["response_time"] for r in self.results) / len(self.results)
            },
            "results": self.results
        }
        
        with open(filename, 'w') as f:
            json.dump(output, f, indent=2)
        
        print(f"💾 Detailed results saved to: {filename}")
        print()
    
    async def monitor_jobs(self):
        """Monitor the execution of created jobs"""
        successful_jobs = [r for r in self.results if r["status"] == "success"]
        
        if not successful_jobs:
            print("⚠️  No jobs were created successfully. Skipping monitoring.")
            return
        
        job_ids = [r["job_id"] for r in successful_jobs]
        
        print()
        print("=" * 80)
        print("👀 MONITORING JOB EXECUTION")
        print("=" * 80)
        print(f"Tracking {len(job_ids)} jobs...")
        print("Press Ctrl+C to stop monitoring")
        print()
        
        try:
            async with aiohttp.ClientSession() as session:
                for i in range(60):  # Monitor for up to 5 minutes
                    # Get status counts
                    status_counts = {
                        "pending": 0,
                        "queued": 0,
                        "running": 0,
                        "success": 0,
                        "failed": 0
                    }
                    
                    for job_id in job_ids[:10]:  # Sample first 10 jobs
                        try:
                            async with session.get(
                                f"{API_BASE_URL}/status/{job_id}",
                                timeout=aiohttp.ClientTimeout(total=5)
                            ) as response:
                                if response.status == 200:
                                    data = await response.json()
                                    status = data.get("status", "unknown")
                                    if status in status_counts:
                                        status_counts[status] += 1
                        except:
                            pass
                    
                    # Print status
                    print(f"[{i*5}s] Pending: {status_counts['pending']} | "
                          f"Queued: {status_counts['queued']} | "
                          f"Running: {status_counts['running']} | "
                          f"Success: {status_counts['success']} | "
                          f"Failed: {status_counts['failed']}")
                    
                    # Check if all done
                    if status_counts["success"] + status_counts["failed"] == len(job_ids[:10]):
                        print()
                        print("✅ All monitored jobs completed!")
                        break
                    
                    await asyncio.sleep(5)
                    
        except KeyboardInterrupt:
            print()
            print("⏸️  Monitoring stopped by user")


async def main():
    """Main entry point"""
    num_jobs = NUM_JOBS
    
    # Allow custom number of jobs from command line
    if len(sys.argv) > 1:
        try:
            num_jobs = int(sys.argv[1])
        except ValueError:
            print(f"Invalid number of jobs: {sys.argv[1]}")
            sys.exit(1)
    
    tester = LoadTester(num_jobs=num_jobs)
    await tester.run_load_test()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print()
        print("👋 Load test interrupted by user")
        sys.exit(0)

