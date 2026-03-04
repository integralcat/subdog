# Using subdog

`subdog` resolves `A` records for candidate subdomains under a parent domain.

## Install

Python: `>= 3.11`

Install `uv`:

macOS / Linux:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Windows (PowerShell):

```powershell
irm https://astral.sh/uv/install.ps1 | iex
```

With `uv`:

```bash
uv sync
```

With `pip`:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install "dnspython>=2.8.0" "tqdm>=4.67.3" "trio>=0.33.0"
```

## Configure

`main.py` currently runs using module-level defaults (there are no CLI flags yet).
To configure it, edit the constants near the top of `main.py`:

- `DEFAULT_PARENT_DOMAIN`
- `DEFAULT_WORDLIST_PATH`
- `DEFAULT_OUTPUT_PATH`
- `DEFAULT_MAX_CONCURRENT_REQUESTS`
- `DEFAULT_REQUESTS_PER_SECOND`
- `DEFAULT_BURST_SIZE`
- `DEFAULT_TIMEOUT_SECONDS`
- `DEFAULT_RETRIES`
- `DNS_SERVERS` (optional)

## Run

As a script:

```bash
python3 main.py
```

With `uv`:

```bash
uv run python main.py
```

## Output Format

The output is a JSON object of `hostname -> [ipv4, ...]`:

```json
{
  "www.example.com": ["93.184.216.34"],
  "api.example.com": ["203.0.113.10", "203.0.113.11"]
}
```

## Useful Flags

- `-w, --wordlist` wordlist file (one subdomain per line)
- `-o, --output` output JSON path
- `-c, --concurrency` max in-flight DNS lookups
- `--rps` target queries/sec (token bucket refill rate)
- `--burst` token bucket capacity (allows short bursts)
- `--timeout` per-query timeout seconds
- `--retries` retries on transient errors
- `--nameservers` override DNS resolvers (space-separated IPs)
- `--no-wildcard-check` disable wildcard DNS detection

Note: the flags listed here reflect intended tuning knobs, but the current
`main.py` entrypoint does not parse CLI arguments yet; configure via constants
in `main.py` for now.
