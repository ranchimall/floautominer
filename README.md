# FLO Auto Miner
The RanchiMall FLO Auto Miner lets anyone with a laptop GPU or CPU automatically contribute to the FLO blockchain whenever the network slows down.


### A Smart FLO Network Controller for cgminer and minerd

---

## Overview

**FLO Auto Miner** is a Python-based controller that allows anyone with a laptop GPU or CPU to contribute efficiently to the FLO network’s stability.

It monitors block production in real time using the FLO Blockbook API.  
When the network slows down, it automatically starts mining to support the network.  
When block intervals return to normal, it stops mining to conserve system resources.

---

## Features

- Monitors FLO block times via Blockbook
- Automatically starts and stops cgminer (GPU) or minerd (CPU)
- Dynamically adjusts intensity based on block speed
- Uses cooldown logic between changes
- Automatically stops after a defined runtime (default: 30 minutes)
- Fully configurable through `config.json`
- Works directly with mining pools (no need for FLO Core wallet)
- Preconfigured for FLOCard Pool

---

## Folder Setup (Example: `D:/flo`)

```

D:/flo/
│
├── floautominer.py.py                # main controller script
├── config.json                       # configuration file
                            
├── gpu miner/
│     └── cgminer.exe
│     └── cgminer.conf                # optional GPU tuning
└── cpuminer minerd/
      └── minerd.exe

```

---

## Installation Guide

### 1. Install Python
Download and install Python from:  
https://www.python.org/downloads/  
During installation, ensure that **"Add Python to PATH"** is checked.

---

### 2. Download GPU Miner (cgminer)

Download **cgminer 3.7.2** (Scrypt-supported) from:  
https://cgminer.info/download/index.html

Extract it to:
```

D:/flo/gpu miner/

```

You should now have:
```

D:/flo/gpu miner/cgminer.exe
D:/flo/gpu miner/cgminer.conf

**Note: If you do not see cgminer.conf, you can create one. This is optional if you want to optimize your laptop's power to be provided for mining

```

---

### 3. Download CPU Miner

Download **cpuminer (minerd)** from:  
https://github.com/pooler/cpuminer/releases

Extract it to:
```

D:/flo/cpuminer minerd/

```

You should now have:
```

D:/flo/cpuminer minerd/minerd.exe

```

---

### 4. Download the Controller Files

Download the following files from this repository:

