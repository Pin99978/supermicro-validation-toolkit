# AI Server Validation Architecture

This document details the high-level architecture for deploying, managing, and executing the `validate_gpu.py` script across a large-scale server fleet.

## 1. Solution Components

* **`validate_gpu.py` (The Validator):** An Object-Oriented Python script that runs on each target server. It validates hardware against a "Golden Standard" and outputs a machine-readable `validation_report.json`.
* **`golden_config.yml` (The "Golden Standard"):** The single source of truth for the entire fleet, stored in Git. It is **BOM-centric (Bill of Materials)**, using the `system_model` (e.g., `SYS-421GU-TNXR`) as the primary key.
* **Diag Host (The Management Server):** A central Linux server that acts as the control point. It hosts the master Git repository for `golden_config.yml` and runs the deployment script (`deploy.sh`).
* **`validation.service` (The Boot-Time Trigger):** A `systemd` service file that ensures `validate_gpu.py` runs automatically on every server boot.

## 2. Deployment & Management Workflows

This architecture relies on standard, reliable Linux tools (`ssh`, `scp`, `git`) and strictly separates the **deployment** of configuration from the **execution** of validation. The validation script itself does not (and should not) know how to fetch its own configuration.

### Workflow 1: Deploying Updates to the multiple servers

This workflow is used to push a new version of the validator script or the `golden_config.yml` to all servers. It is run *from* the Diag Host. 

```bash
#!/bin/bash
# Master deployment script on the Diag Host
# (deploy.sh)

# assume there are multiple servers in server_list.txt 
SERVER_LIST="~/server_list.txt"  # you should defind the path in Diag Host

# Paths to the master files on the Diag Host
SCRIPT_SOURCE="./validate_gpu.py"
CONFIG_SOURCE="./golden_config.yml"
SERVICE_SOURCE="./docs/validation.service"

echo "Beginning deployment..."

while read -r server_ip; do
    echo "--- Deploying to $server_ip ---"
    
    # 1. Use scp to securely copy the new files
    scp "$SCRIPT_SOURCE" "admin@${server_ip}:/usr/local/bin/validate_gpu.py"
    scp "$CONFIG_SOURCE" "admin@${server_ip}:/etc/golden_config.yml"
    scp "$SERVICE_SOURCE" "admin@${server_ip}:/etc/systemd/system/validation.service"
    
    # 2. Use ssh to set permissions and enable the systemd service
    ssh "admin@${server_ip}" << 'EOF'
        chmod +x /usr/local/bin/validate_gpu.py
        systemctl daemon-reload
        systemctl enable validation.service
        echo "Deployment to $server_ip complete."
EOF

done < "$SERVER_LIST"

echo "Fleet deployment finished."
```

### Workflow 2: Change Control (How to safely update `golden_config.yml`)

1.  **Isolate:** A new firmware (e.g., VBIOS `96.00.41.00.02`) is released by a vendor.
2.  **Upgrade:** An engineer manually upgrades a single **"Golden Server"** (a dedicated, non-production test machine) to this new firmware.
3.  **Extract:** The engineer runs `sudo python3 validate_gpu.py` on this Golden Server. The script will **[FAIL]**, but the output `validation_report.json` will contain the *actual* new version string:
    `"actual": "96.00.41.00.02"`
4.  **Verify:** The engineer confirms this is the correct, expected new string.
5.  **Commit:** The engineer updates `golden_config.yml` (on the Diag Host) with this *verified* string and commits it to **Git** with a clear message (e.g., "Update H100 VBIOS to 96.00.41.00.02 per NVIDIA Bulletin").
6.  **Deploy:** The engineer can now safely run the `deploy.sh` script to push this new, verified config to the entire multiple servers 

## 3. Architecture Flowchart

```mermaid
graph TD
    A[Engineer @ Diag Host] -- "1. 'git push' new golden.yml" --> B(Git Repo)
    B -- "2. 'git pull'" --> A
    A -- "3. Runs 'deploy.sh'" --> C{For each 1,000 servers...}
    C -- "4. ssh/scp" --> S(Target Server)
    
    subgraph Target Server (On Boot)
        S -- "5. Boot Trigger" --> S_SYS(systemd: validation.service)
        S_SYS -- "6. Runs" --> S_PY(validate_gpu.py)
        S_PY -- "7. Reads" --> S_CFG(/etc/golden_config.yml)
        S_PY -- "8. Runs" --> S_TOOL(nvidia-smi / rocm-smi)
        S_PY -- "9. Writes" --> S_JSON(validation_report.json)
    end
    
    J[Central Log Collector (Splunk/ELK)] -- "10. Collects Report" --> S_JSON
```
## 4. Testing Strategy

To ensure the reliability of the validation script in a production environment, a multi-layered testing strategy is employed. This ensures that the script's logic is correct, that it integrates properly with real hardware and tools, and that it works within the larger production workflow.

### Layer 1: Unit Tests (`test_validate.py`)

-   **Purpose:** To test the internal logic of the `validate_gpu.py` script in isolation from the real environment.
-   **Implementation:** These tests use `pytest` and `monkeypatch` to mock all external dependencies, including command-line tools (`nvidia-smi`, `rocm-smi`, `dmidecode`) and file system interactions.
-   **Assertions:** The unit tests verify:
    -   The script's exit code (0 for PASS, 1 for FAIL).
    -   The content of the generated `validation_report.json` to ensure it accurately reflects the test scenario (e.g., correct failure reason).
-   **Execution:** These tests are fast and can be run on any development machine without requiring specific hardware.

### Layer 2: Integration Tests (`test_integration.py`)

-   **Purpose:** To verify that the script correctly interacts with the real command-line tools and hardware on a properly configured test machine.
-   **Implementation:** These tests run the `validate_gpu.py` script on a real system. They do *not* mock the `nvidia-smi` or `rocm-smi` commands. They use `pytest.mark.skipif` to automatically skip tests if the required hardware or tools are not present.
-   **Assertions:** The integration tests primarily verify the script's exit code on a known-good test machine.
-   **Execution:** These tests are intended to be run on dedicated test machines that match the hardware configurations of the production fleet.

### Layer 3: End-to-End (E2E) Tests

-   **Purpose:** To test the entire production workflow, from configuration deployment to report collection.
-   **Implementation:** E2E tests are managed by a higher-level test harness. This harness would:
    1.  Deploy a specific version of the `golden_config.yml` to a test server.
    2.  Trigger the `validate_gpu.py` script (e.g., by rebooting the server to activate the `systemd` service).
    3.  Retrieve the `validation_report.json` from the server.
    4.  Assert the content of the report against the expected outcome.
-   **Execution:** E2E tests are the most comprehensive and are typically run as part of a full system validation or release process.
