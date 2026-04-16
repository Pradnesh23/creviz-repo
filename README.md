# Creviz AI Metadata Generation Pipeline

This repository contains the architecture, internal agent prompts, and tool scripts that power the Creviz Multi-Agent Metadata Generation Pipeline using [Letta AI](https://letta.com/).

## 🏗️ End-to-End System Flow

```mermaid
flowchart TD
    subgraph USER["👤 User"]
        U1["Submits natural language\nUI requirement via Letta UI"]
    end

    subgraph MASTER["🤖 Master Agent (Claude Haiku 4.5)"]
        M1["Receives user requirement"]
        M2["Wraps in anti-hallucination preamble:\nIGNORE ALL PREVIOUS REQUIREMENTS\nREQUEST_ID + delimiters"]
        M3["Calls send_message_to_agents_matching_tags\nmatch_all + match_some =\ncreviz-intent-agent"]
        M4{"Check mode\nin Intent Agent\nresponse"}
        M5_UPDATE["mode = update\nExtract existing_metadata_id\nBuild redis key:\nmetadata:UUID"]
        M5_CREATE["mode = create\nForward exact JSON to\nMetadata Gen Agent"]
        M6_REDIS["Call get_metadata_from_redis\nwith exact redis key"]
        M7_PRESENT_UPDATE["Present to user:\n• Metadata ID\n• Redis Key\n• Block Count\n• Full Raw JSON blocks\nin code block"]
        M7_PRESENT_CREATE["Extract response from\nMetadata Gen Agent\nPresent summary to user"]
    end

    subgraph INTENT["🔍 Intent Agent (Claude Haiku 4.5)"]
        I0["Step 0: Extract requirement\nfrom incoming message\nbetween delimiters"]
        I1["Step 1: Call get_intent_schema\nReturns compressed keyword table"]
        I2["Step 2: Detect intents\nPass 1 → Keyword Scan\nPass 2 → Parent-Child Expansion\nPass 3 → Verification"]
        I3["Step 2.5: Call semantic_search_qdrant\nwith requirement text"]
        I4{"Score ≥ 0.80?"}
        I5_MATCH["Call get_metadata_from_redis\nwith EXACT best_match_redis_key\nfrom tool output"]
        I5_NO["Set mode = create"]
        I6_MATCH["Set mode = update\nexisting_metadata_id =\nEXACT UUID from results\n(NEVER fabricate)"]
        I7["Step 4: Output JSON:\nmode, requirement,\nintents_detected,\nexisting_metadata_id"]
    end

    subgraph METAGEN["⚙️ Metadata Gen Agent (Claude Haiku 4.5)"]
        MG0["Step 0: Parse JSON payload\nExtract mode, requirement,\nintents_detected"]
        MG1["Step 1: Call generate_metadata_schema\nwith comma-joined intents"]
        MG2["Step 2: Modular Generation Cycles"]
        MG_C1["Cycle 1: Form Hierarchy\nform → section → component → event"]
        MG_C2["Cycle 2: Report Hierarchy\nreport → columns → sub_report → event"]
        MG_C3["Cycle 3-N: Standalone Intents\ndashboard, page, business_rule, etc."]
        MG_FLAT["Call flatten_metadata_blocks\nnested JSON → flat blocks array"]
        MG_STORE["Call store_flattened_metadata_blocks\nblocks_json + requirement + intent_types"]
        MG3["Step 3: send_message\nwith final summary"]
    end

    subgraph STORAGE["💾 Storage Layer"]
        subgraph STORE_TOOL["store_flattened_metadata_blocks"]
            ST1["Hash requirement → Deterministic UUID\nmd5(requirement.lower())"]
            ST2["Redis: Load existing blocks\nunder same UUID key"]
            ST3["Merge: old blocks + new blocks"]
            ST4["Redis: Save merged array\nmetadata:UUID"]
            ST5["Qdrant: Upsert vector + payload\non deterministic point ID"]
        end
        REDIS[("Redis\nFlat blocks array\nmetadata:UUID")]
        QDRANT[("Qdrant\nTrigram vector + payload\nmetadata_id, intent_types,\nblock_count, summary")]
    end

    %% Main flow
    U1 ==> M1
    M1 ==> M2
    M2 ==> M3
    M3 ==> I0

    %% Intent Agent flow
    I0 ==> I1
    I1 ==> I2
    I2 ==> I3
    I3 ==> I4
    I4 == "Yes (match found)" ==> I5_MATCH
    I4 == "No / Error" ==> I5_NO
    I5_MATCH ==> I6_MATCH
    I6_MATCH ==> I7
    I5_NO ==> I7
    I7 ==> M4

    %% Master Agent branching
    M4 == "update" ==> M5_UPDATE
    M4 == "create" ==> M5_CREATE
    M5_UPDATE ==> M6_REDIS
    M6_REDIS ==> REDIS
    REDIS ==> M7_PRESENT_UPDATE
    M7_PRESENT_UPDATE ==> U1

    %% Create path
    M5_CREATE ==> MG0
    MG0 ==> MG1
    MG1 ==> MG2
    MG2 ==> MG_C1
    MG_C1 ==> MG_FLAT
    MG_FLAT ==> MG_STORE
    MG_STORE ==> ST1
    ST1 ==> ST2
    ST2 ==> ST3
    ST3 ==> ST4
    ST4 ==> REDIS
    ST3 ==> ST5
    ST5 ==> QDRANT
    MG_STORE ==> MG_C2
    MG_C2 ==> MG_FLAT
    MG_C2 ==> MG_C3
    MG_C3 ==> MG_FLAT
    MG_STORE ==> MG3
    MG3 ==> M7_PRESENT_CREATE
    M7_PRESENT_CREATE ==> U1

    %% Qdrant search connections
    I3 -.->|query_points API| QDRANT
    I5_MATCH -.->|get_metadata_from_redis| REDIS

    linkStyle default stroke:#000000,stroke-width:2px
    style USER fill:#1a1a2e,stroke:#e94560,color:#fff
    style MASTER fill:#16213e,stroke:#0f3460,color:#fff
    style INTENT fill:#1a1a2e,stroke:#533483,color:#fff
    style METAGEN fill:#1a1a2e,stroke:#e94560,color:#fff
    style STORAGE fill:#0f3460,stroke:#e94560,color:#fff
    style REDIS fill:#d63031,stroke:#fff,color:#fff
    style QDRANT fill:#6c5ce7,stroke:#fff,color:#fff
    style M4 fill:#fdcb6e,stroke:#e17055,color:#2d3436
    style I4 fill:#fdcb6e,stroke:#e17055,color:#2d3436
```

## 🧠 How it Works Behind the Scenes

```mermaid
%%{init: {'theme': 'dark', 'themeVariables': {'actorLineColor': '#000000', 'signalColor': '#000000', 'signalTextColor': '#000000', 'sequenceNumberColor': '#ffffff', 'noteBkgColor': '#fdcb6e', 'noteTextColor': '#000000'}}}%%
sequenceDiagram
    autonumber
    actor User

    box rgb(22,33,62) Letta AI Pipeline
        participant Master as Master Agent
        participant Intent as Intent Agent
        participant MetaGen as Metadata Gen Agent
    end

    box rgb(15,52,96) Tools
        participant Schema as get_intent_schema
        participant Search as semantic_search_qdrant
        participant RedisT as get_metadata_from_redis
        participant GenSchema as generate_metadata_schema
        participant Flatten as flatten_metadata_blocks
        participant Store as store_flattened_metadata_blocks
    end

    box rgb(108,92,231) Storage
        participant Qdrant as Qdrant (query_points API)
        participant Redis as Redis Cache
    end

    User->>Master: "Staff should be able to book meeting rooms..."

    Note over Master: Phase 1 — Route to Intent Agent
    Master->>Intent: send_message_to_agents_matching_tags<br/>Anti-hallucination preamble + delimiters

    Note over Intent: Step 0 — Extract requirement from delimiters
    Intent->>Schema: get_intent_schema()
    Schema-->>Intent: Compressed keyword table

    Note over Intent: Step 2 — Keyword scan + parent-child expansion
    Intent->>Search: semantic_search_qdrant(requirement_text)
    Search->>Qdrant: query_points(vector, score_threshold=0.80)
    Qdrant-->>Search: Points with scores + metadata_ids
    Search-->>Intent: {found, best_match_redis_key, best_match_score, results}

    alt Score ≥ 0.80 — Existing match
        Intent->>RedisT: get_metadata_from_redis(best_match_redis_key)
        RedisT->>Redis: GET metadata:UUID
        Redis-->>RedisT: Flat blocks JSON array
        RedisT-->>Intent: {found: true, block_count, content}
        Intent-->>Master: {mode: "update", existing_metadata_id: "exact-uuid"}

        Note over Master: SHORT CIRCUIT — Skip Metadata Gen
        Master->>RedisT: get_metadata_from_redis("metadata:" + existing_metadata_id)
        RedisT->>Redis: GET metadata:UUID
        Redis-->>RedisT: Full blocks array
        RedisT-->>Master: {found: true, content: [...all blocks...]}
        Master-->>User: Raw JSON blocks in code block + metadata ID

    else Score < 0.80 — No match
        Intent-->>Master: {mode: "create", intents_detected: [...]}

        Note over Master: Phase 2 — Full Generation
        Master->>MetaGen: Forward exact JSON payload

        MetaGen->>GenSchema: generate_metadata_schema(intents)
        GenSchema-->>MetaGen: Schema templates + examples

        loop Each Intent Cycle (Form → Report → Dashboard → ...)
            Note over MetaGen: Build nested JSON structure
            MetaGen->>Flatten: flatten_metadata_blocks(nested_json)
            Flatten-->>MetaGen: Flat blocks array

            MetaGen->>Store: store_flattened_metadata_blocks(blocks, requirement)
            Note over Store: md5(requirement) → Deterministic UUID
            Store->>Redis: GET existing blocks under UUID
            Redis-->>Store: Previous blocks (if any)
            Note over Store: Merge old + new blocks
            Store->>Redis: SET metadata:UUID → merged array
            Store->>Qdrant: UPSERT vector + payload on same point
            Store-->>MetaGen: Confirmation
        end

        MetaGen-->>Master: Summary text
        Master-->>User: "Metadata generation complete!" + summary
    end
```

## 🚀 How to Run the Environment

### 1. Start Qdrant Vector Database
Run Qdrant via the executable in your environment:
```powershell
C:\Users\prads\OneDrive\Desktop\qdrant\qdrant.exe
```
This runs the vector DB at `http://localhost:6333` which handles our semantic search indexing.

### 2. Start the Letta Server
In your Letta project directory, start the server using `uv`:
```powershell
uv run letta server
```
This boots the Letta runtime at `http://localhost:8283`.

### 3. Check Database Outputs
We use `check_db.py` to view exactly what is stored in both Redis and Qdrant at any given time.
```powershell
uv run python check_db.py
```

### 📊 Sample Output from `check_db.py`

When metadata generation is successfully completed, you will see output grouping all modular blocks properly flattened into array entries in Redis, mapping to exactly one semantic point in Qdrant:

```text
============================================================
REDIS DATA
============================================================
Total keys: 3

Key: metadata:0f39c566-09d7-8cf7-ef3d-7f6186d77329
Format: FLAT BLOCKS (10 blocks)

  --- Block 1: section ---
  {
    "id": "7dc1a92e-3363-44eb-b59a-14d2e1fd4eec",
    "type": "card",
    ...
  }

  --- Block 2: component ---
  {
    "id": "e479c72e-d01d-44a6-9c4c-47fc9aa9882a",
    "name": "prospectName",
    ...
  }
------------------------------------------------------------

============================================================
QDRANT DATA
============================================================
Total points: 3

Point ID: 7363032332737684558
  metadata_id : aa4b2fdb-2dbc-9e0c-6ad3-5e37d40bca1c
  intent_type : action
  types_stored: action, business_rule, component, event, form, section
  block_count : 37
  summary     : Employees need a way to request corporate travel. They should specify their destination...
------------------------------------------------------------
```
