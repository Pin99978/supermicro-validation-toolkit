# Supermicro Validation Toolkit

This repository contains the solution for the interview assignment from David, target is for the validation GPU version 

## Assignment Solution

This solution is built as a complete, professional toolkit, demonstrating best practices in software design, configuration management, and testing.

### 1. The Validator: `validate_gpu.py`

The core Python script that runs on each target server.

* **Object-Oriented Design:** Uses an extensible, class-based design (e.g., `NvidiaValidator`, `AmdValidator`) to easily support new GPU vendors (like Intel) without refactoring the main script.
* **BOM-Centric Logic:** The script first identifies its own System Model (`dmidecode`) and then validates *against* the specific hardware profile defined in `golden_config.yml`.
* **I/O:**
    * **Input:** Parses a YAML config file (`golden_config.yml`).
    * **Output:** Generates a machine-readable JSON report (`validation_report.json`) for easy integration with monitoring tools.
    * **Exit Codes:** Exits with `0` (Pass) or `1` (Fail) for automated workflows.

### 2. The Configuration: `golden_config.yml`

The "Single Source of Truth" that defines the expected hardware for different server models.

* **Format:** Uses YAML for its superior readability and ability to handle complex data structures (like lists of approved VBIOS versions).
* **Structure:** This config is **BOM-centric**, using the `system_model` as the primary key. This allows a single config file to manage an entire diverse fleet of servers.

### 3. The Architecture: (See `/docs/architecture.md`)

This optional document (as requested) details the full deployment and management architecture. It covers:

* The "Diag Host" (`ssh`/`scp`) push model for deploying updates.
* The Change Control workflow (using `git` and a "Golden Server") for safely updating the `golden_config.yml`.
* An example `systemd` service file.

### 4. The Tests: `test_validation.py`

A `pytest` script that provides 100% logical test coverage for `validate_gpu.py`.

* **Mocking:** Uses `pytest-mock` (`monkeypatch`) to simulate system commands (`dmidecode`, `nvidia-smi`) and the file system.
* **Test Cases:** Includes tests for:
    * Happy Path (Correct hardware).
    * VBIOS Mismatch (Wrong firmware).
    * BOM Mismatch (Wrong GPU vendor installed).
    * File Not Found errors.