# scripts/benchmark.py
import asyncio
import httpx
import time
import statistics

URL = "http://localhost:8000/v1/chat"

# Mix of unique and paraphrased prompts to simulate real traffic + cache hits
PROMPTS = [
    "how do I reverse a string in python",
    "what is the way to flip a string in python",      # semantic dupe of above
    "explain binary search algorithm",
    "how does binary search work",                     # semantic dupe
    "what is a hash map in programming",
    "explain hash tables",                             # semantic dupe
    "what is a linked list",
    "how do linked lists work",                        # semantic dupe
    "what is recursion in programming",
    "explain the concept of recursion",                # semantic dupe
]

async def fire(client: httpx.AsyncClient, prompt: str):
    start = time.monotonic()
    try:
        r = await client.post(
            URL,
            json={"messages": [{"role": "user", "content": prompt}]},
            timeout=30.0
        )
        latency = (time.monotonic() - start) * 1000
        return latency, r.status_code
    except Exception as e:
        print(f"  ✗ Request failed: {e}")
        return None, 0

async def run_benchmark(concurrency: int, total_requests: int):
    print(f"\n{'='*50}")
    print(f"Concurrency: {concurrency} | Total requests: {total_requests}")
    print(f"{'='*50}")

    async with httpx.AsyncClient() as client:
        # warm up cache with first pass
        print("  Warming cache...")
        warm_tasks = [fire(client, p) for p in PROMPTS]
        await asyncio.gather(*warm_tasks)

        # actual benchmark
        print(f"  Running {total_requests} requests at concurrency {concurrency}...")
        tasks = [fire(client, PROMPTS[i % len(PROMPTS)]) for i in range(total_requests)]

        results = []
        for i in range(0, len(tasks), concurrency):
            batch = tasks[i:i + concurrency]
            batch_results = await asyncio.gather(*batch)
            results.extend(batch_results)

    latencies = sorted([l for l, s in results if l is not None and s == 200])
    errors = sum(1 for _, s in results if s != 200)
    rate_limited = sum(1 for _, s in results if s == 429)

    if not latencies:
        print("  ✗ No successful requests")
        return

    p50 = statistics.median(latencies)
    p95 = latencies[int(len(latencies) * 0.95)]
    p99 = latencies[int(len(latencies) * 0.99)]
    avg = statistics.mean(latencies)

    print(f"\n  Results:")
    print(f"  Successful : {len(latencies)}/{total_requests}")
    print(f"  Errors     : {errors} | Rate limited: {rate_limited}")
    print(f"  p50        : {p50:.1f}ms")
    print(f"  p95        : {p95:.1f}ms")
    print(f"  p99        : {p99:.1f}ms")
    print(f"  avg        : {avg:.1f}ms")

    return {"concurrency": concurrency, "p50": p50, "p95": p95, "p99": p99}

async def main():
    print("\n🚀 llmgateway Benchmark")
    print("Make sure uvicorn is running on localhost:8000\n")

    results = []
    for concurrency in [10, 50, 100]:
        r = await run_benchmark(concurrency, total_requests=100)
        if r:
            results.append(r)
        await asyncio.sleep(3)  # let rate limiter buckets refill

    # print final table
    print(f"\n{'='*50}")
    print("BENCHMARK SUMMARY")
    print(f"{'='*50}")
    print(f"{'Concurrency':<15} {'p50':>8} {'p95':>8} {'p99':>8}")
    print(f"{'-'*15} {'-'*8} {'-'*8} {'-'*8}")
    for r in results:
        print(f"{r['concurrency']:<15} {r['p50']:>7.1f}ms {r['p95']:>7.1f}ms {r['p99']:>7.1f}ms")
    print(f"\nPaste these numbers into your README benchmark table.")

asyncio.run(main())