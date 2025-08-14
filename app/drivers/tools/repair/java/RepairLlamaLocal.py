import os
from os.path import join
from typing import Any
from typing import Dict

from app.drivers.tools.repair.AbstractRepairTool import AbstractRepairTool


class RepairLlamaLocal(AbstractRepairTool):
    def __init__(self) -> None:
        self.name = os.path.basename(__file__)[:-3].lower()
        super(RepairLlamaLocal, self).__init__(self.name)
        
        # Configure for local/Singularity execution
        self.locally_running = True  # This disables Docker container creation
        self.image_name = "andre15silva/repairllama:latest"
        self.hash_digest = (
            "sha256:84e6a0edc81b9edd08158c41a0ada00aa96ee9dbda699435c61f7f07669af513"
        )
        
        # Singularity specific settings
        self.use_singularity = True
        self.singularity_image_path = None

    def locate(self) -> None:
        """
        Check if Singularity is available and prepare the image
        """
        from app.core import utilities
        from app.core import emitter
        from app.core import values
        
        # Check if singularity is available
        result = utilities.execute_command("which singularity")
        if result != 0:
            result = utilities.execute_command("which apptainer")
            if result != 0:
                utilities.error_exit(
                    "[error] Neither Singularity nor Apptainer found. Please ensure one is installed and available in PATH."
                )
                
        # Set up Singularity image path
        if ":" in self.image_name:
            repo_name, tag_name = self.image_name.split(":")
        else:
            repo_name = self.image_name
            tag_name = "latest"
        
        # Create a directory for storing Singularity images
        sif_dir = os.path.join(values.dir_main, "singularity_images")
        os.makedirs(sif_dir, exist_ok=True)
        
        # Clean image name for file system
        clean_image_name = repo_name.replace("/", "_").replace(":", "_")
        self.singularity_image_path = os.path.join(sif_dir, f"{clean_image_name}_{tag_name}.sif")
        
        # Check if image exists, if not pull it
        if not os.path.exists(self.singularity_image_path):
            emitter.normal(f"\t\t[framework] Pulling Singularity image for {self.name}")
            docker_uri = f"docker://{repo_name}:{tag_name}"
            
            # Use singularity pull to convert Docker image to .sif
            command = f"singularity pull {self.singularity_image_path} {docker_uri}"
            result = utilities.execute_command(command)
            
            if result != 0 or not os.path.exists(self.singularity_image_path):
                utilities.error_exit(f"Failed to pull Singularity image for {self.name}")
        else:
            emitter.normal(f"\t\t[framework] Singularity image found for {self.name}")

    def run_singularity_command(
        self, 
        command: str, 
        log_file_path: str = "/dev/null",
        workdir: str = None,
        env: Dict[str, str] = None
    ) -> int:
        """
        Execute a command using Singularity
        """
        from app.core import utilities
        from app.core import emitter
        
        if not self.singularity_image_path or not os.path.exists(self.singularity_image_path):
            utilities.error_exit("Singularity image not available")
        
        # Build the Singularity exec command
        sing_command = f"singularity exec"
        
        # Add bind mounts for the experiment directories
        # Bind the entire experiment directory tree
        if self.dir_expr:
            experiment_base = os.path.dirname(self.dir_expr)
            sing_command += f" --bind {experiment_base}:{experiment_base}"
        
        # Bind the output directory
        if self.dir_output:
            output_base = os.path.dirname(self.dir_output)
            if output_base != experiment_base:
                sing_command += f" --bind {output_base}:{output_base}"
        
        # Add environment variables
        if env:
            for key, value in env.items():
                sing_command += f" --env {key}={value}"
        
        # Add working directory
        if workdir:
            sing_command += f" --pwd {workdir}"
        elif self.dir_expr:
            sing_command += f" --pwd {self.dir_expr}"
        
        # Add the container image and command
        sing_command += f" {self.singularity_image_path} {command}"
        
        # Redirect output to log file
        if log_file_path and log_file_path != "/dev/null":
            sing_command += f" 2>&1 | tee -a {log_file_path}"
        
        emitter.docker_command(f"(singularity) {sing_command}")
        
        # Execute the command
        return utilities.execute_command(sing_command)

    def invoke(
        self, bug_info: Dict[str, Any], task_config_info: Dict[str, Any]
    ) -> None:
        """
        Main invocation method using Singularity
        """
        from app.core import emitter
        
        emitter.normal(f"\t\t[framework] Running {self.name} with Singularity")
        
        # Ensure Singularity image is available
        if not self.singularity_image_path or not os.path.exists(self.singularity_image_path):
            self.locate()
        
        # Set up directories (same as original)
        dir_java_src = join(self.dir_expr, "src", bug_info["source_directory"])
        dir_test_src = join(self.dir_expr, "src", bug_info["test_directory"])
        dir_java_bin = join(self.dir_expr, "src", bug_info["class_directory"])
        dir_test_bin = join(self.dir_expr, "src", bug_info["test_class_directory"])
        patch_directory = join(self.dir_output, "patches")
        
        # Create output directories on host
        os.makedirs(patch_directory, exist_ok=True)
        
        # Build the RepairLlama command (same as original)
        command = (
            f"python3.10 main.py "
            f"--dir_java_src {dir_java_src} "
            f"--dir_test_src {dir_test_src} "
            f"--dir_java_bin {dir_java_bin} "
            f"--dir_test_bin {dir_test_bin} "
            f"--patch_directory {patch_directory}"
        )

        timeout_h = str(task_config_info[self.key_timeout])
        repair_command = f"timeout -k 5m {timeout_h}h {command}"
        
        # Execute using Singularity
        self.timestamp_log_start()
        
        # Set working directory to where RepairLlama expects to run
        # This might need adjustment based on the container's internal structure
        workdir = "/RepairLlama"  # Adjust this path based on the container
        
        status = self.run_singularity_command(
            repair_command, 
            log_file_path=self.log_output_path,
            workdir=workdir
        )
        
        self.process_status(status)
        self.timestamp_log_end()
        
        emitter.highlight(f"RepairLlama Singularity execution completed. Log: {self.log_output_path}")
