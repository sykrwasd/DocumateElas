import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv
from openai import OpenAI
from langgraph.graph import StateGraph, END
from invoice_prompt import FEEDBACK_ROLE_PROMPT, VALIDATION_ROLE_PROMPT,EXTRACTION_ROLE_PROMPT 
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.runnables.graph_mermaid import draw_mermaid
import json
import uuid
from typing import Dict, Optional, TypedDict
from datetime import datetime
from typing_extensions import Annotated
from operator import add


# Load environment variables
load_dotenv()

# Initialize OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# In-memory session storage
conversation_sessions: Dict[str, dict] = {}

# Define FastAPI app
app = FastAPI(title="Invoice AI API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request model
class InvoiceRequest(BaseModel):
    user_message: str  # user input
    session_id: Optional[str] = None  # Optional session ID for conversation continuity

# Response model
class InvoiceResponse(BaseModel):
    extracted: dict
    validated: dict
    status: str  # "complete" or "incomplete"
    message: str  # User-facing message
    session_id: str  # Return session ID for client to use in next request

# Define state schema for LangGraph
class InvoiceState(TypedDict):
    user_input: str
    session_id: Optional[str]
    extracted: dict
    validated: dict
    came_from_feedback: Optional[bool]
    needs_clarification: Optional[bool]
    clarification_message: Optional[str]

def extraction_node(state):
    user_message = state["user_input"]
    session_id = state.get("session_id")
    
    print(f"\n{'='*60}")
    print(f"EXTRACTION NODE")
    print(f"{'='*60}")
    print(f"User message: {user_message}")
    print(f"Session ID: {session_id}")

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": EXTRACTION_ROLE_PROMPT},
            {"role": "user", "content": user_message}
        ]
    )

    raw = response.choices[0].message.content
    print(f"Raw extraction response: {raw}")

    # Parse JSON safely
    try:
        extracted = json.loads(raw)
        print(f"Parsed extracted data: {json.dumps(extracted, indent=2)}")
    except Exception as e:
        print(f"ERROR parsing JSON: {e}")
        extracted = {"error": "Model did not return valid JSON", "raw": raw}

    return {"extracted": extracted, "session_id": session_id}


def validation_node(state):
    extracted = state["extracted"]
    session_id = state.get("session_id")
    
    print(f"\n{'='*60}")
    print(f"VALIDATION NODE")
    print(f"{'='*60}")
    print(f"Extracted data to validate: {json.dumps(extracted, indent=2)}")

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": VALIDATION_ROLE_PROMPT},
            {"role": "user", "content": json.dumps(extracted)}
        ]
    )

    raw = response.choices[0].message.content
    print(f"Raw validation response: {raw}")

    try:
        validated = json.loads(raw)
        # Ensure the validated dict has the expected fields
        if "missing_fields" not in validated:
            validated["missing_fields"] = []
        print(f"Parsed validation result: {json.dumps(validated, indent=2)}")
    except Exception as e:
        print(f"ERROR parsing validation JSON: {e}")
        validated = {
            "message": raw,
            "status": "incomplete",
            "missing_fields": []
        }

    # IMPORTANT: Return both extracted and validated to preserve extracted in state
    return {"validated": validated, "extracted": extracted, "session_id": session_id}

def feedback_node(state):
    """Apply user feedback to modify existing extracted data"""
    extracted = state.get("extracted", {})
    user_message = state["user_input"]
    session_id = state.get("session_id")
    
    print(f"\n{'='*60}")
    print(f"FEEDBACK NODE")
    print(f"{'='*60}")
    print(f"User feedback: {user_message}")
    print(f"Current extracted data: {json.dumps(extracted, indent=2)}")
    
    # Get existing data from session
    if session_id and session_id in conversation_sessions:
        existing_data = conversation_sessions[session_id].get("extracted", {})
    else:
        existing_data = extracted
    
    # Provide both the current data and the user's feedback
    feedback_prompt = f"""
Current invoice data:
{json.dumps(existing_data, indent=2)}

User's feedback/modification request:
{user_message}

Apply the user's feedback to update the invoice data accordingly.
"""
    
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": FEEDBACK_ROLE_PROMPT},
            {"role": "user", "content": feedback_prompt}
        ]
    )

    raw = response.choices[0].message.content
    print(f"Raw feedback response: {raw}")
    
    try:
        updated = json.loads(raw)
        
        # Check if the model is asking for clarification
        if updated.get("status") == "ASK":
            print(f"Model asking for clarification: {updated.get('message')}")
            return {"extracted": existing_data, "session_id": session_id, "needs_clarification": True, "clarification_message": updated.get("message")}
        
        print(f"Updated extracted data: {json.dumps(updated, indent=2)}")
        # Mark that this came from feedback so merge knows to use it as-is
        return {"extracted": updated, "session_id": session_id, "came_from_feedback": True}
    except Exception as e:
        print(f"ERROR parsing feedback JSON: {e}")
        # If parsing fails, return original data unchanged
        return {"extracted": existing_data, "session_id": session_id}

