# JD Bank and JD Builder

## Executive summary

JD Bank is the archive and review engine. JD Builder is the guided authoring experience. Both are powered by the same rulebook and the same human-approval model.

```mermaid
flowchart TB
    A[Archive + source JDs] --> B[JD Bank]
    B --> C[Parse + validate]
    C --> D[Dedup + cluster]
    D --> E[Harmonize canonical roles]
    E --> F[Library + review queue]

    G[New JD or role clone] --> H[JD Builder]
    H --> I[Guided authoring]
    I --> J[Live compliance checks]
    J --> K[Submit for review]
    K --> F
    F --> L[HR reviewer approves]
    L --> M[Published JD]
```

## 1) JD Bank: archive intelligence

```mermaid
flowchart LR
    RAW[Raw archive files] --> PARSE[Parse]
    PARSE --> VALIDATE[Validate]
    VALIDATE --> DEDUP[Exact + near duplicates]
    DEDUP --> CLUSTER[Cluster similar roles]
    CLUSTER --> HARM[Canonical harmonized draft]
    HARM --> REVIEW[Review + library]
```

## 2) JD Builder: authoring support

```mermaid
flowchart LR
    START[Start from scratch or similar role] --> FORM[Guided form]
    FORM --> LIVE[Live rulebook checks]
    LIVE --> DRAFT[Draft ready for review]
    DRAFT --> REVIEW[HR review]
```

## 3) Shared evaluation model

```mermaid
flowchart TD
    INPUT[JD text + sections] --> RULES[Validator / rulebook]
    RULES --> ISSUES[Issue list + severity]
    RULES --> SCORE[Weighted score]
    SCORE --> GRADE[Grade A–F]
    ISSUES --> GATES[Blocking gates]
    GRADE --> DECISION[Approve / revise / reject]
    GATES --> DECISION
```

## 4) Grade bands

```mermaid
flowchart LR
    S[0–100] --> A{Band}
    A -->|90+| A1[A]
    A -->|75–89| B1[B]
    A -->|60–74| C1[C]
    A -->|40–59| D1[D]
    A -->|0–39| E1[F]
```

## 5) Approver lens

```mermaid
flowchart TD
    Q[Quality score] --> T{Threshold met?}
    Q --> B{Blocking gate?}
    T -->|No| R[Return for edit]
    B -->|Yes| F[Must fix / escalate]
    T -->|Yes| B
    B -->|No| O{Reviewer override?}
    O -->|Yes| A[Approve with reason]
    O -->|No| H[Human approval]
```

## 6) Key principle

The score helps describe quality. The gates determine whether approval is permitted. The reviewer remains the final authority.

> Nothing publishes automatically.

## 7) Final takeaway

JD Bank makes the archive usable and reviewable. JD Builder makes new JDs consistent with that standard. Together they create a single, explainable, HR-governed approval system.
