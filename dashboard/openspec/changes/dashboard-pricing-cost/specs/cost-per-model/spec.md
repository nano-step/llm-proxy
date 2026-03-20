## ADDED Requirements

### Requirement: Cost per model API endpoint
The backend SHALL expose `GET /api/cost/models` that returns cost breakdown per model. Each entry SHALL contain: `model`, `cost` (total), `input_cost`, `output_cost`, `requests`, `input_tokens`, `output_tokens`. Models SHALL be ordered by cost descending.

#### Scenario: Cost per model returns breakdown
- **WHEN** `GET /api/cost/models` is called
- **THEN** the response contains one entry per model with cost computed from pricing rates

### Requirement: Cost per model donut chart
The dashboard SHALL display a doughnut chart showing cost distribution across models. Each slice SHALL represent a model's total cost. Colors SHALL match the existing model color scheme (opus→purple, sonnet→indigo, haiku→teal). The chart SHALL include a legend with model names and formatted costs.

#### Scenario: Cost model donut renders
- **WHEN** the dashboard loads and `/api/cost/models` returns data
- **THEN** a doughnut chart renders with slices proportional to each model's cost

#### Scenario: Tooltip shows cost details
- **WHEN** user hovers over a donut slice
- **THEN** a tooltip displays the model name, cost ($X.XX), and percentage of total cost

### Requirement: Cost column in model usage table
The existing model usage table SHALL gain a "Cost" column showing the total cost per model, formatted as `$X.XX`. The data SHALL come from the `/api/cost/models` response merged with the existing model data.

#### Scenario: Cost column displays in table
- **WHEN** the model table renders
- **THEN** a "Cost" column appears showing dollar amounts per model, ordered by total cost descending
