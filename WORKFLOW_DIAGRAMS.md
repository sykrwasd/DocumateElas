# Invoice AI Workflow Diagram

## Complete Workflow Graph

```mermaid
graph TD
    Start([User Request]) --> Router{Router Node}
    
    Router -->|New Session<br/>or No Data| Extract[Extract Node<br/>Extract invoice data<br/>from user message]
    Router -->|Existing Session<br/>with Data| Feedback[Feedback Node<br/>Apply modifications<br/>to existing data]
    
    Extract --> Merge[Merge Node<br/>Merge with session data]
    Feedback --> Merge
    
    Merge --> Validate[Validate Node<br/>Check required fields]
    
    Validate --> End([Return Response<br/>with session_id])
    
    style Router fill:#FFE5B4
    style Extract fill:#B4E5FF
    style Feedback fill:#FFB4E5
    style Merge fill:#E5FFB4
    style Validate fill:#FFD4B4
    style Start fill:#E0E0E0
    style End fill:#E0E0E0
```

## Routing Decision Logic

```mermaid
graph TD
    A[Incoming Request] --> B{Has session_id?}
    B -->|No| C[Generate new session_id]
    B -->|Yes| D{Session exists<br/>in storage?}
    
    C --> E[Route to EXTRACT]
    D -->|No| E
    D -->|Yes| F{Has existing<br/>data?}
    
    F -->|No| E
    F -->|Yes| G[Route to FEEDBACK]
    
    style A fill:#E0E0E0
    style E fill:#B4E5FF
    style G fill:#FFB4E5
```

## Data Flow Example

### Scenario: Creating and Modifying an Invoice

```mermaid
sequenceDiagram
    participant User
    participant API
    participant Router
    participant Extract
    participant Feedback
    participant Merge
    participant Session

    Note over User,Session: Request 1: Create new invoice
    User->>API: "Invoice for John at ABC"
    API->>Router: Check session (none)
    Router->>Extract: Route to extraction
    Extract->>Merge: New data
    Merge->>Session: Save to session-123
    API->>User: session_id: "session-123"

    Note over User,Session: Request 2: Add more info
    User->>API: "Location: Grand Ballroom"<br/>session_id: "session-123"
    API->>Router: Check session-123
    Router->>Extract: Route to extraction<br/>(adding new info)
    Extract->>Merge: New location data
    Merge->>Session: Merge with existing
    Session->>Merge: Return merged data
    API->>User: Updated invoice

    Note over User,Session: Request 3: Modify existing field
    User->>API: "Change email to john@new.com"<br/>session_id: "session-123"
    API->>Router: Check session-123
    Router->>Feedback: Route to feedback<br/>(modifying existing)
    Feedback->>Session: Get current data
    Session->>Feedback: Current invoice
    Feedback->>Merge: Updated invoice<br/>(only email changed)
    Merge->>Session: Save updated data
    API->>User: Modified invoice
```

## Node Responsibilities

```mermaid
graph LR
    subgraph Router
        R1[Check session_id]
        R2[Check existing data]
        R3[Decide route]
    end
    
    subgraph Extract
        E1[Parse user message]
        E2[Extract fields]
        E3[Return structured data]
    end
    
    subgraph Feedback
        F1[Get existing data]
        F2[Apply modifications]
        F3[Preserve other fields]
        F4[Return updated data]
    end
    
    subgraph Merge
        M1[Check data source]
        M2[Merge if from extract]
        M3[Pass through if from feedback]
    end
    
    subgraph Validate
        V1[Check required fields]
        V2[List missing fields]
        V3[Generate message]
    end
    
    style Router fill:#FFE5B4
    style Extract fill:#B4E5FF
    style Feedback fill:#FFB4E5
    style Merge fill:#E5FFB4
    style Validate fill:#FFD4B4
```

## State Management

```mermaid
stateDiagram-v2
    [*] --> NoSession: New Request
    NoSession --> SessionCreated: Generate session_id
    SessionCreated --> HasData: Extract data
    HasData --> HasData: Add more info (Extract + Merge)
    HasData --> HasData: Modify fields (Feedback)
    HasData --> Complete: All fields filled
    Complete --> [*]: Return final invoice
    
    note right of HasData
        Session storage:
        {
          "extracted": {...},
          "last_updated": datetime
        }
    end note
```
