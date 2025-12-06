##### FILE: ./run.py #####
import subprocess
import sys
import time
import os
import importlib.util

def install_package(package_name):
    print(f"--> Local Mode: Installing '{package_name}' for microphone support...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package_name])
        print(f"--> '{package_name}' installed successfully.\n")
    except subprocess.CalledProcessError:
        print(f"!! Warning: Could not install '{package_name}'. Microphone might not work.\n")

def check_and_install_dependencies():
    # Check if sounddevice is installed
    if importlib.util.find_spec("sounddevice") is None:
        install_package("sounddevice")

def run_services():
    # 1. Auto-install local-only dependencies
    check_and_install_dependencies()

    # Detect the current python executable
    python_exe = sys.executable

    print("--- STARTING AUDIO APP LOCALLY ---")

    # 2. Start the Backend (Audio Engine)
    print(f"[1/2] Launching Backend on port 8765...")
    backend_process = subprocess.Popen(
        [python_exe, "src/backend.py"],
        env=dict(os.environ, PORT="8765")
    )

    # Give backend a moment to initialize
    time.sleep(1)

    # 3. Start the Frontend (Dash)
    print(f"[2/2] Launching Frontend on http://127.0.0.1:8050 ...")
    frontend_process = subprocess.Popen(
        [python_exe, "app.py"]
    )

    print("\n--> App is running! Open your browser to: http://127.0.0.1:8050")
    print("--> Press CTRL+C to stop both servers.\n")

    try:
        while True:
            time.sleep(1)
            if backend_process.poll() is not None:
                print("Backend process ended unexpectedly.")
                break
            if frontend_process.poll() is not None:
                print("Frontend process ended unexpectedly.")
                break
    except KeyboardInterrupt:
        print("\nStopping servers...")
    finally:
        backend_process.terminate()
        frontend_process.terminate()
        backend_process.wait()
        frontend_process.wait()
        print("Servers stopped.")

if __name__ == "__main__":
    run_services()