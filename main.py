import asyncio
import json
import random
import string
import time
from typing import Dict, List, Optional, Union

from tqdm import tqdm

import dns.asyncresolver
import dns.exception
import dns.resolver
from dns.name import Name

import errors


parent_domain = "google.com"
subdomain_file_path = "./subdomains-top1million-5000.txt"
output_file_path = "./resolved_subdomains.json"

# Concurrency controls how many DNS lookups are in-flight at once.
max_concurrent_requests = 200

# Rate limit controls overall DNS query rate (helps avoid bans/timeouts).
# Keep this conservative when using public resolvers.
requests_per_second = 200
burst_size = 400

resolved_subdomains: Dict[str, List[str]] = {}

dns_providers = [
    ["1.1.1.1", "1.0.0.1"],  # cloudflare
    ["8.8.8.8", "8.8.4.4"],  # google
    ["9.9.9.9", "149.112.112.112"],  # quad9
    ["208.67.222.222", "208.67.220.220"],  # opendns
    ["94.140.14.14", "94.140.15.15"],  # adguard
    ["185.228.168.9", "185.228.169.9"],  # cleanbrowsing
    ["76.76.2.0", "76.76.10.0"],  # control d
    ["64.6.64.6", "64.6.65.6"],  # verisign
    ["8.26.56.26", "8.20.247.20"],  # comodo
    ["95.85.95.85", "2.56.220.2"],  # gcore
]


def _flatten_dns_servers() -> List[str]:
    return [ip for pair in dns_providers for ip in pair]


DNS_SERVERS = _flatten_dns_servers()


def pick_nameserver() -> str:
    return random.choice(DNS_SERVERS)


def make_resolver(nameserver: str) -> dns.asyncresolver.Resolver:
    r = dns.asyncresolver.Resolver(configure=False)
    r.nameservers = [nameserver]
    # dnspython uses `timeout` per try and `lifetime` overall; we pass lifetime per call too.
    r.timeout = 1.5
    r.lifetime = 2.0
    return r


RESOLVER_POOL: List[dns.asyncresolver.Resolver] = [
    make_resolver(ns) for ns in DNS_SERVERS
]


def pick_resolver() -> dns.asyncresolver.Resolver:
    return random.choice(RESOLVER_POOL)


class TokenBucketLimiter:
    """Async token bucket limiter for stable, burst-friendly QPS."""

    def __init__(self, rate_per_second: float, capacity: int):
        self._rate = float(rate_per_second)
        self._capacity = float(capacity)
        self._tokens = float(capacity)
        self._updated_at = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: float = 1.0) -> None:
        if self._rate <= 0:
            return

        async with self._lock:
            while True:
                now = time.monotonic()
                elapsed = now - self._updated_at
                if elapsed > 0:
                    self._tokens = min(
                        self._capacity, self._tokens + elapsed * self._rate
                    )
                    self._updated_at = now

                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return

                missing = tokens - self._tokens
                sleep_for = missing / self._rate
                await asyncio.sleep(sleep_for)


def check_wildcard_dns(parent: Union[Name, str]):
    """Detect classic wildcard DNS by testing random hostnames.

    Note: Some large providers route many *valid* hostnames to shared frontends,
    which is different from wildcard DNS. This check only looks for the classic
    "random hostname resolves" behavior.
    """

    characters = string.ascii_letters + string.digits
    trials = 3
    hits = 0
    for _ in range(trials):
        random_string: str = "".join(random.choices(characters, k=25))
        hostname = f"{random_string}.{str(parent)}"
        try:
            r = pick_resolver()
            ans = r.resolve(hostname, rdtype="A", lifetime=2.0)
            # `resolve` returns an awaitable in asyncresolver
            answer = asyncio.get_event_loop().run_until_complete(
                ans
            )  # sync wrapper for startup
            if answer.rrset is not None and len(answer) > 0:
                hits += 1
        except (
            dns.resolver.NXDOMAIN,
            dns.resolver.NoAnswer,
            dns.resolver.NoNameservers,
            dns.asyncresolver.NoRootSOA,
            dns.asyncresolver.NotAbsolute,
            asyncio.TimeoutError,
            dns.resolver.LifetimeTimeout,
            dns.exception.DNSException,
        ):
            continue

    if hits >= 2:
        raise errors.WildcardDNSDetected("wildcard dns detected")


async def resolve_subdomain(
    hostname: Union[Name, str],
    timeout: int = 2,
    limiter: Optional[TokenBucketLimiter] = None,
    retries: int = 2,
) -> None:
    """
    attempt to resolve a subdomain.
    if successful, store the resolved ips in resolved_subdomains.
    """

    for attempt in range(retries + 1):
        if limiter is not None:
            await limiter.acquire(1.0)

        try:
            resolver = pick_resolver()
            answer = await resolver.resolve(
                str(hostname), rdtype="A", lifetime=float(timeout)
            )

            resolved_ips = sorted({str(record) for record in answer})
            normalized_name = str(answer.qname).rstrip(".")
            resolved_subdomains[normalized_name] = resolved_ips
            return

        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
            return

        except (
            dns.resolver.NoNameservers,
            asyncio.TimeoutError,
            dns.resolver.LifetimeTimeout,
            OSError,
            dns.exception.DNSException,
        ):
            # Backoff with jitter to reduce bans / resolver overload.
            if attempt >= retries:
                return
            await asyncio.sleep((0.15 * (2**attempt)) + random.uniform(0, 0.10))


def load_subdomains(file_path: str) -> List[str]:
    """
    read subdomains from file.
    """
    with open(file_path, "r", encoding="utf-8", errors="ignore") as file:
        subs = [line.strip() for line in file.readlines()]
    # Remove blanks and obvious duplicates (wordlists often contain them)
    return [s for s in dict.fromkeys(subs) if s]


async def run_resolution_pipeline():
    # Wildcard detection can be expensive/fragile on some targets; keep it as a safety gate.
    try:
        check_wildcard_dns(parent_domain)
    except errors.WildcardDNSDetected:
        print(f"[-] Aborting: Wildcard DNS detected for {parent_domain}")
        return

    subdomains = load_subdomains(subdomain_file_path)
    limiter = TokenBucketLimiter(
        rate_per_second=requests_per_second, capacity=burst_size
    )

    queue: asyncio.Queue[Optional[str]] = asyncio.Queue(
        maxsize=max_concurrent_requests * 5
    )
    pbar = tqdm(total=len(subdomains), desc="Scanning", unit="subs")
    pbar_lock = asyncio.Lock()

    async def worker() -> None:
        while True:
            hostname = await queue.get()
            try:
                if hostname is None:
                    return
                await resolve_subdomain(hostname, timeout=2, limiter=limiter, retries=2)
            finally:
                async with pbar_lock:
                    pbar.update(1)
                queue.task_done()

    workers = [asyncio.create_task(worker()) for _ in range(max_concurrent_requests)]

    print(f"[*] Starting scan on {parent_domain} ({len(subdomains)} subdomains)...")
    for subdomain in subdomains:
        await queue.put(f"{subdomain}.{parent_domain}")

    for _ in workers:
        await queue.put(None)

    await queue.join()
    await asyncio.gather(*workers)
    pbar.close()

    with open(output_file_path, "w", encoding="utf-8") as f:
        json.dump(resolved_subdomains, f, indent=2, sort_keys=True)

    print(f"[*] Scan complete. {len(resolved_subdomains)} valid subdomains found.")
    print(f"[*] Wrote results to {output_file_path}")


if __name__ == "__main__":
    asyncio.run(run_resolution_pipeline())
