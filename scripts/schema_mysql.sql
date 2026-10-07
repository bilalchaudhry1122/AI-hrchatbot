-- WebAiry HR schema for local MySQL Workbench (database: hr).
-- Run: python scripts/setup_mysql.py

CREATE DATABASE IF NOT EXISTS hr
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE hr;

CREATE TABLE IF NOT EXISTS employees (
  id VARCHAR(64) PRIMARY KEY,
  `Employee Name` VARCHAR(255) NULL,
  `Employee ID` VARCHAR(64) NULL,
  `Discord User ID` VARCHAR(64) NULL,
  `Email` VARCHAR(255) NULL,
  `Department` VARCHAR(64) NULL,
  `Join Date` DATE NULL,
  `Status` VARCHAR(32) NULL,
  `Discord Username` VARCHAR(255) NULL,
  `HR Role` VARCHAR(32) NULL,
  `Discord Roles` TEXT NULL,
  `Manager` JSON NULL,
  `Manager Discord ID` VARCHAR(64) NULL,
  `CNIC` VARCHAR(32) NULL,
  `DOB` DATE NULL,
  `Contact Number` VARCHAR(32) NULL,
  `Address` VARCHAR(500) NULL,
  `Designation` VARCHAR(120) NULL,
  `Photo Path` VARCHAR(255) NULL,
  UNIQUE KEY uq_employees_discord (`Discord User ID`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS leave_types (
  id VARCHAR(64) PRIMARY KEY,
  `Leave Type` VARCHAR(128) NULL,
  `Code` VARCHAR(32) NULL,
  `Description` TEXT NULL,
  `Active` TINYINT(1) NOT NULL DEFAULT 1
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS leave_balances (
  id VARCHAR(64) PRIMARY KEY,
  `Name` VARCHAR(255) NULL,
  `Employee` JSON NULL,
  `Leave Type` JSON NULL,
  `Year` INT NULL,
  `Total Entitlement` DOUBLE NULL,
  `Used` DOUBLE NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS leave_requests (
  id VARCHAR(64) PRIMARY KEY,
  `Request ID` VARCHAR(64) NULL,
  `Employee` JSON NULL,
  `Discord User ID` VARCHAR(64) NULL,
  `Ticket Channel ID` VARCHAR(64) NULL,
  `Leave Type` JSON NULL,
  `Start Date` DATE NULL,
  `End Date` DATE NULL,
  `Days Requested` DOUBLE NULL,
  `Reason` TEXT NULL,
  `Rejection Reason` TEXT NULL,
  `Half Day` VARCHAR(32) NULL,
  `Status` VARCHAR(32) NULL,
  `Balance Before` DOUBLE NULL,
  `Balance After` DOUBLE NULL,
  `Requested At` VARCHAR(64) NULL,
  `Approved At` VARCHAR(64) NULL,
  `Approved By` VARCHAR(255) NULL,
  `Rejected At` VARCHAR(64) NULL,
  `Rejected By` VARCHAR(255) NULL,
  `Manager Approved At` VARCHAR(64) NULL,
  `Manager Approved By` VARCHAR(255) NULL,
  `Cancelled At` VARCHAR(64) NULL,
  `Cancelled By` VARCHAR(255) NULL,
  KEY idx_leave_requests_discord (`Discord User ID`),
  KEY idx_leave_requests_ticket (`Ticket Channel ID`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS discord_roles (
  id VARCHAR(64) PRIMARY KEY,
  `Role Name` VARCHAR(255) NULL,
  `Discord Role ID` VARCHAR(64) NULL,
  `Position` INT NULL,
  `Color` INT NULL,
  `Managed` TINYINT(1) NOT NULL DEFAULT 0,
  `Mentionable` TINYINT(1) NOT NULL DEFAULT 0,
  UNIQUE KEY uq_discord_roles_id (`Discord Role ID`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS leave_utilization (
  id VARCHAR(64) PRIMARY KEY,
  `Record Name` VARCHAR(255) NULL,
  `Employee` JSON NULL,
  `Leave Type` JSON NULL,
  `Leave Request` JSON NULL,
  `Date` DATE NULL,
  `Day of Week` VARCHAR(32) NULL,
  `Status` VARCHAR(32) NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS holidays (
  id VARCHAR(64) PRIMARY KEY,
  `Holiday` VARCHAR(255) NULL,
  `Date` DATE NULL,
  `Name` VARCHAR(255) NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS hr_announcements (
  id VARCHAR(64) PRIMARY KEY,
  `Title` VARCHAR(255) NULL,
  `Description` TEXT NULL,
  `Announce Date` DATE NULL,
  `Announce Time` VARCHAR(16) NULL,
  `Scheduled At` VARCHAR(32) NULL,
  `Status` VARCHAR(32) NULL,
  `Created By Discord ID` VARCHAR(64) NULL,
  `Created By Name` VARCHAR(255) NULL,
  `Posted At` VARCHAR(64) NULL,
  `Cancelled At` VARCHAR(64) NULL,
  `Cancelled By` VARCHAR(255) NULL,
  KEY idx_hr_announcements_status (`Status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
