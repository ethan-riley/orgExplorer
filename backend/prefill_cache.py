#!/usr/bin/env python3
"""
prefill_cache.py - A script to prefill the cache for all organizations by fetching
clusters and summary data.

This script connects to the SQLite database, fetches all organizations that are enabled,
and then fetches the cluster list and full cluster details for each organization,
ensuring the cache is populated.
"""

import sqlite3
import requests
import time
import sys
import os

# Configuration
DB_FILE = "orgs.db"
API_BASE_URL = "http://localhost:7667"

def get_db_connection():
    """Connect to the SQLite database."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def get_all_enabled_orgs():
    """Get all enabled organizations from the database."""
    conn = get_db_connection()
    orgs = conn.execute("SELECT * FROM organizations WHERE enabled=1").fetchall()
    conn.close()
    return [dict(org) for org in orgs]

def prefill_cache(orgs, verbose=False, force_refresh=False):
    """Prefill the cache for each organization by making API calls."""
    total_orgs = len(orgs)
    print(f"Found {total_orgs} enabled organizations")

    for index, org in enumerate(orgs, 1):
        org_id = org["id"]
        org_name = org["org"]

        print(f"[{index}/{total_orgs}] Processing organization: {org_name} (ID: {org_id})")

        # Fetch clusters
        refresh_param = "?refresh=1" if force_refresh else ""
        clusters_url = f"{API_BASE_URL}/org/{org_id}{refresh_param}"

        try:
            if verbose:
                print(f"  Fetching clusters from {clusters_url}")

            response = requests.get(clusters_url)

            if response.status_code == 200:
                clusters_data = response.json()
                clusters_count = len(clusters_data.get("clusters", []))
                print(f"  ✓ Fetched {clusters_count} clusters")
            else:
                print(f"  ✗ Error fetching clusters: {response.status_code}")
                continue

            # Fetch summary data
            summary_url = f"{API_BASE_URL}/org/{org_id}/summary{refresh_param}"

            if verbose:
                print(f"  Fetching summary from {summary_url}")

            summary_response = requests.get(summary_url)

            if summary_response.status_code == 200:
                summary_data = summary_response.json()
                print(f"  ✓ Fetched summary data")
            else:
                print(f"  ✗ Error fetching summary: {summary_response.status_code}")

            # Add small delay to avoid overwhelming the backend
            time.sleep(0.5)

        except Exception as e:
            print(f"  ✗ Exception while processing organization: {str(e)}")

    print("\nCache prefill complete!")

def main():
    """Main function to run the script."""
    # Parse command line arguments
    verbose = "-v" in sys.argv or "--verbose" in sys.argv
    force_refresh = "-f" in sys.argv or "--force" in sys.argv

    # Check if database exists
    if not os.path.exists(DB_FILE):
        print(f"Error: Database file '{DB_FILE}' not found.")
        print("Make sure you're running this script in the same directory as your Flask application.")
        sys.exit(1)

    # Print configuration info
    print("Cache Prefill Script")
    print("===================")
    print(f"Database: {DB_FILE}")
    print(f"API Base URL: {API_BASE_URL}")
    print(f"Force Refresh: {'Yes' if force_refresh else 'No'}")
    print(f"Verbose Output: {'Yes' if verbose else 'No'}")
    print("===================\n")

    # Get all enabled organizations
    orgs = get_all_enabled_orgs()

    # Prefill cache
    prefill_cache(orgs, verbose, force_refresh)

if __name__ == "__main__":
    main()
