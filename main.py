import string
import random
import asyncio
import pprint
from typing import Dict, List, Union
from tqdm.asyncio import tqdm
import dns.asyncresolver
import dns.resolver
from dns.name import Name

import errors


parent_domain = "google.com"
subdomain_file_path = "./subdomains-top1million-5000.txt"

max_concurrent_requests = 100
requests_per_second = 1000  # not currently enforced

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


def pick_resolver():
    return random.choice(random.choice(dns_providers))


def check_wildcard_dns(parent: Union[Name, str]):
    # generate a random subdomain
    characters = string.ascii_letters + string.digits
    random_string: str = "".join(random.choices(characters, k=25))

    hostname = random_string + "." + str(parent)

    wildcard_dns = False
    try:
        resolver = pick_resolver()
        # Note: Added a dot between random_string and parent above
        answer = dns.resolver.resolve(hostname, lifetime=2)
        wildcard_dns = True
    except (
        dns.asyncresolver.NXDOMAIN,
        dns.asyncresolver.NoAnswer,
        dns.asyncresolver.NoRootSOA,
        dns.asyncresolver.NotAbsolute,
        asyncio.TimeoutError,
        dns.resolver.LifetimeTimeout
    ):
        pass

    finally:
        if wildcard_dns:
            raise errors.WildcardDNSDetected("wildcard dns detected")


async def resolve_subdomain(
    hostname: Union[Name, str],
    timeout: int = 2,
) -> None:
    """
    attempt to resolve a subdomain.
    if successful, store the resolved ips in resolved_subdomains.
    """

    try:
        resolver = pick_resolver()
        answer = await dns.asyncresolver.resolve_at(
            resolver, hostname, lifetime=timeout
        )
    except (
        dns.asyncresolver.NXDOMAIN,
        dns.asyncresolver.NoAnswer,
        dns.asyncresolver.NoRootSOA,
        dns.asyncresolver.NotAbsolute,
        asyncio.TimeoutError,
    ):
        return

    resolved_ips = [str(record) for record in answer]
    normalized_name = str(answer.qname).rstrip(".")

    resolved_subdomains[normalized_name] = resolved_ips


async def bounded_resolve(
    semaphore: asyncio.Semaphore,
    hostname: Union[Name, str],
    timeout: int = 2,
    ):
    """
    wrap resolver with concurrency control.
    """
    async with semaphore:
        await resolve_subdomain(hostname, timeout)


def load_subdomains(file_path: str) -> List[str]:
    """
    read subdomains from file.
    """
    with open(file_path, "r") as file:
        return [line.strip() for line in file.readlines()]


async def run_resolution_pipeline():
    try:
        check_wildcard_dns(parent_domain)
    except errors.WildcardDNSDetected:
        print(f"[-] Aborting: Wildcard DNS detected for {parent_domain}")
        return

    subdomains = load_subdomains(subdomain_file_path)
    semaphore = asyncio.Semaphore(max_concurrent_requests)

    tasks = [
        bounded_resolve(
            semaphore,
            f"{subdomain}.{parent_domain}",
        )
        for subdomain in subdomains
    ]

    print(f"[*] Starting scan on {parent_domain} ({len(tasks)} subdomains)...")
    
    await tqdm.gather(*tasks, desc="Scanning", unit="subs")

    print("\n" + "="*30)
    pprint.pprint(resolved_subdomains)
    print("="*30)
    print(f"[*] Scan complete. {len(resolved_subdomains)} valid subdomains found.")

if __name__ == "__main__":
    asyncio.run(run_resolution_pipeline())
