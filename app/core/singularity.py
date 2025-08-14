import json
import os
import random
import traceback
from typing import Any
from typing import cast
from typing import Dict
from typing import List
from typing import Optional
from typing import Sequence
from typing import Set
from typing import Tuple
from typing import Union

from app.core import definitions
from app.core import emitter
from app.core import utilities
from app.core import values

cached_client = None
image_map = {}
container_list: Set[str] = set()


def get_client():
    """
    For Singularity, we don't need a client like Docker, but we maintain the interface
    """
    global cached_client
    if not cached_client:
        # Check if singularity is available
        result = utilities.execute_command("which singularity")
        if result != 0:
            result = utilities.execute_command("which apptainer")
            if result != 0:
                raise RuntimeError(
                    "[error] Neither Singularity nor Apptainer found. Please ensure one is installed and available in PATH."
                )
        cached_client = "singularity"  # Just a placeholder
        emitter.debug("Singularity client initialized")
    return cached_client


def image_exists(image_name: str, tag_name: str = "latest") -> bool:
    """
    Check if a Singularity image exists locally
    """
    _ = get_client()
    
    # For Singularity, we check if the .sif file exists
    sif_path = get_sif_path(image_name, tag_name)
    exists = os.path.exists(sif_path)
    emitter.debug("Checking for Singularity image {} with tag {}: {}".format(image_name, tag_name, exists))
    return exists


def get_image(image_name: str, tag_name: str = "latest") -> Optional[str]:
    """
    Get the path to a Singularity image file
    """
    _ = get_client()
    sif_path = get_sif_path(image_name, tag_name)
    if os.path.exists(sif_path):
        return sif_path
    return None


def get_sif_path(image_name: str, tag_name: str = "latest") -> str:
    """
    Generate the path where Singularity image should be stored
    """
    # Create a directory for storing Singularity images
    sif_dir = os.path.join(values.dir_main, "singularity_images")
    os.makedirs(sif_dir, exist_ok=True)
    
    # Clean image name for file system
    clean_image_name = image_name.replace("/", "_").replace(":", "_")
    sif_filename = f"{clean_image_name}_{tag_name}.sif"
    return os.path.join(sif_dir, sif_filename)


def pull_image(image_name: str, tag_name: str) -> Optional[str]:
    """
    Pull a Docker image and convert it to Singularity format
    """
    _ = get_client()
    emitter.normal(
        "\t\t[framework] pulling docker image {}:{} and converting to Singularity".format(image_name, tag_name)
    )
    
    sif_path = get_sif_path(image_name, tag_name)
    docker_uri = f"docker://{image_name}:{tag_name}"
    
    try:
        # Use singularity pull to convert Docker image to .sif
        command = f"singularity pull {sif_path} {docker_uri}"
        result = utilities.execute_command(command)
        
        if result == 0 and os.path.exists(sif_path):
            emitter.debug(f"Successfully pulled and converted image to {sif_path}")
            return sif_path
        else:
            emitter.warning(f"Failed to pull image {image_name}:{tag_name}")
            return None
            
    except Exception as ex:
        emitter.warning(f"Error pulling image: {ex}")
        return None


def build_container(
    container_name: str,
    volume_list: Dict[str, Dict[str, str]],
    image_name: str,
    cpu: List[str],
    gpu: List[str],
    container_config_dict: Optional[Dict[Any, Any]] = None,
    disable_network: bool = False,
) -> Optional[str]:
    """
    Start a Singularity container (which is more like running a command)
    For Singularity, we don't "build" containers like Docker, we run them
    """
    _ = get_client()
    emitter.normal("\t\t[framework] preparing singularity container: ")
    emitter.normal("\t\t\t container image: {}".format(image_name))
    emitter.normal("\t\t\t container name: {}".format(container_name))
    
    # Get the Singularity image file
    if ":" in image_name:
        repo_name, tag_name = image_name.split(":")
    else:
        repo_name = image_name
        tag_name = "latest"
        
    sif_path = get_sif_path(repo_name, tag_name)
    
    if not os.path.exists(sif_path):
        emitter.warning(f"Singularity image not found: {sif_path}")
        # Try to pull it
        if pull_image(repo_name, tag_name) is None:
            return None
    
    # For Singularity, we return the path to the .sif file as the "container_id"
    # The actual execution will happen in exec_command
    container_list.add(container_name)
    return sif_path


