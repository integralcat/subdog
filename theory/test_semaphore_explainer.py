import asyncio
import time
import random

"""
--------------------------------------------------------------------------------
DEEP DIVE: UNDERSTANDING ASYNCIO SEMAPHORES
--------------------------------------------------------------------------------

WHAT IS A SEMAPHORE?
Think of a Semaphore as a nightclub bouncer with a clicker.
- The club has a capacity of N (the semaphore value).
- When a task wants to enter (acquire), the bouncer checks the clicker.
- If count > 0: "Come on in!" (count decrements by 1).
- If count == 0: "Wait here." (Task is paused/suspended).
- When a task leaves (release), the bouncer clicks +1, and the next waiting task gets in.

WHY DO WE NEED IT FOR DNS?
- File Descriptors: Your OS has a limit on open files/sockets (ulimit -n).
- Network Buffer: Your router/NIC has a small buffer. Flooding it causes packet loss.
- API Limits: Public DNS resolvers will ban you if you send 5000 req/sec.

THE MECHANISM:
1. `sem = asyncio.Semaphore(10)` creates a counter starting at 10.
2. `async with sem:` calls `sem.acquire()` at start and `sem.release()` at exit.
   - It effectively pauses your code at that line if the counter is 0.
   - It guarantees that the code INSIDE the block never has more than N concurrent runners.

--------------------------------------------------------------------------------
"""


async def network_operation(task_id, semaphore=None):
    """
    Simulates a DNS lookup or network request.
    """
    print(f"[Task {task_id:03d}] Created and waiting to start...")

    # --- CRITICAL SECTION START ---
    # If a semaphore is provided, we must acquire it before proceeding.
    # If no semaphore (None), we just run immediately (DANGEROUS).

    if semaphore:
        await semaphore.acquire()

    try:
        # We are now "inside" the active window.
        print(f"[Task {task_id:03d}] >>> RUNNING (Sockets open, consuming resources)")

        # Simulate network latency (0.5 to 1.5 seconds)
        await asyncio.sleep(random.uniform(0.5, 1.5))

    finally:
        if semaphore:
            semaphore.release()

    # --- CRITICAL SECTION END ---

    print(f"[Task {task_id:03d}] <<< FINISHED")


async def run_unsafe_example():
    """
    SCENARIO 1: THE CRASH (Simulated)
    This is what happens when you just run `asyncio.gather(*tasks)` without a semaphore.
    """
    print("\n--- STARTING UNSAFE RUN (All 20 tasks start at once) ---")
    tasks = [network_operation(i, semaphore=None) for i in range(20)]

    # In a real DNS script with 5000 domains, this line would:
    # 1. Create 5000 sockets instantly.
    # 2. Crash with "OSError: [Errno 24] Too many open files"
    await asyncio.gather(*tasks)


async def run_safe_example():
    """
    SCENARIO 2: CONTROLLED CONCURRENCY
    This uses a Semaphore to limit active tasks to 5.
    """
    print("\n--- STARTING SAFE RUN (Limit: 5 concurrent tasks) ---")

    # Create the bouncer. Capacity = 5.
    sem = asyncio.Semaphore(5)

    # We pass the semaphore to every task.
    # They all get created instantly, but they will STOP at `await sem.acquire()`
    tasks = [network_operation(i, semaphore=sem) for i in range(20)]

    await asyncio.gather(*tasks)


if __name__ == "__main__":
    # UNCOMMENT THE SCENARIO YOU WANT TO SEE

    # 1. The Safe Way (Recommended)
    # Notice how you only see 5 "RUNNING" messages at a time.
    asyncio.run(run_safe_example())

    # 2. The Unsafe Way (Chaotic)
    # Notice how ALL 20 print "RUNNING" instantly.
    # In a real app, this is where your OS kills the process.
    # asyncio.run(run_unsafe_example())
