"""Data persistence utilities for training data collection."""

import json
import logging
import os
from datetime import datetime
from typing import List, Dict, Any, Optional
from pathlib import Path


class TrainingDataPersistence:
    """Handles persistence of collected training data."""
    
    def __init__(self, data_dir: Optional[str] = None):
        """Initialize persistence handler.
        
        Args:
            data_dir: Directory to save training data files
        """
        self.logger = logging.getLogger(__name__)
        
        if data_dir is None:
            data_dir = os.path.join(os.path.dirname(__file__), 'collected_data')
        
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self.logger.info(f"Training data persistence initialized with directory: {self.data_dir}")
    
    def save_training_data(self, data: List[Dict[str, Any]], 
                          filename_prefix: str = "training_data") -> str:
        """Save training data to a JSON file.
        
        Args:
            data: List of training samples
            filename_prefix: Prefix for the filename
            
        Returns:
            Path to the saved file
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{filename_prefix}_{timestamp}.json"
        filepath = self.data_dir / filename
        
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            
            if not data:
                self.logger.warning(f"Saved empty training data file to {filepath}")
            else:
                self.logger.info(f"Saved {len(data)} training samples to {filepath}")
                
            return str(filepath)
            
        except Exception as e:
            self.logger.error(f"Failed to save training data to {filepath}: {e}")
            raise
    
    def save_collection_metadata(self, metadata: Dict[str, Any], 
                                filename: Optional[str] = None) -> str:
        """Save metadata about the data collection process.
        
        Args:
            metadata: Collection metadata
            filename: Optional filename (auto-generated if not provided)
            
        Returns:
            Path to the saved metadata file
        """
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"collection_metadata_{timestamp}.json"
        
        filepath = self.data_dir / filename
        
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2)
            
            self.logger.info(f"Saved collection metadata to {filepath}")
            return str(filepath)
            
        except Exception as e:
            self.logger.error(f"Failed to save metadata to {filepath}: {e}")
            raise
    
    def load_training_data(self, filepath: str) -> List[Dict[str, Any]]:
        """Load training data from a JSON file.
        
        Args:
            filepath: Path to the training data file
            
        Returns:
            List of training samples
        """
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            self.logger.info(f"Loaded {len(data)} training samples from {filepath}")
            return data
            
        except Exception as e:
            self.logger.error(f"Failed to load training data from {filepath}: {e}")
            raise
    
    def get_recent_files(self, file_pattern: str = "training_data_*.json", 
                        limit: int = 10) -> List[str]:
        """Get list of recent training data files.
        
        Args:
            file_pattern: Glob pattern to match files
            limit: Maximum number of files to return
            
        Returns:
            List of file paths, sorted by modification time (newest first)
        """
        try:
            files = list(self.data_dir.glob(file_pattern))
            # Sort by modification time, newest first
            files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
            
            return [str(f) for f in files[:limit]]
            
        except Exception as e:
            self.logger.error(f"Failed to get recent files: {e}")
            return []
    
    def cleanup_old_files(self, file_pattern: str = "training_data_*.json", 
                         keep_count: int = 50) -> int:
        """Clean up old training data files, keeping only the most recent ones.
        
        Args:
            file_pattern: Glob pattern to match files
            keep_count: Number of recent files to keep
            
        Returns:
            Number of files deleted
        """
        try:
            files = list(self.data_dir.glob(file_pattern))
            # Sort by modification time, oldest first
            files.sort(key=lambda f: f.stat().st_mtime)
            
            # Keep only the most recent files
            files_to_delete = files[:-keep_count] if len(files) > keep_count else []
            
            deleted_count = 0
            for file_path in files_to_delete:
                try:
                    file_path.unlink()
                    deleted_count += 1
                    self.logger.debug(f"Deleted old training data file: {file_path}")
                except Exception as e:
                    self.logger.warning(f"Failed to delete file {file_path}: {e}")
            
            if deleted_count > 0:
                self.logger.info(f"Cleaned up {deleted_count} old training data files")
                
            return deleted_count
            
        except Exception as e:
            self.logger.error(f"Failed to cleanup old files: {e}")
            return 0
    
    def get_storage_stats(self) -> Dict[str, Any]:
        """Get storage statistics for the data directory.
        
        Returns:
            Dictionary containing storage statistics
        """
        try:
            files = list(self.data_dir.glob("*.json"))
            total_size = sum(f.stat().st_size for f in files)
            
            # Get file counts by type
            training_files = list(self.data_dir.glob("training_data_*.json"))
            metadata_files = list(self.data_dir.glob("collection_metadata_*.json"))
            
            return {
                "data_directory": str(self.data_dir),
                "total_files": len(files),
                "training_data_files": len(training_files),
                "metadata_files": len(metadata_files),
                "total_size_bytes": total_size,
                "total_size_mb": round(total_size / (1024 * 1024), 2),
                "oldest_file": min(files, key=lambda f: f.stat().st_mtime).name if files else None,
                "newest_file": max(files, key=lambda f: f.stat().st_mtime).name if files else None
            }
            
        except Exception as e:
            self.logger.error(f"Failed to get storage stats: {e}")
            return {
                "data_directory": str(self.data_dir),
                "error": str(e)
            }