def exec_command(
    container_id: str,  # This is actually the .sif file path for Singularity
    command: str,
    workdir: str = values.container_base_experiment,
    env: Dict[str, str] = dict(),
) -> Tuple[int, Optional[Tuple[Optional[bytes], Optional[bytes]]]]:
    """
    Execute a command in a Singularity container
    """
    exit_code: int = -1
    output: Optional[Tuple[Optional[bytes], Optional[bytes]]] = None
    
    try:
        # Build the Singularity exec command
        sing_command = f"singularity exec"
        
        # Add environment variables
        for key, value in env.items():
            sing_command += f" --env {key}={value}"
        
        # Add working directory
        if workdir != values.container_base_experiment:
            sing_command += f" --pwd {workdir}"
        
        # Add the container image and command
        sing_command += f" {container_id} {command}"
        
        emitter.docker_command(f"(singularity) {sing_command}")
        
        # Execute the command
        exit_code = utilities.execute_command(sing_command)
        
        # Note: For simplicity, we're not capturing stdout/stderr separately
        # like Docker does. This could be enhanced if needed.
        output = (None, None)
        
    except Exception as ex:
        emitter.error(f"Error executing singularity command: {ex}")
        exit_code = -1
    
    return exit_code, output


def get_container(container_id: str) -> Optional[str]:
    """
    For Singularity, this just returns the container_id (sif path) if it exists
    """
    if os.path.exists(container_id):
        return container_id
    return None


def get_container_id(container_name: str, ignore_not_found: bool) -> Optional[str]:
    """
    For Singularity, we don't have persistent containers like Docker
    Returns None as containers are not persistent
    """
    return None


def get_container_stats(container_id: str) -> Optional[Dict[str, Any]]:
    """
    Singularity doesn't provide the same container stats as Docker
    Return empty stats
    """
    return {"memory": {"usage": 0}, "cpu_stats": {"cpu_usage": {"total_usage": 0}}}


def remove_container(container_id: str) -> None:
    """
    For Singularity, containers are not persistent, so nothing to remove
    """
    if container_id in container_list:
        container_list.remove(container_id)
    emitter.debug(f"Singularity container cleanup: {container_id}")


def start_container(container_id: str) -> None:
    """
    Singularity containers are not persistent, so nothing to start
    """
    emitter.debug(f"Singularity container start (no-op): {container_id}")


def stop_container(container_id: str, timeout: int = 120) -> None:
    """
    Singularity containers are not persistent, so nothing to stop
    """
    emitter.debug(f"Singularity container stop (no-op): {container_id}")


def kill_container(container_id: str, ignore_errors: bool = False) -> None:
    """
    Singularity containers are not persistent, so nothing to kill
    """
    emitter.debug(f"Singularity container kill (no-op): {container_id}")


def clean_containers() -> None:
    """
    Clean up any temporary files if needed
    """
    pass


def create_running_container(
    volume_list: Dict[str, Dict[str, str]],
    image_name: str,
    container_name: str,
    cpu: List[str],
    gpu: List[str],
    container_config_info: Dict[str, Any],
    source_logs: str,
    target_logs: str,
) -> str:
    """
    Create a "running" Singularity container (prepare the environment)
    """
    image_name = image_name.lower()
    emitter.information(
        "\t\t[framework] Creating singularity environment with image {}".format(image_name)
    )
    
    # For Singularity, we prepare the image
    if ":" in image_name:
        repo_name, tag_name = image_name.split(":")
    else:
        repo_name = image_name
        tag_name = "latest"
    
    if not image_exists(repo_name, tag_name):
        pull_image(repo_name, tag_name)
    
    container_id = build_container(
        container_name,
        volume_list,
        image_name,
        cpu,
        gpu,
        container_config_info,
        False,  # Singularity doesn't have the same network isolation
    )
    
    if not container_id:
        utilities.error_exit("Singularity environment was not created successfully")
    
    return container_id


def extract_experiment_logs(
    image_name: str,
    container_name: str,
    cpu: List[str],
    gpu: List[str],
    container_config_info: Dict[str, Any],
    source_logs: str,
    target_logs: str,
) -> None:
    """
    Extract logs from Singularity container
    For Singularity, this is simpler as we can directly access the filesystem
    """
    emitter.information(
        "\t\t[framework] extracting logs from singularity environment"
    )
    
    # Since Singularity shares the host filesystem by default,
    # we can directly copy files if they exist
    if os.path.exists(source_logs):
        copy_command = f"cp -r {source_logs} {target_logs}"
        utilities.execute_command(copy_command)


