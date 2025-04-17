#!/usr/bin/env python3
"""
cache_worker.py - A background worker for processing savings analysis reports

This script runs independently of the main Flask application and processes
background jobs from the job queue stored in the database.
"""

import sqlite3
import time
import json
import os
import sys
import logging
import datetime
from multiprocessing import Process

# Import the monthly savings report module
import monthlySavingsReport as msr

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("cache_worker.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("cache_worker")

DATABASE = "orgs.db"

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_job_queue_table():
    """Create the job queue table if it doesn't exist"""
    conn = get_db_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS job_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            org_id INTEGER,
            job_type TEXT,
            status TEXT DEFAULT 'pending',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            started_at DATETIME,
            completed_at DATETIME,
            error TEXT
        )
    """)
    conn.commit()
    conn.close()

def set_cache(org_id, action, data):
    """Store data in the cache table"""
    json_data = json.dumps(data)
    now = datetime.datetime.now().isoformat()
    conn = get_db_connection()
    conn.execute("""
        INSERT INTO cache (org_id, action, data, timestamp)
        VALUES (?,?,?,?)
        ON CONFLICT(org_id, action) DO UPDATE SET data=excluded.data, timestamp=excluded.timestamp
    """, (org_id, action, json_data, now))
    conn.commit()
    conn.close()
    logger.info(f"Cache updated for org_id={org_id}, action={action}")

def get_org_by_id(org_id):
    """Get organization details by ID"""
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM organizations WHERE id=?", (org_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def get_next_job():
    """Get the next pending job from the queue"""
    conn = get_db_connection()
    job = conn.execute("""
        SELECT * FROM job_queue 
        WHERE status = 'pending' 
        ORDER BY created_at ASC 
        LIMIT 1
    """).fetchone()
    
    if job:
        # Mark job as processing
        job_id = job['id']
        now = datetime.datetime.now().isoformat()
        conn.execute("""
            UPDATE job_queue 
            SET status = 'processing', started_at = ? 
            WHERE id = ?
        """, (now, job_id))
        conn.commit()
    
    conn.close()
    return dict(job) if job else None

def update_job_status(job_id, status, error=None):
    """Update the status of a job"""
    conn = get_db_connection()
    now = datetime.datetime.now().isoformat()
    if status == 'completed':
        conn.execute("""
            UPDATE job_queue 
            SET status = ?, completed_at = ? 
            WHERE id = ?
        """, (status, now, job_id))
    elif status == 'error':
        conn.execute("""
            UPDATE job_queue 
            SET status = ?, completed_at = ?, error = ? 
            WHERE id = ?
        """, (status, now, error, job_id))
    conn.commit()
    conn.close()
    logger.info(f"Job {job_id} updated to status: {status}")

def get_csv(org_id):
    """Get the CSV path for an organization's cluster details"""
    org = get_org_by_id(org_id)
    if not org:
        return None
    
    org_folder = os.path.join("outputs", org["org"].replace(" ", "_"))
    csv_file = os.path.join(org_folder, "full_cluster_details.csv")
    
    from app import get_cache, fetch_full_cluster_info, set_cache
    
    # Check if we have the data in cache
    full_details = get_cache(org_id, "full_cluster_details")
    if full_details is not None:
        import pandas as pd
        cols = ["ClusterID", "Cluster Name", "Provider", "accountID", "Region", "Phase 1", "Phase 2", "CPU Count",
                "WOOP Enabled", "% OnDemand Nodes", "% Spot Nodes", "Fallback Nodes?", "First Rebalance", "Connected Date",
                "Environment", "Evictor", "Scheduled Rebalance", "WOOP enabled %", "Kubernetes version", "Extended Support",
                "3rd Party", "CastAI Nodes Managed", "Provider Nodes Managed", "3rd Party Nodes Managed"]
        df = pd.DataFrame(full_details)
        df = df.reindex(columns=cols)
        os.makedirs(org_folder, exist_ok=True)
        df.to_csv(csv_file, index=False)
    
    if not os.path.exists(csv_file):
        logger.error(f"CSV not found for org_id={org_id}")
        return None
    
    return csv_file

