@echo off
setlocal
set DATABRICKS_CLI_DO_NOT_TRACK=1

set JOB=%1
if "%JOB%"=="" set JOB=deploy_genie_agent

set ROOT=C:\dev\agentforce-databricks-poc
set LOG=%ROOT%\databricks_deploy.log

cd /d %ROOT%\databricks

echo === bundle deploy === > "%LOG%"
call databricks bundle deploy -p sfdc >> "%LOG%" 2>&1
echo. >> "%LOG%"
echo === bundle run %JOB% === >> "%LOG%"
call databricks bundle run %JOB% -p sfdc >> "%LOG%" 2>&1

echo Done. see databricks_deploy.log
