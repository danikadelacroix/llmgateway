"""
Infrastructure Performance Benchmark Script for llmgateway.
Simulates high-concurrency client workloads to validate L1/L2 cache efficiency
and isolate tail latency percentiles (p50, p95, p99).
"""

import asyncio
import logging
import statistics
import time
import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("llmgateway-benchmark")

TARGET_URL = "http://localhost:8000/v1/chat"

# Evaluation dataset simulating overlapping production semantic domains
BENCHMARK_DATASET = [
    "how do I reverse a string in python",
    "what is the way to flip a string in python",
    "explain binary search algorithm",
    "how does binary search work",
    "what is a hash map in programming",
    "explain hash tables",
    "what is a linked list",
    "how do linked lists work",
    "what is recursion in programming",
    "explain the concept of recursion",
]

async def execute_request(client: httpx.AsyncClient, prompt: str) -> tuple[float | None, int]:
    """Executes an isolated POST request against the gateway proxy and tracks latency."""
    start_time = time.monotonic()
    try:
        response = await client.post(
            TARGET_URL,
            json={"messages": [{"role": "user", "content": prompt}]},
            timeout=30.0
        )
        latency_ms = (time.monotonic() - start_time) * 1000
        return latency_ms, response.status_code
    except Exception as e:
        logger.debug(f"Connection dropped or timed out: {str(e)}")
        return None, 0

async def evaluate_load_tier(concurrency: int, total_requests: int) -> dict | None:
    """Evaluates gateway infrastructure stability under specific concurrency bounds."""
    logger.info(f"Initializing evaluation tier | Concurrency: {concurrency} | Total Loads: {total_requests}")

    async with httpx.AsyncClient() as client:
        # Step 1: Warm up the distributed cache layers
        warmup_tasks = [execute_request(client, prompt) for prompt in BENCHMARK_DATASET]
        await asyncio.gather(*warmup_tasks)

        tasks = [execute_request(client, BENCHMARK_DATASET[i % len(BENCHMARK_DATASET)]) for i in range(total_requests)]
        
        raw_results = []
        for i in range(0, len(tasks), concurrency):
            batch = tasks[i:i + concurrency]
            batch_responses = await asyncio.gather(*batch)
            raw_results.extend(batch_responses)

    valid_latencies = sorted([lat for lat, status in raw_results if lat is not None and status == 200])
    error_count = sum(1 for _, status in raw_results if status != 200)
    rate_limited_count = sum(1 for _, status in raw_results if status == 429)

    if not valid_latencies:
        logger.error(f"Tier execution failed: 0/ {total_requests} requests returned HTTP 200")
        return None

    p50 = statistics.median(valid_latencies)
    p95 = valid_latencies[int(len(valid_latencies) * 0.95)]
    p99 = valid_latencies[int(len(valid_latencies) * 0.99)]
    avg = statistics.mean(valid_latencies)

    logger.info(f"Tier complete | Success: {len(valid_latencies)}/{total_requests} | 429 Blocks: {rate_limited_count}")
    
    return {
        "concurrency": concurrency, 
        "p50": p50, 
        "p95": p95, 
        "p99": p99, 
        "avg": avg, 
        "errors": error_count
    }

async def main():
    logger.info("Starting automated llmgateway regression benchmarks...")
    
    evaluation_tiers = [10, 50, 100]
    aggregated_metrics = []

    for concurrency in evaluation_tiers:
        metrics = await evaluate_load_tier(concurrency, total_requests=100)
        if metrics:
            aggregated_metrics.append(metrics)
        await asyncio.sleep(2.0) 
    print("\n" + "="*60)
    print("                      SYSTEM BENCHMARK SUMMARY")
    print("="*60)
    print(f"{'CONCURRENCY':<15} {'p50 (ms)':>10} {'p95 (ms)':>10} {'p99 (ms)':>10} {'ERRORS':>10}")
    print(f"{'-'*14:<15} {'-'*9:>10} {'-'*9:>10} {'-'*9:>10} {'-'*9:>10}")
    
    for record in aggregated_metrics:
        print(f"{record['concurrency']:<15} {record['p50']:>10.1f} {record['p95']:>10.1f} {record['p99']:>10.1f} {record['errors']:>10}")
    print("="*60 + "\n")

if __name__ == "__main__":
    asyncio.run(main())
