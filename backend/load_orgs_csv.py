#!/usr/bin/env python3
"""
load_orgs_csv.py - A script to load organizations from a CSV file into the database.

This script can be used to manually load or update organizations without using the web interface.
"""

import sqlite3
import csv
import os
import sys
import datetime
import argparse

# Database file path
DATABASE = "orgs.db"

def get_db_connection():
    """Create a database connection with row factory"""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initialize the database schema if it doesn't exist"""
    conn = get_db_connection()

    # Create organizations table if not exists
    conn.execute("""
        CREATE TABLE IF NOT EXISTS organizations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            org TEXT NOT NULL,
            key TEXT NOT NULL,
            org_id TEXT,
            enabled INTEGER DEFAULT 1,
            region TEXT DEFAULT 'US',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            latest_sync DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Create cache table if not exists
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            org_id INTEGER,
            action TEXT,
            data TEXT,
            timestamp DATETIME,
            UNIQUE(org_id, action)
        )
    """)

    conn.commit()
    conn.close()
    print("Database initialized successfully.")

def load_orgs_from_csv(csv_path, update_existing=False, clear_all=False):
    """Load organizations from CSV file into the database"""
    if not os.path.exists(csv_path):
        print(f"Error: CSV file '{csv_path}' not found.")
        return False

    conn = get_db_connection()

    # Clear all existing organizations if requested
    if clear_all:
        conn.execute("DELETE FROM organizations")
        conn.execute("DELETE FROM cache")
        print("Cleared all existing organizations and cache entries.")

    # Read the CSV file
    with open(csv_path, newline="") as csvfile:
        reader = csv.DictReader(csvfile)
        orgs_added = 0
        orgs_updated = 0
        orgs_skipped = 0

        for row in reader:
            org_name = row.get("org", "").strip()
            api_key = row.get("key", "").strip()
            org_id = row.get("org_id", "").strip()
            region = row.get("region", "US").strip()

            if not org_name or not api_key:
                print(f"Skipping row - missing required fields: {row}")
                orgs_skipped += 1
                continue

            # Check if organization already exists
            existing_org = conn.execute(
                "SELECT id FROM organizations WHERE org=?", (org_name,)
            ).fetchone()

            if existing_org and update_existing:
                # Update existing organization
                conn.execute(
                    "UPDATE organizations SET key=?, org_id=?, region=?, latest_sync=CURRENT_TIMESTAMP WHERE id=?",
                    (api_key, org_id, region, existing_org["id"])
                )
                orgs_updated += 1
                print(f"Updated organization: {org_name}")
            elif not existing_org:
                # Add new organization
                conn.execute(
                    "INSERT INTO organizations (org, key, org_id, region) VALUES (?,?,?,?)",
                    (org_name, api_key, org_id, region)
                )
                orgs_added += 1
                print(f"Added organization: {org_name}")
            else:
                # Skip existing organization
                print(f"Skipped existing organization: {org_name}")
                orgs_skipped += 1

    conn.commit()
    conn.close()

    print(f"\nSummary:")
    print(f"Organizations added: {orgs_added}")
    print(f"Organizations updated: {orgs_updated}")
    print(f"Organizations skipped: {orgs_skipped}")
    return True

def list_organizations():
    """List all organizations in the database"""
    conn = get_db_connection()
    orgs = conn.execute("SELECT * FROM organizations ORDER BY org").fetchall()
    conn.close()

    if not orgs:
        print("No organizations found in the database.")
        return

    print("\nOrganizations in the database:")
    print("=" * 80)
    print(f"{'ID':<5} {'Name':<30} {'API Key':<15} {'Org ID':<20} {'Region':<10} {'Enabled':<10}")
    print("-" * 80)

    for org in orgs:
        # Mask API key for security
        masked_key = org["key"][:5] + "..." if org["key"] else ""
        enabled = "Yes" if org["enabled"] == 1 else "No"

        print(f"{org['id']:<5} {org['org']:<30} {masked_key:<15} {org['org_id']:<20} {org['region']:<10} {enabled:<10}")

def main():
    parser = argparse.ArgumentParser(description="Load organizations from CSV into the database")
    parser.add_argument("--csv", help="Path to the CSV file", default="orgs.csv")
    parser.add_argument("--update", action="store_true", help="Update existing organizations")
    parser.add_argument("--clear", action="store_true", help="Clear all existing organizations before loading")
    parser.add_argument("--list", action="store_true", help="List all organizations in the database")
    parser.add_argument("--init-db", action="store_true", help="Initialize the database schema")

    args = parser.parse_args()

    if args.init_db:
        init_db()

    if args.list:
        list_organizations()
        return

    if not args.init_db and not args.list:
        print(f"Loading organizations from {args.csv}...")
        if load_orgs_from_csv(args.csv, args.update, args.clear):
            list_organizations()

if __name__ == "__main__":
    main()
