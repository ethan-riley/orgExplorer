#!/usr/bin/env python3
import os
import sys
import subprocess
import requests
import pandas as pd
import datetime
import calendar
import json

# -------------------------
# Helper Functions for Time Ranges
# -------------------------
def get_month_range(year, month):
    """Return start_time and end_time strings for the given month in required format."""
    start = datetime.datetime(year, month, 1)
    last_day = calendar.monthrange(year, month)[1]
    end = datetime.datetime(year, month, last_day, 23, 59, 59, 999999)
    start_str = start.strftime("%Y-%m-%dT%H:%M:%S.000000000Z")
    end_str = end.strftime("%Y-%m-%dT%H:%M:%S.000000000Z")
    return start_str, end_str

# -------------------------
# Efficiency Endpoint Functions
# -------------------------
def get_efficiency_summary(api_key, cluster_id, start_time, end_time):
    url = f"https://api.cast.ai/v1/cost-reports/clusters/{cluster_id}/efficiency?startTime={start_time}&endTime={end_time}"
    headers = {"accept": "application/json", "X-API-Key": api_key}
    resp = requests.get(url, headers=headers)
    try:
        data = resp.json()
    except Exception as e:
        print(f"Error decoding efficiency data for {cluster_id}: {e}", flush=True)
        data = {}
    # if save_json == "on":
    #     file_path = os.path.join(org_dir, "json", f"efficiency_{cluster_id}_{start_time[:7]}.json")
    #     with open(file_path, "w") as f:
    #         json.dump(data, f, indent=4)
    summary = data.get("summary", {})
    try:
        costPerCpu = float(summary.get("costPerCpuProvisioned", 0))
    except:
        costPerCpu = 0.0
    try:
        costPerRam = float(summary.get("costPerRamGibProvisioned", 0))
    except:
        costPerRam = 0.0
    try:
        costPerStorage = float(summary.get("costPerStorageGibProvisioned", 0))
    except:
        costPerStorage = 0.0
    return {"costPerCpu": costPerCpu, "costPerRam": costPerRam, "costPerStorage": costPerStorage}

def get_preonboard_efficiency(api_key, cluster_id, connected_date):
    year = connected_date.year
    month = connected_date.month
    start_str, end_str = get_month_range(year, month)
    days = calendar.monthrange(year, month)[1]
    eff = get_efficiency_summary(api_key, cluster_id, start_str, end_str)
    baseline_cpu = eff["costPerCpu"] * 24 * days
    baseline_ram = eff["costPerRam"] * 24 * days
    baseline_storage = eff["costPerStorage"] * 24 * days
    return {"baseline_cpu": baseline_cpu, "baseline_ram": baseline_ram, "baseline_storage": baseline_storage}

def get_current_efficiency(api_key, cluster_id, start_str, end_str):
    year = int(start_str[:4])
    month = int(start_str[5:7])
    days = calendar.monthrange(year, month)[1]
    eff = get_efficiency_summary(api_key, cluster_id, start_str, end_str)
    current_cpu = eff["costPerCpu"] * 24 * days
    current_ram = eff["costPerRam"] * 24 * days
    current_storage = eff["costPerStorage"] * 24 * days
    return {"current_cpu": current_cpu, "current_ram": current_ram, "current_storage": current_storage}

# -------------------------
# Resource Usage Aggregation
# -------------------------
def get_monthly_resource_usage(api_key, cluster_id, start_time, end_time):
    url = f"https://api.cast.ai/v1/cost-reports/clusters/{cluster_id}/resource-usage?startTime={start_time}&endTime={end_time}"
    headers = {"accept": "application/json", "X-API-Key": api_key}
    resp = requests.get(url, headers=headers)
    try:
        data = resp.json()
    except Exception as e:
        print(f"Error decoding resource usage for {cluster_id}: {e}", flush=True)
        data = {}
    # if save_json == "on":
    #     file_path = os.path.join(org_dir, "json", f"resource_usage_{cluster_id}_{start_time[:7]}.json")
    #     with open(file_path, "w") as f:
    #         json.dump(data, f, indent=4)
    sums = {
        "cpu_provisioned": 0.0,
        "cpu_requested": 0.0,
        "cpu_used": 0.0,
        "ram_provisioned": 0.0,
        "ram_requested": 0.0,
        "ram_used": 0.0,
        "storage_provisioned": 0.0,
        "storage_requested": 0.0
    }
    for item in data.get("items", []):
        try:
            sums["cpu_provisioned"] += float(item.get("cpuProvisioned", 0))
        except:
            pass
        try:
            sums["cpu_requested"] += float(item.get("cpuRequested", 0))
        except:
            pass
        try:
            sums["cpu_used"] += float(item.get("cpuUsed", 0))
        except:
            pass
        try:
            sums["ram_provisioned"] += float(item.get("ramProvisioned", 0))
        except:
            pass
        try:
            sums["ram_requested"] += float(item.get("ramRequested", 0))
        except:
            pass
        try:
            sums["ram_used"] += float(item.get("ramUsed", 0))
        except:
            pass
        try:
            sums["storage_provisioned"] += float(item.get("storageProvisionedGib", item.get("storageProvisioned", 0)))
        except:
            pass
        try:
            sums["storage_requested"] += float(item.get("requestedStorageGib", item.get("storageRequested", 0)))
        except:
            pass
    return sums

