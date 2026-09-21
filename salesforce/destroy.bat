@echo off
set SF_NO_COLOR=1
set FORCE_COLOR=0
cd /d C:\dev\agentforce-databricks-poc\salesforce
echo Deleting old action 3 (ai_query) ...
call sf project deploy start -o agentforce-poc --manifest destructive/package.xml --post-destructive-changes destructive/destructiveChanges.xml --ignore-warnings --json > C:\dev\agentforce-databricks-poc\salesforce\destroy.json 2>&1
echo Done. see destroy.json
