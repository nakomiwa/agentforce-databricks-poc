@echo off
set SF_NO_COLOR=1
set FORCE_COLOR=0
cd /d C:\dev\agentforce-databricks-poc\salesforce
echo Deploying ...
call sf project deploy start -o agentforce-poc -d force-app/main/default/classes -d force-app/main/default/lwc -d force-app/main/default/lightningTypes -d force-app/main/default/genAiFunctions -d force-app/main/default/aiAuthoringBundles --json > C:\dev\agentforce-databricks-poc\salesforce\deploy.json 2>&1
echo Done. see deploy.json
