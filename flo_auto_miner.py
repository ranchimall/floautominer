# gpu_blockbook_combined.py
import requests
import socket
import json
import time
import subprocess
import re
from datetime import datetime, timezone
import threading
import sys
from collections import Counter, deque

# ---------- SESSION PERFORMANCE TRACKERS ----------
session_data = []
session_start_time = time.time()


# ---------- CONFIG ----------
# Load external configuration
with open("config.json", "r") as f:
    config = json.load(f)

# cgminer connection (still local constants)
CGMINER_HOST = "127.0.0.1"
CGMINER_PORT = 4028

# Initialize runtime state
last_change_time = 0.0
last_change_block_height = 0
CURRENT_INTENSITY = config.get("START_INTENSITY", 10)

# Convenience short names (optional for cleaner code)
TARGET_BLOCK_INTERVAL = config["TARGET_BLOCK_INTERVAL"]
LOWER_INTERVAL = config["LOWER_INTERVAL"]
UPPER_INTERVAL = config["UPPER_INTERVAL"]
MIN_INTENSITY = config["MIN_INTENSITY"]
MAX_INTENSITY = config["MAX_INTENSITY"]
MAX_TEMP = config["MAX_TEMP"]
AUTO_APPLY = config["AUTO_APPLY"]
CHANGE_COOLDOWN = config.get("CHANGE_COOLDOWN", True)
UPDATE_INTERVAL = config["UPDATE_INTERVAL"]
COOLDOWN_SECONDS = config["COOLDOWN_SECONDS"]
COOLDOWN_BLOCKS = config["COOLDOWN_BLOCKS"]
NO_BLOCK_TIMEOUT = config["NO_BLOCK_TIMEOUT"]
BLOCKBOOK_API = config["BLOCKBOOK_API"]
MAX_RUNTIME_MINUTES = config.get("MAX_RUNTIME_MINUTES", 30)
MAX_RUNTIME_SECONDS = MAX_RUNTIME_MINUTES * 60

# Optional explicit block-index/detail endpoints in config; if missing derive from BLOCKBOOK_API
# Expect BLOCKBOOK_API like https://host/api/latest-block -> base = https://host/api
_base_api = BLOCKBOOK_API.rsplit('/', 1)[0]
BLOCK_INDEX_API = config.get("BLOCKBOOK_INDEX_API", f"{_base_api}/block-index")
BLOCK_DETAIL_API = config.get("BLOCKBOOK_BLOCK_API", f"{_base_api}/block")

# ---------- Helper Functions ----------
def now_utc_str():
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')

# ----------------- CGMiner process control -----------------
cgminer_process = None

def cgminer_stdout_reader(proc):
    """Thread to read and print cgminer stdout live, filtering noise."""
    important_patterns = [
        "Accepted", "GPU", "Intensity", "Started", "Stratum", "Pool", "Network diff",
        "Summary", "Dead", "ALERT", "error", "fail", "GPU0", "GPU1"
    ]
    ignore_patterns = [
        "Accepted", "Diff", "yay!!!", "booooo", "BLOCK FOUND"
    ]

    buffer = []
    last_flush_time = time.time()

    for line in iter(proc.stdout.readline, ''):
        if not line:
            break
        line = line.strip()

        # Filter out trivial accepted share lines
        if any(ig in line for ig in ignore_patterns):
            continue

        # Capture only meaningful updates
        if any(pat in line for pat in important_patterns):
            buffer.append(line)

        # Print every 30s to avoid spam
        if time.time() - last_flush_time >= 30:
            if buffer:
                print("\n[CGMiner Summary]")
                for msg in buffer[-5:]:  # last few lines only
                    print(f"  {msg}")
                print("-" * 60)
                buffer.clear()
            last_flush_time = time.time()

    proc.stdout.close()


