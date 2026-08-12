import os
import yaml
import hashlib
from typing import List, Tuple

def load_secrets_class(yaml_path: str) -> List[str]:
    if not os.path.exists(yaml_path):
        return []
    try:
        with open(yaml_path, 'r') as f:
            data = yaml.safe_load(f)
            if data and isinstance(data, dict) and 'paths' in data:
                return data['paths']
    except Exception:
        pass
    return []

def validate_secrets_paths(paths: List[str]) -> Tuple[List[str], List[str]]:
    existing = []
    missing = []
    for p in paths:
        if os.path.exists(p):
            existing.append(p)
        else:
            missing.append(p)
    return existing, missing

def checksum_class_file(yaml_path: str) -> str:
    if not os.path.exists(yaml_path):
        return ''
    h = hashlib.sha256()
    with open(yaml_path, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b""):
            h.update(chunk)
    return h.hexdigest()

class SecretsClassManager:
    def __init__(self, yaml_path: str):
        self.yaml_path = yaml_path
        
    @property
    def paths(self) -> List[str]:
        return load_secrets_class(self.yaml_path)
        
    @property
    def existing_paths(self) -> List[str]:
        return validate_secrets_paths(self.paths)[0]
        
    @property
    def missing_paths(self) -> List[str]:
        return validate_secrets_paths(self.paths)[1]
        
    def checksum(self) -> str:
        return checksum_class_file(self.yaml_path)
        
    def add_path(self, path: str):
        paths = self.paths
        if path not in paths:
            paths.append(path)
            self._save(paths)
            
    def remove_path(self, path: str):
        paths = self.paths
        if path in paths:
            paths.remove(path)
            self._save(paths)
            
    def _save(self, paths: List[str]):
        data = {'paths': paths}
        with open(self.yaml_path, 'w') as f:
            yaml.dump(data, f, default_flow_style=False)
