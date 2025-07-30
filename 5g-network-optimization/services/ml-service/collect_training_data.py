#!/usr/bin/env python
"""Script for collecting training data from NEF emulator."""
import argparse
import asyncio
import os
import json
import time
import logging
from datetime import datetime
from services.logging_config import configure_logging
from ml_service.app.data.nef_collector import NEFDataCollector
from ml_service.app.data.feature_store_utils import (
    ingest_samples,
    fetch_training_data,
)

logger = logging.getLogger(__name__)

def main():
    """Main entry point for data collection script."""
    configure_logging(level=os.getenv("LOG_LEVEL"), log_file=os.getenv("LOG_FILE"))
    parser = argparse.ArgumentParser(description='Collect training data from NEF emulator')
    parser.add_argument('--url', type=str, default='http://localhost:8080',
                        help='NEF emulator URL (default: http://localhost:8080)')
    parser.add_argument('--username', type=str, default='admin',
                        help='NEF emulator username (default: admin)')
    parser.add_argument('--password', type=str, default='admin',
                        help='NEF emulator password (default: admin)')
    parser.add_argument('--duration', type=int, default=300,
                        help='Data collection duration in seconds (default: 300)')
    parser.add_argument('--interval', type=int, default=1,
                        help='Sampling interval in seconds (default: 1)')
    parser.add_argument('--output', type=str, default=None,
                        help='Output file path (default: auto-generated based on timestamp)')
    parser.add_argument('--train', action='store_true',
                        help='Train the ML model with collected data')
    parser.add_argument('--ml-service-url', type=str, default=None,
                        help='Call /api/collect-data on the given ML service instead of collecting locally')
    
    args = parser.parse_args()

    if args.ml_service_url:
        import requests

        endpoint = args.ml_service_url.rstrip('/') + '/api/collect-data'
        payload = {
            'username': args.username,
            'password': args.password,
            'duration': args.duration,
            'interval': args.interval,
        }
        try:
            resp = requests.post(endpoint, json=payload)
            if resp.status_code == 200:
                result = resp.json()
                logger.info(f"Service collected {result.get('samples', 0)} samples")
                if result.get('file'):
                    logger.info(f"Data saved to {result['file']}")
                return 0
            logger.warning(
                f"Service responded with {resp.status_code}: {resp.text}"
            )
            return 2
        except requests.exceptions.RequestException as e:
            logger.error(f"Error contacting ML service: {str(e)}")
            return 2

    # Initialize collector
    collector = NEFDataCollector(
        nef_url=args.url,
        username=args.username,
        password=args.password
    )
    
    # Login to NEF emulator
    logger.info(f"Connecting to NEF emulator at {args.url}...")
    if not collector.login():
        logger.error("Failed to authenticate with NEF emulator")
        logger.error("Please check your credentials and try again")
        return 1

    logger.info("Successfully authenticated with NEF emulator")
    
    # Check if there are UEs in movement
    ue_state = collector.get_ue_movement_state()
    if not ue_state:
        logger.warning("No UEs found in movement state")
        logger.warning(
            "Please start UE movement in the NEF emulator before collecting data"
        )
        return 1

    logger.info(f"Found {len(ue_state)} UEs in movement state")
    
    # Collect data
    logger.info(
        f"Collecting data for {args.duration} seconds at {args.interval}s intervals..."
    )
    start_time = time.time()
    data = asyncio.run(
        collector.collect_training_data(
            duration=args.duration, interval=args.interval
        )
    )
    collection_time = time.time() - start_time
    
    if not data:
        logger.warning("No data collected")
        return 1
    
    logger.info(
        f"Successfully collected {len(data)} data points in {collection_time:.1f} seconds"
    )

    # Ingest collected samples into Feast
    try:
        ingest_samples(data)
    except Exception as exc:
        logger.error(f"Failed to ingest data into feature store: {exc}")

    # Save to specified output file if provided
    if args.output:
        output_file = args.output
        os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)
        with open(output_file, 'w') as f:
            json.dump(data, f, indent=2)
        logger.info(f"Data saved to {output_file}")
    
    # Train model if requested
    if args.train:
        import requests

        logger.info("Preparing training data from feature store...")
        try:
            training_samples = fetch_training_data(data)
        except Exception as exc:
            logger.error(f"Failed to fetch training data: {exc}")
            training_samples = data

        logger.info("Training ML model with collected data...")
        try:
            response = requests.post(
                "http://localhost:5050/api/train",
                json=training_samples
            )

            if response.status_code == 200:
                logger.info("Model training successful!")
                try:
                    metrics = response.json().get('metrics', {})
                except json.JSONDecodeError as exc:
                    logger.error(f"Failed to decode training response: {exc}")
                    return 4
                logger.info(f"Trained with {metrics.get('samples', 0)} samples")
                logger.info(f"Found {metrics.get('classes', 0)} antenna classes")

                # If feature importance is available, print top features
                if 'feature_importance' in metrics:
                    logger.info("\nFeature importance:")
                    sorted_features = sorted(
                        metrics['feature_importance'].items(),
                        key=lambda x: x[1],
                        reverse=True
                    )
                    for feature, importance in sorted_features:
                        logger.info(f"  {feature}: {importance:.4f}")
            else:
                logger.error(
                    f"Model training failed: {response.status_code} - {response.text}"
                )
                return 1
        except requests.exceptions.RequestException as e:
            logger.error(f"Error during model training: {str(e)}")
            return 3
    
    return 0

if __name__ == "__main__":
    exit(main())
