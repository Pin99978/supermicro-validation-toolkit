import pytest
import shutil
import os
import validate_gpu

# --- Integration Test Example ---

# This is a real golden config for a specific test machine.
# In a real production environment, this might be stored in a separate
# test-specific config file.
INTEGRATION_CONFIG_CONTENT_NVIDIA = """
SYS-TEST-RIG-NVIDIA:
  expected_gpu_vendor: "nvidia"
  gpu_spec:
    # NOTE: You would change this to match the GPU in your test machine
    expected_model: "NVIDIA GeForce RTX 3080"
    expected_vbios_list:
      - "94.02.71.80.54"
"""

INTEGRATION_CONFIG_CONTENT_AMD = """
SYS-TEST-RIG-AMD:
  expected_gpu_vendor: "amd"
  gpu_spec:
    # NOTE: You would change this to match the GPU in your test machine
    expected_model: "AMD Radeon RX 6800 XT"
    expected_vbios_list:
      - "113-D5121100-102"
"""

@pytest.mark.skipif(not shutil.which("nvidia-smi"), reason="nvidia-smi not found, skipping NVIDIA integration test")
def test_integration_nvidia_on_real_hardware(tmp_path, monkeypatch):
    """
    Integration test to be run on a real machine with an NVIDIA GPU.
    """
    print("\n--- TEST: test_integration_nvidia_on_real_hardware ---")

    # --- Setup ---
    config_file = tmp_path / "golden.yml"
    config_file.write_text(INTEGRATION_CONFIG_CONTENT_NVIDIA)

    monkeypatch.setattr(validate_gpu, "CONFIG_FILE_PATH", str(config_file))
    monkeypatch.setattr(validate_gpu, "JSON_REPORT_PATH", tmp_path / "report.json")

    original_run_command = validate_gpu.run_command
    def mock_run_command_for_integration(command):
        if "dmidecode -s system-product-name" in command:
            return "SYS-TEST-RIG-NVIDIA"
        return original_run_command(command)

    monkeypatch.setattr(validate_gpu, "run_command", mock_run_command_for_integration)

    # --- Execution & Assertion ---
    with pytest.raises(SystemExit) as e:
        validate_gpu.main()
    
    # NOTE: This assertion depends on the test machine being correctly configured
    # to match the INTEGRATION_CONFIG_CONTENT_NVIDIA above.
    assert e.value.code == 0

@pytest.mark.skipif(not shutil.which("rocm-smi"), reason="rocm-smi not found, skipping AMD integration test")
def test_integration_amd_on_real_hardware(tmp_path, monkeypatch):
    """
    Integration test to be run on a real machine with an AMD GPU.
    """
    print("\n--- TEST: test_integration_amd_on_real_hardware ---")

    # --- Setup ---
    config_file = tmp_path / "golden.yml"
    config_file.write_text(INTEGRATION_CONFIG_CONTENT_AMD)

    monkeypatch.setattr(validate_gpu, "CONFIG_FILE_PATH", str(config_file))
    monkeypatch.setattr(validate_gpu, "JSON_REPORT_PATH", tmp_path / "report.json")

    original_run_command = validate_gpu.run_command
    def mock_run_command_for_integration(command):
        if "dmidecode -s system-product-name" in command:
            return "SYS-TEST-RIG-AMD"
        return original_run_command(command)

    monkeypatch.setattr(validate_gpu, "run_command", mock_run_command_for_integration)

    # --- Execution & Assertion ---
    with pytest.raises(SystemExit) as e:
        validate_gpu.main()
    
    # NOTE: This assertion depends on the test machine being correctly configured
    # to match the INTEGRATION_CONFIG_CONTENT_AMD above.
    assert e.value.code == 0
