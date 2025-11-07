import pytest
import shutil
import validate_gpu # Import the main script we are testing
import importlib

# -----------------------------------------------------------------------------
# Pytest Fixture: 'monkeypatch'
# 'monkeypatch' is a built-in pytest tool to replace functions during a test.
#
# Pytest Fixture: 'tmp_path'
# 'tmp_path' is a built-in pytest tool that creates a temporary directory
# for each test run, so we don't clutter our file system.
# -----------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clean_module(monkeypatch):
    """
    This fixture automatically runs for every test. It reloads the 
    `validate_gpu` module to ensure that the global `report_data` dictionary
    is reset to its initial state before each test run. This prevents
    state from leaking between tests.
    """
    importlib.reload(validate_gpu)

@pytest.fixture
def mock_tools(monkeypatch):
    """
    A pytest fixture to mock system commands (nvidia-smi, dmidecode, etc.)
    """
    
    # Create a mock 'run_command' function
    def mock_run_command(command):
        # This acts as a router: returns different fake data based on the command
        if "dmidecode -s system-product-name" in command:
            # Pretend we are this NVIDIA server
            return "SYS-421GU-TNXR"
        
        if "nvidia-smi -L" in command:
            # Pretend we have one H100 GPU
            return "GPU 0: NVIDIA H100 80GB PCIe (UUID: ...)"
        
        if "nvidia-smi -q | grep 'VBIOS Version'" in command:
            # Pretend our VBIOS is the *correct* version
            return "    VBIOS Version                       : 96.00.41.00.01"
        
        # Simulate an AMD server (for the BOM mismatch test)
        if "rocm-smi --showproductname" in command:
            return "Card #0: AMD Instinct MI300X"

        # If a command isn't handled by our mock, log it
        validate_gpu.log_msg(f"[MOCK] Unhandled command: {command}", is_error=True)
        return ""

    # Create a mock 'which' function
    def mock_which(tool_name):
        # Pretend only 'nvidia-smi' is "installed"
        if tool_name == "nvidia-smi":
            return "/usr/bin/nvidia-smi"
        return None

    # Apply the patches!
    # 1. Replace the real 'validate_gpu.run_command' with our mock function
    monkeypatch.setattr(validate_gpu, "run_command", mock_run_command)
    # 2. Replace the real 'shutil.which' with our mock function
    monkeypatch.setattr(shutil, "which", mock_which)

@pytest.fixture
def setup_config_files(tmp_path, monkeypatch):
    """
    A fixture to create a fake golden.yml and mock the file paths
    that the main script will use.
    """
    
    # 1. Define the fake golden.yml content
    config_content = """
SYS-421GU-TNXR:
  expected_gpu_vendor: "nvidia"
  gpu_spec:
    expected_model: "NVIDIA H100 80GB PCIe"
    expected_vbios_list:
      - "96.00.41.00.01"
      - "96.00.40.00.05"

SYS-8125GS-TNHR:
  expected_gpu_vendor: "amd"
  gpu_spec:
    expected_model: "AMD Instinct MI300X"
    expected_vbios_list:
      - "123.456.789.001"
      - "123.456.789.000"
    """
    # 2. Create the file in the temporary directory
    config_file = tmp_path / "golden.yml"
    config_file.write_text(config_content)

    # 3. Define a path for the temporary JSON report
    report_file = tmp_path / "report.json"

    # 4. Patch the main script to use these *temporary* file paths
    monkeypatch.setattr(validate_gpu, "CONFIG_FILE_PATH", str(config_file))
    monkeypatch.setattr(validate_gpu, "JSON_REPORT_PATH", str(report_file))


# -----------------------------------------------------------------------------
# --- Test Cases ---
# -----------------------------------------------------------------------------

def test_happy_path_nvidia_pass(mock_tools, setup_config_files):
    """
    Test Case 1: Happy Path (NVIDIA PASS)
    - System model is correct (SYS-421GU-TNXR)
    - 'nvidia-smi' is found
    - GPU model is correct (H100)
    - VBIOS version is correct (in the list)
    - Expected Result: Script exits with code 0 (PASS) and report is correct
    """
    print("\n--- TEST: test_happy_path_nvidia_pass ---")
    
    # We expect main() to call sys.exit(0)
    with pytest.raises(SystemExit) as e:
        validate_gpu.main()
    
    # Assert the exit code is 0
    assert e.value.code == 0

    # Assert the report content
    import json
    report_path = validate_gpu.JSON_REPORT_PATH
    with open(report_path, 'r') as f:
        report = json.load(f)

    assert report["status"] == "PASS"
    assert report["system_model"] == "SYS-421GU-TNXR"
    
    # Ensure all checks passed
    for check in report["checks_performed"]:
        assert check["status"] == "PASS"

    # Check the GPU model check specifically
    gpu_model_check = report["checks_performed"][1]
    assert gpu_model_check["component"] == "GPU_0_Model"
    assert gpu_model_check["expected"] == "NVIDIA H100 80GB PCIe"