# -------------------------
# Main Report Generation Function
# -------------------------
def generate_monthly_savings_report(api_key, input_csv, savings_output_csv, resource_cost_output_csv):
    #print(input_csv)
    df = pd.read_csv(input_csv)
    if "Connected Date" not in df.columns:
        print("Connected Date column not found in CSV.", flush=True)
        sys.exit(1)
    df.sort_values(by="Connected Date", inplace=True)
    
    savings_rows = []
    resource_cost_rows = []
    
    today = datetime.date.today()
    last_month = today.month - 1
    last_month_year = today.year
    if last_month == 0:
        last_month_year -= 1
        last_month = 12
    last_completed = datetime.date(last_month_year, last_month, 1)
    
    for idx, row in df.iterrows():
        cluster_id = row["ClusterID"]
        cluster_name = row["Cluster Name"]
        connected_date_str = row.get("Connected Date", "")
        if not connected_date_str or pd.isna(connected_date_str):
            print(f"Skipping cluster {cluster_id} ({cluster_name}) due to missing Connected Date.", flush=True)
            continue
        try:
            connected_date = datetime.datetime.strptime(connected_date_str, "%Y-%m-%d").date()
            print(f"Processing {cluster_id} - {cluster_name}")
        except Exception as e:
            print(f"Error parsing Connected Date '{connected_date_str}' for {cluster_id}: {e}", flush=True)
            continue
        
        baseline = get_preonboard_efficiency(api_key, cluster_id, connected_date)
        baseline_cpu = baseline["baseline_cpu"]
        baseline_ram = baseline["baseline_ram"]
        baseline_storage = baseline["baseline_storage"]
        
        current_date = datetime.date(connected_date.year, connected_date.month, 1)
        while current_date <= last_completed:
            year = current_date.year
            month = current_date.month
            month_str = f"{year}-{month:02d}"
            start_str, end_str = get_month_range(year, month)
            days_in_month = calendar.monthrange(year, month)[1]
            
            current_eff = get_current_efficiency(api_key, cluster_id, start_str, end_str)
            current_cpu = current_eff["current_cpu"]
            current_ram = current_eff["current_ram"]
            current_storage = current_eff["current_storage"]
            
            usage = get_monthly_resource_usage(api_key, cluster_id, start_str, end_str)
            try:
                cpu_prov = float(usage.get("cpu_provisioned", 0))
            except:
                cpu_prov = 0.0
            try:
                cpu_req = float(usage.get("cpu_requested", 0))
            except:
                cpu_req = 0.0
            try:
                cpu_used = float(usage.get("cpu_used", 0))
            except:
                cpu_used = 0.0
            try:
                ram_prov = float(usage.get("ram_provisioned", 0))
            except:
                ram_prov = 0.0
            try:
                ram_req = float(usage.get("ram_requested", 0))
            except:
                ram_req = 0.0
            try:
                ram_used = float(usage.get("ram_used", 0))
            except:
                ram_used = 0.0
            try:
                storage_prov = float(usage.get("storage_provisioned", 0))
            except:
                storage_prov = 0.0
            try:
                storage_req = float(usage.get("storage_requested", 0))
            except:
                storage_req = 0.0
            
            avg_cpu_req = cpu_req / days_in_month if days_in_month > 0 else 0.0
            avg_ram_req = ram_req / days_in_month if days_in_month > 0 else 0.0
            avg_storage_req = storage_req / days_in_month if days_in_month > 0 else 0.0
            
            savings_cpu = avg_cpu_req * (baseline_cpu - current_cpu)
            savings_ram = avg_ram_req * (baseline_ram - current_ram)
            savings_storage = avg_storage_req * (baseline_storage - current_storage)
            total_savings = savings_cpu + savings_ram + savings_storage
            
            savings_rows.append({
                "clusterid": cluster_id,
                "clustername": cluster_name,
                "connected_date": connected_date_str,
                "month": month_str,
                "cpu_provisioned": f"{cpu_prov:.2f}",
                "cpu_requested": f"{cpu_req:.2f}",
                "cpu_used": f"{cpu_used:.2f}",
                "cpu_price": f"{current_cpu:.2f}",
                "ram_provisioned": f"{ram_prov:.2f}",
                "ram_requested": f"{ram_req:.2f}",
                "ram_used": f"{ram_used:.2f}",
                "ram_price": f"{current_ram:.2f}",
                "storage_provisioned": f"{storage_prov:.2f}",
                "storage_requested": f"{storage_req:.2f}",
                "avg_cpu_provisioned": f"{(cpu_prov/days_in_month):.2f}",
                "avg_cpu_requested": f"{(cpu_req/days_in_month):.2f}",
                "avg_ram_provisioned": f"{(ram_prov/days_in_month):.2f}",
                "avg_ram_requested": f"{(ram_req/days_in_month):.2f}",
                "avg_storage_provisioned": f"{(storage_prov/days_in_month):.2f}",
                "avg_storage_requested": f"{(storage_req/days_in_month):.2f}",
                "savings_per_month_cpu": f"{savings_cpu:.2f}",
                "savings_per_month_ram": f"{savings_ram:.2f}",
                "savings_per_month_storage": f"{savings_storage:.2f}",
                "total_savings_per_month": f"{total_savings:.2f}"
            })
            
            for resource, eff_key in [
                ("CPU", "costPerCpu"),
                ("RAM", "costPerRam"),
                ("Storage", "costPerStorage")
            ]:
                try:
                    cost_val = float(get_efficiency_summary(api_key, cluster_id, start_str, end_str).get(eff_key, 0))
                except:
                    cost_val = 0.0
                avg_hourly = cost_val
                avg_daily = avg_hourly * 24
                avg_monthly = avg_daily * days_in_month
                resource_cost_rows.append({
                    "cluster_id": cluster_id,
                    "cluster_name": cluster_name,
                    "connected_date": connected_date_str,
                    "month": month_str,
                    "resource": resource,
                    "avg_hourly_cost": f"{avg_hourly:.4f}",
                    "avg_daily_cost": f"{avg_daily:.4f}",
                    "avg_monthly_cost": f"{avg_monthly:.2f}"
                })
            
            if month == 12:
                current_date = datetime.date(year + 1, 1, 1)
            else:
                current_date = datetime.date(year, month + 1, 1)
    
    savings_df = pd.DataFrame(savings_rows)
    #savings_df.to_csv(savings_output_csv, index=False)
    print(f"Monthly savings report saved to {savings_output_csv}")
    
    resource_df = pd.DataFrame(resource_cost_rows)
    #resource_df.to_csv(resource_cost_output_csv, index=False)
    print(f"Resource costs report saved to {resource_cost_output_csv}")
    return savings_df, resource_df

