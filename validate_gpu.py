#!/usr/bin/env python3

"""
Supermicro GPU Validation Script test

This script validates GPU components against a YAML config file
and outputs a structured JSON report.
"""

import subprocess
import sys
import re
import shutil
import json
import datetime
from abc import ABC, abstractmethod
try:
    import yaml
except ImportError:
    print("[FAIL] PyYAML library not found. Please run: pip install pyyaml")
    sys.exit(1)

# --- Configuration ---
CONFIG_FILE_PATH = "./golden_config.yml"
JSON_REPORT_PATH = "./validation_report.json" # Machine-readable output

# --- Global Report Dictionary ---
# We will build this dictionary as the script runs
report_data = {
    "report_id": f"validation_report_{datetime.datetime.now().isoformat()}",
    "status": "FAIL", # Will be set to PASS at the end if failures == 0
    "system_model": "Unknown",
    "checks_performed": []
}

# --- Standalone Helper Functions ---

def log_msg(message, is_error=False):
    """Helper function for logging to stdout."""
    prefix = "[FAIL]" if is_error else "[INFO]"
    print(f"{prefix} {message}")

def add_check_to_report(component, status, expected, actual, notes=""):
    """
    Adds a structured result to our global report_data dictionary.
    This is the core of the JSON reporting.
    """
    report_data["checks_performed"].append({
        "component": component,
        "status": status,
        "expected": expected,
        "actual": actual,
        "notes": notes
    })

