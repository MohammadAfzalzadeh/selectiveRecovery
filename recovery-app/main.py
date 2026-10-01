from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from kubernetes import client, config
import requests
import psycopg2
import time
import os
import json


app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

LOKI_URL = os.getenv("LOKI_URL", "http://loki.monitoring.svc.cluster.local:3100")
PITR_DB_HOST = os.getenv("PITR_DB_HOST", "payment-db-pitr-rw")
PITR_DB_USER = os.getenv("PITR_DB_USER", "app")
PITR_DB_PASSWORD = os.getenv("PITR_DB_PASSWORD", "YOUR_PASSWORD_HERE")
PITR_DB_NAME = os.getenv("PITR_DB_NAME", "app")
PITR_DB_PORT = os.getenv("PITR_DB_PORT", "5432")

PITR_DB_DSN = f"dbname='{PITR_DB_NAME}' user='{PITR_DB_USER}' host='{PITR_DB_HOST}' password='{PITR_DB_PASSWORD}' port='{PITR_DB_PORT}'"

class RecoveryRequest(BaseModel):
    base_time: int 
    bad_queries: list[str]

try:
    config.load_incluster_config()
    k8s_custom_api = client.CustomObjectsApi()
except:
    print("Warning: Not running inside K8s cluster or lack permissions.")


def extract_sql(log_text):
    try:
        log_json = json.loads(log_text)
        
        message = log_json.get("record", {}).get("message", "")
        if not message:
            message = log_json.get("message", log_text)
            
        if message.startswith("statement: "):
            return message[len("statement: "):].strip()
            
        return message.strip()
        
    except json.JSONDecodeError:
        if "statement: " in log_text:
            return log_text.split("statement: ")[-1].strip()
        return log_text.strip()


@app.get("/", response_class=HTMLResponse)
async def read_index():
    with open("static/index.html") as f:
        return f.read()

@app.get("/api/logs")
def get_logs(start: int, end: int):
    query = '{container="postgres"} |~ "statement: (INSERT|UPDATE|DELETE)"'
    params = {
        'query': query, 
        'start': str(start),  
        'end': str(end), 
        'limit': 1000, 
        'direction': 'forward'
    }
    
    loki_endpoint = f"{LOKI_URL}/loki/api/v1/query_range"
    print(f"🔍 Querying Loki: {loki_endpoint}")
    print(f"📦 Params: {params}")
    
    try:
        resp = requests.get(loki_endpoint, params=params, timeout=10)
        
        print(f"✅ Loki Status Code: {resp.status_code}")
        print(f"📝 Loki Response Body: {resp.text[:1000]}") 
        
        resp.raise_for_status()
        
        json_resp = resp.json()
        data = json_resp.get('data', {}).get('result', [])
        
        logs = []
        if data:
            for val in data[0].get('values', []):
                timestamp = val[0]
                log_text = val[1]
                
                # استفاده از تابع استخراج کوئری
                statement = extract_sql(log_text)
                
                logs.append({"timestamp": timestamp, "query": statement})
        return logs
        
    except requests.exceptions.RequestException as e:
        print(f"❌ Request to Loki failed: {e}")
        return {
            "error": "Failed to fetch logs from Loki", 
            "details": resp.text if 'resp' in locals() else str(e)
        }
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return {"error": "Unexpected error processing logs", "details": str(e)}

@app.post("/api/recover")
def execute_recovery(req: RecoveryRequest):
    conn = None
    try:
        print(f"Connecting to PITR database...")
        conn = psycopg2.connect(PITR_DB_DSN)
        cursor = conn.cursor()
        
        cursor.execute("SELECT 1")
        print("✅ Database connection successful")
        
        current_time_ns = req.base_time
        target_time_ns = int(time.time() * 1e9)
        
        print("Fetching logs for replay...")
        params = {
            'query': '{container="postgres"} |~ "statement: (INSERT|UPDATE|DELETE)"',
            'start': current_time_ns,
            'end': target_time_ns,
            'limit': 5000,
            'direction': 'forward'
        }
        
        resp = requests.get(f"{LOKI_URL}/loki/api/v1/query_range", params=params)
        log_data = resp.json().get('data', {}).get('result', [])
        
        applied_count = 0
        failed_count = 0
        
        if log_data:
            for val in log_data[0].get('values', []):
                q_text = extract_sql(val[1])  
                if q_text not in req.bad_queries:
                    try:
                        cursor.execute(q_text)
                        applied_count += 1
                    except psycopg2.errors.InsufficientPrivilege as e:
                        print(f"⚠️ Permission denied: {q_text[:100]}...")
                        failed_count += 1
                        continue
                    except Exception as e:
                        print(f" Error applying query: {e}")
                        failed_count += 1
                        conn.rollback()
                        continue
            
            conn.commit()
        
        # K8s operations
        try:
            pooler_patch = {"spec": {"cluster": {"name": "payment-db-pitr"}}}
            k8s_custom_api.patch_namespaced_custom_object(
                group="postgresql.cnpg.io",
                version="v1",
                namespace="database", 
                plural="poolers",
                name="payment-pooler",
                body=pooler_patch
            )
            print("✅ Pooler switched to PITR cluster")
            
            k8s_custom_api.delete_namespaced_custom_object(
                group="postgresql.cnpg.io",
                version="v1",
                namespace="database",
                plural="clusters",
                name="payment-db"
            )
            print("✅ Old cluster deleted")
            
        except Exception as k8s_err:
            print(f" K8s operations failed: {k8s_err}")
            return {
                "status": "partial_success", 
                "message": f"Recovery applied {applied_count} queries, but K8s operations failed",
                "details": str(k8s_err),
                "applied_queries": applied_count,
                "failed_queries": failed_count
            }
        
        return {
            "status": "success", 
            "message": f"Recovery complete. Applied {applied_count} healthy queries. Switched traffic to PITR.",
            "applied_queries": applied_count,
            "failed_queries": failed_count
        }
        
    except psycopg2.OperationalError as e:
        print(f"❌ Database connection failed: {e}")
        return {"status": "error", "message": "Database connection failed", "details": str(e)}
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        if conn:
            conn.close()