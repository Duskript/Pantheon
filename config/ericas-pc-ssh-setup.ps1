<#
  ericas-pc-ssh-setup.ps1
  Purpose: enable Windows OpenSSH Server on Erica's PC so Hermes (pantheon-laptop,
           100.115.50.41) can SSH in over Tailscale.

  RUN IN AN *ADMINISTRATOR* POWERSHELL ON ERICA'S PC:
      powershell -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\Downloads\ericas-pc-ssh-setup.ps1"

  Idempotent: safe to re-run.
#>

$ErrorActionPreference = 'Stop'
$AUTHKEY = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAINdRfio92he/h8a85eyAhAOPIXHtmRbr8H089P293Nka hermes@pantheon-laptop'
$NOBOM   = New-Object System.Text.UTF8Encoding($false)

Write-Host "==> [1/6] admin rights" -ForegroundColor Cyan
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) { throw "Not elevated. Re-run this in an ADMINISTRATOR PowerShell." }
Write-Host "    OK (elevated)"

Write-Host "==> [2/6] install OpenSSH Server" -ForegroundColor Cyan
$cap = Get-WindowsCapability -Online -Name 'OpenSSH.Server*' | Select-Object -First 1
if ($null -eq $cap) { throw "OpenSSH.Server capability not offered by this Windows build." }
if ($cap.State -ne 'Installed') {
  Write-Host "    adding $($cap.Name) ... (this can take a minute)"
  Add-WindowsCapability -Online -Name $cap.Name | Out-Null
}
$state = (Get-WindowsCapability -Online -Name 'OpenSSH.Server*' | Select-Object -First 1).State
Write-Host "    OpenSSH Server: $state"
if ($state -ne 'Installed') { throw "OpenSSH Server install did not complete (state=$state)." }

Write-Host "==> [3/6] enable + start services" -ForegroundColor Cyan
Set-Service -Name sshd -StartupType Automatic
Start-Service sshd
Set-Service -Name ssh-agent -StartupType Automatic -ErrorAction SilentlyContinue
Start-Service ssh-agent -ErrorAction SilentlyContinue
Write-Host "    sshd: $((Get-Service sshd).Status)"

Write-Host "==> [4/6] firewall rule for TCP/22" -ForegroundColor Cyan
if (Get-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -ErrorAction SilentlyContinue) {
  Set-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -Enabled True -Direction Inbound -Action Allow -Profile Any
} else {
  New-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -DisplayName 'OpenSSH Server (sshd)' `
    -Enabled True -Direction Inbound -Action Allow -Protocol TCP -LocalPort 22 -Profile Any | Out-Null
}
Write-Host "    rule OpenSSH-Server-In-TCP enabled (all profiles)"

Write-Host "==> [5/6] authorize Hermes public key" -ForegroundColor Cyan
# (a) administrators_authorized_keys -- sshd uses THIS for admin accounts, with a locked ACL
$admFile = Join-Path $env:ProgramData 'ssh\administrators_authorized_keys'
New-Item -ItemType Directory -Force -Path (Split-Path $admFile) | Out-Null
New-Item -ItemType File -Path $admFile -Force | Out-Null
$cur = [System.IO.File]::ReadAllText($admFile)
if ($cur -notmatch [regex]::Escape($AUTHKEY)) {
  [System.IO.File]::WriteAllText($admFile, ($cur.TrimEnd() + "`r`n" + $AUTHKEY + "`r`n"), $NOBOM)
}
icacls $admFile /inheritance:r | Out-Null
icacls $admFile /grant 'SYSTEM:F' | Out-Null
icacls $admFile /grant 'BUILTIN\Administrators:F' | Out-Null
# (b) per-user authorized_keys -- used if the login account is NOT an administrator
$usrFile = Join-Path $env:USERPROFILE '.ssh\authorized_keys'
New-Item -ItemType Directory -Force -Path (Split-Path $usrFile) | Out-Null
$cur2 = if (Test-Path $usrFile) { [System.IO.File]::ReadAllText($usrFile) } else { '' }
if ($cur2 -notmatch [regex]::Escape($AUTHKEY)) {
  [System.IO.File]::WriteAllText($usrFile, ($cur2.TrimEnd() + "`r`n" + $AUTHKEY + "`r`n"), $NOBOM)
}
Write-Host "    key installed in both locations, ACL locked down"

Write-Host "==> [6/6] summary" -ForegroundColor Cyan
$acct = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$tsIp = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
         Where-Object { $_.IPAddress -like '100.*' } | Select-Object -First 1).IPAddress
$listen = (Get-NetTCPConnection -LocalPort 22 -State Listen -ErrorAction SilentlyContinue | Measure-Object).Count
Write-Host ""
Write-Host "  WINDOWS_ACCOUNT : $acct"
Write-Host "  TAILSCALE_IP    : $tsIp"
Write-Host "  SSHD_SERVICE    : $((Get-Service sshd).Status)"
Write-Host "  LISTENERS_ON_22 : $listen"
Write-Host ""
Write-Host "  >>> Report WINDOWS_ACCOUNT + TAILSCALE_IP back to Hermes." -ForegroundColor Green
