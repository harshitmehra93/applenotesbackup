PYTHON ?= python3
VENV := .venv
VENV_PYTHON := $(VENV)/bin/python
BACKUP_SCRIPT := apple_notes_backup.py

.PHONY: help setup backup backup-icloud test clean

help:
	@echo "Apple Notes Backup"
	@echo ""
	@echo "Targets:"
	@echo "  make setup         Create .venv"
	@echo "  make backup        Back up all Apple Notes accounts to Markdown"
	@echo "  make backup-icloud Back up only the iCloud Notes account"
	@echo "  make test          Export 5 iCloud notes to verify permissions/output"
	@echo "  make clean         Remove local .venv and Python cache files"

setup: $(VENV_PYTHON)
	@echo "No external dependencies to install."

$(VENV_PYTHON):
	$(PYTHON) -m venv $(VENV)

backup: setup
	$(VENV_PYTHON) $(BACKUP_SCRIPT)

backup-icloud: setup
	$(VENV_PYTHON) $(BACKUP_SCRIPT) --account iCloud

test: setup
	$(VENV_PYTHON) $(BACKUP_SCRIPT) --account iCloud --limit 5

clean:
	rm -rf $(VENV) __pycache__