def test_happy_path_amd_pass(monkeypatch, setup_config_files):
    """
    Test Case 5: Happy Path (AMD PASS)
    - Mocks a server that *is* an AMD server (SYS-8125GS-TNHR).
    - Mocks that 'rocm-smi' is found.
    - Mocks that the model and VBIOS are correct.
    - Expected Result: Script exits with code 0 (PASS)
    """
    print("\n--- TEST: test_happy_path_amd_pass ---")

    # 1. Mock 'which' to find *only* rocm-smi
    def mock_which_amd(tool_name):
        if tool_name == "rocm-smi":
            return "/usr/bin/rocm-smi"
        return None
    
    monkeypatch.setattr(shutil, "which", mock_which_amd)

    # 2. Mock 'run_command' to return AMD-specific values
    def mock_run_command_amd(command):
        if "dmidecode -s system-product-name" in command:
            return "SYS-8125GS-TNHR" # <-- This is the key for the YAML
        
        if "rocm-smi --showproductname" in command:
            # Return the correct model from the YAML
            return "Card #0: AMD Instinct MI300X"
        
        if "rocm-smi --showvbios" in command:
            # Return a VBIOS that is in the YAML's list
            return "Card #0: VBIOS version: 123.456.789.001"
        
        return "" # Ignore other commands
    
    monkeypatch.setattr(validate_gpu, "run_command", mock_run_command_amd)

    # We expect main() to call sys.exit(0)
    with pytest.raises(SystemExit) as e:
        validate_gpu.main()
    
    # Assert the exit code is 0
    assert e.value.code == 0


def test_fail_path_nvidia_wrong_vbios(monkeypatch, setup_config_files):
    """
    Test Case 2: Failure Path (NVIDIA Wrong VBIOS)
    - System model is correct (SYS-421GU-TNXR)
    - 'nvidia-smi' is found
    - GPU model is correct (H100)
    - VBIOS version is *incorrect*
    - Expected Result: Script exits with code 1 (FAIL) and report shows VBIOS mismatch
    """
    print("\n--- TEST: test_fail_path_nvidia_wrong_vbios ---")

    # 1. Mock 'which' to find nvidia-smi
    def mock_which(tool_name):
        if tool_name == "nvidia-smi":
            return "/usr/bin/nvidia-smi"
        return None
    monkeypatch.setattr(shutil, "which", mock_which)

    # 2. Mock 'run_command' to return the wrong VBIOS
    def mock_run_command_wrong_vbios(command):
        if "dmidecode -s system-product-name" in command:
            return "SYS-421GU-TNXR"
        if "nvidia-smi -L" in command:
            return "GPU 0: NVIDIA H100 80GB PCIe (UUID: ...)"
        if "nvidia-smi -q | grep 'VBIOS Version'" in command:
            return "    VBIOS Version                       : 99.99.99.99.99"
        return ""
    monkeypatch.setattr(validate_gpu, "run_command", mock_run_command_wrong_vbios)

    # We expect main() to call sys.exit(1)
    with pytest.raises(SystemExit) as e:
        validate_gpu.main()
    
    # Assert the exit code is 1
    assert e.value.code == 1

    # Assert the report content
    import json
    report_path = validate_gpu.JSON_REPORT_PATH
    with open(report_path, 'r') as f:
        report = json.load(f)

    assert report["status"] == "FAIL"
    vbios_check = next((c for c in report["checks_performed"] if c["component"] == "GPU_0_VBIOS"), None)
    assert vbios_check is not None
    assert vbios_check["status"] == "FAIL"
    assert vbios_check["actual"] == "99.99.99.99.99"

def test_fail_path_bom_mismatch(monkeypatch, mock_tools, setup_config_files):
    """
    Test Case 3: Failure Path (BOM Mismatch - Wrong Vendor)
    - System model is correct (SYS-421GU-TNXR) -> YAML expects 'nvidia'
    - But the system *only* has 'rocm-smi' (AMD card installed)
    - Expected Result: Script fails at BOM validation (Exit Code 1)
    """
    print("\n--- TEST: test_fail_path_bom_mismatch ---")

    # *** Override the mock_tools 'which' return value ***
    def mock_which_amd(tool_name):
        if tool_name == "rocm-smi":
            # Pretend only the AMD tool is found
            return "/usr/bin/rocm-smi" 
        return None
    
    monkeypatch.setattr(shutil, "which", mock_which_amd)

    # We expect main() to call sys.exit(1)
    with pytest.raises(SystemExit) as e:
        validate_gpu.main()
    
    # Assert the exit code is 1
    assert e.value.code == 1

def test_fail_path_config_not_found(monkeypatch):
    """
    Test Case 4: Failure Path (Config Not Found)
    - The golden_config.yml file is missing.
    - Expected Result: Script fails early (Exit Code 1)
    """
    print("\n--- TEST: test_fail_path_config_not_found ---")

    # Patch CONFIG_FILE_PATH to a non-existent path
    monkeypatch.setattr(validate_gpu, "CONFIG_FILE_PATH", "/tmp/non_existent_file.yml")
    # (We don't need to mock commands; it should fail before that)

    with pytest.raises(SystemExit) as e:
        validate_gpu.main()
    
    assert e.value.code == 1

