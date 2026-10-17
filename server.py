from fastapi import FastAPI, Request, Depends, HTTPException, status
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import uvicorn
import agent
import uuid
import json
import secrets
from tools import execute_refund

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
security = HTTPBasic()

# In-memory storage
# {run_id: {"status": "pending/approved/denied", "order": ..., ...}}
pending_refunds = {}

# Mock Admin credentials
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "password"

def get_current_username(credentials: HTTPBasicCredentials = Depends(security)):
    correct_username = secrets.compare_digest(credentials.username, ADMIN_USERNAME)
    correct_password = secrets.compare_digest(credentials.password, ADMIN_PASSWORD)
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

@app.get("/")
async def read_index():
    return FileResponse("static/index.html")

@app.get("/admin", response_class=HTMLResponse)
async def admin_page(username: str = Depends(get_current_username)):
    return FileResponse("static/admin.html")

def send_email(email: str, subject: str, body: str):
    print(f"--- MOCK EMAIL TO {email} ---")
    print(f"Subject: {subject}")
    print(f"Body: {body}")
    print("----------------------------")

# Captures agent output
captured_customer_output = []

def customer_output_handler(msg):
    captured_customer_output.append(msg)

def internal_output_handler(msg):
    # For now, just ignore internal logs or print to server console
    print(f"[Internal]: {msg}")

agent.set_output_handlers(customer_output_handler, internal_output_handler)

@app.post("/chat")
async def chat(request: Request):
    data = await request.json()
    message = data.get("message")
    
    captured_customer_output.clear()
    
    # Run agent
    try:
        agent.run(message)
    except agent.NeedsApprovalException as e:
        run_id = str(uuid.uuid4())[:8]
        pending_refunds[run_id] = {
            "run_id": run_id,
            "order_id": e.order['order_id'],
            "item": e.order['item'],
            "amount_usd": e.order['amount_usd'],
            "order": e.order,
            "eligible": e.eligible,
            "justification": e.justification,
            "status": "pending",
            "reason": None
        }
        print(f"[DEBUG] Stashed refund {run_id}. Current pending_refunds: {pending_refunds}")
        return {
            "response": "I have received your request for a refund on order " + e.order['order_id'] + ". Our support team is currently reviewing your case, and we will get back to you shortly.", 
            "requires_approval": True,
            "run_id": run_id
        }
        
    return {"response": "\n".join(captured_customer_output), "requires_approval": False}

@app.get("/status/{run_id}")
async def get_status(run_id: str):
    return pending_refunds.get(run_id, {"status": "not_found"})

@app.get("/admin/refunds")
async def get_admin_refunds(username: str = Depends(get_current_username)):
    print(f"[DEBUG] Full pending_refunds: {pending_refunds}")
    refunds = [r for r in pending_refunds.values() if r["status"] == "pending"]
    print(f"[DEBUG] Found {len(refunds)} pending refunds")
    return refunds

@app.post("/admin/refunds/{run_id}/approve")
async def approve_refund(run_id: str, request: Request, username: str = Depends(get_current_username)):
    data = await request.json()
    reason = data.get("reason", "Approved by administrator.")
    
    if run_id in pending_refunds:
        refund = pending_refunds[run_id]
        refund["status"] = "approved"
        refund["reason"] = reason
        
        # Execute refund
        result = execute_refund(refund['order'])
        send_email(refund['order']['customer_email'], "Refund Approved", f"Your refund for order {refund['order_id']} has been approved. Reason: {reason}")
        
        return {"status": "approved", "result": result}
    return {"status": "error", "message": "Refund not found"}

@app.post("/admin/refunds/{run_id}/deny")
async def deny_refund(run_id: str, request: Request, username: str = Depends(get_current_username)):
    data = await request.json()
    reason = data.get("reason", "Denied by administrator.")
    
    if run_id in pending_refunds:
        refund = pending_refunds[run_id]
        refund["status"] = "denied"
        refund["reason"] = reason
        
        send_email(refund['order']['customer_email'], "Refund Denied", f"Your refund for order {refund['order_id']} has been denied. Reason: {reason}")
        
        return {"status": "denied"}
    return {"status": "error", "message": "Refund not found"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
