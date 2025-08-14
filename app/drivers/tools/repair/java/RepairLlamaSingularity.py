import os
from os.path import join
from typing import Any
from typing import Dict

from app.drivers.tools.repair.java.RepairLlama import RepairLlama


class RepairLlamaSingularity(RepairLlama):
    def __init__(self) -> None:
        super().__init__()
        self.name = "repairllama-singularity"
        # Set this tool to run with Singularity instead of Docker
        self.locally_running = False  # We still want container-like behavior
        self.use_singularity = True   # Custom flag to indicate Singularity usage
        # Keep the same image name, but it will be converted to Singularity format
        self.image_name = "andre15silva/repairllama:latest"
        self.hash_digest = (
            "sha256:84e6a0edc81b9edd08158c41a0ada00aa96ee9dbda699435c61f7f07669af513"
        )

    def ensure_tool_exists(self, tag_name_default: str = "latest") -> None:
        """
        Override to use Singularity instead of Docker for image handling
        """
        from app.core import singularity
        from app.core import emitter
        from app.core import utilities
        from app.core import values

        # Check if Singularity/Apptainer is available
        try:
            singularity.get_client()
        except RuntimeError as e:
            utilities.error_exit(str(e))

        if self.image_name is None:
            utilities.error_exit(
                f"\t[framework] {self.name} does not provide a Container Image"
            )

        if ":" in self.image_name:
            repo_name, tag_name = self.image_name.split(":")
        else:
            repo_name = self.image_name
            tag_name = tag_name_default

        if not singularity.image_exists(repo_name, tag_name):
            emitter.warning(
                f"\t[framework] singularity image {repo_name}:{tag_name} not found locally"
            )
            image_path = singularity.pull_image(repo_name, tag_name)
            if image_path is None:
                utilities.error_exit(
                    f"\t[framework] {self.name} could not pull Docker image {repo_name}:{tag_name} and convert to Singularity"
                )
        else:
            emitter.information(
                f"\t\t[framework] singularity image {repo_name}:{tag_name} found locally for {self.name}"
            )

    def run_command(
        self,
        command: str,
        log_file_path: str = "/dev/null",
        dir_path: str = None,
        env: Dict[str, str] = dict(),
        run_as_sudo: bool = False,
    ) -> int:
        """
        Override run_command to use Singularity exec when container_id is set
        """
        from app.core import singularity
        from app.core import utilities
        from app.core import values

        temp_env = {
            **env,
            "EXPERIMENT_DIR": (
                values.container_base_experiment
                if self.container_id
                else self.dir_base_expr
            ),
        }

        if self.container_id and hasattr(self, 'use_singularity') and self.use_singularity:
            # Use Singularity exec
            if not dir_path:
                dir_path = values.container_base_experiment
            
            exit_code, output = singularity.exec_command(
                self.container_id, command, dir_path, temp_env
            )
            
            # Handle output logging (simplified version)
            if "/dev/null" not in log_file_path and output:
                stdout, stderr = output
                if stdout:
                    self.append_file([stdout.decode("iso-8859-1")], log_file_path)
                if stderr:
                    self.append_file([stderr.decode("iso-8859-1")], log_file_path)
        else:
            # Fall back to regular command execution for local runs
            if not dir_path:
                dir_path = self.dir_expr
            command += " 2>&1 | tee -a {0}".format(log_file_path)
            exit_code = utilities.execute_command(command, env=temp_env, directory=dir_path)

        self.command_history.append((dir_path, command, temp_env))
        return exit_code

    def invoke(
        self, bug_info: Dict[str, Any], task_config_info: Dict[str, Any]
    ) -> None:
        """
        Main invocation method - same as parent but with Singularity support
        """
        from app.core import singularity
        from app.core import emitter

        if hasattr(self, 'use_singularity') and self.use_singularity and self.container_id:
            emitter.normal(f"\t\t[framework] Using Singularity container: {self.container_id}")

        # Call the parent invoke method which contains the actual RepairLlama logic
        super().invoke(bug_info, task_config_info)

    def update_dir_info(self, dir_info) -> None:
        """
        Override to handle Singularity-specific directory setup
        """
        from app.core import values

        if hasattr(self, 'use_singularity') and self.use_singularity and self.container_id:
            # For Singularity, we use container paths like Docker but with different backend
            self.dir_expr = dir_info["container"]["experiment"]
            self.dir_logs = dir_info["container"]["logs"]
            self.dir_inst = dir_info["container"]["instrumentation"]
            self.dir_setup = dir_info["container"]["setup"]
            self.dir_output = dir_info["container"]["artifacts"]
            self.dir_base_expr = values.container_base_experiment
        else:
            # Fall back to local paths
            super().update_dir_info(dir_info)

        # Set up patch directory
        self.dir_patch = join(
            self.dir_output,
            "patch-valid" if self.use_valkyrie else "patches",
        )
