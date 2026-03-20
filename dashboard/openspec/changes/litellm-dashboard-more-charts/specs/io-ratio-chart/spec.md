## ADDED Requirements

### Requirement: Input/Output ratio horizontal bar chart
The dashboard SHALL display a horizontal stacked bar chart showing the ratio of input (prompt) tokens to output (completion) tokens per model. Each bar SHALL represent one model. The bar SHALL be split into two segments: input tokens (indigo) and output tokens (purple). The X-axis SHALL show token counts. The Y-axis SHALL list model names. Data SHALL come from the existing `GET /api/models` endpoint.

#### Scenario: I/O ratio chart renders with model data
- **WHEN** the dashboard loads and `/api/models` returns data for 4 models
- **THEN** a horizontal stacked bar chart renders with 4 bars, each split into input and output segments

#### Scenario: Tooltip shows I/O breakdown
- **WHEN** user hovers over a bar segment
- **THEN** a tooltip displays the model name, the segment type (Input/Output), token count, and percentage of total for that model

#### Scenario: Models ordered by total tokens
- **WHEN** the I/O ratio chart renders
- **THEN** models are ordered top-to-bottom by total tokens (highest at top)

### Requirement: I/O ratio data reuse
The frontend SHALL reuse data from the `/api/models` endpoint (already fetched for the model table) to render the I/O ratio chart. No separate API call SHALL be made.

#### Scenario: Single fetch serves model table, model donut, and I/O ratio chart
- **WHEN** the dashboard refreshes
- **THEN** `/api/models` is called once and the response is used to populate the model table, model donut chart, and I/O ratio chart
