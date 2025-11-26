import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv
from openai import OpenAI
from langgraph.graph import StateGraph, END
from invoice_prompt import INVOICE_ROLE_PROMPT,SUMMARY_ROLE_PROMPT, FEEDBACK_ROLE_PROMPT, VALIDATION_ROLE_PROMPT, CONFIRMATION_ROLE_PROMPT
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.runnables.graph_mermaid import draw_mermaid
import json
from typing import Optional


# Load environment variables
load_dotenv()

# Initialize OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

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
    user_message: str #user input

# Response model
class InvoiceResponse(BaseModel):
    invoice_json: Optional[str] = None
    summary: Optional[str] = None
    confirmation: Optional[dict] = None  # include confirmation

def invoice_node(state):
    user_input = state.get("user_input", "")
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": INVOICE_ROLE_PROMPT},
            {"role": "user", "content": user_input}
        ],
        temperature=0.8
    )
    invoice_json = response.choices[0].message.content
    return {**state, "invoice_json": invoice_json}

def summary_node(state):
    invoice_json = state.get("invoice_json", "")
    response = client.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": SUMMARY_ROLE_PROMPT},
            {"role": "user", "content": f"{invoice_json}"}
        ],
        temperature=0.3
    )
    summary = response.choices[0].message.content
    return {**state, "summary": summary}

def feedback_node(state):
    invoice_json = state.get("invoice_json", "")
    user_feedback = state.get("user_input", "")

    response = client.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": FEEDBACK_ROLE_PROMPT},
            {"role": "user", "content": f"Existing JSON:\n{invoice_json}\n\nUser feedback:\n{user_feedback}"}
        ],
        temperature=0.3
    )
    feedback_json = response.choices[0].message.content
    return {**state, "invoice_json": feedback_json}


def confirmation_node(state):
    user_input = state.get("user_input", "")
    response = client.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": CONFIRMATION_ROLE_PROMPT},
            {"role": "user", "content": user_input}
        ],
        temperature=0
    )

    output_raw = response.choices[0].message.content.strip()
    print("Confirmation output:", output_raw)

    # Parse JSON from model
    try:
        output_json = json.loads(output_raw)
    except json.JSONDecodeError:
        # fallback if model returns invalid JSON
        output_json = {"status": "ASK", "missing_fields": ["unknown"]}

    next_step = "invoice" if output_json.get("status") == "ASK" else END

    return {**state, "confirmation": output_json, "next_step": next_step}


def create_graph():
    workflow = StateGraph(dict)
    
    workflow.add_node("confirm", confirmation_node)

    #workflow.add_node("invoice", invoice_node)
    #workflow.add_node("summarize", summary_node)
    #workflow.add_node("feedback", feedback_node)
    #workflow.add_node("validate", validation_node)

    workflow.set_entry_point("confirm")

    # Main flow
    #workflow.add_edge("invoice", "summarize")
    #workflow.add_edge("summarize", "feedback")
    #workflow.add_edge("feedback", "validate")

    # Conditional routing based on validation
    """ workflow.add_conditional_edges(
        "validate",
        validation_router,
        {
            "invoice": "invoice",  # loop
            END: END
        }
    )
    """

    app = workflow.compile()
    print(app.get_graph().draw_mermaid())
    return app

graph_app = create_graph()




@app.post("/generate_invoice", response_model=InvoiceResponse)
def generate_invoice(request: InvoiceRequest):
    if not request.user_message:
        print("bruh" *60)
        raise HTTPException(status_code=400, detail="Input text is required")
    
    initial_state = {
        "user_input": request.user_message,
        "confirmation": "",
        "summary": ""
    }
    
    print(initial_state)
    
    result = graph_app.invoke(initial_state)
    
    return {
        "invoice_json": result.get("invoice_json"),
        "summary": result.get("summary"),
        "confirmation": result.get("confirmation")
    }
        
