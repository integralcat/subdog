# How The Script Works

`subdog` is a fast async DNS brute-forcer/resolver.

Given:
- a parent domain (example: `example.com`)
- a wordlist of candidate subdomains (example: `www`, `api`, `dev` ...)

It builds fully-qualified hostnames (`{sub}.{parent}`) and resolves `A` records
using `dnspython`.

## Pipeline

1. Wildcard DNS check (optional)
2. Load wordlist
3. Create a rate limiter (token bucket)
4. Start a worker pool (bounded concurrency)
5. For each hostname:
   - wait for a token (rate limiting)
   - query a public resolver (rotates through `DNS_SERVERS`)
   - store returned IPv4 addresses in memory
6. Dump results to JSON

## Key Implementation Details

## Wildcard Detection

If wildcard detection is enabled, the script tries a few random subdomains like
`<random>.example.com`.

If multiple random names resolve successfully, that strongly suggests wildcard
DNS is in place (many or all names resolve), and the scan is aborted to avoid a
wall of false positives.

## Concurrency

The resolver uses an `asyncio.Queue` and N workers.

- `--concurrency` controls how many resolver tasks run at once.
- A sentinel `None` value is pushed N times to stop workers cleanly.

## Rate Limiting (Token Bucket)

The `TokenBucketLimiter` refills tokens over time at `--rps` and caps at
`--burst`.

- `--rps` sets the long-run average query rate.
- `--burst` allows short spikes until tokens run out.

Each DNS lookup consumes 1 token.

## Retries

Transient failures (timeouts, temporary resolver errors, network errors) are
retried up to `--retries` with exponential backoff plus jitter.

NXDOMAIN / NoAnswer are treated as terminal (the hostname likely does not
exist).

## Output

The script writes a JSON object mapping hostname -> list of IPv4 addresses.