def run_command(command):
    """
    Runs a shell command and returns its stdout.
    Handles command failures and not found errors.
    """
    try:
        result = subprocess.run(
            command, 
            shell=True, 
            check=True, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE,
            text=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        log_msg(f"Command failed: '{command}'", is_error=True)
        log_msg(f"Stderr: {e.stderr.strip()}", is_error=True)
        return None
    except FileNotFoundError:
        log_msg(f"Command '{command.split()[0]}' not found. Is it installed and in PATH?", is_error=True)
        return None

# --- Abstract Base Class (The "Interface") ---

class GpuValidator(ABC):
    """Abstract Base Class for GPU validators."""
    def __init__(self, gpu_spec):
        self.spec = gpu_spec
        self.failures = 0
        self.vendor_name = "Unknown" # Should be overridden by child

    def validate(self):
        """Generic validation flow."""
        log_msg(f"--- Starting {self.vendor_name} GPU Validation ---")
        
        try:
            expected_model = self.spec['expected_model']
            expected_vbios_list = self.spec['expected_vbios_list']
            log_msg(f"Golden YAML loaded. Verifying against:")
            log_msg(f"  - Model: {expected_model}")
            log_msg(f"  - VBIOS (any of): {', '.join(expected_vbios_list)}")
        except KeyError as e:
            log_msg(f"Missing key {e} in [gpu_spec][{self.vendor_name.lower()}] section of YAML", is_error=True)
            add_check_to_report(f"{self.vendor_name.upper()}_CONFIG", "FAIL", "Config to be present", "Missing keys", str(e))
            self.failures += 1
            return False

        # --- Model and VBIOS Checks ---
        self._check_models(expected_model)
        self._check_vbios(expected_vbios_list)

        log_msg(f"--- {self.vendor_name} GPU Validation Finished ---")
        return self.failures == 0

    def _validate_list_of_items(self, items, check_name, expected_value, parser_regex, is_vbios=False):
        """Generic helper to validate a list of strings against an expected value."""
        if not items:
            log_msg(f"  [FAIL] Command returned no items for {check_name}.", is_error=True)
            self.failures += 1
            return

        for i, line in enumerate(items):
            match = re.search(parser_regex, line)
            if match:
                current_value = match.group(1).strip()
                is_match = False
                if is_vbios:
                    is_match = current_value in expected_value
                else:
                    is_match = current_value == expected_value

                if is_match:
                    log_msg(f"  [PASS] GPU {i} {check_name}: {current_value}")
                    add_check_to_report(f"GPU_{i}_{check_name}", "PASS", expected_value, current_value)
                else:
                    log_msg(f"  [FAIL] GPU {i} {check_name} Mismatch. Expected: '{expected_value}', Found: '{current_value}'", is_error=True)
                    add_check_to_report(f"GPU_{i}_{check_name}", "FAIL", expected_value, current_value)
                    self.failures += 1
            else:
                log_msg(f"  [FAIL] Could not parse {check_name} string for GPU {i}: {line}", is_error=True)
                add_check_to_report(f"GPU_{i}_{check_name}", "FAIL", expected_value, "Parse Error", line)
                self.failures += 1

    @abstractmethod
    def _check_models(self, expected_model):
        pass

    @abstractmethod
    def _check_vbios(self, expected_vbios_list):
        pass

# --- Concrete Validator Classes ---

class NvidiaValidator(GpuValidator):
    """Concrete validation class for NVIDIA GPUs using 'nvidia-smi'."""
    def __init__(self, gpu_spec):
        super().__init__(gpu_spec)
        self.vendor_name = "NVIDIA"

    def _check_models(self, expected_model):
        log_msg("Checking GPU Models...")
        models_output = run_command("nvidia-smi -L")
        if models_output is None: self.failures += 1; return
        self._validate_list_of_items(
            models_output.split('\n'), 
            "Model", 
            expected_model, 
            r'GPU \d+: (.*?) \(UUID:'
        )

    def _check_vbios(self, expected_vbios_list):
        log_msg("Checking GPU VBIOS Versions...")
        vbios_output = run_command("nvidia-smi -q | grep 'VBIOS Version'")
        if vbios_output is None: self.failures += 1; return
        self._validate_list_of_items(
            vbios_output.split('\n'), 
            "VBIOS", 
            expected_vbios_list, 
            r':\s+(.*)', 
            is_vbios=True
        )

class AmdValidator(GpuValidator):
    """
    Concrete validation class for AMD GPUs using 'rocm-smi'.
    All AMD-specific logic is encapsulated here.
    """
    def __init__(self, gpu_spec):
        super().__init__(gpu_spec)
        self.vendor_name = "AMD"
        self.gpu_count = 0

    def _check_models(self, expected_model):
        log_msg("Checking GPU Models...")
        models_output = run_command("rocm-smi --showproductname")
        if models_output is None: 
            add_check_to_report("ROCM_SMI_MODEL", "FAIL", "Command to run", "Command failed")
            self.failures += 1
            return
        
        gpu_models = [line for line in models_output.split('\n') if line.strip()]
        self.gpu_count = len(gpu_models)
        log_msg(f"Found {self.gpu_count} AMD GPU(s).")

        self._validate_list_of_items(
            gpu_models, 
            "Model", 
            expected_model, 
            r'Card #\d+:\s+(.*)'
        )

    def _check_vbios(self, expected_vbios_list):
        log_msg("Checking GPU VBIOS Versions...")
        vbios_output = run_command("rocm-smi --showvbios")
        if vbios_output is None: 
            add_check_to_report("ROCM_SMI_VBIOS", "FAIL", "Command to run", "Command failed")
            self.failures += 1
            return
        
        vbios_versions = [line for line in vbios_output.split('\n') if line.strip()]
        
        if len(vbios_versions) != self.gpu_count:
            log_msg(f"  [FAIL] VBIOS count ({len(vbios_versions)}) does not match GPU count ({self.gpu_count}).", is_error=True)
            self.failures += 1
            return

        self._validate_list_of_items(
            vbios_versions, 
            "VBIOS", 
            expected_vbios_list, 
            r'VBIOS version:\s+(.*)', 
            is_vbios=True
        )

class IntelValidator(GpuValidator):
    """Placeholder class for Intel GPU validation."""
    def __init__(self, gpu_spec):
        super().__init__(gpu_spec)
        self.vendor_name = "Intel"

    def _check_models(self, expected_model):
        log_msg("[INFO] Intel Validator (_check_models) is not implemented in this demo.")
        add_check_to_report("Intel_Check", "SKIP", "N/A", "N/A", "Not Implemented")

    def _check_vbios(self, expected_vbios_list):
        log_msg("[INFO] Intel Validator (_check_vbios) is not implemented in this demo.")

# --- Factory Function ---

def get_validator(expected_vendor, gpu_spec):
    """Factory function to return the correct validator instance."""
    if expected_vendor == 'nvidia':
        return NvidiaValidator(gpu_spec)
    elif expected_vendor == 'amd':
        return AmdValidator(gpu_spec)
    elif expected_vendor == 'intel':
        return IntelValidator(gpu_spec)
    else:
        log_msg(f"No validator defined for vendor: {expected_vendor}", is_error=True)
        return None

# --- Main Execution ---

def get_system_model():
    """Gets the system model name."""
    log_msg("--- [Phase 1: BOM Validation] ---")
    current_model = run_command("dmidecode -s system-product-name | tr -d ' '")
    if not current_model:
        log_msg("Cannot read system model name (dmidecode failed or returned empty).", is_error=True)
        log_msg("--> Did you forget to run with 'sudo'?", is_error=True)
        add_check_to_report("System_Model", "FAIL", "Any Model", "Read Error")
        return None
    log_msg(f"Detected system model: {current_model}")
    report_data["system_model"] = current_model
    return current_model

def load_config(file_path):
    """Loads the YAML configuration file."""
    try:
        with open(file_path, 'r') as f:
            config = yaml.safe_load(f)
        if config is None:
            log_msg(f"Golden YAML file is empty or malformed: {file_path}", is_error=True)
            add_check_to_report("YAML_Parse", "FAIL", "Valid YAML data", "File is empty or invalid")
            return None
        return config
    except Exception as e:
        log_msg(f"Failed to load Golden YAML: {e}", is_error=True)
        add_check_to_report("YAML_Load", "FAIL", file_path, "Load Error", str(e))
        return None

def run_validation(current_model, config):
    """Runs the main validation logic."""
    failures = 0
    if current_model not in config:
        log_msg(f"System model '{current_model}' is not defined in {CONFIG_FILE_PATH}", is_error=True)
        add_check_to_report("YAML_Spec", "FAIL", f"Spec for {current_model}", "Not Found")
        return 1

    model_spec = config[current_model]
    log_msg(f"Successfully loaded spec for '{current_model}'")

    log_msg("--- [Phase 2: GPU Validation] ---")
    expected_vendor = model_spec.get('expected_gpu_vendor')
    if not expected_vendor:
        log_msg(f"'expected_gpu_vendor' not defined for '{current_model}' in YAML.", is_error=True)
        add_check_to_report("GPU_Vendor", "FAIL", "Vendor Spec", "Not Defined in YAML")
        return 1

    log_msg(f"BOM requires GPU vendor: {expected_vendor}")

    tool_found = None
    if shutil.which("nvidia-smi"): tool_found = "nvidia"
    elif shutil.which("rocm-smi"): tool_found = "amd"
    elif shutil.which("level-zero-ctl"): tool_found = "intel"

    if tool_found != expected_vendor:
        log_msg(f"BOM validation FAILED! Expected vendor '{expected_vendor}', but found '{tool_found}' tool (or tool not found).", is_error=True)
        add_check_to_report("GPU_Vendor", "FAIL", expected_vendor, str(tool_found))
        failures += 1
    else:
        log_msg(f"[PASS] GPU vendor validated (found {tool_found} tool).")
        add_check_to_report("GPU_Vendor", "PASS", expected_vendor, tool_found)
        
        gpu_spec = model_spec.get('gpu_spec')
        if not gpu_spec:
            log_msg(f"'gpu_spec' not defined for '{current_model}' in YAML.", is_error=True)
            add_check_to_report("GPU_Spec", "FAIL", "Spec to exist", "Not Defined in YAML")
            failures += 1
        else:
            validator = get_validator(expected_vendor, gpu_spec)
            if validator and not validator.validate():
                failures += validator.failures
    return failures

def write_report(failures):
    """Writes the JSON report file."""
    if failures == 0:
        log_msg("All checks passed.")
        report_data["status"] = "PASS"
    else:
        log_msg(f"{failures} failure(s) detected.")
        report_data["status"] = "FAIL"

    try:
        with open(JSON_REPORT_PATH, 'w') as f:
            json.dump(report_data, f, indent=2)
        log_msg(f"Successfully wrote JSON report to {JSON_REPORT_PATH}")
    except PermissionError:
        log_msg(f"Permission denied writing to {JSON_REPORT_PATH}. Try running as root.", is_error=True)
        local_report_path = "./validation_report.json"
        try:
            with open(local_report_path, 'w') as f:
                json.dump(report_data, f, indent=2)
            log_msg(f"Wrote fallback report to {local_report_path}")
        except Exception as e:
            log_msg(f"Failed to write fallback report: {e}", is_error=True)
    except Exception as e:
        log_msg(f"Failed to write JSON report: {e}", is_error=True)

def print_final_result(failures, system_model):
    """Prints the final result to the console."""
    print("\n" + "="*30)
    if failures == 0:
        print(f"  FINAL RESULT: [PASS]")
        print(f"  System '{system_model}' fully matches the Golden YAML standard.")
        print("="*30)
        sys.exit(0)
    else:
        print(f"  FINAL RESULT: [FAIL] ({failures} failure(s) detected)")
        print(f"  System '{system_model}' does NOT match the Golden YAML standard.")
        print("="*30)
        sys.exit(1)

def main():
    """Main function to run the validation script."""
    system_model = get_system_model()
    if not system_model:
        sys.exit(1)

    config = load_config(CONFIG_FILE_PATH)
    if not config:
        sys.exit(1)

    failures = run_validation(system_model, config)
    write_report(failures)
    print_final_result(failures, system_model)

if __name__ == "__main__":
    main()