def process_org(selected_org, org_row):
    api_key = org_row["key"]
    org_dir_local = os.path.join("outputs", selected_org.replace(" ", "_"))
    global org_dir
    org_dir = org_dir_local
    csv_dir = os.path.join(org_dir, "csv")
    details_csv = os.path.join(csv_dir, "cluster_details.csv")
    if not os.path.exists(org_dir) or not os.path.exists(details_csv):
        print(f"Organization directory or cluster_details.csv not found for {selected_org}. Running orgClusterDetails.py...", flush=True)
        try:
            if save_json == "on":
                subprocess.run(["python", "orgClusterDetails.py", selected_org, "on"], check=True)
            else:
                subprocess.run(["python", "orgClusterDetails.py", selected_org], check=True)
        except subprocess.CalledProcessError as e:
            print(f"Error running orgClusterDetails.py for {selected_org}: {e}", flush=True)
            sys.exit(1)
        if not os.path.exists(details_csv):
            print("Failed to generate cluster_details.csv.", flush=True)
            sys.exit(1)
    else:
        print(f"Found cluster_details.csv for {selected_org}.", flush=True)
    os.makedirs(os.path.join(org_dir, "json"), exist_ok=True)
    savings_output_csv = os.path.join(csv_dir, "monthly_savings_report.csv")
    resource_cost_output_csv = os.path.join(csv_dir, "resource_costs_report.csv")
    generate_monthly_savings_report(api_key, details_csv, savings_output_csv, resource_cost_output_csv)

def main():
    global save_json
    if len(sys.argv) < 2:
        print("Usage: python orgClusterDetails.py <Organization | all> <on> (If you want to save resulting jsons)", flush=True)
        sys.exit(1)
    elif len(sys.argv) == 2:
        save_json="off"
    elif len(sys.argv) == 3:
        save_json = sys.argv[2].strip()

    selected_arg = sys.argv[1].strip()
    try:
        orgs_df = pd.read_csv("orgs.csv")
    except Exception as e:
        print(f"Error loading orgs.csv: {e}", flush=True)
        sys.exit(1)
    if selected_arg.lower() == "all":
        for idx, org_row in orgs_df.iterrows():
            selected_org = org_row["org"]
            print(f"Processing organization: {selected_org}", flush=True)
            process_org(selected_org, org_row)
    else:
        try:
            org_row = orgs_df[orgs_df["org"] == selected_arg].iloc[0]
        except Exception as e:
            print(f"Organization '{selected_arg}' not found: {e}", flush=True)
            sys.exit(1)
        process_org(selected_arg, org_row)

if __name__ == "__main__":
    main()