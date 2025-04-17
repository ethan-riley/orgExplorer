#!/usr/bin/env python3
"""
app.py – A Flask-based API for managing organizations, fetching clusters,
and caching all actions at the DB level.

Now every route returns JSON only.

Features:
1. Loads orgs.csv into a SQLite database.
2. Uses a "cache" table to store cached JSON results for each org and action.
3. Every endpoint (except CSV download) returns JSON data.
4. Runs on port 7667.
"""
import sqlite3, os, csv, datetime, json, requests, statistics
import pandas as pd
from flask import Flask, request, redirect, url_for, jsonify, flash, send_file
from gevent.pywsgi import WSGIServer
from app_security import APISecurityManager, flask_api_security_middleware, require_permission

import datetime
import zipfile
import threading
from functools import wraps

# Import the monthly savings report module.
import monthlySavingsReport as msr
import json

# Initialize the API Sec Manager
security_manager = APISecurityManager(
    api_keys_file="api_keys.json",
    env_key_name="EXPLORER_API_KEY",
    token_expiry=315360000 # 24 hours
)
app = Flask(__name__)

# Apply the Flask API security middleware
flask_api_security_middleware(app, security_manager)


DATABASE = "orgs.db"

# ----------------------------
# Database & Cache Helper Functions
# ----------------------------

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    # Create table if not exists.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS organizations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            org TEXT NOT NULL,
            key TEXT NOT NULL,
            org_id TEXT,
            enabled INTEGER DEFAULT 1,
            region TEXT DEFAULT 'US',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            -- Note: latest_sync is not added here if we want to add it later in an upgrade.
        )
    """)
    conn.commit()

    # Check if the column 'latest_sync' exists; if it doesn't, add it.
    cursor = conn.execute("PRAGMA table_info(organizations)")
    columns = [col[1] for col in cursor.fetchall()]
    if "latest_sync" not in columns:
        # SQLite does not support IF NOT EXISTS on ALTER TABLE, so we perform a check first.
        conn.execute("ALTER TABLE organizations ADD COLUMN latest_sync DATETIME DEFAULT CURRENT_TIMESTAMP")
        conn.commit()
        print("Added column 'latest_sync' to organizations table.")
    else:
        print("'latest_sync' column already exists in organizations table.")

    conn.close()

def init_cache_table():
    conn = get_db_connection()
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

def load_orgs_csv():
    if not os.path.exists("orgs.csv"):
        print("orgs.csv not found.")
        return
    conn = get_db_connection()
    cur = conn.execute("SELECT COUNT(*) as cnt FROM organizations")
    count = cur.fetchone()["cnt"]
    if count > 0:
        conn.close()
        return  # Already loaded
    with open("orgs.csv", newline="") as csvfile:
        reader = csv.DictReader(csvfile)
        orgs = [(row["org"], row["key"], row.get("org_id", ""), 1) for row in reader]
    conn.executemany("INSERT INTO organizations (org, key, org_id, enabled) VALUES (?,?,?,?)", orgs)
    conn.commit()
    conn.close()

def get_all_orgs():
    conn = get_db_connection()
    orgs = conn.execute("SELECT * FROM organizations").fetchall()
    conn.close()
    return [dict(row) for row in orgs]

def get_org_by_id(org_id):
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM organizations WHERE id=?", (org_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def add_org(org, key, org_identifier, region="US"):
    conn = get_db_connection()
    conn.execute("INSERT INTO organizations (org, key, org_id, region) VALUES (?,?,?,?)",
                 (org, key, org_identifier, region))
    conn.commit()
    conn.close()

def update_org(org_id, org, key, org_identifier, region):
    conn = get_db_connection()
    conn.execute("UPDATE organizations SET org=?, key=?, org_id=?, region=? WHERE id=?",
                 (org, key, org_identifier, region, org_id))
    conn.commit()
    conn.close()

def disable_org(org_id):
    conn = get_db_connection()
    conn.execute("UPDATE organizations SET enabled=0 WHERE id=?", (org_id,))
    conn.commit()
    conn.close()

def enable_org(org_id):
    conn = get_db_connection()
    conn.execute("UPDATE organizations SET enabled=1 WHERE id=?", (org_id,))
    conn.commit()
    conn.close()

# Cache functions
def get_cache(org_id, action):
    conn = get_db_connection()
    row = conn.execute("SELECT data FROM cache WHERE org_id=? AND action=?", (org_id, action)).fetchone()
    conn.close()
    if row:
        try:
            return json.loads(row["data"])
        except Exception:
            return None
    return None

def set_cache(org_id, action, data):
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

# Initialize our DB, cache table, and load orgs.csv
init_db()
init_cache_table()
load_orgs_csv()
init_job_queue_table()

start_background_worker()

# ------------------------------------------
# API Optimization - Savings Analysis
# ------------------------------------------

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

def get_job_status(job_id):
    """Get the status of a job"""
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM job_queue WHERE id=?", (job_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def check_pending_jobs(org_id, job_type):
    """Check if there are any pending jobs for this org and job type"""
    conn = get_db_connection()
    row = conn.execute(
        "SELECT id FROM job_queue WHERE org_id=? AND job_type=? AND status IN ('pending', 'processing')",
        (org_id, job_type)
    ).fetchone()
    conn.close()
    return r

def start_background_worker():
    """Import and start the cache worker in a separate thread"""
    try:
        import cache_worker
        worker_thread = threading.Thread(target=cache_worker.worker_process)
        worker_thread.daemon = True
        worker_thread.start()
        print("Background worker started")
    except Exception as e:
        print(f"Error starting background worker: {e}")

# ------------------------------------------
# API Helper Functions (Cast.ai API routines)
# ------------------------------------------
def get_extended_support_data(provider):
    endpoints = {
        "EKS": "https://endoflife.date/api/amazon-eks.json",
        "GKE": "https://endoflife.date/api/google-kubernetes-engine.json",
        "AKS": "https://endoflife.date/api/azure-kubernetes-service.json"
    }
    url = endpoints.get(provider.upper())
    if not url:
        print(f"No endpoint defined for provider {provider}")
        return []
    try:
        resp = requests.get(url, headers={"Accept": "application/json"})
        data = resp.json()
    except Exception as e:
        print(f"Error fetching extended support data for {provider}: {e}")
        data = []
    return data

def getKnownAnywhere(cluster_id, api_key):
    url = f"https://api.cast.ai/v1/kubernetes/external-clusters/{cluster_id}/nodes?nodeStatus=node_status_unspecified&lifecycleType=lifecycle_type_unspecified"
    headers = {"X-API-Key": api_key, "accept": "application/json"}
    respuesta = requests.get(url, headers=headers)
    try:
        datados = respuesta.json()
    except Exception as e:
        print(f"Error decoding data for cluster {cluster_id}: {e}", flush=True)
        datados = {}
    items = datados.get("items", [])
    total_nodes = len(items)

    if total_nodes == 0:
        return "Unknown"
    for item in items:
        name = item.get("name", {})
        if "fargate" in name:
            return "fargate"
        else:
            return "Unknown"

def simplify_version(provider, version_str):
    if provider.lower() == "eks":
        parts = version_str.split(".")
        return ".".join(parts[:2])
    elif provider.lower() == "gke":
        return ".".join(version_str.split("-")[0].split(".")[:2])
    elif provider.lower() == "aks":
        parts = version_str.split(".")
        return ".".join(parts[:2])
    elif provider.lower() == "anywhere":
        if version_str.startswith("v"):
            version_str = version_str[1:]
        # Split on "-" to get the version portion
        version_part = version_str.split("-")[0]
        # Split the version portion on "." and join the first two parts
        parts = version_part.split(".")
        return ".".join(parts[:2])
def getFargateVersion(cluster_id, api_key):
    url = f"https://api.cast.ai/v1/kubernetes/external-clusters/{cluster_id}/nodes?nodeStatus=node_status_unspecified&lifecycleType=lifecycle_type_unspecified"
    headers = {"X-API-Key": api_key, "accept": "application/json"}
    respuesta = requests.get(url, headers=headers)
    try:
        datados = respuesta.json()
    except Exception as e:
        print(f"Error decoding data for cluster {cluster_id}: {e}", flush=True)
        datados = {}
    items = datados.get("items", [])
    total_nodes = len(items)

    if total_nodes == 0:
        version =  "Unknown"
    version = 1.32
    for item in items:
        labels = item.get("nodeInfo", {})
        version_str = labels["kubeletVersion"]
        version_new = simplify_version("anywhere", version_str)
        fvn = float(version_new)
        fv = float(version)
        if fvn <= fv:
           fv = fvn
    return fv

def determine_support_status(provider, version_str, support_data=None):
    from datetime import date, datetime
    simple_version = simplify_version(provider, version_str)

    # If no support data is provided, fetch it
    if support_data is None:
        support_data = get_extended_support_data(provider)

    # Iterate over each version object
    for item in support_data:
        cycle = item.get("cycle", "")
        simple_cycle = simplify_version(provider, cycle)
        if simple_cycle == simple_version:
            # For EKS, use 'eol' and 'extendedSupport'
            if provider.lower() == "eks":
                std_date_str = item.get("eol", "")
                ext_date_str = item.get("extendedSupport", "")
            # For GKE, use 'support' and 'eol'
            elif provider.lower() == "gke":
                std_date_str = item.get("support", "")
                ext_date_str = item.get("eol", "")
            # For AKS, use 'eol' and 'lts'
            elif provider.lower() == "aks":
                std_date_str = item.get("eol", "")
                ext_date_str = item.get("lts", "")
            else:
                std_date_str = ""
                ext_date_str = ""

            try:
                std_date = datetime.fromisoformat(std_date_str).date() if std_date_str else None
            except Exception as e:
                print(f"Error parsing standard support date '{std_date_str}': {e}")
                std_date = None
            try:
                ext_date = datetime.fromisoformat(ext_date_str).date() if ext_date_str else None
            except Exception as e:
                print(f"Error parsing extended support date '{ext_date_str}': {e}")
                ext_date = None

            today = date.today()
            if std_date and today <= std_date:
                return "No"
            elif std_date and ext_date and std_date < today <= ext_date:
                return "Yes"
            elif ext_date and today > ext_date:
                return "Not Supported (EOL)"
            else:
                return "Unknown"
    return "Version not found"

def get_cluster_ids(api_key, org_dir="."):
    url = "https://api.cast.ai/v1/cost-reports/organization/clusters/summary"
    headers = {"accept": "application/json", "X-API-Key": api_key}
    resp = requests.get(url, headers=headers)
    data = resp.json()
    offerings = {}
    for item in data.get("items", []):
        cluster_id = item.get("clusterId")
        if cluster_id:
            offerings[cluster_id] = {
                "nodeCountOnDemand": int(item.get("nodeCountOnDemand", "0")),
                "nodeCountOnDemandCastai": int(item.get("nodeCountOnDemandCastai", "0")),
                "nodeCountSpot": int(item.get("nodeCountSpot", "0")),
                "nodeCountSpotCastai": int(item.get("nodeCountSpotCastai", "0")),
                "nodeCountSpotFallbackCastai": int(item.get("nodeCountSpotFallbackCastai", "0"))
            }
    return offerings

def get_cluster_details(api_key, cluster_id):
    url = f"https://api.cast.ai/v1/kubernetes/external-clusters/{cluster_id}"
    headers = {"accept": "application/json", "X-API-Key": api_key}
    resp = requests.get(url, headers=headers)
    return resp.json()

def fetch_cluster_list(api_key):
    offerings = get_cluster_ids(api_key)
    clusters = []
    for cid in offerings.keys():
        details = get_cluster_details(api_key, cid)
        cluster_name = details.get("name", "")
        provider = details.get("providerType", "").lower()
        account_id = "Unknown"
        if provider == "eks":
            account_id = details.get("eks", {}).get("accountId", "Unknown")
        elif provider == "gke":
            account_id = details.get("gke", {}).get("projectId", "Unknown")
        elif provider == "aks":
            account_id = details.get("aks", {}).get("nodeResourceGroup", "Unknown")
        region = "Unknown"
        if provider in ["eks", "gke", "aks"]:
            region_info = details.get("region", {})
            if isinstance(region_info, dict):
                region = region_info.get("name", "Unknown")
        clusters.append({
            "cluster_id": cid,
            "account_id": account_id,
            "cluster_name": cluster_name,
            "region": region
        })
    return clusters

def get_all_rebalancing_schedules(api_key):
    url = "https://api.cast.ai/v1/rebalancing-schedules"
    headers = {"accept": "application/json", "X-API-Key": api_key}
    resp = requests.get(url, headers=headers)
    data = resp.json()
    schedule_map = {}
    for schedule in data.get("schedules", []):
        cron = schedule.get("schedule", {}).get("cron", "")
        next_trigger = schedule.get("nextTriggerAt", "")
        schedule_desc = f"Cron: {cron}, Next: {next_trigger}"
        for job in schedule.get("jobs", []):
            cid = job.get("clusterId", "")
            if cid:
                schedule_map.setdefault(cid, []).append(schedule_desc)
    return schedule_map

def detect_environment(cluster_name, tag_env=""):
    import re
    name = cluster_name.lower()
    prod_patterns = [r'\bprod\b', r'\bproduction\b', r'\bprd\b', r'\bproduccion\b', r'\bp\b', r'\bpd\b', r'\b-p-\b', r'\b-prd\b']
    staging_patterns = [r'\bqa\b', r'\b-qa\b', r'\bqas\b', r'\buat\b', r'\bquality[- ]?assurance\b', r'\bqat\b', r'\bq\b', r'\btest\b', r'\bstaging\b', r'\bqa[0-9]\b', r'\b-q-\b']
    dev_patterns = [r'\bdev\b', r'\bdesa\b', r'\bdv\b', r'\bde\b', r'\bdevelopment\b', r'\bdesarrollo\b', r'\bdes\b', r'\bdev[0-9]\b', r'\b-d-\b']
    integration_patthers = [r'\bcd\b', r'\bci\b', r'\bargo\b', r'\bjenkins\b']
    for pattern in prod_patterns:
        if re.search(pattern, name, re.IGNORECASE):
            tag_env = "Production"
    for pattern in staging_patterns:
        if re.search(pattern, name, re.IGNORECASE):
            tag_env = "Staging"
    for pattern in dev_patterns:
        if re.search(pattern, name, re.IGNORECASE):
            tag_env = "Development"
    for pattern in integration_patthers:
        if re.search(pattern, name, re.IGNORECASE):
            tag_env = "Integration"
    if not tag_env:
        tag_env = "Unknown"
    return tag_env

def get_cpu_count(api_key, cluster_id, org_dir="."):
    url = f"https://api.cast.ai/v1/kubernetes/external-clusters/{cluster_id}/nodes?nodeStatus=node_status_unspecified&lifecycleType=lifecycle_type_unspecified"
    headers = {"X-API-Key": api_key, "accept": "application/json"}
    resp = requests.get(url, headers=headers)
    data = resp.json()
    total_cpu = 0.0
    for node in data.get("items", []):
        try:
            cpu = float(node.get("resources", {}).get("cpuCapacityMilli", 0))
        except Exception:
            cpu = 0.0
        total_cpu += cpu
    total_cpu = total_cpu / 1000
    return int(round(total_cpu, 0))

def get_woop_enabled_percent(api_key, cluster_id):
    url = f"https://api.cast.ai/v1/workload-autoscaling/clusters/{cluster_id}/workloads-summary?includeCosts=true"
    headers = {"accept": "application/json", "X-API-Key": api_key}
    resp = requests.get(url, headers=headers)
    data = resp.json()
    total = data.get("totalCount", 0)
    optimized = data.get("optimizedCount", 0)
    try:
        ratio = float(optimized) / float(total) if float(total) > 0 else 0
    except:
        ratio = 0
    return f"{ratio*100:.2f}%"

def get_rebalancing_plans(api_key, cluster_id):
    url = f"https://api.cast.ai/v1/kubernetes/clusters/{cluster_id}/rebalancing-plans?limit=10"
    headers = {"X-API-Key": api_key, "accept": "application/json"}
    resp = requests.get(url, headers=headers)
    data = resp.json()
    for plan in data.get("items", []):
        if plan.get("status", "").lower() == "finished":
            return "Yes"
    return "No"

def get_evictor_status(api_key, cluster_id, org_dir="."):
    post_url = f"https://api.cast.ai/v1/kubernetes/clusters/{cluster_id}/evictor-config"
    headers = {"accept": "application/json", "X-API-Key": api_key, "Content-Type": "application/json"}
    post_resp = requests.post(post_url, headers=headers, json={})
    try:
        post_data = post_resp.json()
    except Exception:
        post_data = {}
    if not post_data.get("isReady", False):
        return "Uninstalled"
    get_url = f"https://api.cast.ai/v1/kubernetes/clusters/{cluster_id}/evictor-advanced-config"
    get_resp = requests.get(get_url, headers={"accept": "application/json", "X-API-Key": api_key})
    try:
        get_data = get_resp.json()
    except Exception:
        get_data = {}
    if "evictionConfig" in get_data:
        if not get_data["evictionConfig"]:
            return "Installed (Basic)"
        else:
            return "Installed (Advanced)"
    return ""

def get_nodes_managed_detailed(api_key, cluster_id, provider):
    url = f"https://api.cast.ai/v1/kubernetes/external-clusters/{cluster_id}/nodes?nodeStatus=node_status_unspecified&lifecycleType=lifecycle_type_unspecified"
    headers = {"X-API-Key": api_key, "accept": "application/json"}
    resp = requests.get(url, headers=headers)
    data = resp.json()
    items = data.get("items", [])
    total_nodes = len(items)
    if total_nodes == 0:
        return {"CastAI": 0, "Provider": 0, "3rd Party": 0, "Total": 0}
    provider_key = provider.upper()
    counts = {"CastAI": 0, "Karpenter": 0, "ScaleOps": 0, provider_key: 0}
    for item in items:
        labels = item.get("labels", {})
        if labels.get("provisioner.cast.ai/managed-by", "") == "cast.ai":
            counts["CastAI"] += 1
        elif labels.get("karpenter.sh/registered", "") == "true":
            counts["Karpenter"] += 1
        elif labels.get("scaleops.sh/registered", "") == "true":
            counts["ScaleOps"] += 1
        else:
            counts[provider_key] += 1
    third_party_count = counts["Karpenter"] + counts["ScaleOps"]
    details = {
        "CastAI": round((counts["CastAI"] / total_nodes) * 100, 1),
        "Provider": round((counts[provider_key] / total_nodes) * 100, 1),
        "3rd Party": round((third_party_count / total_nodes) * 100, 1),
        "Total": total_nodes
    }
    return details

def extract_full_cluster_info(cluster_id, details, offerings, api_key, schedule_map, org_dir="."):
    info = {}
    info["ClusterID"] = cluster_id
    info["Cluster Name"] = details.get("name", "")
    provider = details.get("providerType", "").lower()
    info["Provider"] = provider.upper() if provider else ""
    is_phase2 = details.get("isPhase2")
    info["Phase 1"] = "Yes"
    info["Phase 2"] = "Yes" if is_phase2 in [True, "true", "True"] else "No"
    woop_percent = get_woop_enabled_percent(api_key, cluster_id)
    info["WOOP Enabled"] = "Yes" if woop_percent != "0.00%" else "No"
    info["WOOP enabled %"] = woop_percent
    if cluster_id in offerings:
        off = offerings[cluster_id]
        total = (off.get("nodeCountOnDemand", 0) + off.get("nodeCountOnDemandCastai", 0) +
                 off.get("nodeCountSpot", 0) + off.get("nodeCountSpotCastai", 0) +
                 off.get("nodeCountSpotFallbackCastai", 0))
        if total > 0:
            od = (off.get("nodeCountOnDemand", 0) + off.get("nodeCountOnDemandCastai", 0)) / total * 100
            spot = (off.get("nodeCountSpot", 0) + off.get("nodeCountSpotCastai", 0)) / total * 100
            fb = off.get("nodeCountSpotFallbackCastai", 0) / total * 100
        else:
            od = spot = fb = 0.0
    else:
        od = spot = fb = 0.0
    info["% OnDemand Nodes"] = f"{round(od,1)}%"
    info["% Spot Nodes"] = f"{round(spot,1)}%"
    info["Fallback Nodes?"] = f"{round(fb,1)}%"
    info["First Rebalance"] = get_rebalancing_plans(api_key, cluster_id)
    date_str = details.get("firstOperationAt", "")
    if provider == "anywhere":
        date_str = details.get("createdAt", "")
    try:
        info["Connected Date"] = datetime.datetime.fromisoformat(date_str[:10]).date().isoformat() if date_str else ""
    except Exception:
        info["Connected Date"] = ""
    tags = details.get("tags", {})
    info["Environment"] = detect_environment(details.get("name", ""), tags.get("Environment", ""))
    info["Evictor"] = get_evictor_status(api_key, cluster_id, org_dir)
    if cluster_id in schedule_map:
        info["Scheduled Rebalance"] = "Yes: " + "; ".join(schedule_map[cluster_id])
    else:
        info["Scheduled Rebalance"] = "No"
    info["CPU Count"] = get_cpu_count(api_key, cluster_id, org_dir)
    region_info = details.get("region", {})
    info["Region"] = region_info.get("name", "Unknown") if isinstance(region_info, dict) else "Unknown"
    nodes_mgmt = get_nodes_managed_detailed(api_key, cluster_id, provider)
    info["3rd Party"] = "Yes" if nodes_mgmt["3rd Party"] > 0 else "No"
    info["CastAI Nodes Managed"] = f"{nodes_mgmt['CastAI']}%"
    info["Provider Nodes Managed"] = f"{nodes_mgmt['Provider']}%"
    info["3rd Party Nodes Managed"] = f"{nodes_mgmt['3rd Party']}%"
    if provider == "anywhere":
        info["accountID"] = "Unknown"
    elif provider == "eks":
        info["accountID"] = details.get("eks", {}).get("accountId", "Unknown")
    elif provider == "gke":
        info["accountID"] = details.get("gke", {}).get("projectId", "Unknown")
    elif provider == "aks":
        info["accountID"] = details.get("aks", {}).get("nodeResourceGroup", "Unknown")
    else:
        info["accountID"] = "Unknown"
    k8sVersion = details.get("kubernetesVersion", "")
    if provider.lower() == "eks":
        info["Kubernetes version"] = k8sVersion
        info["Extended Support"] = determine_support_status(provider, k8sVersion)
    elif provider.lower() == "gke":
        gkeVersion = ".".join(k8sVersion.split("-")[0].split(".")[:2])
        info["Kubernetes version"] = gkeVersion
        info["Extended Support"] = determine_support_status(provider, gkeVersion)
    elif provider.lower() == "aks":
        parts = k8sVersion.split(".")
        aksVersion = ".".join(parts[:2])
        info["Kubernetes version"] = aksVersion
        info["Extended Support"] = determine_support_status(provider, aksVersion)
    elif provider.lower() == "anywhere":
        av = getFargateVersion(cluster_id, api_key)
        info["Kubernetes version"] = av
        k8sversion=str(av)
        knownAnywhere = getKnownAnywhere(cluster_id, api_key)
        if knownAnywhere == "fargate":
            info["Extended Support"] = determine_support_status("eks", k8sversion)
        else:
            info["Extended Support"] = "Not Apply"
    return info

def fetch_full_cluster_info(api_key, org_dir="."):
    offerings = get_cluster_ids(api_key, org_dir)
    schedule_map = get_all_rebalancing_schedules(api_key)
    cluster_ids = list(offerings.keys())
    all_cluster_info = []
    for cid in cluster_ids:
        details = get_cluster_details(api_key, cid)
        cluster_info = extract_full_cluster_info(cid, details, offerings, api_key, schedule_map, org_dir)
        all_cluster_info.append(cluster_info)
    return all_cluster_info

def fetch_full_cluster_details(api_key, cluster_id, org_dir="."):
    offerings = get_cluster_ids(api_key, org_dir)
    schedule_map = get_all_rebalancing_schedules(api_key)
    details = get_cluster_details(api_key, cluster_id)
    return extract_full_cluster_info(cluster_id, details, offerings, api_key, schedule_map, org_dir)

# --------------------------
# Flask Routes (JSON-only endpoints)
# --------------------------
@app.route("/orgs/edit/<int:org_id>")
@require_permission('read')
def edit_org(org_id):
    org_row = get_org_by_id(org_id)
    if not org_row:
        return jsonify(error="Organization not found"), 404
    org = dict(org_row)
    # Return the organization details for editing as JSON.
    return jsonify(org=org)

@app.route("/org/enable/<int:org_db_id>")
@require_permission('read')
def enable_org_route(org_db_id):
    enable_org(org_db_id)
    return jsonify(message="Organization re-enabled successfully")

@app.route("/")
@require_permission('read')
def index():
    orgs = get_all_orgs()
    return jsonify(orgs=orgs)

@app.route("/orgs", methods=["GET", "POST"])
@require_permission('read')
def manage_orgs():
    if request.method == "POST":
        action = request.form.get("action")
        org_name = request.form.get("org")
        key = request.form.get("key")
        org_identifier = request.form.get("org_id")
        region = request.form.get("region", "US Region")
        if action == "add":
            add_org(org_name, key, org_identifier, region)
            return jsonify(message="Organization added successfully")
        elif action == "update":
            org_db_id = request.form.get("id")
            update_org(org_db_id, org_name, key, org_identifier, region)
            return jsonify(message="Organization updated successfully")
    else:
        conn = get_db_connection()
        orgs = conn.execute("SELECT * FROM organizations").fetchall()
        conn.close()
        orgs_list = [dict(row) for row in orgs]
        edit_id = request.args.get("edit_id")
        edit_org_data = None
        if edit_id:
            for org in orgs_list:
                if str(org["id"]) == str(edit_id):
                    edit_org_data = org
                    break
        return jsonify(orgs=orgs_list, edit_org=edit_org_data)

@app.route("/org/disable/<int:org_db_id>")
@require_permission('read')
def disable_org_route(org_db_id):
    disable_org(org_db_id)
    return jsonify(message="Organization disabled successfully")

@app.route("/org/<int:org_db_id>")
@require_permission('read')
def org_clusters(org_db_id):
    org = get_org_by_id(org_db_id)
    if not org:
        return jsonify(error="Organization not found"), 404
    refresh = request.args.get("refresh", None)
    if not refresh:
        clusters = get_cache(org_db_id, "cluster_list")
    else:
        clusters = None
    if clusters is None:
        clusters = fetch_cluster_list(org["key"])
        set_cache(org_db_id, "cluster_list", clusters)
    return jsonify(org=org, clusters=clusters)

@app.route("/org/<int:org_db_id>/cluster/<cluster_id>")
@require_permission('read')
def cluster_details(org_db_id, cluster_id):
    org = get_org_by_id(org_db_id)
    if not org:
        return jsonify(error="Organization not found"), 404
    details = fetch_full_cluster_details(org["key"], cluster_id)
    return jsonify(details=details)

@app.route("/org/<int:org_db_id>/summary")
@require_permission('read')
def org_summary(org_db_id):
    org = get_org_by_id(org_db_id)
    if not org:
        return jsonify(error="Organization not found"), 404
    refresh = request.args.get("refresh", None)
    if not refresh:
        full_details = get_cache(org_db_id, "full_cluster_details")
    else:
        full_details = None
    if full_details is None:
        full_details = fetch_full_cluster_info(org["key"])
        set_cache(org_db_id, "full_cluster_details", full_details)
    df = pd.DataFrame(full_details)
    total_clusters = len(df)
    prod_count = df[df["Environment"].str.lower() == "production"].shape[0]
    non_prod_count = total_clusters - prod_count
    phase1_count = df[df["Phase 1"].str.lower() == "yes"].shape[0]
    phase2_count = df[df["Phase 2"].str.lower() == "yes"].shape[0]
    woop_count = df[df["WOOP Enabled"].str.lower() == "yes"].shape[0]
    total_cpu = df["CPU Count"].sum()
    def parse_percent(x):
        try:
            return float(str(x).replace("%", ""))
        except:
            return 0.0
    optimized_percents = df["WOOP enabled %"].apply(parse_percent)
    avg_optimized = optimized_percents.mean() if len(optimized_percents) > 0 else 0.0
    optimized_cpus_sum = (df["CPU Count"] * optimized_percents / 100.0).sum()
    summary = {
        "Total Clusters": int(total_clusters),
        "Production Clusters": int(prod_count),
        "Non-production Clusters": int(non_prod_count),
        "# of Phase 1 Clusters": int(phase1_count),
        "# of Phase 2 Clusters": int(phase2_count),
        "Clusters with WOOP Enabled": int(woop_count),
        "Average % of Optimized Workloads": f"{avg_optimized:.2f}%",
        "Total CPUs Connected": int(total_cpu),
        "Total Optimized CPUs": int(round(optimized_cpus_sum, 0))
    }
    return jsonify(org=org, summary=summary)

@app.route("/org/<int:org_db_id>/download_csv")
@require_permission('read')
def download_csv(org_db_id):
    org = get_org_by_id(org_db_id)
    if not org:
        return jsonify(error="Organization not found"), 404
    org_folder = os.path.join("outputs", org["org"].replace(" ", "_"))
    csv_file = os.path.join(org_folder, "full_cluster_details.csv")
    full_details = get_cache(org_db_id, "full_cluster_details")
    if full_details is not None:
        cols = ["ClusterID", "Cluster Name", "Provider", "accountID", "Region", "Phase 1", "Phase 2", "CPU Count",
                "WOOP Enabled", "% OnDemand Nodes", "% Spot Nodes", "Fallback Nodes?", "First Rebalance", "Connected Date",
                "Environment", "Evictor", "Scheduled Rebalance", "WOOP enabled %", "Kubernetes version", "Extended Support",
                "3rd Party", "CastAI Nodes Managed", "Provider Nodes Managed", "3rd Party Nodes Managed"]
        df = pd.DataFrame(full_details)
        df = df.reindex(columns=cols)
        os.makedirs(org_folder, exist_ok=True)
        df.to_csv(csv_file, index=False)
    if not os.path.exists(csv_file):
        return jsonify(error="CSV not found. Please refresh the summary.")
    return send_file(csv_file, as_attachment=True)

def get_csv(org_db_id):
    org = get_org_by_id(org_db_id)
    if not org:
        return jsonify(error="Organization not found"), 404
    org_folder = os.path.join("outputs", org["org"].replace(" ", "_"))
    csv_file = os.path.join(org_folder, "full_cluster_details.csv")
    full_details = get_cache(org_db_id, "full_cluster_details")
    if full_details is not None:
        cols = ["ClusterID", "Cluster Name", "Provider", "accountID", "Region", "Phase 1", "Phase 2", "CPU Count",
                "WOOP Enabled", "% OnDemand Nodes", "% Spot Nodes", "Fallback Nodes?", "First Rebalance", "Connected Date",
                "Environment", "Evictor", "Scheduled Rebalance", "WOOP enabled %", "Kubernetes version", "Extended Support",
                "3rd Party", "CastAI Nodes Managed", "Provider Nodes Managed", "3rd Party Nodes Managed"]
        df = pd.DataFrame(full_details)
        df = df.reindex(columns=cols)
        os.makedirs(org_folder, exist_ok=True)
        df.to_csv(csv_file, index=False)
    if not os.path.exists(csv_file):
        return jsonify(error="CSV not found. Please refresh the summary.")
    #return send_file(csv_file, as_attachment=True),
    return csv_file

#
@app.route("/org/<int:org_db_id>/monthly_savings", methods=["GET"])
@require_permission('read')
def monthly_savings(org_db_id):
    """
    Returns the monthly savings report as JSON.
    Uses a cache per organization to avoid recomputation.
    """
    CACHE_KEY_MS = "monthly_savings_report"

    org = get_org_by_id(org_db_id)
    if not org:
        return jsonify(error="Organization not found"), 404

    # Retrieve details CSV path (used as an input for the monthly savings report generation)
    details_csv = get_csv(org["id"])
    api_key = org["key"]
    org_name = org["org"]
    # File name hints used by the savings report generator (adjust as needed)
    savings_csv_name = f"{org_name}_savings.csv"
    resources_csv_name = f"{org_name}_resources.csv"

    # Check if the monthly savings report is already cached
    cached_report = get_cache(org_db_id, CACHE_KEY_MS)
    if cached_report:
        return jsonify(org=org,
                       monthly_savings_report=cached_report.get("savings"),
                       resource_costs=cached_report.get("resource"))

    # Otherwise, generate the report
    try:
        # Call the report-generation function from monthlySavingsReport.py.
        # It is assumed to return two DataFrames: (savings_df, resource_df)
        savings_df, resource_df = msr.generate_monthly_savings_report(api_key, details_csv, savings_csv_name, resources_csv_name)
        # Convert DataFrames to dictionaries so they can be cached (JSON serializable)
        savings_data = savings_df.to_dict(orient="records")
        resource_data = resource_df.to_dict(orient="records")
        report = {"savings": savings_data, "resource": resource_data}
        # Cache the generated report for this organization.
        set_cache(org_db_id, CACHE_KEY_MS, report)
        return jsonify(org=org,
                       monthly_savings_report=savings_data,
                       resource_costs=resource_data)
    except Exception as e:
        return jsonify(error=f"Failed to generate monthly savings report: {str(e)}"), 500

@app.route("/org/<int:org_db_id>/download_monthly_savings_csv", methods=["GET"])
@require_permission('read')
def download_monthly_savings_csv(org_db_id):
    """
    Either returns the cached zip file for download or starts a background job
    to generate it and returns status information.
    """
    CACHE_KEY_MS = "monthly_savings_report"
    
    org = get_org_by_id(org_db_id)
    if not org:
        return jsonify(error="Organization not found"), 404
    
    # Check if job status is requested
    job_id = request.args.get('job_id')
    if job_id:
        # Return the status of the job
        job_status = get_job_status(int(job_id))
        if not job_status:
            return jsonify(error="Job not found"), 404
        return jsonify(job_status)
    
    org_folder = os.path.join("outputs", org["org"].replace(" ", "_"))
    os.makedirs(org_folder, exist_ok=True)
    org_name = org["org"]
    zip_filename = os.path.join(org_folder, f"{org_name}_monthly_savings_report.zip")
    
    # Check if cached report exists
    cached_report = get_cache(org_db_id, CACHE_KEY_MS)
    
    # Check if we should use the cached version or force refresh
    force_refresh = request.args.get('refresh', 'false').lower() == 'true'
    
    if cached_report and not force_refresh and os.path.exists(zip_filename):
        # Return the cached zip file
        return send_file(zip_filename, as_attachment=True)
    
    # Check if there are already pending jobs for this org
    if check_pending_jobs(org_db_id, "monthly_savings_report"):
        # There's already a job in progress
        return jsonify({
            "status": "processing",
            "message": "A job is already in progress to generate the monthly savings report"
        })
    
    # Queue a new job to generate the report
    job_id = queue_job(org_db_id, "monthly_savings_report")
    
    # Return information about the queued job
    return jsonify({
        "status": "processing",
        "message": "Monthly savings report generation has been queued",
        "jobId": job_id
    })

# Add a new route to check job status
@app.route("/api/job-status/<int:job_id>", methods=["GET"])
@require_permission('read')
def check_job_status(job_id):
    """Get the status of a background job"""
    job_status = get_job_status(job_id)
    if not job_status:
        return jsonify(error="Job not found"), 404
    
    # Prepare a more user-friendly response
    status = job_status['status']
    response = {
        "status": status,
        "jobId": job_id,
        "message": f"Job is {status}"
    }
    
    if status == 'completed':
        org_id = job_status['org_id']
        org = get_org_by_id(org_id)
        if org:
            response["downloadUrl"] = f"/api/download-report/{org_id}"
    elif status == 'error':
        response["error"] = job_status.get('error', 'Unknown error')
        
    return jsonify(response)

# Add a new route to download a completed report
@app.route("/api/download-report/<int:org_id>", methods=["GET"])
@require_permission('read')
def download_report(org_id):
    """Download a completed report"""
    org = get_org_by_id(org_id)
    if not org:
        return jsonify(error="Organization not found"), 404
    
    org_folder = os.path.join("outputs", org["org"].replace(" ", "_"))
    zip_filename = os.path.join(org_folder, f"{org['org']}_monthly_savings_report.zip")
    
    if not os.path.exists(zip_filename):
        return jsonify(error="Report file not found"), 404
    
    return send_file(zip_filename, as_attachment=True)

# Add a new route to trigger manual cache refresh (admin only)
@app.route("/admin/refresh-cache/<int:org_id>", methods=["POST"])
@require_permission('admin')
def admin_refresh_cache(org_id):
    """Admin endpoint to trigger a cache refresh for an organization"""
    org = get_org_by_id(org_id)
    if not org:
        return jsonify(error="Organization not found"), 404
    
    job_type = request.args.get('type', 'monthly_savings_report')
    
    # Queue a job
    job_id = queue_job(org_id, job_type)
    
    return jsonify({
        "message": f"Cache refresh for {job_type} queued successfully",
        "jobId": job_id
    })

# Add a new route to refresh all caches (admin only)
@app.route("/admin/refresh-all-caches", methods=["POST"])
@require_permission('admin')
def admin_refresh_all_caches():
    """Admin endpoint to trigger cache refresh for all organizations"""
    job_type = request.args.get('type', 'monthly_savings_report')
    
    # Get all organizations
    orgs = get_all_orgs()
    job_ids = []
    
    for org in orgs:
        if org.get('enabled', 1) == 1:  # Only refresh for enabled orgs
            job_id = queue_job(org['id'], job_type)
            job_ids.append({"org_id": org['id'], "job_id": job_id})
    
    return jsonify({
        "message": f"Cache refresh for {job_type} queued for all organizations",
        "jobs": job_ids
    })

@app.route("/public/manage-keys", methods=["GET", "POST"])
def manage_keys():
    if request.method == "POST":
        action = request.form.get("action")
        role = request.form.get("role", "read")
        user_id = request.form.get("user_id")

        if action == "generate":
            key = security_manager.generate_key(role, user_id)
            return jsonify({"api_key": key, "role": role})
        elif action == "revoke":
            key = request.form.get("key")
            success = security_manager.revoke_key(key)
            return jsonify({"success": success})

    # For GET requests, return the key management form or listing
    keys = security_manager.list_keys(include_hash=False)
    return jsonify({"keys": keys})

if __name__ == "__main__":
    # app.run(debug=True, port=7667)
    http_server = WSGIServer(('', 7667), app)
    http_server.serve_forever()
