## ADDED Requirements

### Requirement: Cost per agent API endpoint
The backend SHALL expose `GET /api/cost/agents` that returns cost breakdown per agent. Each entry SHALL contain: `agent`, `cost` (total), `input_cost`, `output_cost`, `requests`, `input_tokens`, `output_tokens`. Agents SHALL be ordered by cost descending.

#### Scenario: Cost per agent returns breakdown
- **WHEN** `GET /api/cost/agents` is called
- **THEN** the response contains one entry per agent with cost computed from pricing rates

### Requirement: Cost per agent display
The dashboard SHALL display cost per agent either as a donut chart or as additional cost info in the existing agent donut's tooltip/legend. The agent breakdown SHALL show the agent name and its total cost.

#### Scenario: Agent cost visible in legend or tooltip
- **WHEN** the agent donut chart renders
- **THEN** each agent's legend entry or tooltip includes the cost amount ($X.XX) alongside token count
