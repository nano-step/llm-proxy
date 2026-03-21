## ADDED Requirements

### Requirement: IP panel in dashboard header
The dashboard SHALL display an IP list panel showing all distinct client IPs with request count and last seen time. The panel SHALL be collapsible and located adjacent to the existing time-range toggle in the header.

#### Scenario: IP panel displays after data loads
- **WHEN** the dashboard has loaded IP data from `/api/ips`
- **THEN** the IP panel shows each IP as a clickable chip with the format `"IP (N requests)"`

### Requirement: Click IP to filter dashboard by that IP
Clicking an IP chip SHALL set the active IP filter, update the filter banner to show "Filtering by IP: X.X.X.X", and refresh all dashboard charts and tables to show only that IP's data.

#### Scenario: Click IP chip to filter
- **WHEN** user clicks on an IP chip in the IP panel
- **THEN** the filter banner appears showing "Filtering by IP: X.X.X.X" and all charts and tables update to show only that IP's data

### Requirement: Clear IP filter
Clicking the filter banner's clear button SHALL remove the IP filter, hide the filter banner, and refresh all charts and tables to show all IPs.

#### Scenario: Clear IP filter
- **WHEN** the filter banner is showing "Filtering by IP: X.X.X.X" and user clicks "Clear filter"
- **THEN** the filter banner is hidden and all data is shown again

### Requirement: Show user-agent on IP hover
Hovering over an IP chip SHALL display a tooltip showing the user-agent string associated with the most recent request from that IP.

#### Scenario: Hover shows user-agent tooltip
- **WHEN** user hovers over an IP chip
- **THEN** a tooltip shows the full user-agent string for that IP's most recent request

### Requirement: Agent and IP filters are mutually exclusive
The dashboard SHALL support filtering by either agent OR IP, but not both simultaneously. Activating one filter SHALL clear the other.

#### Scenario: Switching from agent to IP filter clears agent
- **WHEN** the dashboard is filtering by agent "NanoSE" and user clicks an IP chip
- **THEN** the agent filter is cleared and the IP filter is activated

### Requirement: IP data refreshes with dashboard
The IP list SHALL be fetched alongside other dashboard data on every refresh cycle (60 seconds) so that new IPs appearing in traffic are reflected in the panel.

#### Scenario: New IP appears in traffic
- **WHEN** a request from a new IP occurs and the dashboard refreshes
- **THEN** the new IP appears in the IP panel on the next refresh