def deep_merge(existing: dict, new: dict) -> dict:
    """Deep merge two dictionaries, preferring non-empty values from new"""
    result = existing.copy()
    
    for key, value in new.items():
        if isinstance(value, dict) and key in result and isinstance(result[key], dict):
            result[key] = deep_merge(result[key], value)
        elif isinstance(value, list) and value:  # Only update if list is not empty
            result[key] = value
        elif isinstance(value, str) and value:  # Only update if string is not empty
            result[key] = value
        elif isinstance(value, (int, float)) and value != 0:  # Only update if number is not zero
            result[key] = value
        elif value and not isinstance(value, (str, list, int, float, dict)):  # Other non-empty values
            result[key] = value
    
    return result


def merge_node(state):
    """Merge newly extracted data with existing session data"""
    session_id = state.get("session_id")
    new_data = state.get("extracted", {})
    came_from_feedback = state.get("came_from_feedback", False)
    
    print(f"\n{'='*60}")
    print(f"MERGE NODE")
    print(f"{'='*60}")
    print(f"Session ID: {session_id}")
    print(f"Came from feedback: {came_from_feedback}")
    print(f"Session exists in storage: {session_id in conversation_sessions if session_id else False}")
    print(f"New data from extraction/feedback: {json.dumps(new_data, indent=2)}")
    
    # If coming from feedback, the data is already merged/updated, just use it
    if came_from_feedback:
        print(f"Using feedback-updated data as-is")
        return {"extracted": new_data, "session_id": session_id}
    
    # Get existing data from session storage, not from state
    if session_id and session_id in conversation_sessions:
        existing_data = conversation_sessions[session_id].get("extracted", {})
        print(f"Existing data from session: {json.dumps(existing_data, indent=2)}")
        merged = deep_merge(existing_data, new_data)
        print(f"Merged result: {json.dumps(merged, indent=2)}")
    else:
        print(f"No existing session data - using new data as-is")
        merged = new_data
    
    return {"extracted": merged, "session_id": session_id}

    
    

def route_entry(state):
    """Determine whether to use extraction or feedback based on session state"""
    session_id = state.get("session_id")
    
    # Check if this session has existing data
    if session_id and session_id in conversation_sessions:
        existing_data = conversation_sessions[session_id].get("extracted", {})
        # If there's meaningful existing data, use feedback node
        if existing_data and any(existing_data.values()):
            print(f"Session {session_id} has existing data - routing to FEEDBACK")
            return "feedback"
    
    print(f"New session or no existing data - routing to EXTRACTION")
    return "extract"

def should_continue(state):
    """Determine next step based on validation status"""
    validated = state.get("validated", {})
    status = validated.get("status", "incomplete")
    
    if status == "complete":
        return "end"
    else:
        return "end"  # For now, we end regardless, but return the status to the user


def router_node(state):
    """Router node that just passes through state - routing happens via conditional edges"""
    return state

def create_graph():
    workflow = StateGraph(InvoiceState)

    # Add all nodes
    workflow.add_node("router", router_node)
    workflow.add_node("extract", extraction_node)
    workflow.add_node("feedback", feedback_node)
    workflow.add_node("merge", merge_node)
    workflow.add_node("validate", validation_node)

    # Set router as entry point
    workflow.set_entry_point("router")
    
    # Add conditional routing from router to extract or feedback
    workflow.add_conditional_edges(
        "router",
        route_entry,
        {
            "extract": "extract",
            "feedback": "feedback"
        }
    )
    
    # Both extract and feedback go to merge
    workflow.add_edge("extract", "merge")
    workflow.add_edge("feedback", "merge")
    workflow.add_edge("merge", "validate")
    
    # Add conditional edge from validate
    workflow.add_conditional_edges(
        "validate",
        should_continue,
        {
            "end": END,
        }
    )

    app = workflow.compile()
    print(app.get_graph().draw_mermaid())
    return app

graph_app = create_graph()




@app.post("/generate_json", response_model=InvoiceResponse)
def generate_invoice(request: InvoiceRequest):
    if not request.user_message:
        raise HTTPException(status_code=400, detail="Input text is required")
    
    # Generate or use existing session ID
    session_id = request.session_id or str(uuid.uuid4())
    
    initial_state = {
        "user_input": request.user_message,
        "session_id": session_id,
        "validated": {},
    }
    
    print(f"Session ID: {session_id}")
    print(f"Initial state: {initial_state}")
    
    result = graph_app.invoke(initial_state)
    
    print(f"\n{'='*60}")
    print(f"FINAL RESULT")
    print(f"{'='*60}")
    print(f"Result from graph: {json.dumps(result, indent=2, default=str)}")
    
    # Save session state
    conversation_sessions[session_id] = {
        "extracted": result.get("extracted", {}),
        "last_updated": datetime.now()
    }
    
    validated = result.get("validated", {})
    status = validated.get("status", "incomplete")
    message = validated.get("message", "Processing complete.")
    
    response_data = {
        "extracted": result.get("extracted", {}),
        "validated": validated,
        "status": status,
        "message": message,
        "session_id": session_id
    }
    
    print(f"Response to client: {json.dumps(response_data, indent=2, default=str)}")
    print(f"{'='*60}\n")
    
    return response_data

    