- [gpu_cpu_blockbook_combined.py](https://github.com/ranchimall/floautominer/blob/main/flo_auto_miner.py)
- [config.json](https://github.com/ranchimall/floautominer/blob/main/config.json)
- [cgminer.conf](https://github.com/ranchimall/floautominer/blob/main/cgminer.conf)

Place all three files in your main folder:

- You can simply copy each of them and paste in the code editor of your choice. Save them with extensions as .py, .json, and .conf respectively.

Place them in:
```

D:/flo/

````

---

## Configuration

### config.json

Example configuration (for FLOCard Pool):

```json
{
  "BLOCKBOOK_API": "https://blockbook.ranchimall.net/api/latest-block",
  "BLOCKBOOK_INDEX_API": "https://blockbook.ranchimall.net/api/block-index",
  "BLOCKBOOK_BLOCK_API": "https://blockbook.ranchimall.net/api/block",

  "TARGET_BLOCK_INTERVAL": 40,
  "LOWER_INTERVAL": 30,
  "UPPER_INTERVAL": 50,

  "MAX_RUNTIME_MINUTES": 30,

  "MIN_INTENSITY": 8,
  "MAX_INTENSITY": 12,
  "NO_BLOCK_TIMEOUT": 600,
  "MAX_TEMP": 85,
  "START_INTENSITY": 10,

  "AUTO_APPLY": true,
  "CHANGE_COOLDOWN": 120,
  "UPDATE_INTERVAL": 30,
  "COOLDOWN_SECONDS": 120,
  "COOLDOWN_BLOCKS": 3,

  "STABILITY_WINDOW_SIZE": 20,
  "STABILITY_REQUIRED_IN_RANGE": 17,
  "STABILITY_REQUIRED_PASSES": 3,

  "GPU_MINER_EXECUTABLE": "D:/flo/gpu miner/cgminer.exe",
  "GPU_MINER_CONFIG": "D:/flo/gpu miner/cgminer.conf",

  "CPU_MINER_EXECUTABLE": "D:/flo/cpuminer minerd/minerd.exe",
  "CPU_MINER_THREADS_START": 3,

  "MINER_POOL_URL": "stratum+tcp://pool.flocard.app:3052",
  "MINER_USER": "<<Your_FLO_Address>>.worker1",
  "MINER_PASS": "x"
}
````

---

### Configuration Explanation

| Key                                    | Description                                 |
| -------------------------------------- | ------------------------------------------- |
| `BLOCKBOOK_API`                        | Endpoint for latest FLO block               |
| `BLOCKBOOK_INDEX_API`                  | Endpoint for block hash lookup by height    |
| `BLOCKBOOK_BLOCK_API`                  | Endpoint for detailed block data            |
| `TARGET_BLOCK_INTERVAL`                | Ideal block interval (seconds)              |
| `LOWER_INTERVAL` / `UPPER_INTERVAL`    | Acceptable timing bounds                    |
| `MAX_RUNTIME_MINUTES`                  | Stops mining after this time                |
| `MIN_INTENSITY` / `MAX_INTENSITY`      | GPU intensity range                         |
| `NO_BLOCK_TIMEOUT`                     | Wait time before retrying higher intensity  |
| `AUTO_APPLY`                           | Automatically apply new settings            |
| `COOLDOWN_BLOCKS` / `COOLDOWN_SECONDS` | Cooldown logic between changes              |
| `STABILITY_WINDOW_SIZE`                | Number of blocks in each stability window   |
| `STABILITY_REQUIRED_IN_RANGE`          | Blocks that must be within range per window |
| `STABILITY_REQUIRED_PASSES`            | Number of consecutive windows required      |
| `GPU_MINER_EXECUTABLE`                 | Path to cgminer.exe                         |
| `GPU_MINER_CONFIG`                     | Path to cgminer.conf                        |
| `CPU_MINER_EXECUTABLE`                 | Path to minerd.exe                          |
| `CPU_MINER_THREADS_START`              | Number of CPU threads to start with         |
| `MINER_POOL_URL`                       | FLOCard pool stratum URL                    |
| `MINER_USER`                           | Your FLO wallet address + worker name       |
| `MINER_PASS`                           | Pool password (usually “x”)                 |

---

### cgminer.conf (Optional GPU Settings)
## You can ignore it if you want to continue with your default laptop power.

You can use this sample configuration:

```json
{
    "scrypt": true,
    "intensity": "12",
    "worksize": "256",
    "lookup-gap": "2",
    "thread-concurrency": "8192",
    "gpu-engine": "1800",
    "gpu-memclock": "6400",
    "gpu-fan": "85",
    "api-listen": true,
    "api-allow": "W:127.0.0.1",
    "api-port": "4028"
}
```

**Notes:**

* These are GPU tuning settings, not pool details.
* Pool credentials come from `config.json` (the controller passes them dynamically).
* Adjust `gpu-engine`, `gpu-memclock`, and fan speeds as appropriate for your GPU.

---

## Running the Controller

1. Open Command Prompt
2. Navigate to your project folder:

   ```bash
   cd /d D:\flo
   ```
3. Run the script:

   ```bash
   python gpu_cpu_blockbook_combined.py
   ```

Example output:

```
Starting controller with fixed GPU intensity 10.
Starting FLO + GPU Monitor (controller)...

Block Height: 7783301 | Interval: 47s
Block interval in range
CPU Miner: 3 threads → 36.5 Kh/s total
```

---

## Mining Pool (No FLO Core Wallet Required)

You do **not** need to run a FLO Core wallet.
Instead, you can mine directly using a FLO mining pool.

Default configuration is set for **FLOCard Pool**:
[https://pool.flocard.app/](https://pool.flocard.app/)

If you wish, you can replace this with any other active FLO-compatible pool in `config.json`.

---

## Code Logic Summary

| Step | Logic                                 | Action                                          |
| ---- | ------------------------------------- | ----------------------------------------------- |
| 1    | Fetch the latest block from Blockbook | Calculate interval between consecutive blocks   |
| 2    | If interval < 30s                     | Too fast → lower intensity (cooldown)           |
| 3    | If interval > 50s                     | Too slow → raise intensity / enable CPU mining  |
| 4    | Every 20 blocks                       | If 17 are within range → stability check passed |
| 5    | After 3 consecutive stability passes  | Stop mining (network stable)                    |

If no new blocks appear for 600 seconds, the intensity increases automatically.

---

## Auto Miner Purpose

This project helps balance FLO block generation during network slowdowns.
It allows community members to contribute hashrate intelligently and stop automatically when the network recovers.

---


