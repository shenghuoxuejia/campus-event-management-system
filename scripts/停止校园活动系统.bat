@echo off
powershell -NoProfile -Command "$p = Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue; if ($p) { Stop-Process -Id $p.OwningProcess -Force; Write-Host '????????' } else { Write-Host '??????????????' }"
ping -n 3 127.0.0.1 >nul
