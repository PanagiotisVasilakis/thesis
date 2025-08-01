"""Hot-swap model manager for zero-downtime model updates."""

import asyncio
import logging
import os
import threading
import time
from pathlib import Path
from typing import Optional, Dict, Any, Callable
import tempfile
import shutil
from datetime import datetime

from .simplified_model_manager import SimplifiedModelManager, _load_metadata, _parse_version_from_path
from ..errors import ModelError


class HotSwapModelManager:
    """Model manager with hot-swapping capability for zero-downtime updates."""
    
    def __init__(self, model_dir: str, backup_dir: Optional[str] = None):
        """Initialize hot-swap model manager.
        
        Args:
            model_dir: Directory containing model files
            backup_dir: Directory for model backups (optional)
        """
        self.model_dir = Path(model_dir)
        self.backup_dir = Path(backup_dir) if backup_dir else self.model_dir / "backups"
        self.backup_dir.mkdir(exist_ok=True)
        
        # Primary and standby managers for zero-downtime swaps
        self._primary_manager = SimplifiedModelManager()
        self._standby_manager = SimplifiedModelManager()
        self._active_manager = self._primary_manager
        
        # Thread-safe access control
        self._swap_lock = threading.RLock()
        self._update_lock = threading.Lock()
        
        # Model health monitoring
        self._health_callbacks: Dict[str, Callable] = {}
        self._last_health_check = 0
        self._health_check_interval = 30  # seconds
        
        self.logger = logging.getLogger(__name__)
        
        # File watching for automatic updates
        self._file_watcher_task: Optional[asyncio.Task] = None
        self._watch_enabled = False
    
    def register_health_callback(self, name: str, callback: Callable[[Any], bool]):
        """Register a health check callback for the active model.
        
        Args:
            name: Unique name for the callback
            callback: Function that takes model and returns True if healthy
        """
        self._health_callbacks[name] = callback
    
    def unregister_health_callback(self, name: str):
        """Remove a health check callback."""
        self._health_callbacks.pop(name, None)
    
    async def _check_model_health(self, model) -> bool:
        """Check model health using registered callbacks."""
        if not self._health_callbacks:
            return True
        
        try:
            for name, callback in self._health_callbacks.items():
                if not callback(model):
                    self.logger.warning("Health check '%s' failed", name)
                    return False
            return True
        except Exception as exc:
            self.logger.error("Health check failed: %s", exc)
            return False
    
    def _create_backup(self, model_path: str) -> str:
        """Create a backup of the current model."""
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Model file not found: {model_path}")
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        model_name = Path(model_path).stem
        backup_name = f"{model_name}_backup_{timestamp}.joblib"
        backup_path = self.backup_dir / backup_name
        
        try:
            shutil.copy2(model_path, backup_path)
            
            # Also backup metadata if exists
            meta_path = model_path + ".meta.json"
            if os.path.exists(meta_path):
                backup_meta_path = str(backup_path) + ".meta.json"
                shutil.copy2(meta_path, backup_meta_path)
            
            self.logger.info("Created model backup: %s", backup_path)
            return str(backup_path)
            
        except (OSError, IOError) as exc:
            self.logger.error("Failed to create backup: %s", exc)
            raise ModelError(f"Backup creation failed: {exc}") from exc
    
    def _cleanup_old_backups(self, keep_count: int = 5):
        """Clean up old backup files, keeping only the most recent ones."""
        try:
            backup_files = list(self.backup_dir.glob("*_backup_*.joblib"))
            if len(backup_files) <= keep_count:
                return
            
            # Sort by modification time, newest first
            backup_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            
            # Remove oldest backups
            for old_backup in backup_files[keep_count:]:
                try:
                    old_backup.unlink()
                    # Also remove metadata backup if exists
                    meta_backup = Path(str(old_backup) + ".meta.json")
                    if meta_backup.exists():
                        meta_backup.unlink()
                    self.logger.info("Removed old backup: %s", old_backup)
                except OSError as exc:
                    self.logger.warning("Failed to remove old backup %s: %s", old_backup, exc)
                    
        except Exception as exc:
            self.logger.error("Backup cleanup failed: %s", exc)
    
    async def initialize(self, model_path: str, **kwargs) -> bool:
        """Initialize the hot-swap manager with an initial model."""
        try:
            # Initialize primary manager
            success = await self._primary_manager.initialize_async(model_path, **kwargs)
            if not success:
                raise ModelError("Failed to initialize primary model")
            
            # Set as active
            with self._swap_lock:
                self._active_manager = self._primary_manager
            
            self.logger.info("Hot-swap manager initialized successfully")
            return True
            
        except Exception as exc:
            self.logger.error("Hot-swap manager initialization failed: %s", exc)
            return False
    
    async def hot_swap_model(self, new_model_path: str, validate: bool = True, **kwargs) -> bool:
        """Perform a hot swap to a new model with zero downtime.
        
        Args:
            new_model_path: Path to the new model file
            validate: Whether to validate the new model before swapping
            **kwargs: Additional arguments for model initialization
            
        Returns:
            True if swap was successful, False otherwise
        """
        if not os.path.exists(new_model_path):
            raise FileNotFoundError(f"New model file not found: {new_model_path}")
        
        # Determine which manager to use for the new model
        with self._swap_lock:
            if self._active_manager is self._primary_manager:
                standby_manager = self._standby_manager
            else:
                standby_manager = self._primary_manager
        
        # Create backup of current model if it exists
        current_path = getattr(self._active_manager, '_model_path', None)
        backup_path = None
        if current_path and os.path.exists(current_path):
            try:
                backup_path = self._create_backup(current_path)
            except Exception as exc:
                self.logger.error("Failed to create backup, aborting swap: %s", exc)
                return False
        
        try:
            # Initialize standby manager with new model
            self.logger.info("Loading new model into standby manager: %s", new_model_path)
            success = await standby_manager.initialize_async(new_model_path, **kwargs)
            
            if not success:
                raise ModelError("Failed to initialize standby model")
            
            # Validate new model if requested
            if validate:
                new_model = standby_manager.get_model(timeout=10)
                health_ok = await self._check_model_health(new_model)
                if not health_ok:
                    raise ModelError("New model failed health checks")
            
            # Atomic swap - this is the critical zero-downtime section
            with self._swap_lock:
                old_active = self._active_manager
                self._active_manager = standby_manager
                
                # Log the successful swap
                self.logger.info(
                    "Successfully swapped to new model: %s (previous: %s)",
                    new_model_path, current_path
                )
            
            # Clean up old model resources (outside the critical section)
            await asyncio.sleep(0.1)  # Brief pause to ensure no ongoing requests
            
            # Optional: Keep the old manager available for quick rollback
            # In production, you might want to keep it for a few minutes
            
            # Clean up old backups
            self._cleanup_old_backups()
            
            return True
            
        except Exception as exc:
            self.logger.error("Model hot-swap failed: %s", exc)
            
            # If we have a backup and something went wrong, consider rollback
            if backup_path and current_path:
                self.logger.info("Attempting rollback to backup: %s", backup_path)
                try:
                    shutil.copy2(backup_path, current_path)
                    # Restore metadata if exists
                    backup_meta = backup_path + ".meta.json"
                    if os.path.exists(backup_meta):
                        shutil.copy2(backup_meta, current_path + ".meta.json")
                    self.logger.info("Rollback completed successfully")
                except Exception as rollback_exc:
                    self.logger.error("Rollback also failed: %s", rollback_exc)
            
            return False
    
    def get_model(self, timeout: Optional[float] = None):
        """Get the currently active model."""
        with self._swap_lock:
            return self._active_manager.get_model(timeout)
    
    def is_ready(self) -> bool:
        """Check if the active model is ready."""
        with self._swap_lock:
            return self._active_manager.is_ready()
    
    def get_metadata(self) -> Dict[str, Any]:
        """Get metadata for the active model."""
        with self._swap_lock:
            return self._active_manager.get_metadata()
    
    def list_versions(self) -> list:
        """List available model versions."""
        with self._swap_lock:
            return self._active_manager.list_versions()
    
    async def switch_version(self, version: str) -> bool:
        """Switch to a specific model version using hot-swap."""
        with self._swap_lock:
            model_paths = self._active_manager._model_paths
            if version not in model_paths:
                raise ValueError(f"Unknown model version: {version}")
            target_path = model_paths[version]
        
        return await self.hot_swap_model(target_path)
    
    def feed_feedback(self, sample: Dict[str, Any], success: bool = True) -> bool:
        """Feed feedback to the active model."""
        with self._swap_lock:
            return self._active_manager.feed_feedback(sample, success)
    
    def save_model(self, metrics: Optional[Dict[str, Any]] = None) -> bool:
        """Save the active model."""
        with self._swap_lock:
            return self._active_manager.save_model(metrics)
    
    async def enable_file_watching(self, check_interval: float = 5.0):
        """Enable automatic model updates when files change."""
        if self._watch_enabled:
            return
        
        self._watch_enabled = True
        self._file_watcher_task = asyncio.create_task(
            self._file_watcher_loop(check_interval)
        )
        self.logger.info("File watching enabled with interval: %s seconds", check_interval)
    
    async def disable_file_watching(self):
        """Disable automatic file watching."""
        self._watch_enabled = False
        if self._file_watcher_task:
            self._file_watcher_task.cancel()
            try:
                await self._file_watcher_task
            except asyncio.CancelledError:
                pass
            self._file_watcher_task = None
        self.logger.info("File watching disabled")
    
    async def _file_watcher_loop(self, check_interval: float):
        """Background task to watch for model file changes."""
        last_check_times = {}
        
        try:
            while self._watch_enabled:
                await asyncio.sleep(check_interval)
                
                # Check all joblib files in model directory
                for model_file in self.model_dir.glob("*.joblib"):
                    try:
                        stat_result = model_file.stat()
                        current_mtime = stat_result.st_mtime
                        
                        # Check if file was modified since last check
                        if (model_file not in last_check_times or 
                            current_mtime > last_check_times[model_file]):
                            
                            last_check_times[model_file] = current_mtime
                            
                            # Skip if this is the currently active model
                            with self._swap_lock:
                                active_path = getattr(self._active_manager, '_model_path', None)
                            
                            if active_path and os.path.samefile(str(model_file), active_path):
                                continue
                            
                            self.logger.info("Detected model file change: %s", model_file)
                            
                            # Attempt hot swap
                            try:
                                success = await self.hot_swap_model(str(model_file))
                                if success:
                                    self.logger.info("Auto-swapped to updated model: %s", model_file)
                                else:
                                    self.logger.warning("Auto-swap failed for: %s", model_file)
                            except Exception as exc:
                                self.logger.error("Auto-swap error for %s: %s", model_file, exc)
                    
                    except (OSError, IOError) as exc:
                        self.logger.warning("Error checking file %s: %s", model_file, exc)
                        
        except asyncio.CancelledError:
            self.logger.info("File watcher loop cancelled")
        except Exception as exc:
            self.logger.error("File watcher loop error: %s", exc)
    
    async def shutdown(self):
        """Clean shutdown of the hot-swap manager."""
        await self.disable_file_watching()
        
        with self._swap_lock:
            self._primary_manager.shutdown()
            self._standby_manager.shutdown()
        
        self.logger.info("Hot-swap manager shutdown completed")


# Factory function for backward compatibility
def create_hot_swap_manager(model_dir: str, **kwargs) -> HotSwapModelManager:
    """Create a new hot-swap model manager instance."""
    return HotSwapModelManager(model_dir, **kwargs)