def process_monthly_savings_job(org_id):
    """Process a monthly savings report generation job"""
    try:
        # Get organization details
        org = get_org_by_id(org_id)
        if not org:
            raise Exception(f"Organization with ID {org_id} not found")
        
        logger.info(f"Processing monthly savings for org: {org['org']} (ID: {org_id})")
        
        # Get the CSV file path
        details_csv = get_csv(org_id)
        if not details_csv:
            raise Exception(f"Could not generate CSV for org_id={org_id}")
        
        # Generate temporary file names (they won't be actually saved to disk)
        api_key = org["key"]
        org_name = org["org"]
        savings_csv_name = f"{org_name}_savings.csv"
        resources_csv_name = f"{org_name}_resources.csv"
        
        # Generate the report
        logger.info(f"Starting report generation for org_id={org_id}")
        savings_df, resource_df = msr.generate_monthly_savings_report(
            api_key, details_csv, savings_csv_name, resources_csv_name
        )
        
        # Convert DataFrames to dictionaries for caching
        savings_data = savings_df.to_dict(orient="records")
        resource_data = resource_df.to_dict(orient="records")
        report = {"savings": savings_data, "resource": resource_data}
        
        # Cache the generated report
        set_cache(org_id, "monthly_savings_report", report)
        
        # Save the CSV files for quick access
        org_folder = os.path.join("outputs", org_name.replace(" ", "_"))
        os.makedirs(org_folder, exist_ok=True)
        
        savings_csv_file = os.path.join(org_folder, savings_csv_name)
        resource_csv_file = os.path.join(org_folder, resources_csv_name)
        
        savings_df.to_csv(savings_csv_file, index=False)
        resource_df.to_csv(resource_csv_file, index=False)
        
        # Create a zip file
        import zipfile
        zip_filename = os.path.join(org_folder, f"{org_name}_monthly_savings_report.zip")
        with zipfile.ZipFile(zip_filename, "w") as zipf:
            zipf.write(savings_csv_file, os.path.basename(savings_csv_file))
            zipf.write(resource_csv_file, os.path.basename(resource_csv_file))
        
        logger.info(f"Monthly savings report completed for org_id={org_id}")
        return True
    
    except Exception as e:
        logger.error(f"Error processing monthly savings for org_id={org_id}: {str(e)}")
        return False

def worker_process():
    """Main worker process that polls for jobs and processes them"""
    logger.info("Starting cache worker process")
    
    while True:
        try:
            # Get the next job
            job = get_next_job()
            
            if job:
                logger.info(f"Processing job: {job['id']} - Type: {job['job_type']} - Org: {job['org_id']}")
                
                if job['job_type'] == 'monthly_savings_report':
                    success = process_monthly_savings_job(job['org_id'])
                    if success:
                        update_job_status(job['id'], 'completed')
                    else:
                        update_job_status(job['id'], 'error', 'Failed to process monthly savings report')
                else:
                    update_job_status(job['id'], 'error', f"Unknown job type: {job['job_type']}")
            else:
                # No jobs to process, sleep for a while
                time.sleep(5)
        
        except Exception as e:
            logger.error(f"Error in worker process: {str(e)}")
            time.sleep(5)

def start_worker():
    """Initialize the database and start the worker process"""
    # Initialize the job queue table
    init_job_queue_table()
    
    # Start the worker process
    process = Process(target=worker_process)
    process.daemon = True
    process.start()
    
    return process

if __name__ == "__main__":
    logger.info("Starting cache worker as standalone process")
    process = start_worker()
    
    try:
        # Keep the main process running to handle keyboard interrupts
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, shutting down...")
        sys.exit(0)