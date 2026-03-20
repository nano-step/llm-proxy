## ADDED Requirements

### Requirement: Model distribution donut chart
The dashboard SHALL display a doughnut chart showing token distribution across models, mirroring the existing agent donut chart. The chart SHALL use data from the existing `GET /api/models` endpoint. Each slice SHALL represent a model's total token count. The chart SHALL include a custom legend below it with model names and formatted token counts.

#### Scenario: Model donut renders with data
- **WHEN** the dashboard loads and `/api/models` returns 4 models
- **THEN** a doughnut chart renders with 4 slices, each proportional to that model's total tokens

#### Scenario: Tooltip shows model details
- **WHEN** user hovers over a donut slice
- **THEN** a tooltip displays the model name, token count, and percentage of total

#### Scenario: Legend displays all models
- **WHEN** the model donut chart renders
- **THEN** a legend below the chart lists each model with a color dot, name, and formatted token count

### Requirement: Model donut color assignment
Each model SHALL be assigned a distinct color from a predefined palette. Model names containing "opus" SHALL use a purple shade, "sonnet" SHALL use indigo, "haiku" SHALL use teal, and unknown models SHALL use gray.

#### Scenario: Color consistency across refreshes
- **WHEN** the dashboard refreshes and model data is reloaded
- **THEN** each model retains its assigned color based on its name
