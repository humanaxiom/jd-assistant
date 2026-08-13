# JD Bank and JD Builder

## 1) Two pieces, one decision system

```mermaid
flowchart TB
    subgraph JD_Bank[JD Bank]
        A[Archive ingest]
        B[Parse + validate]
        C[Dedup + cluster]
        D[Harmonize roles]
        E[Review queue]
    end

    subgraph JD_Builder[JD Builder]
        F[Start from scratch]
        G[Guided authoring]
        H[Live compliance checks]
        I[Submit for review]
    end

    A --> B --> C --> D --> E
    F --> G --> H --> I --> E
    D -->|evidence| G
    E -->|approved draft| F
```

## 2) JD Bank: archive transformation

```mermaid
flowchart LR
    RAW[Raw JD files] --> PARSE[Parse + normalize]
    PARSE --> VALIDATE[Validate against SFU rules]
    VALIDATE --> DEDUP[Deduplicate]
    DEDUP --> CLUSTER[Cluster similar roles]
    CLUSTER --> HARM[Harmonize canonical draft]
    HARM --> REVIEW[Review queue + library]
```

## 3) Validation: the decision engine

```mermaid
flowchart TD
    TEXT[JD text] --> SECTIONS[Parsed sections]
    SECTIONS --> RULES[Rulebook checks]
    RULES --> ISSUES[Issues by severity]
    RULES --> SCORE[Score out of 100]
    RULES --> GATES[Blocking gates]
    ISSUES --> TOTAL[Weighted evaluation]
    SCORE --> GRADE[Grade A–F]
    TOTAL --> DECISION[Approve / revise / reject]
    GATES --> DECISION
```

## 4) Grade logic

```mermaid
flowchart LR
    S[Score 0–100] --> A{Band}
    A -->|90+| A1[A]
    A -->|75–89| B1[B]
    A -->|60–74| C1[C]
    A -->|40–59| D1[D]
    A -->|0–39| E1[F]
```

## 5) Approver view: score is not the whole story

```mermaid
flowchart TD
    SCORE[Quality score] --> THRESHOLD{Meets threshold?}
    SCORE --> BLOCK{Blocking gate present?}
    THRESHOLD -->|No| REVISE[Return for edit]
    BLOCK -->|Yes| FIX[Must fix / escalate]
    THRESHOLD -->|Yes| BLOCK
    BLOCK -->|No| OVERRIDE{Reviewer override?}
    OVERRIDE -->|Yes| APPROVE[Approve with reason]
    OVERRIDE -->|No| REVIEW[Human approval]
```

## 6) Why both systems matter

- JD Bank converts the archive into standardized, comparable role evidence.
- JD Builder uses that evidence to draft a compliant JD in real time.
- Both feed the same approval model: rulebook, score, grade, gate checks, and human decision.
- Nothing auto-publishes.

## 7) Bottom line

JD Bank = archive intelligence and review infrastructure.
JD Builder = guided authoring and live compliance support.
Together they create a single accountable approval process for SFU job descriptions.
