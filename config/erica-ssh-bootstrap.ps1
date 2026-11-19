<#
  erica-ssh-bootstrap.ps1  (v2 — locale-proof ACLs, full diagnostics)
  Enables Windows OpenSSH Server on Erica's PC and authorizes Hermes' key.

  RUN IN AN *ADMINISTRATOR* POWERSHELL:
      powershell -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\Downloads\erica-ssh-bootstrap.ps1"

  Idempotent — safe to re-run.
#>
$ErrorActionPreference = 'Stop'
$AUTHKEY = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAINdRfio92he/h8a85eyAhAOPIXHtmRbr8H089P293Nka hermes@pantheon-laptop'
$ENC = New-Object System.Text.UTF8Encoding($false)   # UTF-8, no BOM

function Say($m,$c='Cyan'){ Write-Host $m -ForegroundColor $c }

Say "==> [1/6] admin check"
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if(-not $isAdmin){ throw "Not elevated. Re-run in an ADMINISTRATOR PowerShell." }
Say "    elevated: OK  (account = $([Security.Principal.WindowsIdentity]::GetCurrent().Name))"

Say "==> [2/6] OpenSSH Server capability"
$cap = Get-WindowsCapability -Online -Name 'OpenSSH.Server*' | Select-Object -First 1
if($null -eq $cap){ throw "This Windows build does not offer OpenSSH.Server." }
if($cap.State -ne 'Installed'){ Say "    installing $($cap.Name) ..."; Add-WindowsCapability -Online -Name $cap.Name | Out-Null }
Say "    state: $((Get-WindowsCapability -Online -Name 'OpenSSH.Server*' | Select-Object -First 1).State)"

Say "==> [3/6] services"
Set-Service sshd -StartupType Automatic; Start-Service sshd
Set-Service ssh-agent -StartupType Automatic -ErrorAction SilentlyContinue; Start-Service ssh-agent -ErrorAction SilentlyContinue
Restart-Service sshd
Say "    sshd: $((Get-Service sshd).Status)"

Say "==> [4/6] firewall TCP/22"
if(Get-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -ErrorAction SilentlyContinue){
  Set-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -Enabled True -Direction Inbound -Action Allow -Profile Any
} else {
  New-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -DisplayName 'OpenSSH Server (sshd)' -Enabled True `
    -Direction Inbound -Action Allow -Protocol TCP -LocalPort 22 -Profile Any | Out-Null
}
Say "    OpenSSH-Server-In-TCP enabled (Profile Any)"

Say "==> [5/6] authorize Hermes key"
$adm = Join-Path $env:ProgramData 'ssh\administrators_authorized_keys'
$usr = Join-Path $env:USERPROFILE '.ssh\authorized_keys'
New-Item -ItemType Directory -Force -Path (Split-Path $adm) | Out-Null
New-Item -ItemType Directory -Force -Path (Split-Path $usr) | Out-Null
foreach($f in @($adm,$usr)){
  New-Item -ItemType File -Force -Path $f | Out-Null
  $cur = [System.IO.File]::ReadAllText($f)
  if($cur -notmatch [regex]::Escape($AUTHKEY)){
    [System.IO.File]::WriteAllText($f, ($cur.TrimEnd() + "`r`n" + $AUTHKEY + "`r`n"), $ENC)
    Say "    key added -> $f"
  } else { Say "    key already present -> $f" }
}
# Locale-proof ACL: S-1-5-18 = SYSTEM, S-1-5-32-544 = Administrators
& icacls $adm /inheritance:r | Out-Null
& icacls $adm /grant:r '*S-1-5-18:F' '*S-1-5-32-544:F' | Out-Null
Say "    ACL on administrators_authorized_keys:"
(icacls $adm) | ForEach-Object { Say "      $_" }

Say "==> [6/6] diagnostics" 'Green'
$acct = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$ts   = (Get-NetIPAddress -AddressFamily IPv4 -EA SilentlyContinue | Where-Object { $_.IPAddress -like '100.*' } | Select-Object -First 1).IPAddress
$lst  = (Get-NetTCPConnection -LocalPort 22 -State Listen -EA SilentlyContinue | Measure-Object).Count
Say ""
Say "  HERMES_ACCOUNT_ELEVATED : $acct" 'Yellow'
Say "  TAILSCALE_IP            : $ts" 'Yellow'
Say "  SSHD_SERVICE            : $((Get-Service sshd).Status)" 'Yellow'
Say "  LISTENERS_ON_22         : $lst" 'Yellow'
Say ""
Say "  --- local accounts (tell Hermes which one is Erica's login) ---" 'Yellow'
Get-LocalUser | Select-Object Name,Enabled,LastLogon | Format-Table -AutoSize | Out-String | ForEach-Object { Write-Host $_ }
Say "  --- Match block in sshd_config (should still point at administrators_authorized_keys) ---" 'Yellow'
Get-Content (Join-Path $env:ProgramData 'ssh\sshd_config') -EA SilentlyContinue |
  Select-String -Pattern 'Match|AuthorizedKeysFile|PubkeyAuth' | ForEach-Object { Write-Host "    $_" }
Say ""
Say "  >>> Paste the block above back to Hermes and the SSH hop gets finished." 'Green'
