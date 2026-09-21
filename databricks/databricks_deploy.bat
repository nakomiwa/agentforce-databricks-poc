@echo off
setlocal
set DATABRICKS_CLI_DO_NOT_TRACK=1

set JOB=%1
if "%JOB%"=="" set JOB=deploy_all

set ROOT=C:\dev\agentforce-databricks-poc\databricks
set LOG=%ROOT%\databricks_deploy.log

cd /d %ROOT%

if exist "%LOG%" move /y "%LOG%" "%ROOT%\databricks_deploy.prev.log" >nul

echo === bundle deploy === > "%LOG%"
call databricks bundle deploy -p sfdc >> "%LOG%" 2>&1
echo. >> "%LOG%"
echo === bundle run %JOB% === >> "%LOG%"
call databricks bundle run %JOB% -p sfdc >> "%LOG%" 2>&1

echo Done. see databricks_deploy.log
