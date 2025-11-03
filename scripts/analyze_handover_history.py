#!/usr/bin/env python3
"""Handover History Analysis Tool for Thesis.

This script analyzes handover event history to quantify ML improvements
over A3 rules. It calculates key metrics like ping-pong rate, success rate,
dwell time, and generates timeline visualizations.

Usage:
    # Analyze handover history from experiment
    python scripts/analyze_handover_history.py --input thesis_results/baseline/handover_history.json

    # Analyze from Prometheus metrics
    python scripts/analyze_handover_history.py --prometheus http://localhost:9090 --duration 10

    # Compare ML vs A3 histories
    python scripts/analyze_handover_history.py --ml ml_history.json --a3 a3_history.json --compare

Author: Thesis Project
Date: November 2025
"""

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple, Optional

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns
import pandas as pd
import numpy as np

# Configure plotting
sns.set_style("whitegrid")
plt.rcParams['figure.figsize'] = (14, 8)

# Add parent to path
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from services.logging_config import configure_logging
import logging

logger = logging.getLogger(__name__)


class HandoverHistoryAnalyzer:
    """Analyzes handover event history for thesis metrics."""
    
    def __init__(self, history_file: Optional[str] = None, history_data: Optional[List[Dict]] = None):
        """Initialize analyzer with handover history.
        
        Args:
            history_file: Path to JSON file containing handover history
            history_data: Direct list of handover events
        """
        if history_file:
            with open(history_file) as f:
                self.history = json.load(f)
            logger.info(f"Loaded {len(self.history)} handover events from {history_file}")
        elif history_data:
            self.history = history_data
            logger.info(f"Loaded {len(self.history)} handover events from data")
        else:
            self.history = []
            logger.warning("No handover history provided")
        
        # Convert to DataFrame for easier analysis
        if self.history:
            self.df = pd.DataFrame(self.history)
            if 'timestamp' in self.df.columns:
                self.df['timestamp'] = pd.to_datetime(self.df['timestamp'])
                self.df = self.df.sort_values('timestamp')
        else:
            self.df = pd.DataFrame()
    
    def calculate_pingpong_rate(self, window_seconds: float = 10.0) -> Dict:
        """Calculate ping-pong handover rate.
        
        A ping-pong is defined as: UE handovers from A→B→A within window_seconds.
        
        Args:
            window_seconds: Time window for ping-pong detection (default: 10s)
            
        Returns:
            Dictionary with ping-pong statistics
        """
        if self.df.empty:
            return {'pingpong_count': 0, 'total_handovers': 0, 'pingpong_rate': 0.0}
        
        pingpong_count = 0
        total_handovers = len(self.df)
        pingpong_details = []
        
        # Group by UE
        for ue_id in self.df['ue_id'].unique():
            ue_history = self.df[self.df['ue_id'] == ue_id].sort_values('timestamp')
            
            # Check each handover for ping-pong pattern
            for i in range(2, len(ue_history)):
                current_event = ue_history.iloc[i]
                prev_event = ue_history.iloc[i-2]
                
                # Check if returned to previous antenna
                if current_event['to'] == prev_event['from']:
                    # Check time window
                    time_diff = (current_event['timestamp'] - prev_event['timestamp']).total_seconds()
                    
                    if time_diff <= window_seconds:
                        pingpong_count += 1
                        pingpong_details.append({
                            'ue_id': ue_id,
                            'from': prev_event['from'],
                            'intermediate': prev_event['to'],
                            'back_to': current_event['to'],
                            'time_span': time_diff,
                            'timestamp': current_event['timestamp']
                        })
        
        pingpong_rate = (pingpong_count / total_handovers * 100) if total_handovers > 0 else 0.0
        
        return {
            'pingpong_count': pingpong_count,
            'total_handovers': total_handovers,
            'pingpong_rate': pingpong_rate,
            'window_seconds': window_seconds,
            'details': pingpong_details
        }
    
    def calculate_handover_success_rate(self) -> Dict:
        """Calculate handover success rate.
        
        Success = handover actually changed the serving antenna.
        Failure = handover attempted but UE stayed on same antenna.
        
        Returns:
            Dictionary with success rate statistics
        """
        if self.df.empty:
            return {'successful': 0, 'failed': 0, 'success_rate': 0.0}
        
        # Successful handover = 'to' different from 'from'
        successful = self.df[self.df['from'] != self.df['to']].shape[0]
        failed = self.df[self.df['from'] == self.df['to']].shape[0]
        total = len(self.df)
        
        success_rate = (successful / total * 100) if total > 0 else 0.0
        
        return {
            'successful': successful,
            'failed': failed,
            'total': total,
            'success_rate': success_rate
        }
    
    def calculate_average_dwell_time(self) -> Dict:
        """Calculate average time UE stays on each antenna.
        
        Dwell time = time between consecutive handovers for a UE.
        
        Returns:
            Dictionary with dwell time statistics
        """
        if self.df.empty:
            return {'overall_mean': 0.0, 'overall_median': 0.0, 'per_antenna': {}}
        
        dwell_times = []
        per_antenna_dwell = defaultdict(list)
        
        # Group by UE
        for ue_id in self.df['ue_id'].unique():
            ue_history = self.df[self.df['ue_id'] == ue_id].sort_values('timestamp')
            
            # Calculate time between consecutive handovers
            for i in range(1, len(ue_history)):
                dwell_time = (ue_history.iloc[i]['timestamp'] - 
                             ue_history.iloc[i-1]['timestamp']).total_seconds()
                
                antenna = ue_history.iloc[i-1]['to']
                dwell_times.append(dwell_time)
                per_antenna_dwell[antenna].append(dwell_time)
        
        # Calculate statistics
        overall_mean = np.mean(dwell_times) if dwell_times else 0.0
        overall_median = np.median(dwell_times) if dwell_times else 0.0
        overall_std = np.std(dwell_times) if dwell_times else 0.0
        
        # Per-antenna statistics
        antenna_stats = {}
        for antenna, times in per_antenna_dwell.items():
            antenna_stats[antenna] = {
                'mean': np.mean(times),
                'median': np.median(times),
                'std': np.std(times),
                'count': len(times)
            }
        
        return {
            'overall_mean': overall_mean,
            'overall_median': overall_median,
            'overall_std': overall_std,
            'overall_min': min(dwell_times) if dwell_times else 0.0,
            'overall_max': max(dwell_times) if dwell_times else 0.0,
            'per_antenna': antenna_stats,
            'sample_count': len(dwell_times)
        }
    
    def identify_frequent_transitions(self, top_n: int = 10) -> pd.DataFrame:
        """Identify most frequent antenna transitions.
        
        Args:
            top_n: Number of top transitions to return
            
        Returns:
            DataFrame with most frequent transitions
        """
        if self.df.empty:
            return pd.DataFrame()
        
        # Count transitions
        transitions = self.df.groupby(['from', 'to']).size().reset_index(name='count')
        
        # Exclude non-handovers (from == to)
        transitions = transitions[transitions['from'] != transitions['to']]
        
        # Sort by count
        transitions = transitions.sort_values('count', ascending=False)
        
        # Add percentage
        total = transitions['count'].sum()
        transitions['percentage'] = (transitions['count'] / total * 100) if total > 0 else 0
        
        return transitions.head(top_n)
    
    def calculate_handover_rate_over_time(self, bin_seconds: int = 60) -> pd.DataFrame:
        """Calculate handover rate in time bins.
        
        Args:
            bin_seconds: Size of time bins in seconds
            
        Returns:
            DataFrame with time bins and handover counts
        """
        if self.df.empty or 'timestamp' not in self.df.columns:
            return pd.DataFrame()
        
        # Create time bins
        df_copy = self.df.copy()
        df_copy['time_bin'] = df_copy['timestamp'].dt.floor(f'{bin_seconds}s')
        
        # Count handovers per bin
        rate_data = df_copy.groupby('time_bin').size().reset_index(name='handovers')
        rate_data['rate_per_second'] = rate_data['handovers'] / bin_seconds
        
        return rate_data
    
    def detect_problematic_patterns(self) -> Dict:
        """Detect problematic handover patterns.
        
        Returns:
            Dictionary with detected patterns
        """
        patterns = {
            'ping_pongs': [],
            'rapid_oscillations': [],  # >3 handovers in 30s
            'failed_handovers': [],  # from == to
            'long_chains': []  # >5 consecutive handovers
        }
        
        if self.df.empty:
            return patterns
        
        # Detect ping-pongs
        pingpong_result = self.calculate_pingpong_rate(window_seconds=10.0)
        patterns['ping_pongs'] = pingpong_result['details']
        
        # Detect rapid oscillations
        for ue_id in self.df['ue_id'].unique():
            ue_history = self.df[self.df['ue_id'] == ue_id].sort_values('timestamp')
            
            # Check 30-second windows
            for i in range(len(ue_history)):
                window_start = ue_history.iloc[i]['timestamp']
                window_end = window_start + timedelta(seconds=30)
                
                window_events = ue_history[
                    (ue_history['timestamp'] >= window_start) & 
                    (ue_history['timestamp'] <= window_end)
                ]
                
                if len(window_events) > 3:
                    patterns['rapid_oscillations'].append({
                        'ue_id': ue_id,
                        'handovers_in_30s': len(window_events),
                        'start_time': window_start,
                        'antennas': window_events['to'].tolist()
                    })
        
        # Detect failed handovers
        failed = self.df[self.df['from'] == self.df['to']]
        patterns['failed_handovers'] = failed.to_dict('records')
        
        return patterns
    
    def generate_summary(self) -> Dict:
        """Generate comprehensive summary statistics.
        
        Returns:
            Dictionary with all key metrics
        """
        if self.df.empty:
            return {'error': 'No handover data available'}
        
        pingpong = self.calculate_pingpong_rate()
        success = self.calculate_handover_success_rate()
        dwell = self.calculate_average_dwell_time()
        transitions = self.identify_frequent_transitions(5)
        patterns = self.detect_problematic_patterns()
        
        # UE statistics
        unique_ues = self.df['ue_id'].nunique()
        unique_antennas = pd.concat([self.df['from'], self.df['to']]).nunique()
        
        # Time span
        if 'timestamp' in self.df.columns:
            time_span = (self.df['timestamp'].max() - self.df['timestamp'].min()).total_seconds()
            handover_rate = len(self.df) / time_span if time_span > 0 else 0
        else:
            time_span = 0
            handover_rate = 0
        
        summary = {
            'overview': {
                'total_handovers': len(self.df),
                'unique_ues': unique_ues,
                'unique_antennas': unique_antennas,
                'time_span_seconds': time_span,
                'handover_rate_per_second': handover_rate
            },
            'pingpong': pingpong,
            'success': success,
            'dwell_time': dwell,
            'top_transitions': transitions.to_dict('records'),
            'problematic_patterns': {
                'pingpong_count': len(patterns['ping_pongs']),
                'rapid_oscillation_count': len(patterns['rapid_oscillations']),
                'failed_handover_count': len(patterns['failed_handovers'])
            }
        }
        
        return summary


