import subprocess
import shutil
import os
from typing import List, Optional

def run_mysqldump(output_path: str, host: str = 'localhost', port: int = 3306, user: str = 'root', databases: Optional[List[str]] = None, logger=None) -> bool:
    cmd = ['mysqldump', '-h', host, '-P', str(port), '-u', user]
    if databases:
        cmd.extend(['--databases'] + databases)
    else:
        cmd.append('--all-databases')
    
    try:
        with open(output_path, 'w') as f:
            result = subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE, text=True)
        if result.returncode == 0:
            return True
        else:
            if logger:
                logger.error(f"mysqldump failed: {result.stderr}")
            return False
    except Exception as e:
        if logger:
            logger.error(f"mysqldump exception: {e}")
        return False

def run_dpkg_selections(output_path: str, logger=None) -> bool:
    try:
        with open(output_path, 'w') as f:
            result = subprocess.run(['dpkg', '--get-selections'], stdout=f, stderr=subprocess.PIPE, text=True)
        if result.returncode == 0:
            return True
        if logger:
            logger.error(f"dpkg selections failed: {result.stderr}")
        return False
    except Exception as e:
        if logger:
            logger.error(f"dpkg exception: {e}")
        return False

def run_pip_freeze(output_path: str, python_bin: str = 'python3', logger=None) -> bool:
    try:
        with open(output_path, 'w') as f:
            result = subprocess.run([python_bin, '-m', 'pip', 'freeze'], stdout=f, stderr=subprocess.PIPE, text=True)
        if result.returncode == 0:
            return True
        if logger:
            logger.error(f"pip freeze failed: {result.stderr}")
        return False
    except Exception as e:
        if logger:
            logger.error(f"pip freeze exception: {e}")
        return False

def run_apt_sources(output_path: str, logger=None) -> bool:
    try:
        src_dir = '/etc/apt'
        if not os.path.exists(src_dir):
            if logger: logger.warning(f"{src_dir} not found")
            return False
            
        if os.path.exists(output_path):
            shutil.rmtree(output_path)
        shutil.copytree(src_dir, output_path, dirs_exist_ok=True)
        return True
    except Exception as e:
        if logger:
            logger.error(f"apt sources exception: {e}")
        return False

def run_hook(command: str, logger=None) -> bool:
    try:
        result = subprocess.run(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode == 0:
            if logger and result.stdout:
                logger.info(f"Hook output: {result.stdout}")
            return True
        if logger:
            logger.error(f"Hook failed ({result.returncode}): {result.stderr}")
        return False
    except Exception as e:
        if logger:
            logger.error(f"Hook exception: {e}")
        return False

class HookRunner:
    def __init__(self, logger=None):
        self.logger = logger
        
    def run_class_hooks(self, data_class: str, staging_dir: str) -> List[str]:
        os.makedirs(staging_dir, exist_ok=True)
        generated = []
        if data_class == 'packages':
            dpkg_out = os.path.join(staging_dir, 'dpkg-selections.txt')
            if run_dpkg_selections(dpkg_out, self.logger):
                generated.append(dpkg_out)
                
            pip_out = os.path.join(staging_dir, 'pip-freeze.txt')
            if run_pip_freeze(pip_out, logger=self.logger):
                generated.append(pip_out)
                
            apt_out = os.path.join(staging_dir, 'apt-sources')
            if run_apt_sources(apt_out, self.logger):
                generated.append(apt_out)
                
        elif data_class == 'data':
            sql_out = os.path.join(staging_dir, 'mysqldump_all.sql')
            if run_mysqldump(sql_out, logger=self.logger):
                generated.append(sql_out)
                
        return generated