# File operations for Singularity
def is_file(container_id: str, file_path: str) -> bool:
    """Check if file exists in Singularity container"""
    command = f"test -f {file_path}"
    exit_code, _ = exec_command(container_id, command)
    return exit_code == 0


def is_dir(container_id: str, dir_path: str) -> bool:
    """Check if directory exists in Singularity container"""
    command = f"test -d {dir_path}"
    exit_code, _ = exec_command(container_id, command)
    return exit_code == 0


def is_file_empty(container_id: str, file_path: str) -> bool:
    """Check if file is empty in Singularity container"""
    command = f"[ -s {file_path} ]"
    exit_code, _ = exec_command(container_id, command)
    return exit_code != 0


def fix_permissions(container_id: str, dir_path: str) -> Tuple[int, Optional[Tuple[Optional[bytes], Optional[bytes]]]]:
    """Fix permissions in Singularity container"""
    command = f"chmod -R g+w {dir_path}"
    return exec_command(container_id, command)


def list_dir(container_id: str, dir_path: str, regex: Optional[str] = None) -> List[str]:
    """List directory contents in Singularity container"""
    if not regex:
        regex = "*"
    command = f'find {dir_path} -name "{regex}"'
    
    # For Singularity, we'll use a simpler approach since exec_command doesn't capture stdout properly
    # We can execute directly on the host if the paths are bind-mounted
    try:
        import subprocess
        result = subprocess.run(
            f"singularity exec {container_id} {command}",
            shell=True,
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            return [line.strip() for line in result.stdout.split('\n') if line.strip()]
    except:
        pass
    
    return []


def copy_file_from_container(container_id: str, from_path: str, to_path: str) -> int:
    """Copy file from Singularity container to host"""
    # For Singularity, we can often access files directly due to bind mounts
    # or use singularity exec to copy
    copy_command = f"singularity exec {container_id} cp {from_path} {to_path}"
    return utilities.execute_command(copy_command)


def copy_file_to_container(container_id: str, from_path: str, to_path: str) -> int:
    """Copy file from host to Singularity container"""
    copy_command = f"singularity exec {container_id} cp {from_path} {to_path}"
    return utilities.execute_command(copy_command)


def write_file(container_id: str, file_path: str, content: Sequence[str]) -> None:
    """Write file in Singularity container"""
    tmp_file_path = os.path.join(
        "/tmp", "write-file-{}".format(random.randint(0, 1000000))
    )
    with open(tmp_file_path, "w") as f:
        for line in content:
            f.write(line)
    
    copy_command = f"singularity exec {container_id} cp {tmp_file_path} {file_path}"
    utilities.execute_command(copy_command)
    os.remove(tmp_file_path)


def read_file(container_id: str, file_path: str, encoding: str = "utf-8") -> List[str]:
    """Read file from Singularity container"""
    tmp_file_path = os.path.join(
        "/tmp", "container-file-{}".format(random.randint(0, 1000000))
    )
    copy_command = f"singularity exec {container_id} cp {file_path} {tmp_file_path}"
    utilities.execute_command(copy_command)
    
    try:
        with open(tmp_file_path, "r", encoding=encoding) as f:
            file_content = f.readlines()
        os.remove(tmp_file_path)
        return file_content
    except:
        if os.path.exists(tmp_file_path):
            os.remove(tmp_file_path)
        return []


def append_file(container_id: str, file_path: str, content: Sequence[str]) -> None:
    """Append to file in Singularity container"""
    tmp_file_path = os.path.join(
        "/tmp", "append-file-{}".format(random.randint(0, 1000000))
    )
    
    # First copy existing file
    copy_command = f"singularity exec {container_id} cp {file_path} {tmp_file_path}"
    utilities.execute_command(copy_command)
    
    # Append content
    with open(tmp_file_path, "a") as f:
        for line in content:
            f.write(line)
    
    # Copy back
    copy_command = f"singularity exec {container_id} cp {tmp_file_path} {file_path}"
    utilities.execute_command(copy_command)
    os.remove(tmp_file_path)


def get_file_object(container_id: str, file_path: str, encoding: str = "utf-8") -> Any:
    """Get file object from Singularity container"""
    tmp_file_path = os.path.join(
        "/tmp", "container-file-{}".format(random.randint(0, 1000000))
    )
    copy_command = f"singularity exec {container_id} cp {file_path} {tmp_file_path}"
    utilities.execute_command(copy_command)
    f_obj = open(tmp_file_path, "r", encoding=encoding)
    return f_obj
