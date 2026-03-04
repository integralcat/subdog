import asyncio
import time
from abc import ABC, abstractmethod

# =============================================================================
# Abstract Base Class for Rate Limiters
# =============================================================================


class RateLimiter(ABC):
    @abstractmethod
    async def acquire(self):
        """Wait until permission is granted to proceed."""
        pass


# =============================================================================
# 1. Token Bucket Implementation
# =============================================================================


class TokenBucket(RateLimiter):
    """
    A Token Bucket implementation for rate limiting.

    Allow bursts of requests up to `capacity`, but refill tokens at a constant rate.
    Ideal for API clients where short bursts are acceptable.
    """

    def __init__(self, capacity, fill_rate):
        self.capacity = capacity  # Max tokens the bucket can hold (Burst Size)
        self.fill_rate = fill_rate  # Tokens added per second
        self.tokens = capacity  # Start full
        self.last_fill_time = time.monotonic()
        self.lock = asyncio.Lock()  # To ensure thread/task safety during updates

    async def acquire(self, tokens=1):
        """
        Request `tokens`. If not enough tokens are available, wait until they are.
        """
        async with self.lock:
            while True:
                self._refill()

                if self.tokens >= tokens:
                    self.tokens -= tokens
                    return  # Success! Proceed.

                # Calculate time to wait for enough tokens
                missing_tokens = tokens - self.tokens
                wait_time = missing_tokens / self.fill_rate

                # Release lock while waiting so others can check (though strictly speaking
                # in single-threaded asyncio, only one task runs at a time, but this mimics thread safety)
                # However, since we are inside an async lock, we must be careful not to block others
                # from refilling if we were using threads. In pure asyncio, this is fine.
                print(f"[TokenBucket] Not enough tokens. Waiting {wait_time:.2f}s...")
                await asyncio.sleep(wait_time)

    def _refill(self):
        """Add tokens based on time elapsed since last check."""
        now = time.monotonic()
        elapsed = now - self.last_fill_time
        new_tokens = elapsed * self.fill_rate

        if new_tokens > 0:
            self.tokens = min(self.capacity, self.tokens + new_tokens)
            self.last_fill_time = now


# =============================================================================
# 2. Leaky Bucket Implementation
# =============================================================================


class LeakyBucket(RateLimiter):
    """
    A Leaky Bucket implementation.

    Processes requests at a constant fixed rate, regardless of incoming burst.
    Think of it as a queue that drains at a specific speed.
    """

    def __init__(self, rate_per_second):
        self.rate_per_second = rate_per_second
        self.time_per_request = 1.0 / rate_per_second
        self.last_leak_time = 0
        self.lock = asyncio.Lock()

    async def acquire(self):
        """
        Wait until the 'bucket leaks' enough to allow another drop (request).
        """
        async with self.lock:
            now = time.monotonic()

            # Calculate when the next request is allowed
            next_allowed_time = self.last_leak_time + self.time_per_request

            if now < next_allowed_time:
                wait_time = next_allowed_time - now
                print(f"[LeakyBucket] Too fast. Slowing down by {wait_time:.2f}s...")
                await asyncio.sleep(wait_time)
                # After sleeping, time has passed, so update now
                now = time.monotonic()

            self.last_leak_time = now


# =============================================================================
# "Small" Example: Basic Usage
# =============================================================================


async def small_example():
    print("\n--- Small Example: Token Bucket basic usage ---")
    # Allow burst of 5, refill 2 per second
    bucket = TokenBucket(capacity=5, fill_rate=2)

    # Simulate 10 instant requests
    for i in range(10):
        await bucket.acquire()
        print(f"Request {i + 1} processed at {time.strftime('%X')}")


# =============================================================================
# "Large" Example: Simulated Async Web Scraper
# =============================================================================


async def fetch_url(id, limiter):
    """Simulate fetching a URL with rate limiting."""
    await limiter.acquire()

    # Simulate network latency (0.1 to 0.5s)
    latency = 0.1 + (id % 5) / 10
    await asyncio.sleep(latency)

    print(f"✅ Task {id} finished fetching (simulated latency: {latency:.2f}s)")


async def large_example():
    print("\n--- Large Example: Async Scraper with Leaky Bucket ---")

    # Scenario: We want to scrape 20 URLs, but the server only allows 5 requests per second.
    # We use a Leaky Bucket to smooth our traffic.
    limiter = LeakyBucket(rate_per_second=5)

    tasks = []
    start_time = time.monotonic()

    # Launch 20 tasks "simultaneously"
    print("🚀 Launching 20 async scraping tasks...")
    for i in range(20):
        tasks.append(asyncio.create_task(fetch_url(i, limiter)))

    # Wait for all to complete
    await asyncio.gather(*tasks)

    duration = time.monotonic() - start_time
    print(f"\n🏁 All tasks completed in {duration:.2f} seconds.")
    print(f"Expected minimum time for 20 requests at 5 req/s is ~4.0 seconds.")


# =============================================================================
# Main Entry Point
# =============================================================================


async def main():
    await small_example()
    print("-" * 40)
    await large_example()


if __name__ == "__main__":
    asyncio.run(main())
