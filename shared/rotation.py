from typing import Optional, List
from .database import Database
from .models import Remote, RemoteStatus, RotationEvent
# Assuming .rclone and .config exist per prompt context
from .rclone import RcloneRunner, CapacityInfo
from .config import AppConfig

class RotationEngine:
    def __init__(self, db: Database, rclone: RcloneRunner, cfg: AppConfig):
        self.db = db
        self.rclone = rclone
        self.cfg = cfg

    def get_active_remote(self) -> Optional[Remote]:
        active_id = self.db.get_active_remote_id()
        if active_id is not None:
            remote_dict = self.db.get_remote(active_id)
            if remote_dict:
                return Remote.from_row(remote_dict)
        return None

    def check_and_rotate(self, current_remote_id: int, run_id: Optional[int] = None, reason: str = 'full') -> Optional[Remote]:
        remotes = self.db.get_remotes(enabled_only=True)
        if not remotes:
            return None
            
        remotes.sort(key=lambda x: (x.get('priority', 99), x.get('id', 0)))
        
        # Find index of current, then pick next
        idx = -1
        for i, r in enumerate(remotes):
            if r['id'] == current_remote_id:
                idx = i
                break
                
        if idx == -1:
            next_remote_dict = remotes[0]
        else:
            next_remote_dict = remotes[(idx + 1) % len(remotes)]
            
        new_remote_id = next_remote_dict['id']
        self.db.set_active_remote_id(new_remote_id)
        self.db.create_rotation_event(
            run_id=run_id,
            from_remote_id=current_remote_id,
            to_remote_id=new_remote_id,
            reason=reason
        )
        return Remote.from_row(next_remote_dict)

    def refresh_capacity(self, remote: Remote) -> Optional[CapacityInfo]:
        try:
            info = self.rclone.check_capacity(remote.crypt_remote)
            if info:
                self.db.update_remote_status(
                    id=remote.id, 
                    status=RemoteStatus.OK.value,
                    capacity_info={
                        'total_gb': info.total_gb,
                        'used_gb': info.used_gb,
                        'free_gb': info.free_gb,
                        'pct_used': info.pct_used
                    }
                )
                return info
        except Exception:
            self.db.update_remote_status(id=remote.id, status=RemoteStatus.UNKNOWN.value)
        return None

    def needs_rotation(self, remote: Remote) -> bool:
        if remote.capacity_pct_used is None:
            return False
        # Assuming cfg has a max_pct_used threshold or similar
        threshold = getattr(self.cfg, 'rotation_threshold_pct', 95.0)
        return remote.capacity_pct_used >= threshold

    def get_rotation_history(self, limit=20) -> List[dict]:
        query = "SELECT * FROM rotation_events ORDER BY id DESC LIMIT ?"
        rows = self.db.conn.execute(query, (limit,)).fetchall()
        return [dict(row) for row in rows]
