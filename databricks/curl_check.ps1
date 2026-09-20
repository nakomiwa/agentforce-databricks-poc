# =============================================================================
# curl_check.ps1  （Windows PowerShell 版）
# Salesforce が叩くのと同じ HTTP リクエストを再現して ①②③ の疎通を確認する。
# Databricks の中ではなく、手元の PC の PowerShell で実行すること。
#
#   $env:DATABRICKS_HOST  = "https://dbc-xxxxxxxx-xxxx.cloud.databricks.com"
#   $env:DATABRICKS_TOKEN = "dapi..."
#   $env:WAREHOUSE_ID     = "xxxxxxxxxxxx"
#   .\curl_check.ps1
# =============================================================================

$ErrorActionPreference = "Stop"

$DatabricksHost = $env:DATABRICKS_HOST
$Token          = $env:DATABRICKS_TOKEN
$WarehouseId    = $env:WAREHOUSE_ID
$Catalog        = "workspace"
$Schema         = "sfdc_poc"

if (-not $DatabricksHost -or -not $Token -or -not $WarehouseId) {
    Write-Host "DATABRICKS_HOST / DATABRICKS_TOKEN / WAREHOUSE_ID を環境変数に設定してください。"
    exit 1
}
$DatabricksHost = $DatabricksHost.TrimEnd("/")

function Invoke-UcFunction {
    param([string]$Label, [string]$FunctionName, [hashtable[]]$Args)

    $argRefs = ($Args | ForEach-Object { ":" + $_.name }) -join ", "
    $statement = "SELECT $Catalog.$Schema.$FunctionName($argRefs) AS v"

    $payload = @{
        warehouse_id    = $WarehouseId
        statement       = $statement
        parameters      = @($Args | ForEach-Object {
                              @{ name = $_.name; value = $_.value; type = "STRING" } })
        wait_timeout    = "50s"
        on_wait_timeout = "CANCEL"
        format          = "JSON_ARRAY"
        disposition     = "INLINE"
    } | ConvertTo-Json -Depth 6

    Write-Host ("=" * 70)
    Write-Host "$Label   $FunctionName"
    Write-Host ("=" * 70)

    try {
        $res = Invoke-RestMethod -Method Post `
            -Uri "$DatabricksHost/api/2.0/sql/statements" `
            -Headers @{ Authorization = "Bearer $Token" } `
            -ContentType "application/json; charset=utf-8" `
            -Body ([System.Text.Encoding]::UTF8.GetBytes($payload))
    } catch {
        Write-Host "NG  リクエスト失敗: $($_.Exception.Message)"
        return $false
    }

    if ($res.status.state -ne "SUCCEEDED") {
        Write-Host "NG  state = $($res.status.state)"
        Write-Host ($res.status | ConvertTo-Json -Depth 5)
        return $false
    }

    $value = $res.result.data_array[0][0]
    if (-not $value) { Write-Host "NG  結果が空でした"; return $false }

    Write-Host "OK  state = SUCCEEDED / 応答長 = $($value.Length) 文字"
    Write-Host ("-" * 70)
    if ($value.Length -gt 1200) { Write-Host ($value.Substring(0, 1200) + " ...") }
    else { Write-Host $value }
    Write-Host ""
    return $true
}

$results = @(
    (Invoke-UcFunction "① 営業サマリ (JSON)"    "get_sales_summary_json" @(@{name="p_region";value="関東"}, @{name="p_period";value="2026-Q3"}))
    (Invoke-UcFunction "② 営業レポート (HTML)"  "get_sales_report_html"  @(@{name="p_region";value="関東"}, @{name="p_period";value="2026-Q3"}))
    (Invoke-UcFunction "③ カスタムエージェント" "ask_sales_agent"        @(@{name="p_question";value="最も受注率が高い地域はどこですか"}))
)

$ok = ($results | Where-Object { $_ -eq $true }).Count
Write-Host ("=" * 70)
Write-Host "結果: $ok / $($results.Count) 成功"
Write-Host ("=" * 70)
