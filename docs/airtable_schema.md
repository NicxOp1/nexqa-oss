# Airtable Schema Definition

To enable reporting, create a Base and add a table named **`QA Runs`**.

## Table: QA Runs

| Field Name | Field Type | Details |
| :--- | :--- | :--- |
| **Run ID** | Single Line Text | **Primary Field** (e.g. `run_agent_123_17000000`) |
| **Agent ID** | Single Line Text | The Retell Agent ID |
| **Status** | Single Select | Options: `approved`, `review_needed`, `blocked`, `failed`, `running` |
| **Score** | Number | Format: Decimal (1.00 - 5.00 or 0.0 - 1.0) |
| **Iterations** | Number | Format: Integer |
| **Cost** | Currency | Format: USD ($), Precision: 4 decimals |
| **Timestamp** | Date | Include Time (ISO format if possible) |

## Configuration
Once created, get your API Key and Base ID:
1.  Go to [Airtable Developer Hub](https://airtable.com/create/tokens) to generate a PAT (Personal Access Token).
2.  Add to `.env`:
    ```env
    AIRTABLE_API_KEY=pat...
    AIRTABLE_BASE_ID=app...
    ```
