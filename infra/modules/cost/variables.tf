variable "budget_name" {
  type        = string
  default     = "graveyard-project-monthly"
  description = "Name of the monthly budget. It is unique within the account, and the account is shared with other projects."

  validation {
    condition     = startswith(var.budget_name, "graveyard-")
    error_message = "The budget name must start with graveyard- (INF-SHARED-1)."
  }
}

variable "budget_limit" {
  type = object({
    amount = string
    unit   = string
  })
  default = {
    amount = "40"
    unit   = "USD"
  }
  description = "Monthly limit for Graveyard-tagged spend only. Default 40 USD (decision C8). Switch to { amount = \"30\", unit = \"GBP\" } if the account's billing currency is GBP (PRD section 12: 30 pounds a month)."

  validation {
    condition     = contains(["USD", "GBP"], var.budget_limit.unit)
    error_message = "unit must be USD or GBP."
  }

  validation {
    condition     = can(tonumber(var.budget_limit.amount)) && tonumber(var.budget_limit.amount) > 0
    error_message = "amount must be a number greater than 0, written as a string."
  }
}

variable "alert_emails" {
  type        = list(string)
  description = "Addresses that get the budget and anomaly notifications. Not committed: supply them from the gitignored terraform.tfvars (INF-COST-5). Email only, no SNS."

  validation {
    condition     = length(var.alert_emails) >= 1 && length(var.alert_emails) <= 10
    error_message = "Give between 1 and 10 addresses (a budget notification takes at most 10)."
  }

  validation {
    condition     = alltrue([for a in var.alert_emails : can(regex("^[^@[:space:]]+@[^@[:space:]]+\\.[^@[:space:]]+$", a))])
    error_message = "Every entry must look like an email address."
  }
}

variable "project_tag_key" {
  type        = string
  description = "Key of the Project cost allocation tag, from the root's locals, the same source as the Project entry of default_tags (INF-COST-6). Case-sensitive."

  validation {
    condition     = length(var.project_tag_key) > 0
    error_message = "project_tag_key must not be empty."
  }
}

variable "project_tag_value" {
  type        = string
  description = "Value of the Project cost allocation tag, from the same source (INF-COST-6). Case-sensitive."

  validation {
    condition     = length(var.project_tag_value) > 0
    error_message = "project_tag_value must not be empty."
  }
}

variable "anomaly_monitor_name" {
  type        = string
  default     = "graveyard-project"
  description = "Name of the custom anomaly monitor this module creates. Nothing is imported and no existing monitor is read or changed (INF-COST-4)."

  validation {
    condition     = startswith(var.anomaly_monitor_name, "graveyard-")
    error_message = "The monitor name must start with graveyard- (INF-SHARED-1)."
  }
}

variable "anomaly_threshold_amount" {
  type        = number
  default     = 10
  description = "Absolute anomaly impact, in the account currency, at which the subscription sends an email (decision O2: 10)."

  validation {
    condition     = var.anomaly_threshold_amount > 0
    error_message = "The threshold must be greater than 0."
  }
}

variable "activate_cost_allocation_tag_keys" {
  type        = set(string)
  default     = []
  description = "Cost allocation tag keys to activate. Account-wide (F2): put in only the keys that are NOT already active. Graveyard never manages a key that is already active, because other projects may rely on it. Allowed values: Project and Env."

  validation {
    condition     = alltrue([for k in var.activate_cost_allocation_tag_keys : contains(["Project", "Env"], k)])
    error_message = "Only the keys Project and Env may be activated."
  }
}