def start_cgminer(intensity):
    """Start cgminer using parameters from config.json."""
    global cgminer_process

    miner_exe = config.get("GPU_MINER_EXECUTABLE", r"D:\flo\gpu miner\cgminer.exe")
    miner_conf = config.get("GPU_MINER_CONFIG", r"D:\flo\gpu miner\cgminer.conf")
    pool_url = config.get("MINER_POOL_URL")
    pool_user = config.get("MINER_USER")
    pool_pass = config.get("MINER_PASS", "x")

    cmd = [
        miner_exe,
        "-o", pool_url,
        "-u", pool_user,
        "-p", pool_pass,
        "-c", miner_conf,
        "-I", str(intensity),
        "--api-listen",
        "--api-allow", "W:127.0.0.1",
        "--text-only"
    ]

    print(f"▶️ Launching cgminer (Intensity {intensity}) ...")
    cgminer_process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
        bufsize=1
    )
    threading.Thread(target=cgminer_stdout_reader, args=(cgminer_process,), daemon=True).start()
    print("🟢 cgminer started successfully.\n")
    print("⏳ Waiting 5 seconds for cgminer API to become ready...")
    time.sleep(5)



def stop_cgminer():
    global cgminer_process
    if cgminer_process and cgminer_process.poll() is None:
        cgminer_process.terminate()
        try:
            cgminer_process.wait(timeout=10)
        except Exception:
            cgminer_process.kill()
        print("⏹️ Stopped cgminer")

def stop_mining():
    """Stop cgminer due to prolonged no-block condition."""
    try:
        stop_cgminer()
        print("⛔ Mining stopped due to prolonged no-block condition.")
    except Exception as e:
        print(f"⚠️ Failed to stop mining: {e}")
        
# ----------------- CPU miner control (minerd) -----------------
cpuminer_process = None
# ----------------- CPU miner hashrate tracker -----------------
cpu_hashrate_data = {
    "latest": 0.0,
    "per_thread": {}
}

def minerd_stdout_reader(proc):
    """Thread to read and parse minerd stdout for live CPU hashrates."""
    global cpu_hashrate_data
    hashrate_pattern = re.compile(r"thread\s*(\d+).*?([\d.]+)\s*(?:k?hash|H)/s", re.IGNORECASE)
    buffer = []
    last_update = time.time()

    for line in iter(proc.stdout.readline, ''):
        if not line:
            break
        line = line.strip()

        # Match "thread 0: 12.34 khash/s"
        m = hashrate_pattern.search(line)
        if m:
            tid = int(m.group(1))
            hrate = float(m.group(2))
            cpu_hashrate_data["per_thread"][tid] = hrate

            # Every few seconds, compute total
            if time.time() - last_update >= 5:
                total_hrate = sum(cpu_hashrate_data["per_thread"].values())
                cpu_hashrate_data["latest"] = total_hrate
                print(f"🧠 CPU Miner: {len(cpu_hashrate_data['per_thread'])} threads → {total_hrate:.2f} Kh/s total")
                last_update = time.time()

    proc.stdout.close()

    
def start_minerd(threads):
    """Start minerd (CPU miner) with given thread count using pool creds in config."""
    global cpuminer_process
    miner_exe = config.get("CPU_MINER_EXECUTABLE")
    pool_url = config.get("MINER_POOL_URL")
    pool_user = config.get("MINER_USER")
    pool_pass = config.get("MINER_PASS", "x")

    if not miner_exe:
        print("⚠️ CPU_MINER_EXECUTABLE not set in config - cannot start CPU miner")
        return

    cmd = [miner_exe, "-o", pool_url, "-u", pool_user, "-p", pool_pass, "-t", str(threads)]
    print(f"▶️ Launching minerd (Threads {threads}) ...")

    cpuminer_process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
        bufsize=1
    )

    threading.Thread(target=minerd_stdout_reader, args=(cpuminer_process,), daemon=True).start()
    print("🟢 minerd started successfully.\n")


def stop_minerd():
    global cpuminer_process
    if cpuminer_process and cpuminer_process.poll() is None:
        cpuminer_process.terminate()
        try:
            cpuminer_process.wait(timeout=10)
        except Exception:
            cpuminer_process.kill()
        print("⏹️ Stopped minerd")

# ----------------- Hybrid chain state -----------------
START_INTENSITY = config.get("START_INTENSITY", 10)
CPU_THREADS_START = config.get("CPU_MINER_THREADS_START", 3)
MIN_INTENSITY = config.get("MIN_INTENSITY", 8)

# Build adaptive chain: GPU → CPU
# Example: [('GPU', 10), ('GPU',9), ('GPU',8), ('CPU',3), ('CPU',2), ('CPU',1)]
_chain = []
for I in range(START_INTENSITY, MIN_INTENSITY - 1, -1):
    _chain.append(("GPU", I))
