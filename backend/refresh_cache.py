#!/usr/bin/env python3
"""
refresh_cache.py - A script to refresh the savings analysis cache for all organizations

This script can be run manually or scheduled via cron to ensure all organizations
have up-to-date savings analysis data without impacting application performance.
"""

import sqlite3
import argparse
import datetime
import os
import sys
import logging

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("cache_refresh.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("cache_refresh")

DATABASE = "orgs.db"

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def get_all_orgs():
    """Get all enabled organizations from the database"""
    conn = get_db_connection()
    orgs = conn.execute("SELECT * FROM organizations WHERE enabled=1").fetchall()
    conn.close()
    return [dict(row) for row in orgs]

def queue_job(org_id, job_type):
    """Add a job to the queue and return the job ID"""
    conn = get_db_connection()
    cursor = conn.execute(
        "INSERT INTO job_queue (org_id, job_type) VALUES (?, ?)",
        (org_id, job_type)
    )
    job_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return job_id

def refresh_all_caches(job_type="monthly_savings_report"):
    """Queue cache refresh jobs for all enabled organizations"""
    orgs = get_all_orgs()
    logger.info(f"Found {len(orgs)} enabled organizations")
    
    jobs = []
    for org in orgs:
        logger.info(f"Queueing {job_type} job for org: {org['org']} (ID: {org['id']})")
        job_id = queue_job(org['id'], job_type)
        jobs.append({
            "org_id": org['id'],
            "org_name": org['org'],
            "job_id": job_id
        })
    
    logger.info(f"Queued {len(jobs)} jobs")
    return jobs

def refresh_specific_org(org_id, job_type="monthly_savings_report"):
    """Queue a cache refresh job for a specific organization"""
    conn = get_db_connection()
    org = conn.execute("SELECT * FROM organizations WHERE id=?", (org_id,)).fetchone()
    conn.close()
    
    if not org:
        logger.error(f"Organization with ID {org_id} not found")
        return None
    
    logger.info(f"Queueing {job_type} job for org: {org['org']} (ID: {org['id']})")
    job_id = queue_job(org['id'], job_type)
    
    return {
        "org_id": org['id'],
        "org_name": org['org'],
        "job_id": job_id
    }

def clear_old_jobs(days=7):
    """Clear completed jobs older than the specified number of days"""
    conn = get_db_connection()
    cutoff_date = (datetime.datetime.now() - datetime.timedelta(days=days)).isoformat()
    
    cursor = conn.execute(
        "DELETE FROM job_queue WHERE status IN ('completed', 'error') AND created_at < ?",
        (cutoff_date,)
    )
    deleted_count = cursor.rowcount
    conn.commit()
    conn.close()
    
    logger.info(f"Cleared {deleted_count} old jobs from the queue")
    return deleted_count

def display_job_status():
    """Display the status of all jobs in the queue"""
    conn = get_db_connection()
    jobs = conn.execute("""
        SELECT jq.*, o.org 
        FROM job_queue jq
        JOIN organizations o ON jq.org_id = o.id
        ORDER BY jq.created_at DESC
        LIMIT 100
    """).fetchall()
    conn.close()
    
    if not jobs:
        logger.info("No jobs found in the queue")
        return []
    
    job_list = []
    for job in jobs:
        job_dict = dict(job)
        job_list.append(job_dict)
        
        status_str = f"{job['status']}"
        if job['status'] == 'error' and job['error']:
            status_str += f" - {job['error']}"
            
        logger.info(f"Job {job['id']} - Org: {job['org']} - Type: {job['job_type']} - Status: {status_str}")
    
    return job_list

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Refresh the savings analysis cache for organizations")
    parser.add_argument("--all", action="store_true", help="Refresh cache for all organizations")
    parser.add_argument("--org", type=int, help="Refresh cache for a specific organization ID")
    parser.add_argument("--clean", action="store_true", help="Clean up old completed jobs")
    parser.add_argument("--status", action="store_true", help="Display the status of all jobs")
    parser.add_argument("--days", type=int, default=7, help="Number of days to keep completed jobs (default: 7)")
    parser.add_argument("--type", type=str, default="monthly_savings_report", help="Type of job to queue (default: monthly_savings_report)")
    
    args = parser.parse_args()
    
    if args.status:
        display_job_status()
    elif args.clean:
        clear_old_jobs(args.days)
    elif args.all:
        refresh_all_caches(args.type)
    elif args.org is not None:
        refresh_specific_org(args.org, args.type)
    else:
        parser.print_help()