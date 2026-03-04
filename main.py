import time
import json
import string
import random
import asyncio
from typing import List, Dict, Optional, Sequence, Union

import dns.name
import dns.resolver
import dns.asyncresolver
import dns.exception
from tqdm import tqdm

class WildcardDNSDetected(Exception): pass

DEFAULT_PARENT_DOMAIN = "google.com"
DEFAULT_WORDLIST_PATH = "./subdomains-top1million-5000.txt"
DEFAULT_OUTPUT_PATH = "./resolved_subdomains.json"

DEFAULT_MAX_CONCURRENT_REQUESTS = 200
DEFAULT_REQUESTS_PER_SECOND = 1000
DEFAULT_BURST_SIZE = 500
DEFAULT_TIMEOUT_SECONDS = 2.0
DEFAULT_RETRIES = 2

DNS_SERVERS = [
    "1.1.1.1", "1.0.0.1", "8.8.8.8", "8.8.4.4",
    "9.9.9.9", "149.112.112.112", "208.67.222.222", "208.67.220.220"
]

class TokenBucketLimiter:
    """Async token bucket limiter for stable, burst-friendly QPS/RPS"""
    def __init__(self, capacity: float, rps: float):
        self._capacity = capacity
        self._rps = rps
        self._tokens = capacity
        self._last_update = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: float = 1.0):
        if self._rps <= 0: return
        async with self._lock:
            while True:
                now = time.monotonic()
                elapsed = now - self._last_update
                self._tokens = min(self._capacity, self._tokens + self._rps * elapsed)
                self._last_update = now

                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                await asyncio.sleep((tokens - self._tokens) / self._rps)



async def check_wildcard_dns(
    parent: str,
    trials: int = 3,
    hits_to_fail: int = 2,
    timeout: float = 2.0,
) -> None:
    characters = string.ascii_letters + string.digits
    hits = 0
    for _ in range(trials):
        rand = "".join(random.choices(characters, k=25))
        try:
            await dns.asyncresolver.resolve(f"{rand}.{parent}", "A", lifetime=timeout)
            hits += 1
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.exception.DNSException):
            continue
    if hits >= hits_to_fail:
        raise WildcardDNSDetected(f"Wildcard detected for {parent}")

async def resolve_subdomain(
    hostname: str,
    results: Dict[str, List[str]],
    limiter: TokenBucketLimiter,
    timeout: float,
    retries: int,
):
    for attempt in range(retries + 1):
        await limiter.acquire(1.0)
        try:
            resolver_ip = random.choice(DNS_SERVERS)
            # resolve_at is used to rotate public resolvers and avoid local cache
            answer = await dns.asyncresolver.resolve_at(resolver_ip, hostname, "A", lifetime=timeout)
            
            # FIXED: Actually extract and store the results
            results[hostname] = [str(rdata) for rdata in answer]
            return

        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
            return  # Terminal: Subdomain does not exist
        except (dns.resolver.NoNameservers, asyncio.TimeoutError, dns.exception.DNSException, OSError):
            if attempt < retries:
                # Exponential backoff with jitter
                await asyncio.sleep((0.2 * 2**attempt) + random.uniform(0, 0.1))
                continue
            return

async def run_resolution_pipeline(
    parent_domain: str,
    subdomain_file_path: str,
    output_file_path: str,
    **kwargs
):
    # Setup
    max_concurrent = kwargs.get('max_concurrent', DEFAULT_MAX_CONCURRENT_REQUESTS)
    resolved_subdomains: Dict[str, List[str]] = {}
    
    if kwargs.get('wildcard_check', True):
        try:
            await check_wildcard_dns(parent_domain)
        except WildcardDNSDetected as e:
            print(f"[-] {e}")
            return {}

    # Load wordlist
    with open(subdomain_file_path, 'r') as f:
        subdomains = [line.strip() for line in f if line.strip()]

    limiter = TokenBucketLimiter(kwargs.get('burst', DEFAULT_BURST_SIZE), kwargs.get('rps', DEFAULT_REQUESTS_PER_SECOND))
    queue = asyncio.Queue(maxsize=max_concurrent * 2)
    pbar = tqdm(total=len(subdomains), desc="Scanning", unit="subs")

    async def worker():
        while True:
            hostname = await queue.get()
            try:
                if hostname is None: break
                await resolve_subdomain(
                    hostname, 
                    resolved_subdomains, 
                    limiter, 
                    kwargs.get('timeout', DEFAULT_TIMEOUT_SECONDS),
                    kwargs.get('retries', DEFAULT_RETRIES)
                )
            finally:
                # Ensure task_done is called even for None to prevent queue.join() hang
                queue.task_done()
                if hostname is not None:
                    pbar.update(1)

    # Give Birth to workers ;)
    workers = [asyncio.create_task(worker()) for _ in range(max_concurrent)]

    # Populate queue
    for sub in subdomains:
        await queue.put(f"{sub}.{parent_domain}")
    
    # Sentinel values to kill workers :(
    for _ in range(max_concurrent):
        await queue.put(None)

    await queue.join()
    await asyncio.gather(*workers)
    pbar.close()

    with open(output_file_path, "w") as f:
        json.dump(resolved_subdomains, f, indent=2)
    
    print(f"[*] Done. Found {len(resolved_subdomains)} subdomains. Saved to {output_file_path}")
    return resolved_subdomains

def main():
    asyncio.run(run_resolution_pipeline(
        parent_domain=DEFAULT_PARENT_DOMAIN,
        subdomain_file_path=DEFAULT_WORDLIST_PATH,
        output_file_path=DEFAULT_OUTPUT_PATH
    ))

if __name__ == "__main__":
    main()