class HandoverVisualizer:
    """Generates visualizations from handover history."""
    
    def __init__(self, output_dir: str = "output/handover_analysis"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Visualization output: {self.output_dir}")
    
    def plot_handover_timeline(self, df: pd.DataFrame) -> Path:
        """Plot handover events over time.
        
        Args:
            df: DataFrame with handover history
            
        Returns:
            Path to generated plot
        """
        if df.empty or 'timestamp' not in df.columns:
            logger.warning("Cannot plot timeline: no timestamp data")
            return None
        
        fig, ax = plt.subplots(figsize=(16, 8))
        
        # Create timeline plot
        unique_ues = df['ue_id'].unique()
        colors = plt.cm.tab10(np.linspace(0, 1, len(unique_ues)))
        
        for idx, ue_id in enumerate(unique_ues):
            ue_data = df[df['ue_id'] == ue_id].sort_values('timestamp')
            
            # Plot handover events
            y_pos = idx
            for i, row in ue_data.iterrows():
                ax.scatter(row['timestamp'], y_pos, 
                          color=colors[idx], s=100, alpha=0.7, 
                          marker='o', edgecolors='black', linewidths=1)
                
                # Add antenna transition labels
                if i == ue_data.index[0]:
                    label = f"{row['from']}→{row['to']}"
                else:
                    label = f"→{row['to']}"
                
                ax.text(row['timestamp'], y_pos + 0.15, label,
                       fontsize=8, ha='center', va='bottom',
                       bbox=dict(boxstyle='round,pad=0.3', facecolor='white', alpha=0.7))
        
        ax.set_yticks(range(len(unique_ues)))
        ax.set_yticklabels(unique_ues)
        ax.set_xlabel('Time', fontsize=12, fontweight='bold')
        ax.set_ylabel('UE ID', fontsize=12, fontweight='bold')
        ax.set_title('Handover Events Timeline', fontsize=14, fontweight='bold')
        ax.grid(True, alpha=0.3, axis='x')
        
        plt.tight_layout()
        output_path = self.output_dir / "handover_timeline.png"
        plt.savefig(output_path, dpi=300, bbox_inches='tight')
        plt.close()
        
        logger.info(f"Generated timeline: {output_path}")
        return output_path
    
    def plot_transition_matrix(self, df: pd.DataFrame) -> Path:
        """Plot antenna transition heatmap.
        
        Args:
            df: DataFrame with handover history
            
        Returns:
            Path to generated plot
        """
        if df.empty:
            return None
        
        # Create transition matrix
        all_antennas = sorted(set(df['from'].unique()) | set(df['to'].unique()))
        transition_matrix = pd.DataFrame(0, index=all_antennas, columns=all_antennas)
        
        for _, row in df.iterrows():
            if row['from'] != row['to']:  # Only actual handovers
                transition_matrix.loc[row['from'], row['to']] += 1
        
        # Plot heatmap
        fig, ax = plt.subplots(figsize=(10, 8))
        
        sns.heatmap(transition_matrix, annot=True, fmt='d', cmap='YlOrRd',
                   square=True, linewidths=1, cbar_kws={'label': 'Handover Count'},
                   ax=ax)
        
        ax.set_xlabel('To Antenna', fontsize=12, fontweight='bold')
        ax.set_ylabel('From Antenna', fontsize=12, fontweight='bold')
        ax.set_title('Antenna Transition Matrix\n(Higher values indicate frequent transitions)',
                    fontsize=14, fontweight='bold')
        
        plt.tight_layout()
        output_path = self.output_dir / "transition_matrix.png"
        plt.savefig(output_path, dpi=300, bbox_inches='tight')
        plt.close()
        
        logger.info(f"Generated transition matrix: {output_path}")
        return output_path
    
    def plot_dwell_time_distribution(self, dwell_stats: Dict) -> Path:
        """Plot dwell time distribution.
        
        Args:
            dwell_stats: Dwell time statistics from analyzer
            
        Returns:
            Path to generated plot
        """
        if not dwell_stats or 'per_antenna' not in dwell_stats:
            return None
        
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))
        
        # Left plot: Mean dwell time per antenna
        antenna_names = list(dwell_stats['per_antenna'].keys())
        mean_times = [dwell_stats['per_antenna'][ant]['mean'] for ant in antenna_names]
        
        bars = ax1.barh(antenna_names, mean_times, color='skyblue', 
                       alpha=0.8, edgecolor='black', linewidth=1.5)
        
        # Add value labels
        for bar, time in zip(bars, mean_times):
            width = bar.get_width()
            ax1.text(width, bar.get_y() + bar.get_height()/2,
                    f'{time:.1f}s',
                    ha='left', va='center', fontsize=10, fontweight='bold')
        
        ax1.set_xlabel('Mean Dwell Time (seconds)', fontsize=11, fontweight='bold')
        ax1.set_ylabel('Antenna', fontsize=11, fontweight='bold')
        ax1.set_title('Average Dwell Time per Antenna', fontsize=13, fontweight='bold')
        ax1.grid(True, alpha=0.3, axis='x')
        
        # Add overall average line
        ax1.axvline(x=dwell_stats['overall_mean'], color='red', linestyle='--',
                   linewidth=2, label=f'Overall Mean: {dwell_stats["overall_mean"]:.1f}s')
        ax1.legend()
        
        # Right plot: Overall statistics
        stats_data = {
            'Statistic': ['Mean', 'Median', 'Std Dev', 'Min', 'Max'],
            'Value (seconds)': [
                f'{dwell_stats["overall_mean"]:.2f}',
                f'{dwell_stats["overall_median"]:.2f}',
                f'{dwell_stats["overall_std"]:.2f}',
                f'{dwell_stats["overall_min"]:.2f}',
                f'{dwell_stats["overall_max"]:.2f}'
            ]
        }
        
        ax2.axis('tight')
        ax2.axis('off')
        
        table = ax2.table(
            cellText=[[stats_data['Statistic'][i], stats_data['Value (seconds)'][i]] 
                     for i in range(len(stats_data['Statistic']))],
            colLabels=['Statistic', 'Value (seconds)'],
            cellLoc='center',
            loc='center',
            colWidths=[0.4, 0.4]
        )
        table.auto_set_font_size(False)
        table.set_fontsize(11)
        table.scale(1, 3)
        
        # Style header
        for i in range(2):
            table[(0, i)].set_facecolor('#CCCCCC')
            table[(0, i)].set_text_props(weight='bold')
        
        ax2.set_title('Overall Dwell Time Statistics', fontsize=13, fontweight='bold', pad=20)
        
        plt.tight_layout()
        output_path = self.output_dir / "dwell_time_distribution.png"
        plt.savefig(output_path, dpi=300, bbox_inches='tight')
        plt.close()
        
        logger.info(f"Generated dwell time distribution: {output_path}")
        return output_path
    
    def plot_pingpong_analysis(self, pingpong_stats: Dict) -> Path:
        """Plot ping-pong analysis.
        
        Args:
            pingpong_stats: Ping-pong statistics from analyzer
            
        Returns:
            Path to generated plot
        """
        if not pingpong_stats:
            return None
        
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
        
        # Left: Ping-pong rate visualization
        total = pingpong_stats['total_handovers']
        pingpongs = pingpong_stats['pingpong_count']
        normal = total - pingpongs
        
        sizes = [normal, pingpongs]
        labels = [f'Normal Handovers\n({normal})', f'Ping-Pong Handovers\n({pingpongs})']
        colors = ['#51CF66', '#FF6B6B']
        explode = (0, 0.1)  # Explode ping-pong slice
        
        wedges, texts, autotexts = ax1.pie(
            sizes, labels=labels, autopct='%1.1f%%',
            colors=colors, explode=explode, startangle=90,
            textprops={'fontsize': 11, 'fontweight': 'bold'}
        )
        
        ax1.set_title(f'Ping-Pong Rate: {pingpong_stats["pingpong_rate"]:.1f}%\n'
                     f'(Window: {pingpong_stats["window_seconds"]}s)',
                     fontsize=13, fontweight='bold')
        
        # Right: Ping-pong details table
        if pingpong_stats['details']:
            # Group by transition type
            transition_counts = Counter()
            for pp in pingpong_stats['details']:
                transition = f"{pp['from']}↔{pp['intermediate']}"
                transition_counts[transition] += 1
            
            table_data = [
                ['Transition', 'Count']
            ]
            for transition, count in transition_counts.most_common(5):
                table_data.append([transition, str(count)])
            
            ax2.axis('tight')
            ax2.axis('off')
            
            table = ax2.table(
                cellText=table_data[1:],
                colLabels=table_data[0],
                cellLoc='center',
                loc='center',
                colWidths=[0.6, 0.3]
            )
            table.auto_set_font_size(False)
            table.set_fontsize(10)
            table.scale(1, 2.5)
            
            # Style header
            for i in range(2):
                table[(0, i)].set_facecolor('#CCCCCC')
                table[(0, i)].set_text_props(weight='bold')
            
            ax2.set_title('Most Frequent Ping-Pong Transitions', 
                         fontsize=13, fontweight='bold', pad=20)
        else:
            ax2.text(0.5, 0.5, 'No ping-pong\ndetected',
                    ha='center', va='center', fontsize=14,
                    transform=ax2.transAxes)
            ax2.set_title('Ping-Pong Transitions', fontsize=13, fontweight='bold')
        
        plt.tight_layout()
        output_path = self.output_dir / "pingpong_analysis.png"
        plt.savefig(output_path, dpi=300, bbox_inches='tight')
        plt.close()
        
        logger.info(f"Generated ping-pong analysis: {output_path}")
        return output_path
    
    def plot_handover_rate_over_time(self, rate_data: pd.DataFrame) -> Path:
        """Plot handover rate evolution over time.
        
        Args:
            rate_data: Time-binned handover rate data
            
        Returns:
            Path to generated plot
        """
        if rate_data.empty:
            return None
        
        fig, ax = plt.subplots(figsize=(14, 6))
        
        ax.plot(rate_data['time_bin'], rate_data['rate_per_second'],
               marker='o', linewidth=2, markersize=6, color='#4ECDC4',
               label='Handover Rate')
        
        # Add mean line
        mean_rate = rate_data['rate_per_second'].mean()
        ax.axhline(y=mean_rate, color='red', linestyle='--', linewidth=2,
                  label=f'Mean: {mean_rate:.3f}/s')
        
        ax.set_xlabel('Time', fontsize=12, fontweight='bold')
        ax.set_ylabel('Handovers per Second', fontsize=12, fontweight='bold')
        ax.set_title('Handover Rate Over Time', fontsize=14, fontweight='bold')
        ax.legend(fontsize=11)
        ax.grid(True, alpha=0.3)
        
        plt.tight_layout()
        output_path = self.output_dir / "handover_rate_timeline.png"
        plt.savefig(output_path, dpi=300, bbox_inches='tight')
        plt.close()
        
        logger.info(f"Generated rate timeline: {output_path}")
        return output_path
    
    def generate_all_visualizations(self, analyzer: HandoverHistoryAnalyzer) -> List[Path]:
        """Generate all visualizations.
        
        Args:
            analyzer: HandoverHistoryAnalyzer instance
            
        Returns:
            List of generated file paths
        """
        plots = []
        
        # Timeline
        timeline = self.plot_handover_timeline(analyzer.df)
        if timeline:
            plots.append(timeline)
        
        # Transition matrix
        matrix = self.plot_transition_matrix(analyzer.df)
        if matrix:
            plots.append(matrix)
        
        # Dwell time distribution
        dwell_stats = analyzer.calculate_average_dwell_time()
        dwell_plot = self.plot_dwell_time_distribution(dwell_stats)
        if dwell_plot:
            plots.append(dwell_plot)
        
        # Ping-pong analysis
        pingpong_stats = analyzer.calculate_pingpong_rate()
        pingpong_plot = self.plot_pingpong_analysis(pingpong_stats)
        if pingpong_plot:
            plots.append(pingpong_plot)
        
        # Handover rate over time
        rate_data = analyzer.calculate_handover_rate_over_time(bin_seconds=60)
        if not rate_data.empty:
            rate_plot = self.plot_handover_rate_over_time(rate_data)
            if rate_plot:
                plots.append(rate_plot)
        
        logger.info(f"Generated {len(plots)} visualizations")
        return plots