for t in range(CPU_THREADS_START, 0, -1):
    _chain.append(("CPU", t))

# Find starting point on the chain (GPU START_INTENSITY)
chain_index = 0
for idx, (mode, val) in enumerate(_chain):
    if mode == "GPU" and val == START_INTENSITY:
        chain_index = idx
        break

current_mode = _chain[chain_index][0]
current_cpu_threads = CPU_THREADS_START
        

# ----------------- Other helper functions -----------------
def get_nvidia_temps():
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,temperature.gpu", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, check=True
        )
        temps = {}
        for line in result.stdout.strip().splitlines():
            if not line.strip():
                continue
            m = re.match(r"\s*(\d+)\s*,\s*(\d+)\s*$", line)
            if m:
                idx = int(m.group(1))
                temp = int(m.group(2))
                temps[idx] = temp
        return temps
    except Exception:
        return {}

# Latest-block fetch (with small retry logic)
def get_latest_block(retries=3, timeout=10):
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(BLOCKBOOK_API, timeout=timeout)
            r.raise_for_status()
            data = r.json()
            return {
                "height": data.get("blockheight"),
                "hash": data.get("blockhash"),
                "time": datetime.fromtimestamp(data.get("latest_time"), tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC'),
                "timestamp": data.get("latest_time")
            }
        except requests.exceptions.Timeout as e:
            # Informational (not noisy): print once per attempt
            print(f"⚠️ Error fetching latest block (attempt {attempt}/{retries}): {e}")
            if attempt < retries:
                time.sleep(1)
                continue
            return None
        except Exception as e:
            print(f"⚠️ Error fetching FLO block: {e}")
            return None

# Fetch block by height using /block-index/{height} -> /block/{hash}
def get_block_by_height(height, max_retries=5):
    attempt = 0
    while attempt < max_retries:
        attempt += 1
        try:
            r1 = requests.get(f"{BLOCK_INDEX_API}/{height}", timeout=10)
            r1.raise_for_status()
            j1 = r1.json()
            block_hash = j1.get("blockHash") or j1.get("blockhash") or j1.get("hash")
            if not block_hash:
                raise ValueError("no blockHash in block-index response")

            r2 = requests.get(f"{BLOCK_DETAIL_API}/{block_hash}", timeout=10)
            r2.raise_for_status()
            block = r2.json()
            ts = block.get("time")
            if ts is None:
                raise ValueError("no time in block detail")
            return {
                "height": height,
                "hash": block_hash,
                "timestamp": ts,
                "time": datetime.fromtimestamp(ts, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
            }
        except Exception as e:
            # keep these retry messages minimal so console isn't spammed
            print(f"⚠️ Error fetching block {height} (attempt {attempt}/{max_retries}): {e}")
            time.sleep(1 + attempt * 0.5)
    # final failure
    print(f"❌ Failed to fetch block {height} after {max_retries} attempts.")
    return None

def get_cgminer_stats():
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((CGMINER_HOST, CGMINER_PORT))
        sock.sendall(b'{"command":"devs"}\n')
        response = b""
        while True:
            part = sock.recv(4096)
            if not part:
                break
            response += part
        sock.close()

        text = response.decode('utf-8', errors='ignore')
        start, end = text.find("{"), text.rfind("}") + 1
        data = json.loads(text[start:end])
        gpu_stats = []
        nvidia_temps = get_nvidia_temps()

        for dev in data.get("DEVS", []):
            mhs_5s = dev.get('MHS 5s') or dev.get('MHS av') or 0
            hash_kh = float(mhs_5s) * 1000
            gpu_id = dev.get("GPU")
            cg_temp = dev.get("Temperature") or dev.get("Temp") or 0
            temp = int(float(cg_temp)) if cg_temp else nvidia_temps.get(gpu_id, 'N/A')
            intensity_field = dev.get("Intensity") or dev.get("intensity")
            try:
                intensity_val = int(intensity_field)
            except Exception:
                intensity_val = None

            gpu_stats.append({
                "gpu": gpu_id,
                "hashrate_kh": hash_kh,
                "accepted": dev.get("Accepted", 0),
                "rejected": dev.get("Rejected", 0),
                "hw_errors": dev.get("Hardware Errors", 0),
                "temperature": temp,
                "intensity": intensity_val
            })
        return gpu_stats
    except Exception as e:
        print(f"⚠️ Error connecting to cgminer API: {e}")
        return []

# ----------------- STARTUP -----------------
print(f"🚀 Starting controller with fixed GPU intensity {CURRENT_INTENSITY}.")
start_cgminer(CURRENT_INTENSITY)

print(f"\n Starting FLO + GPU Monitor (controller)...\n")
print(f"Controller mode: {'AUTO-APPLY' if AUTO_APPLY else 'SUGGEST-ONLY'} | Target interval: {TARGET_BLOCK_INTERVAL}s | Bounds: [{LOWER_INTERVAL}s , {UPPER_INTERVAL}s]\n")

# ----------------- Controller Logic with sequential indexing -----------------
previous_block = None
last_change_time = 0
current_intensity = CURRENT_INTENSITY
max_intensity_start_time = None

# Cooldown tracking
cooldown_active = False
cooldown_start_time = None
cooldown_blocks_count = 0
cooldown_direction = None  # 'fast' (<LOWER_INTERVAL) or 'slow' (>UPPER_INTERVAL)
# --- Stability tracking (multi-window, configurable) ---
current_window_blocks = []      # store status of last 20 blocks
passed_stability_checks = 0     # number of consecutive stable 20-block sets

WINDOW_SIZE = config.get("STABILITY_WINDOW_SIZE", 20)
STABLE_THRESHOLD = config.get("STABILITY_REQUIRED_IN_RANGE", 17)
REQUIRED_PASSED_SETS = config.get("STABILITY_REQUIRED_PASSES", 3)


# track last_block_time so no-block logic can work
last_block_time = time.time()
block_intervals = []  # track block intervals for session summary

# track last processed height for sequential fetch
# initialize from latest-block, but we will use block-index to enumerate forward
initial_latest = get_latest_block()
if not initial_latest:
    print("❌ Could not fetch initial latest block. Exiting.")
    stop_cgminer()
    sys.exit(1)

previous_block = {
    "height": initial_latest["height"],
    "hash": initial_latest["hash"],
    "timestamp": initial_latest["timestamp"],
    "time": initial_latest["time"]
}
last_processed_height = previous_block["height"]

# --- TINY TWEAK: Print the initial latest block as reference ---
print(f"Block Height: {previous_block['height']} | Hash: {previous_block['hash']} | "
      f"Time: {previous_block['time']} | Interval: N/A")

# silent verification toggles: do not print verification details, only errors
SILENT_VERIFY = True

# ----------------- Refactored Controller Loop -----------------
try:
    # --- Safety cutoff timer ---
    controller_start_time = time.time()
    
    while True:
        # Safety: auto-stop after max runtime
        elapsed_runtime = time.time() - controller_start_time
        if elapsed_runtime >= MAX_RUNTIME_SECONDS:
            print(f"\n⏰ Safety limit reached ({MAX_RUNTIME_MINUTES} minutes).")
            print("🛑 Gracefully stopping all mining processes to protect your system...")
            stop_cgminer()
            stop_minerd()

            # Give miners time to shut down cleanly
            time.sleep(3)

            print(f"✅ Controller stopped automatically after {int(elapsed_runtime//60)}m {int(elapsed_runtime%60)}s runtime.")
            print("─────────────────────────────────────────────")
            print("💤 Mining stopped safely. Console will remain open — close this window when you’re ready.\n")

            # Keep console open for user review
            input("Press Enter to close the controller... ")
            break
        
        # --- Normal controller operations below ---
        latest = get_latest_block()
        new_block_detected = False
        block_interval = None

        if latest and latest["height"] > last_processed_height:
            # Sequentially fetch all missing blocks
            for h in range(last_processed_height + 1, latest["height"] + 1):
                blk = get_block_by_height(h)
                if not blk:
                    continue  # skip if fetch failed

                # New block found
                new_block_detected = True
                block_interval = blk["timestamp"] - previous_block["timestamp"] if previous_block else None
                if block_interval is not None:
                    block_intervals.append(block_interval)


                # Print block info
                print(f"Block Height: {blk['height']} | Hash: {blk['hash']} | Time: {blk['time']} | Interval: {block_interval if block_interval else 'N/A'}s")

                # ---- Cooldown / Intensity Logic ----
                if block_interval is not None:
                    # Determine if block interval is too fast, too slow, or in range
                    if block_interval < LOWER_INTERVAL:
                        direction = 'fast'
                        print(f"⏱️ Too fast! Interval {block_interval}s < {LOWER_INTERVAL}s")
                    elif block_interval > UPPER_INTERVAL:
                        direction = 'slow'
                        print(f"⏱️ Too slow! Interval {block_interval}s > {UPPER_INTERVAL}s")
                    else:
                        direction = 'in_range'
                        # Optional: print(f"✅ Block interval {block_interval}s in target range")

                    # Cooldown handling
                    if direction in ['fast', 'slow']:
                        if not cooldown_active:
                            cooldown_active = True
                            cooldown_start_time = time.time()
                            cooldown_blocks_count = 1
                            cooldown_direction = direction
                            print(f"⏸️ Cooldown started ({direction}) Block {cooldown_blocks_count}/{COOLDOWN_BLOCKS}")
                        else:
                            if direction == cooldown_direction:
                                cooldown_blocks_count += 1
                                print(f"⏸️ Cooldown ongoing ({direction}) Block {cooldown_blocks_count}/{COOLDOWN_BLOCKS}")
                            else:
                                # Direction changed, reset cooldown
                                cooldown_start_time = time.time()
                                cooldown_blocks_count = 1
                                cooldown_direction = direction
                                print(f"✅ Cooldown direction changed → reset ({direction})")                            
                            
                    else:
                        # --- Multi-window stability check (3 consecutive 20-block sets) ---
                        # Record each block’s interval status
                        if LOWER_INTERVAL <= block_interval <= UPPER_INTERVAL:
                            status = "in_range"
                        else:
                            status = "out_of_range"

                        current_window_blocks.append(status)

                        # Once 20 blocks are collected, evaluate the set
                        if len(current_window_blocks) == WINDOW_SIZE:
                            stable_blocks = sum(1 for s in current_window_blocks if s == "in_range")

                            if stable_blocks >= STABLE_THRESHOLD:
                                passed_stability_checks += 1
                                print(f"✅ Stability check {passed_stability_checks}/{REQUIRED_PASSED_SETS} passed "
                                      f"({stable_blocks}/{WINDOW_SIZE} blocks in range).")
                            else:
                                print(f"⚠️ Stability check failed ({stable_blocks}/{WINDOW_SIZE} in range). "
                                      f"Resetting progress.")
                                passed_stability_checks = 0

                            # reset window for next 20-block group
                            current_window_blocks = []

                            # stop mining after 3 consecutive successful sets
                            if passed_stability_checks >= REQUIRED_PASSED_SETS:
                                print("\n✅ Network stabilized — 3 consecutive 20-block sets passed.")
                                print("🛑 Stopping mining to conserve resources.\n")
                                stop_cgminer()
                                stop_minerd()
                                sys.exit(0)



        
            
                    
                    # --- Adaptive hybrid GPU↔CPU chain logic for cooldown---
                    if cooldown_active:
                        cooldown_elapsed = time.time() - cooldown_start_time

                        # Always show cooldown progress
                        print(f"Cooldown: {cooldown_blocks_count}/{COOLDOWN_BLOCKS} | "
                              f"{int(cooldown_elapsed)}/{COOLDOWN_SECONDS}s | Mode: {cooldown_direction}")

                        # Check if either block or time threshold reached
                        if cooldown_blocks_count >= COOLDOWN_BLOCKS or cooldown_elapsed >= COOLDOWN_SECONDS:
                            step = 1 if cooldown_direction == 'fast' else -1  # fast → move right (lower), slow → move left (higher)
                            new_index = max(0, min(len(_chain) - 1, chain_index + step))

                            if new_index == chain_index:
                                print(f"⚠️ Adaptive chain limit reached at {_chain[chain_index]} — cannot step further.")
                            else:
                                target_mode, target_val = _chain[new_index]
                                reason = "blocks" if cooldown_blocks_count >= COOLDOWN_BLOCKS else "time"
                                print(f"✔️ Cooldown threshold reached ({reason}) — moving {_chain[chain_index]} → {(target_mode, target_val)}")

                                # Apply the move
                                if target_mode == "GPU":
                                    if current_mode == "CPU":
                                        stop_minerd()
                                        time.sleep(1)
                                    if AUTO_APPLY:
                                        stop_cgminer()
                                        start_cgminer(target_val)
                                    current_mode = "GPU"
                                    current_intensity = target_val
                                else:
                                    if current_mode == "GPU":
                                        stop_cgminer()
                                        time.sleep(1)
                                    if AUTO_APPLY:
                                        stop_minerd()
                                        start_minerd(target_val)
                                    current_mode = "CPU"
                                    current_cpu_threads = target_val

                                chain_index = new_index

                            cooldown_active = False
                            cooldown_blocks_count = 0
                            cooldown_direction = None





                # Update trackers
                previous_block = blk
                last_processed_height = blk["height"]
                last_block_time = time.time()

        else:
            # No new block yet → do nothing (just sleep)
            pass

        # ---- Handle No-Block Timeout ----
        if not new_block_detected:
            time_since_last_block = time.time() - last_block_time
            if time_since_last_block > NO_BLOCK_TIMEOUT:
                if current_intensity < MAX_INTENSITY:
                    current_intensity += 1
                    print(f"⚠️ No new block for {NO_BLOCK_TIMEOUT}s → boosting intensity {current_intensity}")
                    if AUTO_APPLY:
                        stop_cgminer()
                        start_cgminer(current_intensity)
                    last_block_time = time.time()
                    max_intensity_start_time = None
                else:
                    if max_intensity_start_time is None:
                        max_intensity_start_time = time.time()
                        print(f"⚠️ Max intensity {MAX_INTENSITY} reached, monitoring for {NO_BLOCK_TIMEOUT}s...")
                    elif time.time() - max_intensity_start_time > NO_BLOCK_TIMEOUT:
                        print(f"⛔ No new block at max intensity → stopping mining")
                        stop_mining()
                        break

            
        # ---- Miner stats logging (GPU or CPU aware) ----
        timestamp = now_utc_str()

        if current_mode == "GPU":
            # only poll cgminer API when we're in GPU mode
            gpu_stats = get_cgminer_stats()
            if gpu_stats:
                avg_hash = sum(g["hashrate_kh"] for g in gpu_stats) / len(gpu_stats)
                max_hash = max(g["hashrate_kh"] for g in gpu_stats)
                min_hash = min(g["hashrate_kh"] for g in gpu_stats)
                # avg_temp may sometimes encounter 'N/A' entries so guard it
                temps = [g["temperature"] for g in gpu_stats if isinstance(g["temperature"], int)]
                avg_temp = sum(temps) / len(temps) if temps else 0
                intensities = [g.get("intensity") or 0 for g in gpu_stats]
                total_accepted = sum(g.get("accepted", 0) for g in gpu_stats)
                total_rejected = sum(g.get("rejected", 0) for g in gpu_stats)

                # Print per GPU
                for gpu in gpu_stats:
                    print(f"[{timestamp}] GPU {gpu['gpu']}: {gpu['hashrate_kh']:.1f} Kh/s | "
                          f"T:{gpu['temperature']}°C | A:{gpu['accepted']} R:{gpu['rejected']} HW:{gpu['hw_errors']} | I:{gpu.get('intensity')}")

                # Append **aggregated snapshot per interval**
                session_data.append({
                    "time": time.time(),
                    "avg_hashrate": avg_hash,
                    "max_hashrate": max_hash,
                    "min_hashrate": min_hash,
                    "intensities": intensities,
                    "avg_temp": avg_temp,
                    "total_accepted": total_accepted,
                    "total_rejected": total_rejected
                })
            else:
                # No data returned (cgminer API unreachable or returned empty)
                print(f"[{timestamp}] GPU mode but no cgminer stats returned (cgminer might be starting/stopping).")
           
        else:
            # CPU mode: read latest hashrate parsed from minerd stdout
            cpu_hashrate = cpu_hashrate_data.get("latest", 0.0)

            if cpu_hashrate == 0.0:
                print(f"[{timestamp}] CPU mode (threads={current_cpu_threads}) → waiting for hashrate...")
            else:
                print(f"[{timestamp}] CPU mode (threads={current_cpu_threads}) → {cpu_hashrate:.2f} Kh/s")

            # Always append a CPU snapshot (even if hashrate = 0)
            session_data.append({
                "time": time.time(),
                "avg_hashrate": cpu_hashrate,
                "max_hashrate": cpu_hashrate,
                "min_hashrate": cpu_hashrate,
                "cpu_threads": current_cpu_threads,
                "intensities": [],
                "avg_temp": 0,
                "total_accepted": 0,
                "total_rejected": 0
            })
               
        time.sleep(UPDATE_INTERVAL)


except KeyboardInterrupt:
    print("\n\n🛑 Keyboard interrupt received — stopping miner and summarizing session...")
    stop_cgminer()
    stop_minerd()

    print("\n📊 Session Performance Summary")
    print("─────────────────────────────────────────────")

    if session_data:
        total_duration = time.time() - session_start_time
            
            
        # --- Organize hashrates by power mode (GPU/CPU unified) ---
        mode_data = {"GPU": {}, "CPU": {}}

        for entry in session_data:
            # GPU records (with intensity)
            for i in entry.get("intensities", []):
                if i is None or i == 0:
                    continue
                mode_data["GPU"].setdefault(i, []).append(entry["avg_hashrate"])
            # CPU records (you can later expand to store threads in session_data)
            if not entry.get("intensities"):  # indicates CPU placeholder record
                threads = entry.get("cpu_threads", 0) if "cpu_threads" in entry else 0
                if threads:
                    mode_data["CPU"].setdefault(threads, []).append(entry["avg_hashrate"])

        # Clean invalid entries
        for m in ["GPU", "CPU"]:
            for k in list(mode_data[m].keys()):
                mode_data[m][k] = [h for h in mode_data[m][k] if h > 0]
                if not mode_data[m][k]:
                    del mode_data[m][k]

        # Find min/max power levels across both GPU and CPU
        combined_points = []
        for mode in mode_data:
            for val, hashes in mode_data[mode].items():
                avg_hash = sum(hashes) / len(hashes)
                combined_points.append((mode, val, avg_hash))

        if combined_points:
            max_point = max(combined_points, key=lambda x: x[2])
            min_point = min(combined_points, key=lambda x: x[2])
            max_mode, max_val, max_hash = max_point
            min_mode, min_val, min_hash = min_point
        else:
            max_mode = min_mode = "N/A"
            max_val = min_val = "N/A"
            max_hash = min_hash = 0
            
            
            
    

        # --- Overall averages ---
        valid_data = [d for d in session_data if d["avg_hashrate"] > 0]
        avg_hash = sum(d["avg_hashrate"] for d in valid_data) / len(valid_data) if valid_data else 0
        avg_temp = sum(d["avg_temp"] for d in valid_data) / len(valid_data) if valid_data else 0
        total_accepted = sum(d["total_accepted"] for d in session_data)
        total_rejected = sum(d["total_rejected"] for d in session_data)

        # --- Print summary ---
        print(f"⏱️  Total Duration: {int(total_duration//3600)}h {(total_duration%3600)//60:.0f}m {(total_duration%60):.0f}s")
        print(f"⚡  Average Hashrate: {avg_hash:.2f} KH/s")
        print(f"🔺 Maximum Power Mode: {max_mode} {max_val} → Avg {max_hash:.2f} KH/s")
        print(f"🔻 Minimum Power Mode: {min_mode} {min_val} → Avg {min_hash:.2f} KH/s")

        # Most-used intensity
        all_intensities = [i for d in session_data for i in d["intensities"] if i]
        most_common_intensity = Counter(all_intensities).most_common(1)[0][0] if all_intensities else "N/A"
        print(f"🎚️  Most Used Intensity: {most_common_intensity}")

        print(f"🌡️  Average Temperature: {avg_temp:.1f}°C")
        print(f"✅ Total Accepted Shares: {total_accepted}")
        print(f"❌ Total Rejected Shares: {total_rejected}")

        # Block interval
        if block_intervals:
            avg_block_interval = sum(block_intervals) / len(block_intervals)
            print(f"⏳ Average Block Interval: {avg_block_interval:.2f}s")
        else:
            print(f"⏳ Average Block Interval: N/A")

    else:
        print("⚠️  No mining data recorded.")

    print("─────────────────────────────────────────────")
    print("✅ Mining session ended successfully.")
    sys.exit(0)


except Exception as e:
    # Catch any unexpected exception, print a short message and clean up
    print(f"\n❌ Unhandled exception: {e}")
    print("⚠️ Exiting due to unexpected error.")
    try:
        stop_cgminer()
        stop_minerd()
    finally:    
        sys.exit(1)
