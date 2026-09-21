@echo off
set SF_NO_COLOR=1
set FORCE_COLOR=0
cd /d C:\dev\agentforce-databricks-poc\salesforce
echo Retrieving ...
call sf project retrieve start -o agentforce-poc -m AiAuthoringBundle -m GenAiFunction -r _org_snapshot2 --json > C:\dev\agentforce-databricks-poc\salesforce\retrieve.json 2>&1
echo Done.