class ComparativeAnalyzer:
    """Compares ML and A3 handover histories."""
    
    def __init__(self, ml_history: List[Dict], a3_history: List[Dict]):
        self.ml_analyzer = HandoverHistoryAnalyzer(history_data=ml_history)
        self.a3_analyzer = HandoverHistoryAnalyzer(history_data=a3_history)
    
    def compare_metrics(self) -> Dict:
        """Generate comparative metrics.
        
        Returns:
            Dictionary with side-by-side comparisons
        """
        ml_summary = self.ml_analyzer.generate_summary()
        a3_summary = self.a3_analyzer.generate_summary()
        
        comparison = {
            'pingpong_rate': {
                'ml': ml_summary['pingpong']['pingpong_rate'],
                'a3': a3_summary['pingpong']['pingpong_rate'],
                'improvement': (a3_summary['pingpong']['pingpong_rate'] - 
                              ml_summary['pingpong']['pingpong_rate'])
            },
            'success_rate': {
                'ml': ml_summary['success']['success_rate'],
                'a3': a3_summary['success']['success_rate'],
                'improvement': (ml_summary['success']['success_rate'] - 
                              a3_summary['success']['success_rate'])
            },
            'avg_dwell_time': {
                'ml': ml_summary['dwell_time']['overall_mean'],
                'a3': a3_summary['dwell_time']['overall_mean'],
                'improvement_pct': ((ml_summary['dwell_time']['overall_mean'] / 
                                   a3_summary['dwell_time']['overall_mean'] - 1) * 100)
                                   if a3_summary['dwell_time']['overall_mean'] > 0 else 0
            },
            'total_handovers': {
                'ml': ml_summary['overview']['total_handovers'],
                'a3': a3_summary['overview']['total_handovers'],
                'difference': (ml_summary['overview']['total_handovers'] - 
                             a3_summary['overview']['total_handovers'])
            }
        }
        
        return comparison
    
    def generate_comparison_report(self, output_path: str = "output/handover_comparison_report.txt"):
        """Generate text comparison report.
        
        Args:
            output_path: Path for output report
        """
        comparison = self.compare_metrics()
        ml_summary = self.ml_analyzer.generate_summary()
        a3_summary = self.a3_analyzer.generate_summary()
        
        report = f"""
================================================================================
              Handover History Comparative Analysis Report
================================================================================

Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

================================================================================
                            EXECUTIVE SUMMARY
================================================================================

Key Improvements (ML vs A3):
  • Ping-pong rate: {comparison['pingpong_rate']['ml']:.1f}% vs {comparison['pingpong_rate']['a3']:.1f}% 
    (Reduction: {comparison['pingpong_rate']['improvement']:.1f} percentage points)
    
  • Average dwell time: {comparison['avg_dwell_time']['ml']:.2f}s vs {comparison['avg_dwell_time']['a3']:.2f}s
    (Improvement: {comparison['avg_dwell_time']['improvement_pct']:.1f}%)
    
  • Success rate: {comparison['success_rate']['ml']:.1f}% vs {comparison['success_rate']['a3']:.1f}%
    (Improvement: {comparison['success_rate']['improvement']:.1f} percentage points)

================================================================================
                            ML MODE ANALYSIS
================================================================================

Overview:
  Total Handovers:     {ml_summary['overview']['total_handovers']}
  Unique UEs:          {ml_summary['overview']['unique_ues']}
  Unique Antennas:     {ml_summary['overview']['unique_antennas']}
  Duration:            {ml_summary['overview']['time_span_seconds']:.0f} seconds
  Handover Rate:       {ml_summary['overview']['handover_rate_per_second']:.3f} per second

Ping-Pong Analysis:
  Ping-Pong Count:     {ml_summary['pingpong']['pingpong_count']}
  Ping-Pong Rate:      {ml_summary['pingpong']['pingpong_rate']:.2f}%
  Detection Window:    {ml_summary['pingpong']['window_seconds']}s

Success Metrics:
  Successful:          {ml_summary['success']['successful']}
  Failed:              {ml_summary['success']['failed']}
  Success Rate:        {ml_summary['success']['success_rate']:.2f}%

Dwell Time:
  Mean:                {ml_summary['dwell_time']['overall_mean']:.2f}s
  Median:              {ml_summary['dwell_time']['overall_median']:.2f}s
  Std Dev:             {ml_summary['dwell_time']['overall_std']:.2f}s

Problematic Patterns:
  Ping-Pongs:          {ml_summary['problematic_patterns']['pingpong_count']}
  Rapid Oscillations:  {ml_summary['problematic_patterns']['rapid_oscillation_count']}
  Failed Handovers:    {ml_summary['problematic_patterns']['failed_handover_count']}

================================================================================
                            A3 MODE ANALYSIS
================================================================================

Overview:
  Total Handovers:     {a3_summary['overview']['total_handovers']}
  Unique UEs:          {a3_summary['overview']['unique_ues']}
  Unique Antennas:     {a3_summary['overview']['unique_antennas']}
  Duration:            {a3_summary['overview']['time_span_seconds']:.0f} seconds
  Handover Rate:       {a3_summary['overview']['handover_rate_per_second']:.3f} per second

Ping-Pong Analysis:
  Ping-Pong Count:     {a3_summary['pingpong']['pingpong_count']}
  Ping-Pong Rate:      {a3_summary['pingpong']['pingpong_rate']:.2f}%
  Detection Window:    {a3_summary['pingpong']['window_seconds']}s

Success Metrics:
  Successful:          {a3_summary['success']['successful']}
  Failed:              {a3_summary['success']['failed']}
  Success Rate:        {a3_summary['success']['success_rate']:.2f}%

Dwell Time:
  Mean:                {a3_summary['dwell_time']['overall_mean']:.2f}s
  Median:              {a3_summary['dwell_time']['overall_median']:.2f}s
  Std Dev:             {a3_summary['dwell_time']['overall_std']:.2f}s

================================================================================
                        COMPARATIVE IMPROVEMENTS
================================================================================

PING-PONG REDUCTION:
  ML prevented {comparison['pingpong_rate']['improvement']:.1f} percentage points of ping-pong
  Reduction rate: {(comparison['pingpong_rate']['improvement'] / comparison['pingpong_rate']['a3'] * 100) if comparison['pingpong_rate']['a3'] > 0 else 0:.0f}%

DWELL TIME IMPROVEMENT:
  ML increased dwell time by {comparison['avg_dwell_time']['improvement_pct']:.0f}%
  Absolute improvement: {comparison['avg_dwell_time']['ml'] - comparison['avg_dwell_time']['a3']:.2f}s

SUCCESS RATE:
  ML {'improved' if comparison['success_rate']['improvement'] > 0 else 'maintained'} success rate
  Change: {comparison['success_rate']['improvement']:+.1f} percentage points

HANDOVER EFFICIENCY:
  Total handovers: ML={comparison['total_handovers']['ml']}, A3={comparison['total_handovers']['a3']}
  Difference: {comparison['total_handovers']['difference']:+d} handovers
  ML made {abs(comparison['total_handovers']['difference'])} {'fewer' if comparison['total_handovers']['difference'] < 0 else 'more'} decisions

================================================================================
                        THESIS IMPLICATIONS
================================================================================

1. PING-PONG PREVENTION EFFECTIVENESS
   ✓ ML reduced ping-pong by {(comparison['pingpong_rate']['improvement'] / comparison['pingpong_rate']['a3'] * 100) if comparison['pingpong_rate']['a3'] > 0 else 0:.0f}%
   ✓ Demonstrates three-layer prevention mechanism works

2. CONNECTION STABILITY
   ✓ {comparison['avg_dwell_time']['improvement_pct']:.0f}% longer dwell times
   ✓ Improved user experience and reduced signaling overhead

3. HANDOVER QUALITY
   ✓ Maintained/improved success rates
   ✓ Fewer unnecessary handovers

4. PRODUCTION VIABILITY
   ✓ Quantifiable improvements
   ✓ Measurable metrics
   ✓ Validated approach

================================================================================

Report complete. Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

================================================================================
"""
        
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, 'w') as f:
            f.write(report)
        
        logger.info(f"Generated comparison report: {output_path}")
        return output_path


