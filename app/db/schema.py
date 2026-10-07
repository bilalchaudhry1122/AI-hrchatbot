"""Table keys and column lists for the MySQL HR schema.

Kept lean: only tables the Discord leave bot actually uses.
Dropped Attendance (no punch feed; policy answers cover attendance questions).
"""

# Logical key (config / client.table) → physical MySQL table name.
TABLE_NAMES = {
    "employees": "employees",
    "leaveTypes": "leave_types",
    "leaveBalances": "leave_balances",
    "leaveRequests": "leave_requests",
    "discordRoles": "discord_roles",
    "leaveUtilization": "leave_utilization",
    "holidays": "holidays",
    "hrAnnouncements": "hr_announcements",
}

# Columns that Airtable stored as linked-record arrays. Stored as JSON in MySQL
# and returned to the app as Python lists (same shape as pyairtable).
LINK_FIELDS = {
    "employees": {"Manager"},
    "leaveBalances": {"Employee", "Leave Type"},
    "leaveRequests": {"Employee", "Leave Type"},
    "leaveUtilization": {"Employee", "Leave Type", "Leave Request"},
}

# Boolean / checkbox fields stored as TINYINT(1).
BOOL_FIELDS = {
    "leaveTypes": {"Active"},
    "discordRoles": {"Managed", "Mentionable"},
}

# Date-only columns (ISO YYYY-MM-DD).
DATE_FIELDS = {
    "employees": {"Join Date", "DOB"},
    "leaveRequests": {"Start Date", "End Date"},
    "leaveUtilization": {"Date"},
    "holidays": {"Date"},
    "hrAnnouncements": {"Announce Date"},
}

# Full column lists for CREATE TABLE / inserts (excluding id).
TABLE_COLUMNS = {
    "employees": [
        "Employee Name",
        "Employee ID",
        "Discord User ID",
        "Email",
        "Department",
        "Join Date",
        "Status",
        "Discord Username",
        "HR Role",
        "Discord Roles",
        "Manager",
        "Manager Discord ID",
        "CNIC",
        "DOB",
        "Contact Number",
        "Address",
        "Designation",
        "Photo Path",
    ],
    "leaveTypes": ["Leave Type", "Code", "Description", "Active"],
    "leaveBalances": [
        "Name",
        "Employee",
        "Leave Type",
        "Year",
        "Total Entitlement",
        "Used",
    ],
    "leaveRequests": [
        "Request ID",
        "Employee",
        "Discord User ID",
        "Ticket Channel ID",
        "Leave Type",
        "Start Date",
        "End Date",
        "Days Requested",
        "Reason",
        "Rejection Reason",
        "Half Day",
        "Status",
        "Balance Before",
        "Balance After",
        "Requested At",
        "Approved At",
        "Approved By",
        "Rejected At",
        "Rejected By",
        "Manager Approved At",
        "Manager Approved By",
        "Cancelled At",
        "Cancelled By",
    ],
    "discordRoles": [
        "Role Name",
        "Discord Role ID",
        "Position",
        "Color",
        "Managed",
        "Mentionable",
    ],
    "leaveUtilization": [
        "Record Name",
        "Employee",
        "Leave Type",
        "Leave Request",
        "Date",
        "Day of Week",
        "Status",
    ],
    "holidays": ["Holiday", "Date", "Name"],
    "hrAnnouncements": [
        "Title",
        "Description",
        "Announce Date",
        "Announce Time",
        "Scheduled At",
        "Status",
        "Created By Discord ID",
        "Created By Name",
        "Posted At",
        "Cancelled At",
        "Cancelled By",
    ],
}