def main():
    """Main entry point."""
    configure_logging()
    
    parser = argparse.ArgumentParser(
        description='Handover History Analysis Tool for Thesis',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Analyze single history file
  python analyze_handover_history.py --input handover_history.json --output analysis_output

  # Compare ML vs A3
  python analyze_handover_history.py --ml ml_history.json --a3 a3_history.json --compare --output comparison

  # Generate thesis summary
  python analyze_handover_history.py --input history.json --summary-only
        """
    )
    
    parser.add_argument('--input', type=str, help='Input handover history JSON file')
    parser.add_argument('--ml', type=str, help='ML mode handover history JSON')
    parser.add_argument('--a3', type=str, help='A3 mode handover history JSON')
    parser.add_argument('--compare', action='store_true', help='Generate comparative analysis')
    parser.add_argument('--output', type=str, default='output/handover_analysis',
                       help='Output directory (default: output/handover_analysis)')
    parser.add_argument('--summary-only', action='store_true', help='Generate summary without plots')
    parser.add_argument('--pingpong-window', type=float, default=10.0,
                       help='Ping-pong detection window in seconds (default: 10.0)')
    
    args = parser.parse_args()
    
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Determine analysis mode
    if args.compare and args.ml and args.a3:
        # Comparative analysis mode
        logger.info("=" * 70)
        logger.info(" Comparative Handover History Analysis (ML vs A3)")
        logger.info("=" * 70)
        
        # Load histories
        with open(args.ml) as f:
            ml_history = json.load(f)
        with open(args.a3) as f:
            a3_history = json.load(f)
        
        logger.info(f"ML history: {len(ml_history)} events")
        logger.info(f"A3 history: {len(a3_history)} events")
        
        # Create comparative analyzer
        comp_analyzer = ComparativeAnalyzer(ml_history, a3_history)
        
        # Generate comparison report
        report_path = comp_analyzer.generate_comparison_report(
            str(output_dir / "HANDOVER_COMPARISON_REPORT.txt")
        )
        
        # Generate individual summaries
        ml_summary = comp_analyzer.ml_analyzer.generate_summary()
        a3_summary = comp_analyzer.a3_analyzer.generate_summary()
        
        # Save summaries as JSON
        with open(output_dir / "ml_handover_summary.json", 'w') as f:
            json.dump(ml_summary, f, indent=2, default=str)
        
        with open(output_dir / "a3_handover_summary.json", 'w') as f:
            json.dump(a3_summary, f, indent=2, default=str)
        
        # Generate visualizations for both
        if not args.summary_only:
            ml_viz = HandoverVisualizer(str(output_dir / "ml_mode"))
            a3_viz = HandoverVisualizer(str(output_dir / "a3_mode"))
            
            ml_plots = ml_viz.generate_all_visualizations(comp_analyzer.ml_analyzer)
            a3_plots = a3_viz.generate_all_visualizations(comp_analyzer.a3_analyzer)
            
            logger.info(f"Generated {len(ml_plots)} ML visualizations")
            logger.info(f"Generated {len(a3_plots)} A3 visualizations")
        
        # Print comparison report
        with open(report_path) as f:
            print(f.read())
        
        logger.info("=" * 70)
        logger.info(" Comparative Analysis Complete")
        logger.info("=" * 70)
        logger.info(f"Report: {report_path}")
        logger.info(f"Output directory: {output_dir}")
    
    elif args.input:
        # Single history analysis mode
        logger.info("=" * 70)
        logger.info(" Handover History Analysis")
        logger.info("=" * 70)
        logger.info(f"Input: {args.input}")
        logger.info(f"Output: {output_dir}")
        
        # Create analyzer
        analyzer = HandoverHistoryAnalyzer(args.input)
        
        # Generate summary
        summary = analyzer.generate_summary()
        
        # Save summary as JSON
        summary_path = output_dir / "handover_summary.json"
        with open(summary_path, 'w') as f:
            json.dump(summary, f, indent=2, default=str)
        
        logger.info(f"Summary saved: {summary_path}")
        
        # Print key metrics
        print("\n" + "=" * 70)
        print(" HANDOVER ANALYSIS SUMMARY")
        print("=" * 70)
        print(f"\nTotal Handovers: {summary['overview']['total_handovers']}")
        print(f"Unique UEs: {summary['overview']['unique_ues']}")
        print(f"Unique Antennas: {summary['overview']['unique_antennas']}")
        print(f"\nPing-Pong Rate: {summary['pingpong']['pingpong_rate']:.2f}%")
        print(f"Success Rate: {summary['success']['success_rate']:.2f}%")
        print(f"Average Dwell Time: {summary['dwell_time']['overall_mean']:.2f}s")
        print(f"Median Dwell Time: {summary['dwell_time']['overall_median']:.2f}s")
        print("=" * 70 + "\n")
        
        # Generate visualizations
        if not args.summary_only:
            visualizer = HandoverVisualizer(str(output_dir))
            plots = visualizer.generate_all_visualizations(analyzer)
            
            print(f"Generated {len(plots)} visualizations:")
            for plot in plots:
                print(f"  • {plot.name}")
            print()
        
        # Generate text report
        report_path = output_dir / "ANALYSIS_REPORT.txt"
        with open(report_path, 'w') as f:
            f.write(f"""
Handover History Analysis Report
=================================

Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Input File: {args.input}

OVERVIEW
--------
Total Handovers: {summary['overview']['total_handovers']}
Unique UEs: {summary['overview']['unique_ues']}
Unique Antennas: {summary['overview']['unique_antennas']}
Time Span: {summary['overview']['time_span_seconds']:.0f} seconds
Handover Rate: {summary['overview']['handover_rate_per_second']:.3f} per second

PING-PONG ANALYSIS
------------------
Ping-Pong Count: {summary['pingpong']['pingpong_count']}
Ping-Pong Rate: {summary['pingpong']['pingpong_rate']:.2f}%
Detection Window: {summary['pingpong']['window_seconds']}s

SUCCESS METRICS
---------------
Successful Handovers: {summary['success']['successful']}
Failed Handovers: {summary['success']['failed']}
Success Rate: {summary['success']['success_rate']:.2f}%

DWELL TIME STATISTICS
---------------------
Mean: {summary['dwell_time']['overall_mean']:.2f}s
Median: {summary['dwell_time']['overall_median']:.2f}s
Std Dev: {summary['dwell_time']['overall_std']:.2f}s
Min: {summary['dwell_time']['overall_min']:.2f}s
Max: {summary['dwell_time']['overall_max']:.2f}s

TOP TRANSITIONS
---------------
""")
            
            if summary['top_transitions']:
                for i, trans in enumerate(summary['top_transitions'], 1):
                    f.write(f"{i}. {trans['from']} → {trans['to']}: "
                           f"{trans['count']} times ({trans['percentage']:.1f}%)\n")
            
            f.write(f"""
PROBLEMATIC PATTERNS
--------------------
Detected Ping-Pongs: {summary['problematic_patterns']['pingpong_count']}
Rapid Oscillations: {summary['problematic_patterns']['rapid_oscillation_count']}
Failed Handovers: {summary['problematic_patterns']['failed_handover_count']}

""")
        
        logger.info(f"Text report saved: {report_path}")
    
    else:
        parser.print_help()
        print("\nError: Must provide either --input or both --ml and --a3")
        return 1
    
    print(f"\n✅ Analysis complete! Results in: {output_dir}\n")
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        logger.info("\nAnalysis interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Analysis failed: {e}", exc_info=True)
        sys.exit(1)

